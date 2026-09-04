"""
旧数据迁移：中文文件名 / friend_id → 拼音 friend_id

扫描 storage/history、storage/profiles、storage/vector_db/chroma，
将中文命名的历史、画像、向量库统一迁移为拼音 friend_id。

用法:
  python tools/migrate_friend_ids.py --dry-run
  python tools/migrate_friend_ids.py --apply
  python tools/migrate_friend_ids.py --apply --storage-dir storage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from context.name_mapper import FriendNameMapper, _has_cjk
from memory.friend import FriendMemory

logger = logging.getLogger("migrate_friend_ids")


@dataclass
class MigrationTarget:
    """单个中文名 → 拼音 friend_id 的迁移目标"""

    chinese_name: str
    pinyin_id: str = ""
    history_src: str | None = None
    profile_src: str | None = None
    chroma_old: str | None = None
    chroma_new: str | None = None
    friends_needs_update: bool = False
    notes: list[str] = field(default_factory=list)


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _chroma_safe_name(friend_id: str) -> str:
    """与 memory/vector_memory.py VectorMemory._safe_name 保持一致"""
    name = f"friend_{friend_id}"
    if name.isascii():
        return name
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return f"friend_{h}"


def _pinyin_collection_name(pinyin_id: str) -> str:
    return f"friend_{pinyin_id}"


class FriendIdMigrator:
    def __init__(self, storage_dir: str, dry_run: bool = True):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)

        self.storage_dir = storage_dir
        self.dry_run = dry_run
        self.history_dir = os.path.join(storage_dir, "history")
        self.profile_dir = os.path.join(storage_dir, "profiles")
        self.chroma_dir = os.path.join(storage_dir, "vector_db", "chroma")
        self.name_mapper = FriendNameMapper(
            map_path=os.path.join(storage_dir, "name_map.json"),
            storage_dir=storage_dir,
        )
        self.friends = FriendMemory(os.path.join(storage_dir, "friends.json"))
        self._actions: list[str] = []

    # ========== 发现与规划 ==========

    def discover(self) -> dict[str, MigrationTarget]:
        targets: dict[str, MigrationTarget] = {}

        def ensure(name: str) -> MigrationTarget:
            name = name.strip()
            if not name:
                raise ValueError("empty chinese name")
            if name not in targets:
                targets[name] = MigrationTarget(chinese_name=name)
            return targets[name]

        if os.path.isdir(self.history_dir):
            for fname in os.listdir(self.history_dir):
                if not fname.endswith(".jsonl"):
                    continue
                stem = fname[:-6]
                if _has_cjk(stem):
                    t = ensure(stem)
                    t.history_src = os.path.join(self.history_dir, fname)

        if os.path.isdir(self.profile_dir):
            for fname in os.listdir(self.profile_dir):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(self.profile_dir, fname)
                stem = fname[:-5]
                friend_id = stem
                chinese_name = stem
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    friend_id = str(data.get("friend_id") or stem)
                    chinese_name = str(data.get("name") or stem)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("无法读取 profile %s: %s", path, e)

                if _has_cjk(stem) or _has_cjk(friend_id):
                    name_key = chinese_name if _has_cjk(chinese_name) else stem
                    t = ensure(name_key)
                    t.profile_src = path
                    if chinese_name and not _has_cjk(chinese_name):
                        t.notes.append(f"profile 显示名非中文: {chinese_name}")

        for name, entry in self.friends.get_all_friends().items():
            if not _has_cjk(name):
                continue
            fid = str(entry.get("friend_id") or "")
            if not fid or _has_cjk(fid):
                t = ensure(name)
                t.friends_needs_update = True

        for name, t in targets.items():
            t.pinyin_id = self._resolve_pinyin_id(name)
            t.chroma_old = _chroma_safe_name(name)
            t.chroma_new = _pinyin_collection_name(t.pinyin_id)

        return targets

    def _resolve_pinyin_id(self, chinese_name: str) -> str:
        existing = self.name_mapper.get_id(chinese_name)
        if existing:
            return existing

        base = self.name_mapper.to_pinyin_id(chinese_name)
        used = set(self.name_mapper.all_mappings().values())
        used |= self._existing_file_ids()
        if base not in used:
            return base
        n = 2
        while f"{base}{n}" in used:
            n += 1
        return f"{base}{n}"

    def _existing_file_ids(self) -> set[str]:
        used: set[str] = set()
        for sub, ext, trim in (
            ("history", ".jsonl", 6),
            ("profiles", ".json", 5),
        ):
            dir_path = os.path.join(self.storage_dir, sub)
            if not os.path.isdir(dir_path):
                continue
            for fname in os.listdir(dir_path):
                if fname.endswith(ext):
                    used.add(fname[:-trim])
        return used

    # ========== 执行 ==========

    def run(self) -> int:
        mode = "DRY-RUN" if self.dry_run else "APPLY"
        logger.info("=== 好友 ID 迁移 [%s] storage=%s ===", mode, self.storage_dir)

        targets = self.discover()
        if not targets:
            logger.info("未发现需要迁移的中文 friend_id / 文件名")
            return 0

        logger.info("发现 %d 个待迁移中文名", len(targets))
        errors = 0

        for name, target in sorted(targets.items(), key=lambda x: x[0]):
            logger.info("--- %s → %s ---", name, target.pinyin_id)
            for note in target.notes:
                logger.info("  备注: %s", note)

            if target.history_src:
                dst = os.path.join(self.history_dir, f"{target.pinyin_id}.jsonl")
                ok = self._migrate_history(target.history_src, dst)
                if not ok:
                    errors += 1

            if target.profile_src:
                dst = os.path.join(self.profile_dir, f"{target.pinyin_id}.json")
                ok = self._migrate_profile(target.profile_src, dst, target.pinyin_id, name)
                if not ok:
                    errors += 1

            if target.chroma_old and target.chroma_new:
                ok = self._migrate_chroma(target.chroma_old, target.chroma_new, target.pinyin_id)
                if not ok:
                    errors += 1

            if target.friends_needs_update:
                self._update_friends_entry(name, target.pinyin_id)

            self._update_name_map(name, target.pinyin_id)

        self._log_summary(errors)
        return 1 if errors else 0

    def _migrate_history(self, src: str, dst: str) -> bool:
        if os.path.normcase(src) == os.path.normcase(dst):
            self._log("history 已是目标路径，跳过", src)
            return True

        if not os.path.exists(src):
            self._log("history 源文件不存在，跳过", src)
            return True

        if os.path.exists(dst):
            self._log("合并 history → 已有目标文件", f"{src} → {dst}")
            if self.dry_run:
                return True
            try:
                with open(src, "r", encoding="utf-8") as sf, open(dst, "a", encoding="utf-8") as df:
                    shutil.copyfileobj(sf, df)
                os.remove(src)
                self._log("已合并并删除源 history", src)
                return True
            except OSError as e:
                logger.error("合并 history 失败: %s", e)
                return False

        self._log("重命名 history", f"{src} → {dst}")
        if self.dry_run:
            return True
        try:
            os.rename(src, dst)
            self._log("history 重命名成功", dst)
            return True
        except OSError as e:
            logger.error("history 重命名失败: %s", e)
            return False

    def _migrate_profile(self, src: str, dst: str, pinyin_id: str, chinese_name: str) -> bool:
        if not os.path.exists(src):
            self._log("profile 源文件不存在，跳过", src)
            return True

        self._log("迁移 profile", f"{src} → {dst}")
        if self.dry_run:
            return True

        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("读取 profile 失败: %s", e)
            return False

        data["friend_id"] = pinyin_id
        if not data.get("name"):
            data["name"] = chinese_name

        if os.path.exists(dst) and os.path.normcase(src) != os.path.normcase(dst):
            logger.warning("目标 profile 已存在，更新内容: %s", dst)
            try:
                with open(dst, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                if os.path.normcase(src) != os.path.normcase(dst):
                    os.remove(src)
                self._log("profile 已写入目标并删除源", dst)
                return True
            except OSError as e:
                logger.error("写入 profile 失败: %s", e)
                return False

        try:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.normcase(src) != os.path.normcase(dst):
                os.remove(src)
            self._log("profile 迁移成功", dst)
            return True
        except OSError as e:
            logger.error("profile 迁移失败: %s", e)
            return False

    def _migrate_chroma(self, old_name: str, new_name: str, pinyin_id: str) -> bool:
        if not os.path.isdir(self.chroma_dir):
            self._log("vector_db 目录不存在，跳过 chroma", self.chroma_dir)
            return True

        if old_name == new_name:
            self._log("chroma collection 名称已正确，跳过", new_name)
            return True

        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            logger.warning("chromadb 未安装，跳过向量库迁移")
            return True

        client = chromadb.PersistentClient(
            path=self.chroma_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        collections = {c.name: c for c in client.list_collections()}
        if old_name not in collections:
            self._log("chroma 无旧 collection，跳过", old_name)
            return True

        old_col = collections[old_name]
        count = old_col.count()
        self._log("迁移 chroma collection", f"{old_name} ({count} 条) → {new_name}")

        if self.dry_run:
            return True

        if count == 0:
            try:
                client.delete_collection(old_name)
                self._log("已删除空 chroma collection", old_name)
            except Exception as e:
                logger.error("删除空 collection 失败: %s", e)
                return False
            return True

        try:
            payload = old_col.get(include=["embeddings", "documents", "metadatas"])
            ids = payload.get("ids") or []
            if not ids:
                client.delete_collection(old_name)
                return True

            if new_name in collections:
                new_col = client.get_collection(new_name)
            else:
                new_col = client.create_collection(
                    name=new_name,
                    metadata={"friend_id": pinyin_id},
                )

            embeddings = payload.get("embeddings")
            documents = payload.get("documents")
            metadatas = payload.get("metadatas")

            has_embeddings = embeddings is not None and len(embeddings) > 0

            batch_size = 100
            for i in range(0, len(ids), batch_size):
                kwargs = {
                    "ids": ids[i : i + batch_size],
                    "documents": documents[i : i + batch_size] if documents else None,
                    "metadatas": metadatas[i : i + batch_size] if metadatas else None,
                }
                if has_embeddings:
                    kwargs["embeddings"] = embeddings[i : i + batch_size]
                new_col.upsert(**{k: v for k, v in kwargs.items() if v is not None})

            if new_col.count() < count:
                logger.error(
                    "chroma 迁移校验失败: 新 collection 条数 %d < 旧 %d",
                    new_col.count(),
                    count,
                )
                return False

            client.delete_collection(old_name)
            self._log("chroma 迁移成功并删除旧 collection", new_name)
            return True
        except Exception as e:
            logger.error("chroma 迁移失败: %s", e)
            return False

    def _update_friends_entry(self, chinese_name: str, pinyin_id: str) -> None:
        entry = self.friends.get_friend(chinese_name)
        if not entry:
            self._log("friends.json 无此好友，跳过", chinese_name)
            return

        current = str(entry.get("friend_id") or "")
        if current == pinyin_id:
            self._log("friends.json friend_id 已正确", chinese_name)
            return

        self._log("更新 friends.json", f"{chinese_name}.friend_id = {pinyin_id}")
        if self.dry_run:
            return

        entry["friend_id"] = pinyin_id
        entry.setdefault("name", chinese_name)
        self.friends._data[chinese_name] = entry
        self.friends.save()

    def _update_name_map(self, chinese_name: str, pinyin_id: str) -> None:
        current = self.name_mapper.get_id(chinese_name)
        if current == pinyin_id:
            self._log("name_map 已存在正确映射", f"{chinese_name} → {pinyin_id}")
            return

        self._log("更新 name_map.json", f"{chinese_name} → {pinyin_id}")
        if self.dry_run:
            return

        self.name_mapper._map[chinese_name] = pinyin_id
        self.name_mapper._save()

    def _log(self, action: str, detail: str = "") -> None:
        msg = f"{action}: {detail}" if detail else action
        self._actions.append(msg)
        logger.info("  %s", msg)

    def _log_summary(self, errors: int) -> None:
        logger.info("=== 迁移摘要 ===")
        logger.info("操作数: %d, 错误: %d, 模式: %s", len(self._actions), errors, "dry-run" if self.dry_run else "apply")
        if self.dry_run:
            logger.info("以上为预览，使用 --apply 执行实际迁移")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 storage 中的中文 friend_id / 文件名迁移为拼音 friend_id",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="预览迁移计划，不修改文件（默认行为）",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="执行迁移",
    )
    parser.add_argument(
        "--storage-dir",
        default="storage",
        help="storage 根目录（默认: storage）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="输出 DEBUG 日志",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # argparse store_true 与 default=True 组合时，--dry-run 无法关闭默认；
    # 以 --apply 为准。
    dry_run = not args.apply

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    for noisy in ("chromadb", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    migrator = FriendIdMigrator(storage_dir=args.storage_dir, dry_run=dry_run)
    return migrator.run()


if __name__ == "__main__":
    raise SystemExit(main())
