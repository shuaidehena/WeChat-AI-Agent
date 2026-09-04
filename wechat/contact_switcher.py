"""
联系人切换模块
点击侧边栏指定联系人，切换到该聊天窗口
"""

import sys
import time
import pyautogui
from wechat.screenshot import ScreenCapture
from config.settings import SIDEBAR_REGION

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ContactSwitcher:
    """联系人切换器

    根据联系人的 Y 坐标，点击侧边栏切换到该聊天。
    """

    def __init__(self):
        self._window_rect: dict | None = None

    def set_window_rect(self, rect: dict):
        self._window_rect = rect

    def switch_to(self, name: str, contact_y: float, red_dot_y: float = None):
        """
        点击联系人，切换到该聊天

        Args:
            name: 联系人名称
            contact_y: 联系人 Y 坐标
            red_dot_y: 红点 Y 坐标（优先点击红点位置）
        """
        if not self._window_rect:
            print("⚠️ 窗口坐标未设置")
            return

        sidebar_abs = ScreenCapture.get_absolute_region(
            self._window_rect, SIDEBAR_REGION
        )
        # 点击联系人名称位置(名称区X=120~180最可靠)
        click_x = sidebar_abs[0] + 160
        click_y = sidebar_abs[1] + contact_y  # 直接点OCR识别的名称Y

        pyautogui.moveTo(click_x, click_y, duration=0.1)
        pyautogui.click()
        time.sleep(0.8)
        print(f"👆 切换到: {name} @({click_x},{click_y})")


# ========== 测试 ==========

if __name__ == "__main__":
    from wechat.window import WeChatWindow
    from wechat.contact_list import ContactList

    w = WeChatWindow()
    if w.find():
        w.activate()
        cl = ContactList()
        cl.set_window_rect(w.get_rectangle())
        contacts = cl.scan()

        sw = ContactSwitcher()
        sw.set_window_rect(w.get_rectangle())

        # 点击第一个联系人测试
        for name, info in contacts.items():
            if "助手" in name or "传输" in name:
                sw.switch_to(name, info["y"])
                break
