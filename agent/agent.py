"""
Agent 核心模块
协调决策、上下文、Prompt 生成、LLM 调用

数据流:
  消息 → Decision(判断是否回复) → Context(获取历史)
       → PromptBuilder(生成Prompt) → LLMClient(调用LLM) → 返回结果
"""

import sys
from agent.decision import ReplyDecision
from agent.context import ConversationContext
from agent.prompt import PromptBuilder
from agent.reply_guard import ReplyGuard
from llm.client import LLMClient
from wechat.sender import WeChatSender
from utils.chat_logger import ChatLogger
from utils.privacy import display_text

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatAgent:
    """微信聊天 AI Agent

    完整流程:
      消息 → 判断回复 → 构建Prompt → LLM生成 → 安全检查 → 微信发送 → 日志

    Attributes:
        auto_send: 是否自动发送到微信（True=自动, False=仅生成回复）
    """

    def __init__(self, profile: dict = None, style: dict = None,
                 auto_send: bool = False):
        """
        Args:
            profile:   用户画像
            style:     聊天风格
            auto_send: 是否自动发送到微信
        """
        self.profile = profile or {}
        self.style = style or {}
        self.auto_send = auto_send

        # 子模块
        self.decision = ReplyDecision()
        self.context = ConversationContext(max_size=20)
        self.prompt_builder = PromptBuilder()
        self.llm = LLMClient()
        self.guard = ReplyGuard()
        self.sender = WeChatSender()
        self.logger = ChatLogger()

        # 好友信息（外部设置）
        self._friend_info: dict = {}
        self._friend_name: str = ""

        # 回复冷却：发完一条后跳过 `cooldown_rounds` 轮
        self._cooldown_rounds = 0   # 0=每条都回
        self._cooldown_remaining = 0
        self._last_replied_content = ""  # 上一轮回复的内容（精确去重）

    # ========== 主入口 ==========

    def process_message(
        self,
        message,
        memories: list[str] = None,
        profile_text: str = "",
        history_context: list[dict] = None,
        screen_messages: list = None,
        style_context: dict = None,
        knowledge: list[dict] = None,
    ) -> dict:
        """
        处理一条消息

        Args:
            message:  Message 对象或 dict (含 sender, content)
            memories: 长期记忆列表 ["正在准备考研", "喜欢篮球"]

        Returns:
            dict: {need_reply, reply, prompt, context_size, sent, status}
        """
        content = self._get_content(message)
        sender = self._get_sender(message)

        print(f"\n📩 收到消息: [{sender}] {display_text(content)}")

        # 0. 冷却检查：刚发完回复，暂停几轮
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            # 冷却期间只记录上下文，不处理新消息
            self.context.add_message(message)
            if self._cooldown_remaining == 0:
                print("  🟢 冷却结束，恢复监听")
            else:
                print(f"  ⏳ 冷却中（剩余 {self._cooldown_remaining} 轮）")
            return {
                "need_reply": False, "reply": "", "prompt": "",
                "context_size": self.context.size(), "sent": False, "status": "cooldown",
            }

        # 1. 判断是否需要回复
        need_reply = self.decision.should_reply(message)

        # 2. 记录到上下文（无论是否回复都记录）
        self.context.add_message(message)

        # 3-4. 只构建一次完整 Prompt 并生成回复
        prompt = ""
        reply = ""
        if need_reply:
            reply, prompt = self._generate_reply(
                message=message,
                memories=memories,
                profile_text=profile_text,
                history_context=history_context,
                screen_messages=screen_messages,
                style_context=style_context,
                knowledge=knowledge,
            )

        # 5. 安全检查 + 发送 + 日志
        sent = False
        outgoing = reply
        if need_reply and reply:
            ok, reason = self.guard.check(reply)
            if ok and self.auto_send:
                outgoing = WeChatSender.format_outgoing(reply)
                ok, reason = self.guard.check(outgoing)
                if ok:
                    sent = self.sender.send(outgoing, expected_name=self._friend_name)
                    status = "sent" if sent else "failed"
                    if sent:
                        self.context.add_message({"sender": "我", "content": outgoing})
                else:
                    print(f"  🛑 回复被拦截: {reason}")
                    self.logger.log_reply(self._friend_name, outgoing, "blocked")
                    status = "blocked"
            elif not ok:
                print(f"  🛑 回复被拦截: {reason}")
                self.logger.log_reply(self._friend_name, reply, "blocked")
                status = "blocked"
            else:
                status = "generated"
                self.logger.log_info(f"回复已生成（未自动发送，{len(reply)}字）")
        else:
            status = "skipped"

        # 记录日志 + 启动冷却
        if need_reply and reply and status in ("sent", "generated"):
            log_text = outgoing if sent else reply
            self.logger.log_reply(self._friend_name, log_text, status)
            self._cooldown_remaining = self._cooldown_rounds
            self._last_replied_content = log_text
            print(f"  ⏳ 冷却 {self._cooldown_rounds} 轮（防止重复回复）")

        result = {
            "need_reply": need_reply,
            "reply": outgoing if sent else reply,
            "prompt": prompt,
            "context_size": self.context.size(),
            "sent": sent,
            "status": status,
        }

        print(f"  → need_reply={need_reply}, reply={display_text(result['reply'], 40)}, status={status}")
        return result

    # ========== 好友信息 ==========

    def set_friend_info(self, friend_name: str, info: dict):
        """
        设置当前聊天对象的信息

        Args:
            friend_name: 好友名称
            info: {"relation":"同学","tags":[...],"notes":[...]}
        """
        self._friend_name = friend_name
        self._friend_info = info
        self._friend_info["name"] = friend_name

    def set_window_rect(self, rect: dict):
        """设置微信窗口坐标（用于定位输入框）"""
        self.sender.set_window_rect(rect)
        self.logger.log_info(f"窗口坐标已更新: {rect['width']}x{rect['height']}")

    def set_wechat(self, wechat):
        """绑定微信窗口，发送前自动激活"""
        self.sender.set_wechat(wechat)

    def set_pre_send_guard(self, guard):
        """绑定发送前联系人身份复核函数。"""
        self.sender.set_pre_send_guard(guard)

    # ========== 上下文管理 ==========

    def get_context(self) -> ConversationContext:
        """获取上下文管理器"""
        return self.context

    def clear_context(self):
        """清空上下文（切换聊天对象时调用）"""
        self.context.clear()
        self._friend_info = {}
        self._friend_name = ""

    # ========== 内部方法 ==========

    def _generate_reply(
        self,
        message,
        memories: list[str] = None,
        profile_text: str = "",
        history_context: list[dict] = None,
        screen_messages: list = None,
        style_context: dict = None,
        knowledge: list[dict] = None,
    ) -> tuple[str, str]:
        """生成回复：构建 Prompt → 调用 LLM"""
        prompt = self.prompt_builder.build(
            message=message,
            context=self.context.get_recent_messages(count=20),
            style=self.style,
            profile=self.profile,
            friend_info=self._friend_info,
            memories=memories,
            knowledge=knowledge,
            friend_profile_text=profile_text,
            history_context=history_context,
            screen_messages=screen_messages,
            style_context=style_context,
            friend_name=self._friend_name,
            personal_style=self._load_personal_style(),
        )
        self._save_prompt_debug(prompt, history_context, screen_messages)
        return self.llm.chat(prompt, task="chat"), prompt

    def _load_personal_style(self):
        """加载个人风格模型"""
        try:
            from personal.style_storage import StyleStorage
            return StyleStorage().load()
        except Exception:
            return None

    def _save_prompt_debug(
        self,
        prompt: str,
        history_context: list = None,
        screen_messages: list = None,
    ):
        """保存最近一次 Prompt 供调试"""
        try:
            import os
            if os.getenv("WECHAT_SAVE_DEBUG_PROMPT", "0") != "1":
                return
            from utils.atomic_io import write_text_atomic
            os.makedirs("debug", exist_ok=True)
            h = len(history_context or [])
            s = len(screen_messages or [])
            header = f"# history={h}, screen={s}\n\n"
            write_text_atomic("debug/last_prompt.txt", header + prompt)
        except Exception:
            pass

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


