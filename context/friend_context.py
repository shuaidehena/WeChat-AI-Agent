"""
好友上下文管理器
维护当前聊天对象，确保记忆和画像绑定正确
"""

import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class FriendContextManager:
    """好友上下文管理器

    追踪当前正在聊天的好友，切换时自动清旧加载新。
    """

    def __init__(self):
        self._current_id: str = ""
        self._current_name: str = ""
        self._switch_time: float = 0
        self._switch_count: int = 0

    # ========== 操作 ==========

    def set_friend(self, friend_id: str, friend_name: str = ""):
        """切换当前好友"""
        old_id = self._current_id
        self._current_id = friend_id
        self._current_name = friend_name or friend_id
        self._switch_time = time.time()
        self._switch_count += 1

        if old_id != friend_id:
            print(f"🔄 [Context] {old_id or '(无)'} → {friend_id}")

    def get_current(self) -> dict:
        """获取当前好友"""
        return {
            "id": self._current_id,
            "name": self._current_name,
        }

    @property
    def friend_id(self) -> str:
        return self._current_id

    @property
    def friend_name(self) -> str:
        return self._current_name

    def is_same_friend(self, friend_id: str) -> bool:
        return self._current_id == friend_id

    def clear(self):
        self._current_id = ""
        self._current_name = ""

    def is_set(self) -> bool:
        return bool(self._current_id)
