"""
上下文管理模块
管理短期聊天上下文（最近对话记录）

为 AI 生成回复提供对话历史参考，
只保留最近 N 条消息，超出自动淘汰。
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ConversationContext:
    """短期对话上下文

    保存最近的聊天记录，提供给 PromptBuilder 构建上下文。
    默认保存最近 20 条消息。
    """

    def __init__(self, max_size: int = 20):
        """
        Args:
            max_size: 最大保存消息数，默认 20 条
        """
        self.max_size = max_size
        self._messages: list[dict] = []

    def add_message(self, message):
        """
        添加一条消息到上下文

        Args:
            message: Message 对象或 dict（含 sender, content）
        """
        record = {
            "sender": self._get_sender(message),
            "content": self._get_content(message),
        }
        self._messages.append(record)

        # 超出限制时淘汰最旧的
        while len(self._messages) > self.max_size:
            self._messages.pop(0)

    def add_messages(self, messages: list):
        """批量添加消息"""
        for msg in messages:
            self.add_message(msg)

    def get_recent_messages(self, count: int = None) -> list[dict]:
        """
        获取最近 N 条消息

        Args:
            count: 获取条数，默认返回全部

        Returns:
            list[dict]: [{"sender":"friend","content":"..."}, ...]
        """
        if count is None:
            return list(self._messages)
        return self._messages[-count:]

    def get_last_message(self) -> dict | None:
        """获取最后一条消息"""
        return self._messages[-1] if self._messages else None

    def clear(self):
        """清空上下文"""
        self._messages.clear()

    def size(self) -> int:
        """当前消息数"""
        return len(self._messages)

    # ========== 工具方法 ==========

    @staticmethod
    def _get_content(message) -> str:
        if hasattr(message, 'content'):
            return message.content
        elif isinstance(message, dict):
            return message.get("content", "")
        return str(message)

    @staticmethod
    def _get_sender(message) -> str:
        if hasattr(message, 'sender'):
            return message.sender
        elif isinstance(message, dict):
            return message.get("sender", "")
        return ""


# ========== 测试 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  ConversationContext 测试")
    print("=" * 50)

    class M:
        def __init__(self, s, c):
            self.sender = s
            self.content = c

    ctx = ConversationContext(max_size=5)

    # 测试1: 添加消息
    ctx.add_message(M("friend", "最近怎么样"))
    ctx.add_message(M("me", "还行哈哈"))
    ctx.add_message(M("friend", "晚上一起吃饭吗"))
    print(f"\n[测试1] 添加3条: size={ctx.size()}")
    assert ctx.size() == 3

    # 测试2: 获取最近消息
    recent = ctx.get_recent_messages(2)
    print(f"[测试2] 最近2条: {recent}")
    assert len(recent) == 2
    assert recent[-1]["content"] == "晚上一起吃饭吗"

    # 测试3: 超出限制
    for i in range(5):
        ctx.add_message(M("friend", f"消息{i}"))
    print(f"[测试3] 超出max_size后: size={ctx.size()} (max=5)")
    assert ctx.size() == 5
    # 最旧的已被淘汰，第一条是"消息0"
    first = ctx.get_recent_messages()[0]["content"]
    print(f"  第一条: \"{first}\" (应该是\"消息0\")")
    assert first == "消息0"

    # 测试4: 清空
    ctx.clear()
    print(f"[测试4] 清空后: size={ctx.size()}")
    assert ctx.size() == 0

    print("\n✅ 全部通过！")
