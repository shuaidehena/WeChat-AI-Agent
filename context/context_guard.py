"""
上下文保护器
发送消息前验证 friend_id 一致性，防止记忆/画像串好友
"""

import sys
import re

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ContextGuard:
    """上下文保护器

    确保: 回复消息时记忆和画像属于当前聊天对象
    """

    FRIEND_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

    @staticmethod
    def verify(expected_id: str, actual_id: str) -> bool:
        """验证 friend_id 一致"""
        if not expected_id or not actual_id:
            return bool(actual_id)
        if expected_id != actual_id:
            print(f"🛑 [Guard] 好友不匹配: 期望={expected_id}, 实际={actual_id}")
            return False
        return True

    @staticmethod
    def verify_memory(friend_id: str, memory_friend_id: str) -> bool:
        """验证记忆属于当前好友"""
        if not friend_id or not memory_friend_id:
            return True
        if friend_id != memory_friend_id:
            print(f"🛑 [Guard] 记忆隔离: {friend_id} 试图访问 {memory_friend_id} 的记忆")
            return False
        return True

    @staticmethod
    def verify_session(
        session_id: str,
        session_name: str,
        target_id: str,
        target_name: str = "",
    ) -> bool:
        """
        验证当前会话与目标好友一致

        session: 已绑定的活跃好友（FriendContext / MemoryService）
        target:  本次操作针对的好友
        """
        if not session_id:
            return False
        if not ContextGuard.verify(session_id, target_id):
            return False
        if session_name and target_name and session_name != target_name:
            # 同名冲突极少；friend_id 一致即可
            pass
        return True

    @staticmethod
    def require_friend_id(friend_id: str, operation: str = "操作") -> bool:
        """friend_id 必须非空且不能包含路径字符。"""
        if not friend_id or not ContextGuard.FRIEND_ID_RE.fullmatch(friend_id):
            print(f"🛑 [Guard] {operation} 的 friend_id 无效，已中止")
            return False
        return True
