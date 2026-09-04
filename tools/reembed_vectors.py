"""
用当前 Embedding 模型（bge-small-zh-v1.5）重新向量化所有 Chroma 记忆

旧向量（MiniLM 384维）与新模型（512维）不兼容，需全量 re-embed。

用法:
  python tools/reembed_vectors.py --dry-run
  python tools/reembed_vectors.py --apply
  python tools/reembed_vectors.py --apply --friend yangchunhui
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import chromadb
from chromadb.config import Settings

from memory.embedding import EmbeddingModel, CHINESE_DIM, CHINESE_MODEL

logger = logging.getLogger("reembed_vectors")

BATCH_SIZE = 32


def _normalize_metadata(meta: dict | None) -> dict:
    """Chroma 只接受 str/int/float/bool"""
    if not meta:
        return {}
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


class VectorReembedder:
    def __init__(self, storage_dir: str = "storage", dry_run: bool = True):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)

        self.chroma_dir = os.path.join(storage_dir, "vector_db", "chroma")
        self.dry_run = dry_run
        self._client = None
        self._model: EmbeddingModel | None = None

    def _get_client(self):
        if self._client is None:
            os.makedirs(self.chroma_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self.chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client

    def _get_model(self, require_chinese: bool = True) -> EmbeddingModel:
        if self._model is None:
            self._model = EmbeddingModel()
        if require_chinese and self._model.dim != CHINESE_DIM:
            raise RuntimeError(
                f"当前模型维度 {self._model.dim}，需要中文模型 {CHINESE_MODEL} ({CHINESE_DIM}维)。"
                "请安装 fastembed: pip install fastembed"
            )
        return self._model

    def list_collections(self, friend_filter: str | None = None) -> list[dict]:
        client = self._get_client()
        items = []
        for col in client.list_collections():
            name = col.name
            if friend_filter:
                target = f"friend_{friend_filter}"
                if name != target:
                    continue
            count = col.count()
            meta = col.metadata or {}
            items.append({
                "name": name,
                "count": count,
                "friend_id": meta.get("friend_id", name.replace("friend_", "")),
            })
        return sorted(items, key=lambda x: x["name"])

    def reembed_collection(self, collection_name: str) -> dict:
        """重建单个 collection 的全部向量"""
        client = self._get_client()
        col = client.get_collection(collection_name)
        count = col.count()

        if count == 0:
            return {"name": collection_name, "count": 0, "status": "skip_empty"}

        raw = col.get(include=["documents", "metadatas"])
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []

        # 过滤空文档
        valid = [
            (ids[i], docs[i], _normalize_metadata(metas[i] if i < len(metas) else {}))
            for i in range(len(docs))
            if docs[i] and str(docs[i]).strip()
        ]
        if not valid:
            return {"name": collection_name, "count": 0, "status": "skip_no_docs"}

        friend_id = (col.metadata or {}).get("friend_id", collection_name.replace("friend_", ""))

        logger.info("  %s: %d 条待 re-embed", collection_name, len(valid))

        if self.dry_run:
            return {
                "name": collection_name,
                "friend_id": friend_id,
                "count": len(valid),
                "status": "dry_run",
            }

        model = self._get_model(require_chinese=True)
        v_ids, v_docs, v_metas = zip(*valid)

        # 删除旧 collection（384维向量无法就地更新为512维）
        client.delete_collection(collection_name)
        new_col = client.create_collection(
            name=collection_name,
            metadata={"friend_id": friend_id, "embedding_model": CHINESE_MODEL},
        )

        total = len(v_docs)
        for start in range(0, total, BATCH_SIZE):
            batch_ids = list(v_ids[start : start + BATCH_SIZE])
            batch_docs = list(v_docs[start : start + BATCH_SIZE])
            batch_metas = list(v_metas[start : start + BATCH_SIZE])
            batch_emb = model.encode_batch(batch_docs)
            new_col.add(
                ids=batch_ids,
                embeddings=batch_emb,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            logger.info("    进度: %d/%d", min(start + BATCH_SIZE, total), total)

        new_count = new_col.count()
        if new_count != len(valid):
            return {
                "name": collection_name,
                "count": new_count,
                "expected": len(valid),
                "status": "error_count_mismatch",
            }

        return {
            "name": collection_name,
            "friend_id": friend_id,
            "count": new_count,
            "status": "ok",
        }

    def run(self, friend_filter: str | None = None) -> int:
        mode = "DRY-RUN" if self.dry_run else "APPLY"
        logger.info("=== 向量 Re-embed [%s] ===", mode)
        logger.info("Chroma: %s", self.chroma_dir)

        if not self.dry_run:
            self._get_model(require_chinese=True)

        collections = self.list_collections(friend_filter)
        nonempty = [c for c in collections if c["count"] > 0]

        if not nonempty:
            logger.info("无需要 re-embed 的非空 collection")
            return 0

        logger.info("发现 %d 个非空 collection（共 %d 条）",
                    len(nonempty), sum(c["count"] for c in nonempty))

        errors = 0
        for info in nonempty:
            logger.info("--- %s (%d 条) ---", info["name"], info["count"])
            result = self.reembed_collection(info["name"])
            status = result.get("status")
            if status == "ok":
                logger.info("  ✅ 完成: %d 条 → %s", result["count"], CHINESE_MODEL)
            elif status == "dry_run":
                logger.info("  📋 预览: %d 条将 re-embed", result["count"])
            elif status.startswith("skip"):
                logger.info("  ⏭ 跳过: %s", status)
            else:
                logger.error("  ❌ 失败: %s", result)
                errors += 1

        logger.info("=== 完成: 错误 %d ===", errors)
        if self.dry_run:
            logger.info("使用 --apply 执行实际 re-embed")
        return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description="Re-embed Chroma 向量（中文模型）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="预览（默认）")
    mode.add_argument("--apply", action="store_true", help="执行 re-embed")
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument("--friend", default="", help="仅处理指定 friend_id")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    for noisy in ("chromadb", "httpx", "urllib3", "fastembed"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    dry_run = not args.apply
    reembedder = VectorReembedder(storage_dir=args.storage_dir, dry_run=dry_run)
    friend = args.friend.strip() or None
    raise SystemExit(reembedder.run(friend_filter=friend))


if __name__ == "__main__":
    main()
