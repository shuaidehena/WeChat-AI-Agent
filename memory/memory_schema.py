"""
记忆数据结构
定义长期记忆的数据格式
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryItem:
    """一条长期记忆"""

    friend_id: str
    type: str              # fact | preference | event | relationship | goal | habit | identity
    content: str           # 总结后的记忆文本
    importance: float = 0.5
    time: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    source: str = "chat"   # chat | rule | llm | history_init
    source_quote: str = "" # 原始聊天片段

    def to_dict(self) -> dict:
        return {
            "friend_id": self.friend_id,
            "type": self.type,
            "content": self.content,
            "importance": self.importance,
            "time": self.time,
            "source": self.source,
            "source_quote": self.source_quote,
        }

    def __str__(self):
        return f"[{self.type}] {self.content} (重要性:{self.importance})"
