"""
微信消息发送模块
通过模拟键盘操作在微信聊天窗口中发送消息

流程:
  1. 激活微信窗口（LLM 调用期间焦点可能已丢失）
  2. 刷新窗口坐标
  3. 点击输入区域获取焦点
  4. 粘贴文本
  5. 按 Enter 发送
"""

import sys
import time
from collections.abc import Callable
import pyautogui
from automation.keyboard import Keyboard
from config.settings import INPUT_REGION
from wechat.screenshot import ScreenCapture
from utils.privacy import display_text

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class WeChatSender:
    """微信消息发送器

    通过 pyautogui 粘贴 + Enter 方式发送消息到当前聊天窗口。
    不涉及任何 hook、注入或协议逆向。
    """

    OUTGOING_PREFIX = "[自动回复]:"
    # 历史前缀 + 全角冒号变体，用于 OCR 回读时识别「自己的消息」
    OUTGOING_PREFIXES = ("[自动回复]:", "机器人:", "机器人：")

    def __init__(self):
        self.keyboard = Keyboard(interval=0.08)
        self._window_rect = None
        self._wechat = None
        self._pre_send_guard: Callable[[str], bool] | None = None
        self._ocr = None

    def set_window_rect(self, rect: dict):
        """设置微信窗口坐标"""
        self._window_rect = rect

    def set_wechat(self, wechat):
        """绑定微信窗口对象，发送前自动激活"""
        self._wechat = wechat

    def set_pre_send_guard(self, guard: Callable[[str], bool] | None):
        """绑定发送前身份复核函数。guard(expected_name) 必须明确返回 True。"""
        self._pre_send_guard = guard

    def send(self, text: str, expected_name: str = "") -> bool:
        """
        发送文本消息到微信当前聊天窗口

        Args:
            text: 要发送的消息内容

        Returns:
            bool: 是否发送成功
        """
        if not text or not text.strip():
            print("⚠️ 消息为空，跳过发送")
            return False

        text = self.format_outgoing(text)

        try:
            # 1. 激活微信并刷新坐标（LLM 耗时期间焦点常丢失）
            if not self._ensure_wechat_focus():
                print("⚠️ 无法激活微信窗口，发送中止")
                return False

            # LLM 调用期间用户可能手动切换聊天。必须在点击输入框前重新核对。
            if self._pre_send_guard:
                if not expected_name or not self._pre_send_guard(expected_name):
                    print(f"🛑 发送前身份复核失败，已中止: {expected_name or '(空)'}")
                    return False
            elif expected_name:
                print("🛑 未配置发送前身份复核器，已中止")
                return False

            # 2. 点击输入框获取焦点
            if not self._click_input_area():
                print("⚠️ 输入框定位失败，发送中止")
                return False

            # 3. 不覆盖用户正在编辑的草稿；无法确认输入框为空时安全中止。
            if not self._input_is_empty():
                print("🛑 输入框已有内容或无法确认为空，已保留草稿并中止发送")
                return False

            # 4. 粘贴文本
            if not self.keyboard.write(text):
                return False

            time.sleep(0.15)

            # 5. 发送前再次确认焦点在输入框
            if not self._click_input_area(fine_tune=True):
                print("⚠️ 发送前输入框焦点复核失败，发送中止")
                return False

            # 6. 按 Enter 发送
            if not self.keyboard.press_enter():
                return False

            time.sleep(0.2)
            print(f"✅ 微信已发送: {display_text(text)}")
            return True

        except Exception as e:
            print(f"❌ 发送失败: {e}")
            return False

    @classmethod
    def is_auto_reply(cls, text: str) -> bool:
        """判断 OCR 文本是否为 Agent 自己发出的自动回复"""
        text = (text or "").strip()
        if not text:
            return False
        return any(text.startswith(prefix) for prefix in cls.OUTGOING_PREFIXES)

    @classmethod
    def format_outgoing(cls, text: str) -> str:
        """发送前统一加前缀，避免重复添加"""
        text = (text or "").strip()
        if not text:
            return ""
        if cls.is_auto_reply(text):
            return text
        return f"{cls.OUTGOING_PREFIX}{text}"

    def _ensure_wechat_focus(self) -> bool:
        """激活微信窗口并刷新坐标"""
        if self._wechat:
            if not self._wechat.is_running():
                print("⚠️ 微信窗口未运行")
                return False
            self._wechat.activate()
            time.sleep(0.35)
            self._window_rect = self._wechat.get_rectangle()
            return self._window_rect.get("width", 0) > 0

        return self._window_rect is not None

    def _click_input_area(self, fine_tune: bool = False) -> bool:
        """点击输入框区域获取焦点"""
        if not self._window_rect:
            print("⚠️ 未设置窗口坐标，无法定位输入框")
            return False

    def _input_is_empty(self) -> bool:
        """通过输入区截图 OCR 检查草稿；检测失败时按非空处理。"""
        if not self._window_rect:
            return False
        try:
            from wechat.ocr import OCRReader

            if self._ocr is None:
                self._ocr = OCRReader()
            region = ScreenCapture.get_absolute_region(self._window_rect, INPUT_REGION)
            image = ScreenCapture().capture(region)
            texts = [str(t).strip() for t in self._ocr.recognize_image(image)]
            return not any(texts)
        except Exception as e:
            print(f"⚠️ 输入框草稿检查失败: {e}")
            return False

        try:
            left, top, right, bottom = ScreenCapture.get_absolute_region(
                self._window_rect, INPUT_REGION
            )
            if right <= left or bottom <= top:
                print(f"⚠️ 输入框区域无效: ({left},{top})→({right},{bottom})")
                return False

            cx = (left + right) // 2
            cy = (top + bottom) // 2

            duration = 0.05 if fine_tune else 0.15
            pyautogui.moveTo(cx, cy, duration=duration)
            pyautogui.click()
            if not fine_tune:
                time.sleep(0.1)
                pyautogui.click()
            time.sleep(0.15)
            return True

        except Exception as e:
            print(f"⚠️ 点击输入框失败: {e}")
            return False

    @staticmethod
    def _clear_input():
        """清空输入框残留内容"""
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        pyautogui.press("backspace")
        time.sleep(0.05)


# ========== 测试 ==========

if __name__ == "__main__":
    from wechat.window import WeChatWindow

    wechat = WeChatWindow()
    if wechat.find():
        wechat.activate()
        print("\n3 秒后发送测试消息...")
        time.sleep(3)

        sender = WeChatSender()
        sender.set_wechat(wechat)
        sender.send("测试消息——AI自动发送")
