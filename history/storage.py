"""
历史消息存储
保存到 JSONL 格式（每行一条JSON）
"""

import sys
import os
import json
from datetime import datetime
from context.context_guard import ContextGuard

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryStorage:
    """历史消息存储器

    保存到 storage/history/{friend_id}.jsonl
    """

    def __init__(self, friend_id: str):
        if not ContextGuard.require_friend_id(friend_id, "历史存储"):
            raise ValueError("invalid friend_id")
        history_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "history"
        )
        os.makedirs(history_dir, exist_ok=True)
        self._path = os.path.join(history_dir, f"{friend_id}.jsonl")
        self._count: int = 0

    def save(self, messages: list[dict]):
        """追加保存消息"""
        with open(self._path, "a", encoding="utf-8") as f:
            for msg in messages:
                record = {
                    "time": msg.get("time", datetime.now().strftime("%H:%M:%S")),
                    "sender": msg.get("sender", "friend"),
                    "text": msg.get("text", ""),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._count += 1

    def load(self) -> list[dict]:
        """加载全部消息"""
        if not os.path.exists(self._path):
            return []
        messages = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return messages

    def get_recent(self, limit: int = 20, scan_tail: int = 800) -> list[dict]:
        """
        获取最近 N 条聊天记录（去重，供 Prompt 上下文使用）

        Args:
            limit: 返回条数上限
            scan_tail: 从文件尾部扫描的行数（大文件性能优化）

        Returns:
            [{"sender": "friend/me", "content": "..."}, ...]
        """
        if not os.path.exists(self._path):
            return []

        raw: list[dict] = []
        with open(self._path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines[-scan_tail:]:
            line = line.strip()
            if not line:
                continue
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        deduped: list[dict] = []
        for msg in raw:
            sender = msg.get("sender", "friend")
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            prev = deduped[-1] if deduped else None
            if prev and prev["sender"] == sender and prev["content"] == text:
                continue
            deduped.append({"sender": sender, "content": text})

        return deduped[-limit:]

    def count(self) -> int:
        return self._count
