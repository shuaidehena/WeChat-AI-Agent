"""
历史消息去重
防止滚动时重叠区域的消息被重复保存
"""

import sys
import hashlib

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryDeduplicator:
    """历史消息去重器

    使用 sender+text+位置 生成哈希，过滤重复消息
    """

    def __init__(self):
        self._seen: set[str] = set()

    def is_new(self, msg: dict) -> bool:
        """判断消息是否未见过"""
        key = self._make_key(msg)
        return key not in self._seen

    def add(self, msg: dict):
        """标记消息为已处理"""
        key = self._make_key(msg)
        self._seen.add(key)

    def count(self) -> int:
        return len(self._seen)

    @staticmethod
    def _make_key(msg: dict) -> str:
        text = msg.get("text", "")
        sender = msg.get("sender", "")
        y = int(msg.get("y", 0) / 50) * 50  # 量化Y（去OCR微小抖动）
        raw = f"{sender}_{text}_{y}"
        return hashlib.md5(raw.encode()).hexdigest()[:8]
