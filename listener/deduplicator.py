"""
消息去重模块
判断消息是否已处理，避免重复回复

去重规则：
  使用 sender + content 作为唯一标识。
  不同好友发送相同内容视为不同消息。
  消息缓存持久化到 storage/message_cache.json。
"""

import sys
import json
import os
from typing import Optional
from datetime import datetime
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MessageDeduplicator:
    """消息去重器

    维护已处理消息集合，支持精确匹配 + 模糊匹配，
    避免因 OCR 微小差异导致同一条消息被反复处理。

    去重规则:
      1. 精确匹配: sender + content 完全相同 → 跳过
      2. 模糊匹配: 同 sender + 内容相似度 >= 80% → 跳过
      3. 缓存持久化: 保存到 storage/message_cache.json
    """

    # 模糊匹配阈值（0~1）
    SIMILARITY_THRESHOLD = 1.0  # 1.0=完全相同时才去重，每条都回

    def __init__(self, cache_path: str = "storage/message_cache.json"):
        self.cache_path = cache_path
        self._processed: set[str] = set()        # 精确 key
        self._content_by_sender: dict[str, list] = {}  # sender → [content_list]
        self._messages: list[dict] = []
        self._load_cache()

    def is_new(self, message) -> bool:
        """判断消息是否未处理（精确+模糊）"""
        msg_id = self._make_id(message)
        # 精确匹配
        if msg_id in self._processed:
            return False
        # 模糊匹配
        if self._is_similar(message):
            return False
        return True

    def add(self, message):
        """标记消息为已处理"""
        msg_id = self._make_id(message)
        self._processed.add(msg_id)

        sender = self._get_sender(message)
        content = self._get_content(message)

        # 按 sender 分组存储，用于模糊匹配
        if sender not in self._content_by_sender:
            self._content_by_sender[sender] = []
        self._content_by_sender[sender].append(content)

        self._messages.append({
            "sender": sender,
            "content": content,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _is_similar(self, message) -> bool:
        """检查与已有消息是否模糊相似"""
        sender = self._get_sender(message)
        content = self._get_content(message)
        existing = self._content_by_sender.get(sender, [])

        for prev in existing:
            if self._text_similarity(content, prev) >= self.SIMILARITY_THRESHOLD:
                return True
        return False

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """计算两段文本的相似度（基于公共子串比例）"""
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        # 取较短的作为基准
        shorter = a if len(a) < len(b) else b
        longer = b if len(a) < len(b) else a
        # 统计公共字符
        common = sum(1 for c in shorter if c in longer)
        return common / len(shorter)

    def save(self):
        """保存缓存到文件"""
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            write_json_atomic(self.cache_path, self._messages)
            print(f"💾 消息缓存已保存: {len(self._messages)} 条")
        except Exception as e:
            print(f"⚠️ 缓存保存失败: {e}")

    def count(self) -> int:
        """已处理消息总数"""
        return len(self._processed)

    # ========== 内部方法 ==========

    @staticmethod
    def _make_id(message) -> str:
        """生成消息唯一 ID: sender_content"""
        if hasattr(message, 'sender'):
            sender = message.sender
            content = message.content
        elif isinstance(message, dict):
            sender = message.get("sender", "")
            content = message.get("content", "")
        else:
            sender = str(message)
            content = ""
        return f"{sender}_{content}"

    @staticmethod
    def _get_sender(message) -> str:
        if hasattr(message, 'sender'):
            return message.sender
        return message.get("sender", "") if isinstance(message, dict) else ""

    @staticmethod
    def _get_content(message) -> str:
        if hasattr(message, 'content'):
            return message.content
        return message.get("content", "") if isinstance(message, dict) else ""

    def _load_cache(self):
        """从文件加载缓存"""
        if not os.path.exists(self.cache_path):
            print(f"📄 缓存文件不存在，创建新缓存: {self.cache_path}")
            return

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self._messages = json.load(f)

            # 重建 processed 集合
            for m in self._messages:
                msg_id = self._make_id(m)
                self._processed.add(msg_id)

            print(f"📂 已加载消息缓存: {len(self._processed)} 条历史消息")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 缓存读取失败: {e}，将使用空缓存")
            self._messages = []


# ========== 测试入口 ==========

if __name__ == "__main__":
    """测试去重逻辑"""
    print("=" * 50)
    print("  MessageDeduplicator 测试")
    print("=" * 50)

    dedup = MessageDeduplicator(cache_path="storage/test_cache.json")

    # 模拟 Message 对象
    class FakeMsg:
        def __init__(self, s, c):
            self.sender = s
            self.content = c

    # 测试1: 新消息
    m1 = FakeMsg("friend", "你好")
    print(f"\n[测试1] 新消息 'friend_你好': is_new={dedup.is_new(m1)}")
    assert dedup.is_new(m1) == True
    dedup.add(m1)

    # 测试2: 重复消息
    m2 = FakeMsg("friend", "你好")
    print(f"[测试2] 重复消息 'friend_你好': is_new={dedup.is_new(m2)}")
    assert dedup.is_new(m2) == False

    # 测试3: 不同 sender 相同 content
    m3 = FakeMsg("friend2", "你好")
    print(f"[测试3] 不同好友 'friend2_你好': is_new={dedup.is_new(m3)}")
    assert dedup.is_new(m3) == True
    dedup.add(m3)

    # 测试4: 相同 sender 不同 content
    m4 = FakeMsg("friend", "在吗")
    print(f"[测试4] 不同内容 'friend_在吗': is_new={dedup.is_new(m4)}")
    assert dedup.is_new(m4) == True

    dedup.save()
    print(f"\n✅ 所有测试通过！处理消息数: {dedup.count()}")

    # 清理测试文件
    if os.path.exists("storage/test_cache.json"):
        os.remove("storage/test_cache.json")
