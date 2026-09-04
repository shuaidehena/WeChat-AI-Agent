"""
微信消息监听器
定时截图 → OCR → 解析 → 去重 → 返回新消息

数据流:
  ScreenCapture → OCRReader(含坐标) → BubbleParser → Deduplicator → 新消息

用法:
  listener = MessageListener(interval=2)
  for msg in listener.listen():
      print(f"新消息: {msg}")
"""

import sys
import time
from typing import Iterator, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 项目模块
from wechat.window import WeChatWindow
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from parser.bubble_parser import BubbleParser
from context.title_name_validator import pick_valid_title
from listener.deduplicator import MessageDeduplicator
from listener.chat_tracker import ChatTracker
from config.settings import CHAT_REGION, TITLE_REGION, SCREENSHOT_DIR, SCREENSHOT_FILENAME


class MessageListener:
    """微信消息监听器

    持续监听微信聊天区域，定期截图 + OCR + 解析，
    自动识别当前聊天对象名称，通过去重器过滤已处理消息。

    Attributes:
        interval:      轮询间隔（秒），默认 2 秒
        chat_partner:  当前聊天对象名称（从标题栏自动识别）
    """

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._running = False

        self._wechat = WeChatWindow()
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._parser: Optional[BubbleParser] = None
        self._dedup = MessageDeduplicator()
        self._tracker = ChatTracker()

        self._window_rect = None
        self.chat_partner: str = ""   # 当前聊天对象名称

    # ========== 主循环 ==========

    def listen(self) -> Iterator:
        """
        持续监听新消息（生成器）

        每次循环:
          1. 截图聊天区域
          2. OCR 识别（含坐标）
          3. BubbleParser 解析
          4. 去重过滤
          5. yield 新消息

        Yields:
            Message: 新消息对象

        Usage:
            for msg in listener.listen():
                print(f"[新消息] {msg.sender}: {msg.content}")
        """
        print("\n" + "=" * 60)
        print("  🔔 开始监听微信消息...")
        print(f"  轮询间隔: {self.interval} 秒")
        print(f"  按 Ctrl+C 停止")
        print("=" * 60)

        self._running = True

        try:
            while self._running:
                # 1. 截图 + OCR + 解析
                messages = self._poll()

                # 2. 去重 + 返回新消息
                for msg in messages:
                    if self._dedup.is_new(msg):
                        self._dedup.add(msg)
                        yield msg

                # 3. 等待下一轮
                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n\n⏸️ 监听已停止")
        finally:
            self.stop()

    def refresh_chat_partner(self, allow_stale: bool = True) -> str:
        """读取标题栏，更新并返回当前聊天对象名称"""
        try:
            if not self._wechat.is_running():
                return self.chat_partner or ""

            self._wechat.activate()
            self._window_rect = self._wechat.get_rectangle()
            name = self._read_title()
            if name:
                self.chat_partner = name
            elif allow_stale and self.chat_partner:
                print(f"  ⚠️ 标题栏 OCR 无效，沿用上次联系人: {self.chat_partner}")
            elif not allow_stale:
                return ""
            return self.chat_partner or ""
        except Exception:
            return self.chat_partner or "" if allow_stale else ""

    def _poll(self, lock_partner: str = "") -> list:
        """
        单次轮询：标题栏OCR → 截图 → OCR → 解析

        Args:
            lock_partner: 已确认的好友名；设置后不再读标题栏，防止切换窗口时串人

        Returns:
            list[Message]: 当前屏幕上的所有消息（sender 已映射为真实名称）
        """
        try:
            if not self._wechat.is_running():
                print("⚠️ 微信窗口未找到，等待...")
                return []

            self._wechat.activate()
            self._window_rect = self._wechat.get_rectangle()

            # ---- 标题栏 OCR → 获取聊天对象名 ----
            if lock_partner:
                self.chat_partner = lock_partner
            else:
                title_name = self._read_title()
                if title_name:
                    self.chat_partner = title_name

            # ---- 聊天区域截图 ----
            chat_abs = ScreenCapture.get_absolute_region(
                self._window_rect, CHAT_REGION
            )
            chat_img = self._capture.capture(chat_abs)
            self._capture.save(
                f"{SCREENSHOT_DIR}/{SCREENSHOT_FILENAME}", chat_img
            )

            # ---- OCR 含坐标 ----
            ocr_raw = self._ocr.recognize_with_boxes(
                f"{SCREENSHOT_DIR}/{SCREENSHOT_FILENAME}"
            )
            if not ocr_raw:
                return []

            # ---- BubbleParser（传截图用于颜色识别）----
            if self._parser is None:
                chat_width = chat_abs[2] - chat_abs[0]
                self._parser = BubbleParser(chat_width=chat_width)

            messages = self._parser.parse(ocr_raw, screenshot=chat_img)

            # ---- 映射 sender 名称 ----
            for msg in messages:
                if msg.sender == "friend" and self.chat_partner:
                    msg.sender = self.chat_partner
                elif msg.sender == "me":
                    msg.sender = "我"

            return messages

        except Exception as e:
            print(f"⚠️ 轮询异常: {e}")
            return []

    def poll_messages(self, lock_partner: str = "") -> list:
        """单次轮询；lock_partner 用于身份已确认后锁定当前好友"""
        return self._poll(lock_partner=lock_partner)

    def diff_messages(self, friend_id: str, messages: list) -> list:
        """对已有消息列表做增量 diff"""
        if not friend_id:
            return []
        return self._tracker.diff(friend_id, messages)

    def poll_new_messages(self, friend_id: str) -> tuple[list, list]:
        """
        单次轮询并做增量对比

        Args:
            friend_id: 当前好友 ID（用于游标隔离）

        Returns:
            (all_messages, new_messages)
        """
        all_msgs = self._poll()
        if not friend_id:
            return all_msgs, []

        new_msgs = self._tracker.diff(friend_id, all_msgs)
        return all_msgs, new_msgs

    def get_tracker(self) -> ChatTracker:
        """获取聊天游标追踪器"""
        return self._tracker

    def _read_title(self) -> str:
        """
        读取微信标题栏，返回聊天对象名称

        Returns:
            str: 聊天对象名称，识别失败返回空字符串
        """
        try:
            title_abs = ScreenCapture.get_absolute_region(
                self._window_rect, TITLE_REGION
            )
            title_img = self._capture.capture(title_abs)
            title_texts = self._ocr.recognize_image(title_img)

            candidates = [
                t.strip() for t in title_texts
                if 2 <= len(t.strip()) <= 30
            ]
            return pick_valid_title(candidates)
        except Exception:
            return ""

    # ========== 控制方法 ==========

    def stop(self):
        """停止监听并保存缓存"""
        self._running = False
        self._dedup.save()
        self._tracker.save()
        print(f"💾 缓存已保存，共处理 {self._dedup.count()} 条消息")

    def get_deduplicator(self) -> MessageDeduplicator:
        """获取去重器（供外部查询已处理消息数等）"""
        return self._dedup


