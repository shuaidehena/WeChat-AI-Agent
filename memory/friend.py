"""
好友记忆模块
管理好友信息和与好友的互动记忆
"""

import json
import os
import sys
from datetime import datetime
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class FriendMemory:
    """好友记忆管理器

    从 storage/friends.json 读取好友信息，
    支持新增好友、更新记忆、查询好友。

    数据格式:
      {
        "好友名": {
          "relation": "大学同学",
          "tags": ["考研", "篮球"],
          "notes": ["最近准备考研"],
          "first_met": "2026-01-01"
        }
      }
    """

    def __init__(self, filepath: str = "storage/friends.json"):
        self.filepath = filepath
        self._data: dict = {}
        self.load()

    def load(self) -> dict:
        """从文件加载好友信息"""
        if not os.path.exists(self.filepath):
            print(f"⚠️ 好友信息文件不存在: {self.filepath}")
            self._data = {}
            return self._data

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            print(f"👥 好友信息已加载: {len(self._data)} 位好友")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 好友信息读取失败: {e}")
            self._data = {}
        return self._data

    def save(self) -> bool:
        """保存好友信息到文件"""
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            write_json_atomic(self.filepath, self._data)
            return True
        except IOError as e:
            print(f"❌ 好友信息保存失败: {e}")
            return False

    # ========== 好友操作 ==========

    def add_friend(self, name: str, relation: str = "",
                   tags: list = None, notes: list = None,
                   friend_id: str = "") -> bool:
        """新增好友或更新已有好友"""
        if name in self._data:
            print(f"⚠️ 好友 '{name}' 已存在，将更新信息")

        entry = {
            "relation": relation,
            "tags": tags or [],
            "notes": notes or [],
            "first_met": datetime.now().strftime("%Y-%m-%d"),
            "name": name,
        }
        if friend_id:
            entry["friend_id"] = friend_id
        elif name in self._data and self._data[name].get("friend_id"):
            entry["friend_id"] = self._data[name]["friend_id"]

        self._data[name] = entry
        return self.save()

    def get_friend_id(self, name: str) -> str | None:
        """获取好友的英文 friend_id"""
        friend = self._data.get(name)
        if not friend:
            return None
        return friend.get("friend_id")

    def update_memory(self, name: str, note: str) -> bool:
        """
        给好友添加一条记忆

        Args:
            name: 好友名称
            note: 记忆内容（如 "他说下个月要考研"）

        Returns:
            bool: 是否成功
        """
        if name not in self._data:
            # 自动创建好友
            self._data[name] = {
                "relation": "",
                "tags": [],
                "notes": [],
                "first_met": datetime.now().strftime("%Y-%m-%d"),
            }

        self._data[name]["notes"].append(note)
        return self.save()

    def get_friend(self, name: str) -> dict | None:
        """
        查询好友信息

        Args:
            name: 好友名称

        Returns:
            dict: 好友信息，不存在返回 None
        """
        return self._data.get(name)

    def get_all_friends(self) -> dict:
        """返回所有好友信息"""
        return self._data.copy()

    def get_friend_tags(self, name: str) -> list:
        """获取好友标签"""
        friend = self._data.get(name, {})
        return friend.get("tags", [])

    def get_friend_notes(self, name: str) -> list:
        """获取好友记忆"""
        friend = self._data.get(name, {})
        return friend.get("notes", [])


# ========== 测试 ==========

if __name__ == "__main__":
    fm = FriendMemory()

    # 测试查询
    friend = fm.get_friend("张三")
    print(f"\n好友 '张三': {friend}")

    # 测试新增
    fm.add_friend("李四", relation="同事", tags=["工作", "技术"], notes=["上周一起吃饭"])
    print(f"\n新增 '李四': {fm.get_friend('李四')}")

    # 测试更新记忆
    fm.update_memory("张三", "他说下个月考研")
    print(f"\n更新 '张三' 记忆: {fm.get_friend('张三')}")
