"""
记忆管理器
统一管理用户画像、聊天风格、好友记忆、聊天历史

为后续 AI Agent 提供统一接口：
  - get_user_profile()     → 我是谁
  - get_style()            → 我怎么说话
  - get_friend_memory()    → 好友是谁
  - save_message()         → 记录聊天
  - get_history()          → 查询聊天历史
"""

import json
import os
import sys
from datetime import datetime

from memory.profile import UserProfile
from memory.style import ChatStyle
from memory.friend import FriendMemory
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryManager:
    """AI Agent 记忆管理器

    统一封装所有记忆模块，提供简洁的读写接口。
    后续 AI Agent 只需依赖这一个类即可获取全部上下文。
    """

    def __init__(self, storage_dir: str = "storage"):
        """
        Args:
            storage_dir: 数据文件存放目录
        """
        self.storage_dir = storage_dir

        # 子模块
        self.profile = UserProfile(f"{storage_dir}/profile.json")
        self.style = ChatStyle(f"{storage_dir}/style.json")
        self.friends = FriendMemory(f"{storage_dir}/friends.json")

        # 聊天记录文件
        self._messages_path = f"{storage_dir}/messages.json"
        self._messages: list[dict] = []
        self._load_messages()

    # ========== 用户画像 ==========

    def get_user_profile(self) -> dict:
        """获取用户个人信息"""
        return self.profile.get_profile()

    def update_profile(self, key: str, value) -> bool:
        """更新用户信息"""
        return self.profile.update(key, value)

    # ========== 聊天风格 ==========

    def get_style(self) -> dict:
        """获取聊天风格"""
        return self.style.get_style()

    def update_style(self, key: str, value) -> bool:
        """更新聊天风格"""
        return self.style.update(key, value)

    # ========== 好友记忆 ==========

    def get_friend_memory(self, name: str) -> dict | None:
        """
        获取指定好友的全部信息

        Returns:
            dict: {relation, tags, notes} 或 None
        """
        return self.friends.get_friend(name)

    def add_friend(self, name: str, relation: str = "",
                   tags: list = None, notes: list = None,
                   friend_id: str = "") -> bool:
        """新增或更新好友"""
        return self.friends.add_friend(
            name, relation, tags, notes, friend_id=friend_id
        )

    def remember_about_friend(self, name: str, note: str) -> bool:
        """给好友添加一条记忆"""
        return self.friends.update_memory(name, note)

    # ========== 聊天记录 ==========

    def save_message(self, friend_name: str, sender: str, content: str,
                     time_str: str = None) -> bool:
        """
        保存一条聊天记录

        Args:
            friend_name: 聊天对象名称
            sender: "friend" 或 "me"
            content: 消息内容
            time_str: 时间字符串，默认当前时间

        Returns:
            bool: 是否成功
        """
        record = {
            "friend": friend_name,
            "sender": sender,
            "content": content,
            "time": time_str or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._messages.append(record)
        return self._save_messages()

    def get_history(self, friend_name: str = None, limit: int = 20) -> list[dict]:
        """
        获取聊天历史

        Args:
            friend_name: 指定好友，None 返回全部
            limit: 返回最近 N 条

        Returns:
            list[dict]: 聊天记录列表
        """
        if friend_name:
            records = [m for m in self._messages if m["friend"] == friend_name]
        else:
            records = list(self._messages)

        return records[-limit:]

    def get_recent_context(self, friend_name: str, count: int = 10) -> list[dict]:
        """
        获取与好友的最近 N 条对话（供 AI Agent 构建上下文）

        Args:
            friend_name: 好友名称
            count: 条数

        Returns:
            list[dict]: 最近对话记录
        """
        return self.get_history(friend_name=friend_name, limit=count)

    # ========== 内部方法 ==========

    def _load_messages(self):
        """加载聊天记录"""
        if not os.path.exists(self._messages_path):
            self._messages = []
            return

        try:
            with open(self._messages_path, "r", encoding="utf-8") as f:
                self._messages = json.load(f)
            print(f"📨 聊天记录已加载: {len(self._messages)} 条")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 聊天记录读取失败: {e}")
            self._messages = []

    def _save_messages(self) -> bool:
        """保存聊天记录到文件"""
        try:
            os.makedirs(os.path.dirname(self._messages_path), exist_ok=True)
            write_json_atomic(self._messages_path, self._messages)
            return True
        except IOError as e:
            print(f"❌ 聊天记录保存失败: {e}")
            return False


# ========== 综合测试 ==========

if __name__ == "__main__":
    print("=" * 60)
    print("  MemoryManager 综合测试")
    print("=" * 60)

    mm = MemoryManager()

    # 测试1: 用户画像
    print("\n── 测试1: 用户画像 ──")
    profile = mm.get_user_profile()
    print(f"  姓名: {profile.get('name')}")
    print(f"  爱好: {profile.get('hobbies')}")

    # 测试2: 聊天风格
    print("\n── 测试2: 聊天风格 ──")
    style = mm.get_style()
    print(f"  语气: {style.get('tone')}")
    print(f"  常用词: {style.get('common_words')}")

    # 测试3: 好友查询
    print("\n── 测试3: 好友查询 ──")
    friend = mm.get_friend_memory("张三")
    print(f"  张三: {friend}")

    # 测试4: 保存聊天记录
    print("\n── 测试4: 聊天记录 ──")
    mm.save_message("张三", "friend", "最近怎么样")
    mm.save_message("张三", "me", "还行哈哈")
    history = mm.get_history("张三")
    print(f"  与张三的聊天历史 ({len(history)} 条):")
    for h in history:
        print(f"    [{h['sender']}] {h['content']} ({h['time']})")

    # 测试5: 新增好友
    print("\n── 测试5: 新增好友 ──")
    mm.add_friend("王五", relation="高中同学", tags=["篮球", "游戏"])
    print(f"  王五: {mm.get_friend_memory('王五')}")

    # 测试6: 给好友添加记忆
    print("\n── 测试6: 好友记忆 ──")
    mm.remember_about_friend("张三", "准备考研中")
    print(f"  张三记忆: {mm.get_friend_memory('张三')}")

    print("\n✅ MemoryManager 综合测试完成！")