# ========== 模拟测试 ==========

if __name__ == "__main__":
    """
    模拟测试：用固定 OCR 数据验证监听流程
    不连接真实微信，只测去重 + 过滤逻辑
    """
    print("=" * 60)
    print("  MessageListener 模拟测试")
    print("=" * 60)

    from listener.deduplicator import MessageDeduplicator

    # 用临时缓存
    dedup = MessageDeduplicator(cache_path="storage/test_listener_cache.json")

    # 模拟已处理: friend_你好
    class FakeMsg:
        def __init__(self, s, c):
            self.sender = s
            self.content = c
        def __str__(self):
            return f"[{self.sender}] {self.content}"
    dedup.add(FakeMsg("friend", "你好"))

    # 模拟本轮 OCR 解析结果
    current_messages = [
        FakeMsg("friend", "你好"),          # 已处理 → 跳过
        FakeMsg("friend", "在吗"),          # 新消息 ✓
        FakeMsg("me", "我也在"),            # 新消息 ✓
        FakeMsg("friend2", "你好"),         # 不同好友，新消息 ✓
    ]

    print("\n模拟当前屏幕消息:")
    for m in current_messages:
        status = "🆕 新消息" if dedup.is_new(m) else "⏭ 已处理"
        print(f"  {status} | {m}")

    # 只取新消息
    new_messages = [m for m in current_messages if dedup.is_new(m)]
    for m in new_messages:
        dedup.add(m)

    print(f"\n✅ 新消息数: {len(new_messages)}")
    assert len(new_messages) == 3, f"应有3条新消息,实际{len(new_messages)}"
    print("✅ 模拟测试通过！")

    dedup.save()

    # 清理
    import os
    if os.path.exists("storage/test_listener_cache.json"):
        os.remove("storage/test_listener_cache.json")
