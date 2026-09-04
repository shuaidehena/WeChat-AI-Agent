"""
用户画像 + 好友画像数据结构
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from utils.atomic_io import write_json_atomic


class UserProfile:
    """用户画像管理器（自身信息）"""

    def __init__(self, filepath: str = "storage/profile.json"):
        self.filepath = filepath
        self._data: dict = {}
        self.load()

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            self._data = {}
            return self._data
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._data = {}
        return self._data

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            write_json_atomic(self.filepath, self._data)
            return True
        except IOError:
            return False

    def get_profile(self) -> dict:
        return self._data.copy()

    def update(self, key: str, value) -> bool:
        self._data[key] = value
        return self.save()


@dataclass
class FriendProfile:
    """好友画像（综合长期记忆 + 聊天历史总结）"""

    friend_id: str = ""
    name: str = ""
    relationship: str = ""
    interests: list[str] = field(default_factory=list)
    personality: list[str] = field(default_factory=list)
    communication_style: list[str] = field(default_factory=list)
    common_topics: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    recent_summary: str = ""
    background: str = ""              # 工作/学校/所在地等背景
    current_status: str = ""          # 当前状态（比 recent_summary 更具体）
    summary: str = ""                 # 整体概括（100字内）
    dislikes: list[str] = field(default_factory=list)   # 讨厌/雷点
    how_to_talk: list[str] = field(default_factory=list)  # 和TA聊天注意点
    relationship_notes: str = ""      # 认识经过/关系细节
    voice_samples: list[str] = field(default_factory=list)
    history_count: int = 0          # storage 中 friend 消息数（去重后）
    data_source: str = "storage/history"
    updated_time: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    memory_count: int = 0           # 向量记忆条数

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FriendProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def is_empty(self) -> bool:
        return not any([
            self.relationship, self.interests, self.personality,
            self.communication_style, self.common_topics,
            self.key_facts, self.recent_summary, self.background,
            self.current_status, self.summary, self.dislikes,
            self.how_to_talk, self.relationship_notes,
        ])
