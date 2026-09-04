"""
回复安全检查模块
在发送前检查 AI 回复是否安全、合理

检查项:
  1. 回复不能为空
  2. 长度不超过限制
  3. 不包含风险词
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ReplyGuard:
    """回复安全检查器

    在 AI 回复发送到微信前进行安全检查，
    防止不合适的消息被发出。
    """

    # 最大回复长度（字符数）
    MAX_LENGTH = 120

    # 风险词列表（包含任一则拒绝发送）
    RISK_WORDS = [
        "我是AI", "我是人工智能", "作为一个AI", "作为AI",
        "我是机器人", "我是助手", "AI助手",
        "I am an AI", "as an AI",
        "根据我的训练数据", "根据我的知识",
        "我不能", "我无法回答",
    ]

    # 错误前缀（API 错误等）
    ERROR_PREFIXES = ["[错误]", "[配置错误]", "Error:", "[ERROR]"]

    def check(self, reply: str) -> tuple[bool, str]:
        """
        检查回复是否允许发送

        Args:
            reply: AI 生成的回复文本

        Returns:
            (允许发送, 原因):
                (True, "ok") — 允许
                (False, "原因") — 拒绝
        """
        # 1. 空内容
        if not reply or not reply.strip():
            return False, "回复为空"

        reply = reply.strip()

        # 2. API 错误消息
        for prefix in self.ERROR_PREFIXES:
            if reply.startswith(prefix):
                return False, f"API错误: {reply[:50]}"

        # 3. 长度限制
        if len(reply) > self.MAX_LENGTH:
            return False, f"回复过长 ({len(reply)} > {self.MAX_LENGTH})"

        # 4. 风险词检查
        for word in self.RISK_WORDS:
            if word in reply:
                return False, f"包含风险词: \"{word}\""

        return True, "ok"


# ========== 测试 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  ReplyGuard 测试")
    print("=" * 50)

    guard = ReplyGuard()

    tests = [
        ("还行哈哈", True),
        ("", False),
        ("[错误] API超时", False),
        ("我是AI助手，很高兴为你服务", False),
        ("a" * 150, False),
        ("好的，晚上见", True),
    ]

    all_pass = True
    for reply, expected in tests:
        ok, reason = guard.check(reply)
        status = "✅" if ok == expected else "❌"
        if ok != expected:
            all_pass = False
        print(f"  {status} \"{reply[:40]}\" → {ok} ({reason})")

    print(f"\n{'✅ 全部通过' if all_pass else '❌ 有失败'}")
