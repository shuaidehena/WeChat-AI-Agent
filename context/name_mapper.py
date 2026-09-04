"""
中文好友名 → 英文 friend_id 映射

使用拼音转换，持久化到 storage/name_map.json。
"""

import hashlib
import json
import os
import re
import sys
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:
    lazy_pinyin = None
    Style = None


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


class FriendNameMapper:
    """中文名 → 英文 friend_id（拼音）映射器"""

    def __init__(self, map_path: str = "storage/name_map.json", storage_dir: str = "storage"):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(map_path):
            map_path = os.path.join(base, map_path)
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)

        self.map_path = map_path
        self.storage_dir = storage_dir
        self._map: dict[str, str] = {}  # 中文名 → friend_id
        self._load()

    # ========== 公开 API ==========

    def get_id(self, chinese_name: str) -> str | None:
        """查询已存在的 friend_id，不存在返回 None"""
        name = chinese_name.strip()
        if not name:
            return None
        return self._map.get(name)

    def resolve_or_create(self, chinese_name: str) -> str:
        """解析或创建 friend_id（拼音）"""
        name = chinese_name.strip()
        if not name:
            return ""

        existing = self._map.get(name)
        if existing:
            return existing

        base_id = self.to_pinyin_id(name)
        friend_id = self._unique_id(base_id)
        self._map[name] = friend_id
        self._save()
        print(f"  🆔 名字映射: {name} → {friend_id}")
        return friend_id

    def to_pinyin_id(self, name: str) -> str:
        """将显示名转为拼音/ASCII 形式的 friend_id"""
        name = name.strip()
        if not name:
            return "unknown"

        if name.isascii():
            slug = re.sub(r"[^a-zA-Z0-9]+", "", name).lower()
            if len(slug) > 48:
                slug = f"{slug[:39]}_{self._hash_id(name)}"
            return slug or self._hash_id(name)

        if lazy_pinyin is None:
            print("⚠️ pypinyin 未安装，使用 hash 作为 friend_id")
            return self._hash_id(name)

        parts: list[str] = []
        for char in name:
            if "\u4e00" <= char <= "\u9fff":
                parts.extend(lazy_pinyin(char, style=Style.NORMAL))
            elif char.isalnum():
                parts.append(char.lower())

        slug = re.sub(r"[^a-z0-9]+", "", "".join(parts))
        if len(slug) > 48:
            slug = f"{slug[:39]}_{self._hash_id(name)}"
        return slug or self._hash_id(name)

    def all_mappings(self) -> dict[str, str]:
        return dict(self._map)

    # ========== 内部 ==========

    def _unique_id(self, base: str) -> str:
        used = set(self._map.values()) | self._existing_ids()
        if base not in used:
            return base
        n = 2
        while f"{base}{n}" in used:
            n += 1
        return f"{base}{n}"

    def _existing_ids(self) -> set[str]:
        used: set[str] = set()
        for sub in ("history", "profiles"):
            dir_path = os.path.join(self.storage_dir, sub)
            if not os.path.isdir(dir_path):
                continue
            for fname in os.listdir(dir_path):
                if sub == "history" and fname.endswith(".jsonl"):
                    used.add(fname[:-6])
                elif sub == "profiles" and fname.endswith(".json"):
                    used.add(fname[:-5])
        return used

    @staticmethod
    def _hash_id(name: str) -> str:
        return hashlib.md5(name.encode("utf-8")).hexdigest()[:8]

    def _load(self):
        if not os.path.exists(self.map_path):
            self._bootstrap_from_profiles()
            return
        try:
            with open(self.map_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._map = {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ name_map 读取失败: {e}")
            self._map = {}

        self._bootstrap_from_profiles()

    def _bootstrap_from_profiles(self):
        """从已有 profile 文件补充映射"""
        profile_dir = os.path.join(self.storage_dir, "profiles")
        if not os.path.isdir(profile_dir):
            return
        changed = False
        for fname in os.listdir(profile_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(profile_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                cname = data.get("name", "")
                eid = data.get("friend_id", "") or fname[:-5]
                if cname and cname not in self._map:
                    self._map[cname] = eid
                    changed = True
            except (json.JSONDecodeError, IOError):
                pass
        if changed:
            self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.map_path) or ".", exist_ok=True)
            write_json_atomic(self.map_path, self._map)
        except IOError as e:
            print(f"⚠️ name_map 保存失败: {e}")


if __name__ == "__main__":
    mapper = FriendNameMapper(map_path="storage/test_name_map.json")
    samples = ["杨春辉", "张玉萍", "白文彦", "铁三鱼(3)", "Alice", "埋索"]
    for s in samples:
        fid = mapper.resolve_or_create(s)
        print(f"  {s} → {fid}")
    if os.path.exists("storage/test_name_map.json"):
        os.remove("storage/test_name_map.json")
    print("✅ name_mapper 测试完成")
