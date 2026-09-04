"""
新好友自动建档

记忆库中不存在的好友首次发消息时：
  1. 中文名 → 拼音 friend_id
  2. 写入 friends.json / name_map.json
  3. 初始化 profile 与向量记忆目录
  4. 将消息写入 JSONL 历史
"""

import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from context.name_mapper import FriendNameMapper
from context.title_name_validator import TitleNameValidator
from memory.friend import FriendMemory
from memory.profile import FriendProfile
from memory.content_filter import clean_for_memory, is_memory_noise
from utils.atomic_io import write_json_atomic
from history.storage import HistoryStorage
import json


class FriendRegistry:
    """好友注册中心：确保好友在记忆系统中存在"""

    def __init__(self, storage_dir: str = "storage"):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)

        self.storage_dir = storage_dir
        self.name_mapper = FriendNameMapper(
            map_path=os.path.join(storage_dir, "name_map.json"),
            storage_dir=storage_dir,
        )
        self.friends = FriendMemory(os.path.join(storage_dir, "friends.json"))
        self._validator = TitleNameValidator(storage_dir=storage_dir)
        self._known_ids: set[str] = set()

    def ensure_friend(self, chinese_name: str) -> str:
        """
        确保好友已建档，返回 friend_id（英文拼音）

        Args:
            chinese_name: 微信显示名（中文）

        Returns:
            friend_id 如 "yangchunhui"
        """
        name = (chinese_name or "").strip()
        if not name:
            return ""

        self._validator._reload_known()
        valid, reason = self._validator.validate(name)
        if not valid:
            print(f"  ⚠️ 忽略无效好友名: {name} ({reason})")
            return ""

        friend_id = self.name_mapper.resolve_or_create(name)
        if not friend_id:
            return ""

        is_new = name not in self.friends.get_all_friends()
        if is_new:
            self.friends.add_friend(name, friend_id=friend_id)
            self._create_profile(friend_id, name)
            print(f"  ✨ 新好友建档: {name} → {friend_id}")

        self._known_ids.add(friend_id)
        return friend_id

    def exists(self, chinese_name: str) -> bool:
        """是否已在记忆库中"""
        name = (chinese_name or "").strip()
        if not name:
            return False
        if name in self.friends.get_all_friends():
            return True
        return self.name_mapper.get_id(name) is not None

    def save_incoming_messages(self, friend_id: str, messages: list) -> int:
        """
        将收到的好友消息写入 JSONL 历史

        Args:
            friend_id: 英文 ID
            messages: Message 对象或 dict 列表

        Returns:
            写入条数
        """
        if not friend_id or not messages:
            return 0

        records = []
        for msg in messages:
            content = clean_for_memory(self._get_content(msg))
            if not content or is_memory_noise(content):
                continue
            records.append({"sender": "friend", "text": content})

        if not records:
            return 0

        HistoryStorage(friend_id).save(records)
        print(f"  📝 已存入历史: {len(records)} 条 → storage/history/{friend_id}.jsonl")
        return len(records)

    def get_friend_id(self, chinese_name: str) -> str | None:
        """仅查询 friend_id，不创建"""
        name = (chinese_name or "").strip()
        if not name:
            return None
        fid = self.name_mapper.get_id(name)
        if fid:
            return fid
        friend = self.friends.get_friend(name)
        if friend:
            return friend.get("friend_id")
        return None

    # ========== 内部 ==========

    def _create_profile(self, friend_id: str, chinese_name: str):
        profile_dir = os.path.join(self.storage_dir, "profiles")
        os.makedirs(profile_dir, exist_ok=True)
        path = os.path.join(profile_dir, f"{friend_id}.json")

        if os.path.exists(path):
            return

        profile = FriendProfile(friend_id=friend_id, name=chinese_name)
        write_json_atomic(path, profile.to_dict())

    @staticmethod
    def _get_content(msg) -> str:
        if hasattr(msg, "content"):
            return str(msg.content).strip()
        if isinstance(msg, dict):
            return str(msg.get("text") or msg.get("content", "")).strip()
        return str(msg).strip()