# ========== 综合测试 ==========

if __name__ == "__main__":
    print("=" * 60)
    print("  ChatAgent 综合测试")
    print("=" * 60)

    class M:
        def __init__(self, s, c):
            self.sender = s
            self.content = c

    # 初始化 Agent
    agent = ChatAgent(
        profile={"name": "小明", "current_status": "在读大学生", "hobbies": ["编程", "篮球"]},
        style={"tone": "casual", "sentence_length": "short", "common_words": ["哈哈", "确实"], "emoji_frequency": "low"},
    )
    class FakeLLM:
        @staticmethod
        def chat(prompt, task="chat"):
            return "测试回复"

    agent.llm = FakeLLM()
    class FakeLogger:
        @staticmethod
        def log_info(*args, **kwargs):
            pass

        @staticmethod
        def log_reply(*args, **kwargs):
            pass

    agent.logger = FakeLogger()
    agent.set_friend_info("张三", {
        "relation": "大学同学",
        "tags": ["考研", "篮球"],
        "notes": ["最近准备考研"],
    })

    # ---- 测试1: 好友语气词也按当前策略回复 ----
    print("\n── 测试1: 语气词（回复）──")
    r = agent.process_message(M("friend", "哈哈"))
    assert r["need_reply"] is True
    assert r["reply"] == "测试回复"
    assert r["context_size"] == 1
    print("✅ 测试1 通过")

    # ---- 测试2: 需要回复的消息 ----
    print("\n── 测试2: 问句（需回复）──")
    r = agent.process_message(M("friend", "最近怎么样？"))
    assert r["need_reply"] == True
    assert r["reply"] != ""
    assert r["context_size"] == 2
    # Prompt 应包含上下文
    assert "在吗" not in r["prompt"]  # 这条还没加
    assert "最近怎么样" in r["prompt"]
    print("✅ 测试2 通过")

    # ---- 测试3: 上下文保留 ----
    print("\n── 测试3: 上下文检查 ──")
    ctx = agent.get_context()
    msgs = ctx.get_recent_messages()
    assert len(msgs) == 2
    assert msgs[0]["content"] == "哈哈"
    assert msgs[1]["content"] == "最近怎么样？"
    print(f"  上下文: {msgs}")
    print("✅ 测试3 通过")

    # ---- 测试4: 自己的消息不回复 ----
    print("\n── 测试4: 自己消息（不回复）──")
    r = agent.process_message(M("me", "还行哈哈"))
    assert r["need_reply"] == False
    print("✅ 测试4 通过")

    # ---- 测试5: Prompt 包含所有信息 ----
    print("\n── 测试5: Prompt 完整性 ──")
    r = agent.process_message(M("friend", "考研准备得怎么样了"))
    assert r["need_reply"] == True
    assert "小明" in r["prompt"]
    assert "大学同学" in r["prompt"]
    assert "考研" in r["prompt"]
    assert "最近怎么样" in r["prompt"]
    print(f"  Prompt 长度: {len(r['prompt'])} 字符")
    print("✅ 测试5 通过")

    # ---- 测试6: 确认词也按当前策略回复 ----
    print("\n── 测试6: 确认词回复 ──")
    r = agent.process_message(M("friend", "好的"))
    assert r["need_reply"] is True
    assert r["prompt"]
    assert r["context_size"] == 5  # 上下文仍记录
    print("✅ 测试6 通过")

    print(f"\n{'=' * 60}")
    print("  ✅ 全部 6 项测试通过！")
    print(f"{'=' * 60}")
