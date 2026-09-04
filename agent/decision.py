"""
回复决策模块
判断收到的消息是否需要 AI 回复

规则：
  不回复: 单字确认类（哈哈、嗯、好的、收到、哦、OK）
  需回复: 问句、较长的陈述、新话题
"""

import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ReplyDecision:
    """回复决策器

    判断收到的消息是否需要回复，避免对无意义消息过度响应。
    """

    # 默认不回复的消息模式
    NO_REPLY_EXACT = {
        "哈哈", "呵呵", "嘿嘿", "嘻嘻",
        "嗯", "嗯嗯", "嗯嗯嗯",
        "好的", "好", "ok", "OK", "Ok",
        "收到", "知道了", "明白",
        "哦", "哦哦", "噢",
        "1", "2", "3",
        "。", "…", "...",
    }

    # 包含这些词的消息需要回复
    NEED_REPLY_PATTERNS = [
        r'\?', r'？',            # 问号 → 问题
        r'在吗', r'在不在',       # 询问在线
        r'怎么', r'如何',         # 询问方式
        r'什么', r'啥',           # 询问内容
        r'哪里', r'哪儿',         # 询问地点
        r'几点', r'什么时候',     # 询问时间
        r'能不能', r'可以吗',     # 请求
        r'帮我', r'帮忙',         # 求助
        r'有空', r'忙吗',         # 邀约
    ]

    def should_reply(self, message) -> bool:
        """
        对方发的每条消息都回（除了自己的和系统消息）
        """
        content = self._get_content(message)
        sender = self._get_sender(message)

        # 自己的消息不回复
        if sender in ("me", "我"):
            return False

        content = content.strip()
        if not content:
            return False

        # 系统消息不回复
        if content in {"[图片]", "[视频]", "[语音]", "[文件]", "[链接]", "[表情]"}:
            return False

        # 对方发的都回
        return True

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
    print("  ReplyDecision 测试")
    print("=" * 50)

    dec = ReplyDecision()

    # 模拟 Message
    class M:
        def __init__(self, s, c):
            self.sender = s
            self.content = c

    tests = [
        (M("friend", "哈哈"), True,   "对方发的"),
        (M("friend", "嗯"), True,     "对方发的"),
        (M("friend", "最近怎么样"), True, "对方发的"),
        (M("me", "哈哈"), False,      "自己的不回复"),
        (M("me", "在吗"), False,      "自己的不回复"),
        (M("friend", "[图片]"), False, "系统消息"),
    ]

    all_pass = True
    for msg, expected, desc in tests:
        result = dec.should_reply(msg)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_pass = False
        print(f"  {status} {desc}: \"{msg.content}\" → {result} (预期 {expected})")

    print(f"\n{'✅ 全部通过' if all_pass else '❌ 有失败'}")
