"""
系统运行器
管理整个 AI Agent 程序的生命周期和主循环

数据流:
  MessageListener(轮询消息) → ChatAgent(处理+回复) → 循环

状态:
  RUNNING  — 正常运行
  PAUSED   — 暂停（手动或微信断连）
  STOPPED  — 已停止
"""

import sys
import os
import time
import signal
from enum import Enum

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wechat.window import WeChatWindow
from listener.message_listener import MessageListener
from wechat.unread_detector import UnreadDetector
from wechat.contact_switcher import ContactSwitcher
from wechat.identity_verifier import ChatIdentityVerifier
from context.friend_context import FriendContextManager
from context.identity_resolver import IdentityResolver
from memory.friend_registry import FriendRegistry
from context.title_name_validator import TitleNameValidator
from memory.memory_manager import MemoryManager
from memory.memory_service import MemoryService
from knowledge.base import PersonalKnowledgeBase
from agent.agent import ChatAgent
from parser.message import Message
from listener.chat_tracker import ChatTracker
from utils.privacy import display_text


class State(Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class AgentRunner:
    """AI Agent 运行器

    统一管理: 微信窗口、消息监听、Agent、记忆系统，
    在单一主循环中协调所有模块。

    用法:
        runner = AgentRunner()
        runner.start()   # 阻塞运行，Ctrl+C 停止
    """

    def __init__(self, auto_send: bool = True, listen_interval: float = 2.0):
        """
        Args:
            auto_send:       是否自动发送到微信
            listen_interval: 消息轮询间隔（秒）
        """
        self.auto_send = auto_send
        self.listen_interval = listen_interval
        self._state = State.STOPPED

        # 各模块
        self._wechat: WeChatWindow | None = None
        self._listener: MessageListener | None = None
        self._unread_detector: UnreadDetector | None = None
        self._switcher: ContactSwitcher | None = None
        self._memory: MemoryManager | None = None
        self._knowledge: PersonalKnowledgeBase | None = None
        self._agent: ChatAgent | None = None

        # 统计
        self._start_time: str = ""
        self._msg_received: int = 0
        self._msg_replied: int = 0
        self._scan_cycles: int = 0       # 轮询计数
        self._processed_contacts = set()  # 本轮已处理的联系人
        self._unread_cooldown: dict[str, float] = {}  # 未读处理冷却（秒级时间戳）
        self._unread_false_positive: dict[str, float] = {}  # 红点误报冷却
        self._UNREAD_COOLDOWN_SEC = 8.0
        self._UNREAD_FALSE_COOLDOWN_SEC = 120.0  # 误报后 2 分钟内不再切换
        self._IDENTITY_RETRY = 3
        self._IDENTITY_RETRY_DELAY = 0.45

    # ========== 生命周期 ==========

    def start(self):
        """启动系统"""
        self._state = State.RUNNING
        self._start_time = time.strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "=" * 60)
        print("  🤖 WeChat AI Agent 启动")
        print(f"  时间: {self._start_time}")
        print(f"  自动发送: {'是' if self.auto_send else '否'}")
        print(f"  轮询间隔: {self.listen_interval}s")
        print("=" * 60)

        # 1. 初始化微信
        self._wechat = WeChatWindow()
        if not self._wechat.find():
            print("\n❌ 未检测到微信，请先启动微信！")
            return
        self._wechat.activate()
        rect = self._wechat.get_rectangle()
        if rect["left"] < 0 or rect["top"] < 0:
            print("⚠️ 微信窗口部分超出屏幕，红点检测可能失败！")
            print("   请把微信窗口完全移到屏幕内")

        # 2. 初始化记忆
        self._memory = MemoryManager()

        # 3. 初始化监听 + 未读检测 + 切换器 + 身份验证
        self._listener = MessageListener(interval=self.listen_interval)
        self._unread_detector = UnreadDetector()
        self._unread_detector.set_window_rect(self._wechat.get_rectangle())
        self._switcher = ContactSwitcher()
        self._switcher.set_window_rect(self._wechat.get_rectangle())
        self._verifier = ChatIdentityVerifier()
        self._verifier.set_window_rect(self._wechat.get_rectangle())
        self._friend_ctx = FriendContextManager()
        self._identity = IdentityResolver()
        self._identity.set_window_rect(self._wechat.get_rectangle())
        self._friend_registry = FriendRegistry()
        self._memory_service = MemoryService()
        self._knowledge = PersonalKnowledgeBase()
        self._knowledge.ensure_layout()
        self._title_validator = TitleNameValidator()

        # 4.5 个人风格：从 storage/history 提取 me 消息并分析
        try:
            from personal.style_analyzer import StyleAnalyzer
            ps = StyleAnalyzer().sync_from_storage(force=False)
            if ps.message_count > 0:
                n_friends = len(ps.sources)
                print(
                    f"  🎭 个人风格: {ps.message_count}条 "
                    f"(storage/history, {n_friends}个好友, avg={ps.avg_length:.1f}字)"
                )
        except Exception as e:
            print(f"  ⚠️ 个人风格加载跳过: {e}")

        # 4.6 好友画像：从 storage/history 批量同步
        try:
            self._memory_service.sync_all_friend_profiles(force=False)
        except Exception as e:
            print(f"  ⚠️ 好友画像同步跳过: {e}")

        # 4. 初始化 Agent（从记忆加载画像和风格）
        self._agent = ChatAgent(
            profile=self._memory.get_user_profile(),
            style=self._memory.get_style(),
            auto_send=self.auto_send,
        )
        # 传入窗口坐标用于定位输入框
        self._agent.set_window_rect(self._wechat.get_rectangle())
        self._agent.set_wechat(self._wechat)
        self._agent.set_pre_send_guard(self._verify_before_send)

        # 5. 进入主循环
        self._run_loop()

    def stop(self):
        """停止系统"""
        self._state = State.STOPPED
        if self._listener:
            self._listener.stop()
        if hasattr(self, "_memory_service") and self._memory_service:
            self._memory_service.shutdown(wait=True, timeout=10.0)
        print(f"\n👋 系统已停止 | 收到: {self._msg_received} | 回复: {self._msg_replied}")

    def pause(self):
        """暂停监听"""
        self._state = State.PAUSED
        print("\n⏸️ 系统已暂停")

    def resume(self):
        """恢复监听"""
        self._state = State.RUNNING
        print("\n▶️ 系统已恢复")

    # ========== 主循环 ==========

    def _run_loop(self):
        """主循环: 优先处理未读 → 否则监控当前聊天"""
        try:
            while self._state != State.STOPPED:
                if self._state == State.PAUSED:
                    time.sleep(min(self.listen_interval, 0.5))
                    continue
                print("📋 红点检测...", end=" ")
                raw_unread = []
                if self._unread_detector:
                    raw_unread = self._unread_detector.detect_unread() or []

                actionable = self._filter_actionable_unread(raw_unread)

                if actionable:
                    print(f"发现{len(actionable)}个!")
                    handled_any = False
                    for contact in actionable:
                        if self._handle_unread(contact):
                            handled_any = True
                    # 未读均跳过（冷却/误报）时，仍监控当前窗口，避免漏消息
                    if not handled_any:
                        self._scan_chat()
                elif raw_unread:
                    print("无(误报/冷却已忽略)")
                    self._scan_chat()
                else:
                    print("无")
                    self._scan_chat()

                time.sleep(self.listen_interval)

        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _filter_actionable_unread(self, unread: list[dict]) -> list[dict]:
        """过滤处于误报/短冷却中的联系人，其他人不受影响"""
        now = time.time()
        result = []
        for contact in unread:
            name = contact.get("name", "")
            if not name:
                continue
            if now - self._unread_false_positive.get(name, 0) < self._UNREAD_FALSE_COOLDOWN_SEC:
                continue
            if now - self._unread_cooldown.get(name, 0) < self._UNREAD_COOLDOWN_SEC:
                continue
            result.append(contact)
        return result

    def _handle_unread(self, contact: dict) -> bool:
        """处理未读联系人。返回 True 表示已处理新消息。"""
        name = contact["name"]

        last_handled = self._unread_cooldown.get(name, 0)
        if time.time() - last_handled < self._UNREAD_COOLDOWN_SEC:
            print(f"\n⏭ 未读冷却: {name}（{self._UNREAD_COOLDOWN_SEC}s 内已处理）")
            return False

        print(f"\n🔔 未读: {name}")
        if not self._title_validator.is_auto_reply_allowed(name):
            ok, reason = self._title_validator.validate(name)
            print(f"  ⏭ 跳过无效/系统联系人: {name} ({reason if not ok else 'no_auto_reply'})")
            return False

        if self._agent:
            self._agent.clear_context()
        self._memory_service.clear_session()

        self._switcher.switch_to(name, contact["y"])
        time.sleep(0.6)

        if not self._verifier.verify(name):
            print(f"❌ 身份验证失败，重试点击...")
            self._switcher.switch_to(name, contact["y"])
            time.sleep(0.6)
            if not self._verifier.verify(name):
                print(f"❌ 二次验证仍失败，跳过 {name}")
                return False

        print(f"✅ 身份确认: {name}")
        had_new = self._scan_chat(expected_name=name)
        self._unread_cooldown[name] = time.time()

        if had_new:
            self._unread_false_positive.pop(name, None)
            return True

        self._unread_false_positive[name] = time.time()
        print(
            f"  ⚠️ 红点误报: {name} 界面无新消息，"
            f"{self._UNREAD_FALSE_COOLDOWN_SEC:.0f}s 内不再切换"
        )
        return False

    @staticmethod
    def _names_match(a: str, b: str) -> bool:
        a = (a or "").strip()
        b = (b or "").strip()
        if not a or not b:
            return False
        return a == b

    def _verify_before_send(self, expected_name: str) -> bool:
        """LLM 返回后、键盘发送前再次精确核对当前聊天标题。"""
        expected_name = (expected_name or "").strip()
        if not expected_name or not self._wechat or not self._listener:
            return False
        try:
            if not self._wechat.activate():
                return False
            rect = self._wechat.get_rectangle()
            self._verifier.set_window_rect(rect)
            current_name = self._listener.refresh_chat_partner(allow_stale=False)
            if current_name and self._names_match(current_name, expected_name):
                return True
            print(
                f"🛑 发送前联系人已变化: "
                f"期望={expected_name}, 当前={current_name or '(无法识别)'}"
            )
            return False
        except Exception as e:
            print(f"🛑 发送前身份复核异常: {e}")
            return False

    def _resolve_chat_identity(self, expected_name: str = "") -> tuple[str, str]:
        """
        解析当前聊天窗口身份，返回 (friend_id, friend_name)。

        expected_name: 从未读切换进来时传入，必须与标题栏一致才继续。
        """
        expected_name = (expected_name or "").strip()

        for attempt in range(self._IDENTITY_RETRY):
            self._wechat.activate()
            self._identity.set_window_rect(self._wechat.get_rectangle())
            self._verifier.set_window_rect(self._wechat.get_rectangle())

            title_name = self._listener.refresh_chat_partner(allow_stale=False)
            if not title_name:
                _, title_name = self._identity.resolve()

            resolved_name = ""

            if expected_name:
                if title_name and self._names_match(title_name, expected_name):
                    resolved_name = title_name
                elif self._verifier.verify(expected_name):
                    resolved_name = expected_name
                    if title_name and not self._names_match(title_name, expected_name):
                        print(
                            f"  ⚠️ 标题({title_name})与目标({expected_name})不一致，"
                            f"以身份验证为准"
                        )
                else:
                    if attempt < self._IDENTITY_RETRY - 1:
                        time.sleep(self._IDENTITY_RETRY_DELAY)
                        continue
                    print(
                        f"🛑 身份未确认: 期望={expected_name}, "
                        f"标题={title_name or '(空)'}"
                    )
                    return "", ""
            elif title_name:
                resolved_name = title_name
            else:
                if attempt < self._IDENTITY_RETRY - 1:
                    time.sleep(self._IDENTITY_RETRY_DELAY)
                    continue
                print("🛑 无法识别当前聊天对象，跳过（禁止沿用上一联系人）")
                return "", ""

            if not self._title_validator.is_auto_reply_allowed(resolved_name):
                ok, reason = self._title_validator.validate(resolved_name)
                print(f"  ⏭ 跳过无效/系统联系人: {resolved_name} ({reason if not ok else 'no_auto_reply'})")
                return "", ""

            friend_id = self._friend_registry.ensure_friend(resolved_name)
            if friend_id:
                return friend_id, resolved_name

            if attempt < self._IDENTITY_RETRY - 1:
                time.sleep(self._IDENTITY_RETRY_DELAY)

        return "", ""

    def _bind_chat_session(self, friend_id: str, friend_name: str):
        """切换好友时清旧会话并绑定新身份（记忆/Agent 隔离）"""
        if self._friend_ctx.friend_id and self._friend_ctx.friend_id != friend_id:
            print(f"  🔀 切换会话: {self._friend_ctx.friend_name} → {friend_name}")
            if self._agent:
                self._agent.clear_context()
            self._memory_service.clear_session()
            # 等待聊天区刷新，避免仍显示上一人的消息
            time.sleep(0.35)

        self._friend_ctx.set_friend(friend_id, friend_name)
        self._memory_service.bind_friend(friend_id, friend_name)
        self._listener.chat_partner = friend_name

    def _scan_chat(self, expected_name: str = "") -> bool:
        """扫描当前聊天区。返回 True 表示检测到并处理了新的 friend 消息。"""
        try:
            self._wechat.activate()

            friend_id, friend_name = self._resolve_chat_identity(expected_name)
            if not friend_id:
                return False

            self._bind_chat_session(friend_id, friend_name)

            all_msgs = self._listener.poll_messages(lock_partner=friend_name)

            if self._listener.chat_partner and not self._names_match(
                self._listener.chat_partner, friend_name
            ):
                print(
                    f"🛑 轮询后身份漂移: {friend_name} → {self._listener.chat_partner}，中止"
                )
                return False

            tracker: ChatTracker = self._listener.get_tracker()
            new_msgs = self._listener.diff_messages(friend_id, all_msgs)

            if not all_msgs:
                return False

            friend_new = [m for m in new_msgs if tracker.is_friend_message(m)]
            if not friend_new:
                return False

            unreplied = tracker.get_unreplied_friend_msgs(friend_id, friend_new)
            if not unreplied:
                return False

            if all_msgs and tracker.is_me_message(all_msgs[-1]):
                # 当前屏幕最后一条已经是“我”的消息，视为人工或既有回复。
                tracker.mark_replied(friend_id, unreplied)
                return False

            merged_content = tracker.merge_contents(unreplied)
            last = unreplied[-1]
            batch_msg = Message(
                sender=last.sender,
                content=merged_content,
                x=last.x,
                y=last.y,
                width=last.width,
                height=last.height,
                confidence=last.confidence,
            )

            print(f"\n📬 新消息 x{len(unreplied)} [{friend_name}]:")
            for m in unreplied:
                print(f"   · {display_text(m.content)}")
            if len(unreplied) > 1:
                print(f"   ↳ 合并回复")

            self._msg_received += len(unreplied)

            # 存入 JSONL 历史（统一存储层）
            try:
                self._memory_service.store.save_incoming_messages(friend_id, unreplied)
            except Exception as e:
                print(f"  ⚠️ 消息存入历史失败: {e}")

            self._update_friend_context(friend_name, batch_msg, friend_id)

            # 从 JSONL 加载最近对话（优先于 OCR 屏幕）
            history_context = self._memory_service.get_chat_history(friend_id, limit=20)
            style_history = self._memory_service.get_chat_history(friend_id, limit=40)
            if history_context:
                print(f"  📜 历史上下文: {len(history_context)} 条")

            # 同步检索记忆 + 画像（不阻塞回复）
            memories = self._memory_service.retrieve_and_rank(
                friend_id, merged_content, limit=10
            )
            profile_text = self._memory_service.get_profile_text(friend_id, friend_name)
            knowledge = []
            try:
                knowledge = self._knowledge.search(
                    merged_content,
                    friend_id=friend_id,
                    friend_name=friend_name,
                    limit=4,
                )
                if knowledge:
                    print(f"  📚 个人知识: {len(knowledge)} 个已授权相关片段")
            except Exception as e:
                print(f"  ⚠️ 个人知识检索跳过: {e}")

            # 双方风格 + 好友身份卡
            style_context = self._memory_service.get_style_context(
                friend_id=friend_id,
                friend_name=friend_name,
                history=style_history,
                memories=memories,
                user_style=self._memory.get_style(),
            )
            if style_context.get("friend_card"):
                print(f"  👤 对象: {friend_name} | 我的样本: {len(style_context.get('user_voice', {}).get('samples', []))} | TA样本: {len(style_context.get('friend_voice', {}).get('samples', []))}")

            if not memories and not profile_text:
                print("  ⚠️ 未找到该好友的记忆和画像，AI可能瞎猜")
            verbose_memory = os.getenv("WECHAT_VERBOSE_MEMORY", "0") == "1"
            if memories and verbose_memory:
                print(f"  🧠 记忆({friend_name}/{friend_id}, {len(memories)}): {[m[:30] for m in memories]}")
            if profile_text and verbose_memory:
                print(f"  🖼 画像: {profile_text.split(chr(10))[1] if chr(10) in profile_text else profile_text[:60]}")

            result = self._agent.process_message(
                batch_msg,
                memories=memories,
                profile_text=profile_text,
                history_context=history_context,
                screen_messages=all_msgs if not history_context else None,
                style_context=style_context,
                knowledge=knowledge,
            )

            # 回复成功或已生成 → 标记已回复，避免重复
            if result.get("reply") and result.get("status") in ("sent", "generated"):
                tracker.mark_replied(friend_id, unreplied)

            self._after_reply(result, friend_name, friend_id, batch_msg, unreplied)

            # 后台异步提取记忆 + 更新画像（不阻塞主流程）
            self._memory_service.submit_extract(friend_id, friend_name, unreplied)
            return True

        except Exception as e:
            print(f"⚠️ 聊天扫描异常: {e}")
            return False

    def _after_reply(self, result, friend_name, friend_id, msg, source_msgs=None):
        """发送后的收尾工作"""
        if result.get("sent"):
            self._msg_replied += 1
            reply_text = result.get("reply", "")
            if reply_text:
                self._listener._dedup.add({"sender": "我", "content": reply_text})

        # 写入 JSONL 历史：自己的回复
        # 预览模式生成的候选回复不等于真实发言，不能写入聊天史或污染个人风格。
        if friend_id and result.get("reply") and result.get("status") == "sent":
            try:
                self._memory_service.store.save_reply(friend_id, result["reply"])
            except Exception:
                pass
            # 个人风格增量学习
            try:
                from personal.style_analyzer import StyleAnalyzer
                StyleAnalyzer().update_style({"sender": "me", "text": result["reply"]})
            except Exception:
                pass

        for m in (source_msgs or [msg]):
            self._listener._dedup.add(m)

        if friend_name:
            sender_type = "friend" if not ChatTracker.is_me_message(msg) else "me"
            self._memory_service.store.append_audit_log(friend_name, sender_type, msg.content)

    def _scan_sidebar(self):
        """扫描联系人列表，发现未读就切过去回复"""
        if not self._unread_detector or not self._switcher:
            print("⚠️ 未读检测器未初始化")
            return
        try:
            print("\n📋 [侧边栏扫描] 检测红点...")
            unread = self._unread_detector.detect_unread()
            if not unread:
                print("  ✅ 无未读消息")
            for contact in unread:
                name = contact["name"]
                if name in self._processed_contacts:
                    continue
                if name == self._listener.chat_partner:
                    continue

                print(f"\n🔔 未读: {name} ({contact.get('unread_count',1)}条)")
                self._switcher.switch_to(name, contact["y"], contact.get("red_dot_y"))
                time.sleep(0.8)

                # 切过去后扫聊天区
                self._scan_chat()
                self._processed_contacts.add(name)
                time.sleep(0.5)

        except Exception as e:
            print(f"⚠️ 侧边栏扫描异常: {e}")

    # ========== 好友上下文 ==========

    def _update_friend_context(self, friend_name: str, msg, friend_id: str = ""):
        """更新好友信息到 Agent"""
        if not friend_name or not self._memory:
            return

        if not friend_id:
            friend_id = self._friend_registry.ensure_friend(friend_name)

        friend_info = self._memory.get_friend_memory(friend_name)
        if not friend_info:
            self._memory.add_friend(friend_name, friend_id=friend_id)
            print(f"  ✅ 自动建档: {friend_name} → {friend_id}")
        elif friend_id and not friend_info.get("friend_id"):
            self._memory.add_friend(friend_name, friend_id=friend_id)

        # 同步到 Agent
        info = self._memory.get_friend_memory(friend_name) or {}
        self._agent.set_friend_info(friend_name, info)


# ========== 快速测试 ==========

if __name__ == "__main__":
    """
    测试 Runner（5秒自动停止）
    """
    import threading

    runner = AgentRunner(auto_send=False, listen_interval=2)

    # 10秒后自动停止
    def auto_stop():
        time.sleep(10)
        print("\n⏰ 测试时间到，自动停止...")
        runner.stop()

    timer = threading.Thread(target=auto_stop, daemon=True)
    timer.start()

    runner.start()
