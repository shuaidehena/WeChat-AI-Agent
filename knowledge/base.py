"""本地个人知识库。

资料位于 ``storage/knowledge/sources``，访问策略位于
``storage/knowledge/access.json``。文档只在策略明确授权后才会进入回复。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from memory.embedding import get_embedding_model


SUPPORTED_SUFFIXES = {".md", ".txt", ".json"}
DEFAULT_POLICY = {
    "default_access": "private",
    "default_allowed_contacts": [],
    "files": {},
}


class PersonalKnowledgeBase:
    """独立于好友记忆的个人知识库。"""

    COLLECTION_NAME = "personal_knowledge"

    def __init__(
        self,
        storage_dir: str = "storage",
        embedding_model=None,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
    ):
        root = Path(storage_dir).resolve()
        self.root = root / "knowledge"
        self.source_dir = self.root / "sources"
        self.policy_path = self.root / "access.json"
        self.persist_dir = root / "vector_db" / "chroma"
        self.chunk_size = max(100, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size // 2))
        self._embedding = embedding_model
        self._collection = None

    def ensure_layout(self) -> None:
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        if not self.policy_path.exists():
            self.policy_path.write_text(
                json.dumps(DEFAULT_POLICY, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    @property
    def collection(self):
        if self._collection is None:
            self.ensure_layout()
            client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"kind": "personal_knowledge", "hnsw:space": "cosine"},
            )
        return self._collection

    @property
    def embedding(self):
        if self._embedding is None:
            self._embedding = get_embedding_model()
        return self._embedding

    def load_policy(self) -> dict:
        self.ensure_layout()
        try:
            raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"知识库权限配置无效: {self.policy_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("知识库权限配置必须是 JSON 对象")
        result = dict(DEFAULT_POLICY)
        result.update(raw)
        if result["default_access"] not in {"private", "allowlist", "all"}:
            raise ValueError("default_access 只能是 private、allowlist 或 all")
        if not isinstance(result.get("files"), dict):
            raise ValueError("files 必须是 JSON 对象")
        return result

    def import_all(self) -> dict:
        """重新索引 sources 下的全部支持文件，并清理已删除文件的旧分段。"""
        policy = self.load_policy()
        files = sorted(
            path
            for path in self.source_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_SUFFIXES
            and not path.name.lower().endswith(".meta.json")
        )

        imported_sources: set[str] = set()
        chunk_total = 0
        for path in files:
            source = path.relative_to(self.source_dir).as_posix()
            text = self._read_document(path)
            chunks = self.chunk_text(text, self.chunk_size, self.chunk_overlap)
            imported_sources.add(source)
            self._replace_source(source, chunks, self._file_policy(policy, source))
            chunk_total += len(chunks)

        existing = self.collection.get(include=["metadatas"])
        for metadata in existing.get("metadatas") or []:
            source = str((metadata or {}).get("source", ""))
            if source and source not in imported_sources:
                self.collection.delete(where={"source": source})

        return {"files": len(files), "chunks": chunk_total}

    def search(
        self,
        query: str,
        friend_id: str,
        friend_name: str = "",
        limit: int = 4,
        min_score: float | None = None,
    ) -> list[dict]:
        """检索当前联系人获准使用的知识片段。"""
        query = (query or "").strip()
        if not query or limit <= 0 or self.collection.count() == 0:
            return []
        if min_score is None:
            min_score = float(os.getenv("WECHAT_KNOWLEDGE_MIN_SCORE", "0.35"))
        min_score = max(0.0, min(1.0, float(min_score)))

        fetch_count = min(self.collection.count(), max(limit * 8, 24))
        result = self.collection.query(
            query_embeddings=[self.embedding.encode(query)],
            n_results=fetch_count,
            include=["documents", "metadatas", "distances"],
        )
        items: list[dict] = []
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            if not self.is_allowed(metadata or {}, friend_id, friend_name):
                continue
            distance = distances[index] if index < len(distances) else 2.0
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            if score < min_score:
                continue
            items.append({
                "text": document,
                "source": (metadata or {}).get("source", ""),
                "score": round(score, 3),
                "sensitivity": (metadata or {}).get("sensitivity", "normal"),
            })
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def is_allowed(metadata: dict, friend_id: str, friend_name: str = "") -> bool:
        access = str(metadata.get("access", "private")).lower()
        allowed = PersonalKnowledgeBase._decode_contacts(
            metadata.get("allowed_contacts", "[]")
        )
        identities = {
            value.strip().casefold()
            for value in (friend_id, friend_name)
            if value and value.strip()
        }
        explicitly_allowed = "*" in allowed or bool(identities.intersection(allowed))
        if str(metadata.get("sensitivity", "normal")).lower() == "sensitive":
            return explicitly_allowed
        if access == "all":
            return True
        if access == "allowlist":
            return explicitly_allowed
        return False

    @staticmethod
    def chunk_text(text: str, size: int = 500, overlap: int = 80) -> list[str]:
        text = "\n".join(line.rstrip() for line in (text or "").splitlines()).strip()
        if not text:
            return []
        size = max(100, int(size))
        overlap = max(0, min(int(overlap), size // 2))
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            if end < len(text):
                candidates = [text.rfind(mark, start + size // 2, end) for mark in ("\n\n", "\n", "。", "！", "？", ";", "；")]
                boundary = max(candidates)
                if boundary > start:
                    end = boundary + (2 if text.startswith("\n\n", boundary) else 1)
            chunk = text[start:end].strip()
            if chunk and (not chunks or chunk != chunks[-1]):
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return chunks

    def _replace_source(self, source: str, chunks: list[str], file_policy: dict) -> None:
        self.collection.delete(where={"source": source})
        if not chunks:
            return
        source_hash = hashlib.sha256("\n".join(chunks).encode("utf-8")).hexdigest()
        ids = [hashlib.sha256(f"{source}:{i}:{source_hash}".encode()).hexdigest()[:24] for i in range(len(chunks))]
        metadata = {
            "source": source,
            "source_hash": source_hash,
            "access": file_policy["access"],
            "allowed_contacts": json.dumps(file_policy["allowed_contacts"], ensure_ascii=False),
            "sensitivity": file_policy["sensitivity"],
        }
        self.collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=self.embedding.encode_batch(chunks),
            metadatas=[dict(metadata, chunk_index=i) for i in range(len(chunks))],
        )

    def _file_policy(self, policy: dict, source: str) -> dict:
        override = policy.get("files", {}).get(source, {})
        if not isinstance(override, dict):
            raise ValueError(f"文件权限必须是对象: {source}")
        access = override.get("access", policy.get("default_access", "private"))
        if access not in {"private", "allowlist", "all"}:
            raise ValueError(f"无效 access: {source}: {access}")
        contacts = override.get(
            "allowed_contacts", policy.get("default_allowed_contacts", [])
        )
        if not isinstance(contacts, list) or not all(isinstance(x, str) for x in contacts):
            raise ValueError(f"allowed_contacts 必须是字符串数组: {source}")
        sensitivity = str(override.get("sensitivity", "normal")).lower()
        if sensitivity not in {"normal", "sensitive"}:
            raise ValueError(f"无效 sensitivity: {source}: {sensitivity}")
        return {
            "access": access,
            "allowed_contacts": contacts,
            "sensitivity": sensitivity,
        }

    @staticmethod
    def _decode_contacts(value: Any) -> set[str]:
        if isinstance(value, list):
            contacts = value
        else:
            try:
                contacts = json.loads(str(value or "[]"))
            except json.JSONDecodeError:
                contacts = []
        return {
            str(item).strip().casefold()
            for item in contacts
            if str(item).strip()
        }

    def _read_document(self, path: Path) -> str:
        raw = self._read_text(path)
        if path.suffix.lower() != ".json":
            return raw
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 文档无效: {path}: {exc}") from exc
        lines: list[str] = []
        self._flatten_json(data, lines)
        return "\n".join(lines)

    @staticmethod
    def _read_text(path: Path) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法识别文件编码: {path}")

    @classmethod
    def _flatten_json(cls, value: Any, lines: list[str], prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                cls._flatten_json(item, lines, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._flatten_json(item, lines, f"{prefix}[{index}]")
        elif value is not None:
            lines.append(f"{prefix}: {value}" if prefix else str(value))
