"""
从 storage/history/*.jsonl 提取用户（me）消息

每个 jsonl 文件 = 与一个好友的聊天记录
只提取 sender=me / 我 的消息，去重 + 过滤 OCR 噪音
"""

import sys
import os
import re
import json
import glob

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.content_filter import clean_for_memory, is_memory_noise

# OCR 常见误识别
DATE_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日")
TIME_RE = re.compile(r"^(昨天|今天|星期)?\s*\d{1,2}:\d{2}")
PURE_NUM_RE = re.compile(r"^[\d\(\)\[\]\s\.,]+$")


class HistoryReader:
    """读取 storage 聊天历史，提取 me 消息"""

    NOISE_EXACT = {
        "哈哈", "呵呵", "嗯", "嗯嗯", "哦", "好的", "好", "ok", "OK",
        "收到", "👍", "在", "在的", "？", "?", "。", "…", "...",
    }
    MIN_LEN = 2

    def __init__(self, history_dir: str = None):
        if history_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            history_dir = os.path.join(base, "storage", "history")
        self.history_dir = history_dir

    def collect(self) -> dict:
        """
        从所有好友 jsonl 采集

        Returns:
            {
              "my_messages": [{"sender":"me","text":"...","friend_id":"..."}, ...],
              "all_history": [...],  # 完整对话（按文件顺序拼接，用于样例）
              "sources": {"yangchunhui": 45, ...},  # 每个好友贡献的 me 条数
              "raw_count": 1200,      # 去重前
              "unique_count": 350,    # 去重后
              "files_read": 8,
            }
        """
        my_messages = []
        all_history = []
        sources: dict[str, int] = {}
        seen_texts: set[str] = set()
        raw_count = 0
        files_read = 0

        if not os.path.isdir(self.history_dir):
            return self._empty_result()

        for path in sorted(glob.glob(os.path.join(self.history_dir, "*.jsonl"))):
            friend_id = os.path.basename(path)[:-6]  # 去掉 .jsonl
            file_history = self._read_file(path)
            if not file_history:
                continue

            files_read += 1
            friend_me_count = 0

            for msg in file_history:
                all_history.append(msg)
                sender = msg.get("sender", "")
                if sender not in ("me", "我"):
                    continue

                text = clean_for_memory(
                    str(msg.get("text") or msg.get("content", "")).strip()
                )
                if not self._is_valid_me_message(text):
                    continue

                raw_count += 1
                norm = self._normalize(text)
                if norm in seen_texts:
                    continue
                seen_texts.add(norm)

                my_messages.append({
                    "sender": "me",
                    "text": text,
                    "friend_id": friend_id,
                })
                friend_me_count += 1

            if friend_me_count > 0:
                sources[friend_id] = friend_me_count

        return {
            "my_messages": my_messages,
            "all_history": all_history,
            "sources": sources,
            "raw_count": raw_count,
            "unique_count": len(my_messages),
            "files_read": files_read,
        }

    def _read_file(self, path: str) -> list[dict]:
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
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

    def _is_valid_me_message(self, text: str) -> bool:
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
        # 纯英文 OCR 乱码（超过80% ASCII 且很短）
        ascii_ratio = sum(c.isascii() for c in text) / max(len(text), 1)
        if ascii_ratio > 0.8 and len(text) < 15 and not any("\u4e00" <= c <= "\u9fff" for c in text):
            return False
        return True

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", text.lower())

    @staticmethod
    def _empty_result() -> dict:
        return {
            "my_messages": [],
            "all_history": [],
            "sources": {},
            "raw_count": 0,
            "unique_count": 0,
            "files_read": 0,
        }
