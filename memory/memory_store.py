"""
统一记忆存储层

职责划分:
  chat    → storage/history/{friend_id}.jsonl   近期对话（Prompt 主上下文）
  vector  → storage/vector_db/chroma/          长期语义记忆
  profile → storage/profiles/{friend_id}.json  好友画像摘要
  meta    → storage/friends.json                关系/标签/notes
  audit   → storage/messages.json               调试审计日志（不参与 Prompt）
  map     → storage/name_map.json               中文名 ↔ friend_id
"""

import os
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from history.storage import HistoryStorage
from memory.vector_memory import VectorMemory
from memory.profile_builder import ProfileBuilder
from memory.friend_registry import FriendRegistry
from memory.friend import FriendMemory
from utils.atomic_io import write_json_atomic
from context.context_guard import ContextGuard


class MemoryStore:
    """记忆系统统一存储门面"""

    def __init__(self, storage_dir: str = "storage"):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)
        self.storage_dir = storage_dir
        self.registry = FriendRegistry(storage_dir)
        self.friends = FriendMemory(os.path.join(storage_dir, "friends.json"))

    # ========== 好友解析 ==========

    def resolve_friend_id(self, name_or_id: str) -> str:
        """中文名或已有 friend_id → 拼音 friend_id"""
        key = (name_or_id or "").strip()
        if not key:
            return ""
        fid = self.registry.get_friend_id(key)
        if fid:
            return fid
        if key.isascii() and not any("\u4e00" <= c <= "\u9fff" for c in key):
            return key if ContextGuard.FRIEND_ID_RE.fullmatch(key) else ""
        return self.registry.ensure_friend(key)

    def resolve_display_name(self, friend_id: str) -> str:
        """friend_id → 中文显示名（若无则返回 friend_id）"""
        for name, info in self.friends.get_all_friends().items():
            if info.get("friend_id") == friend_id:
                return name
        try:
            import json
            path = os.path.join(self.storage_dir, "profiles", f"{friend_id}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("name") or friend_id
        except (OSError, json.JSONDecodeError):
            pass
        return friend_id

    def list_friends(self) -> list[dict]:
        """列出所有好友及存储概况"""
        chroma_counts = self._chroma_counts()
        result = []
        for name, info in self.friends.get_all_friends().items():
            fid = info.get("friend_id") or self.registry.get_friend_id(name) or ""
            hist_count = 0
            if fid:
                try:
                    hist_count = len(HistoryStorage(fid).load())
                except Exception:
                    pass
            vm_count = chroma_counts.get(f"friend_{fid}", 0) if fid else 0
            result.append({
                "name": name,
                "friend_id": fid,
                "relation": info.get("relation", ""),
                "tags": info.get("tags", []),
                "vector_count": vm_count,
                "history_count": hist_count,
            })
        return result

    def _chroma_counts(self) -> dict[str, int]:
        """批量读取 chroma collection 条数（不加载 embedding）"""
        path = os.path.join(self.storage_dir, "vector_db", "chroma")
        if not os.path.isdir(path):
            return {}
        try:
            import chromadb
            from chromadb.config import Settings
            client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
            return {c.name: c.count() for c in client.list_collections()}
        except Exception:
            return {}

    # ========== chat 层（JSONL）==========

    def get_chat_history(self, friend_id: str, limit: int = 20) -> list[dict]:
        """近期对话，供 Prompt 使用"""
        if not friend_id:
            return []
        return HistoryStorage(friend_id).get_recent(limit)

    def save_incoming_messages(self, friend_id: str, messages: list) -> int:
        return self.registry.save_incoming_messages(friend_id, messages)

    def save_reply(self, friend_id: str, reply_text: str) -> bool:
        if not friend_id or not reply_text:
            return False
        HistoryStorage(friend_id).save([{"sender": "me", "text": reply_text}])
        return True

    def get_full_history(self, friend_id: str) -> list[dict]:
        if not friend_id:
            return []
        return HistoryStorage(friend_id).load()

    # ========== vector 层（ChromaDB）==========

    def _vm(self, friend_id: str) -> VectorMemory:
        return VectorMemory(friend_id)

    def list_memories(self, friend_id: str, limit: int = 100) -> list[dict]:
        if not friend_id:
            return []
        return self._vm(friend_id).list_all(limit=limit)

    def search_memories(self, friend_id: str, query: str, limit: int = 10) -> list[dict]:
        if not friend_id:
            return []
        return self._vm(friend_id).search(query, limit=limit)

    def delete_memory(self, friend_id: str, mem_id: str) -> bool:
        if not friend_id or not mem_id:
            return False
        self._vm(friend_id).delete(mem_id)
        return True

    def memory_count(self, friend_id: str) -> int:
        if not friend_id:
            return 0
        return self._vm(friend_id).count()

    # ========== profile 层 ==========

    def get_profile_text(self, friend_id: str, friend_name: str = "") -> str:
        if not friend_id:
            return ""
        name = friend_name or self.resolve_display_name(friend_id)
        return ProfileBuilder(friend_id, name).get_profile_text()

    # ========== meta 层 ==========

    def get_friend_meta(self, chinese_name: str) -> dict | None:
        return self.friends.get_friend(chinese_name)

    # ========== audit 层（调试日志）==========

    def append_audit_log(self, friend_name: str, sender: str, content: str) -> None:
        """写入 messages.json，仅作审计，不参与 Prompt"""
        if os.getenv("WECHAT_AUDIT_LOG", "0") != "1":
            return
        path = os.path.join(self.storage_dir, "messages.json")
        records = []
        if os.path.exists(path):
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (OSError, json.JSONDecodeError):
                records = []
        records.append({
            "friend": friend_name,
            "sender": sender,
            "content": content,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 审计日志仅用于调试，设置上限避免每次整体覆盖无限变慢。
        records = records[-10000:]
        try:
            write_json_atomic(path, records)
        except OSError:
            pass
