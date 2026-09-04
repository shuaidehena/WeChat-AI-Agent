"""
从 storage/history/{friend_id}.jsonl 提取好友（friend）消息

每个 jsonl = 与一个好友的完整聊天记录
提取 sender=friend 的消息，去重 + 过滤 OCR 噪音
"""

import sys
import os
import re
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.content_filter import clean_for_memory, is_memory_noise

DATE_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日")
TIME_RE = re.compile(r"^(昨天|今天|星期)?\s*\d{1,2}:\d{2}")
PURE_NUM_RE = re.compile(r"^[\d\(\)\[\]\s\.,]+$")


class FriendHistoryReader:
    """读取单个好友的 storage 聊天历史"""

    NOISE_EXACT = {
        "哈哈", "呵呵", "嗯", "嗯嗯", "哦", "好的", "好", "ok", "OK",
        "收到", "👍", "在吗", "？", "?", "。", "…", "...",
    }
    MIN_LEN = 2

    def __init__(self, friend_id: str, history_dir: str = None):
        self.friend_id = friend_id
        if history_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            history_dir = os.path.join(base, "storage", "history")
        self._path = os.path.join(history_dir, f"{friend_id}.jsonl")

    def collect(self) -> dict:
        """
        Returns:
            {
              "friend_messages": [{"sender":"friend","text":"..."}, ...],
              "all_history": [...],           # 完整对话（去重后）
              "raw_friend_count": int,        # 去重前 friend 条数
              "unique_friend_count": int,
              "total_lines": int,
            }
        """
        if not os.path.exists(self._path):
            return self._empty()

        raw_lines = self._read_lines()
        friend_msgs = []
        all_history = []
        seen_friend: set[str] = set()
        raw_friend = 0
        prev = None

        for msg in raw_lines:
            sender = msg.get("sender", "friend")
            text = clean_for_memory(
                str(msg.get("text") or msg.get("content", "")).strip()
            )
            if not text:
                continue

            # 连续重复去重
            if prev and prev["sender"] == sender and prev["text"] == text:
                continue
            prev = {"sender": sender, "text": text}
            all_history.append({"sender": sender, "text": text})

            if sender not in ("friend",):
                continue

            if not self._is_valid_friend_message(text):
                continue

            raw_friend += 1
            norm = self._normalize(text)
            if norm in seen_friend:
                continue
            seen_friend.add(norm)
            friend_msgs.append({"sender": "friend", "text": text})

        return {
            "friend_messages": friend_msgs,
            "all_history": all_history,
            "raw_friend_count": raw_friend,
            "unique_friend_count": len(friend_msgs),
            "total_lines": len(raw_lines),
        }

    def _read_lines(self) -> list[dict]:
        records = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass
        return records

    def _is_valid_friend_message(self, text: str) -> bool:
        if not text or len(text) < self.MIN_LEN:
            return False
        if text in self.NOISE_EXACT:
            return False
        if is_memory_noise(text):
            return False
        if DATE_RE.search(text):
            return False
        if TIME_RE.match(text):
            return False
        if PURE_NUM_RE.match(text):
            return False
        return True

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", text.lower())

    @staticmethod
    def _empty() -> dict:
        return {
            "friend_messages": [],
            "all_history": [],
            "raw_friend_count": 0,
            "unique_friend_count": 0,
            "total_lines": 0,
        }
