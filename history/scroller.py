"""
聊天滚动控制
模拟鼠标滚轮向上滚动微信聊天区域
"""

import sys
import time
import pyautogui

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatScroller:
    """微信聊天滚动器

    定位聊天区域 → 向上滚动 → 检测是否到顶

    注意: Windows 上 pyautogui.scroll(正数) = 向上滚（查看更早消息）
    """

    def __init__(self):
        self._chat_region: tuple[int, int, int, int] | None = None
        self._prev_hash: str = ""
        self._no_change_count: int = 0

    def set_chat_center(self, x: int, y: int):
        """设置聊天区域中心点（屏幕绝对坐标，兼容旧接口）"""
        self._chat_region = (x - 1, y - 1, x + 1, y + 1)

    def set_chat_region(self, left: int, top: int, right: int, bottom: int):
        """设置聊天区域绝对坐标"""
        self._chat_region = (left, top, right, bottom)

    def scroll_up(self, amount: int = 240) -> bool:
        """向上滚动一页（查看更早的历史消息）"""
        cx, cy = self._focus_point()
        if cx is None:
            return False

        pyautogui.moveTo(cx, cy, duration=0.1)
        pyautogui.click()
        time.sleep(0.15)

        # Windows: 正数 = 向上滚
        steps = max(3, amount // 80)
        for _ in range(steps):
            pyautogui.scroll(80)
            time.sleep(0.06)

        time.sleep(0.6)
        return True

    def scroll_to_bottom(self, times: int = 8):
        """滚到聊天底部（最新消息），采集前可选调用"""
        cx, cy = self._focus_point()
        if cx is None:
            return

        pyautogui.moveTo(cx, cy, duration=0.1)
        pyautogui.click()
        time.sleep(0.15)

        for _ in range(times):
            pyautogui.scroll(-120)
            time.sleep(0.08)
        time.sleep(0.4)

    def is_top(self, current_screenshot_hash: str) -> bool:
        """连续 2 次截图 hash 相同 → 已到顶"""
        if current_screenshot_hash == self._prev_hash:
            self._no_change_count += 1
        else:
            self._no_change_count = 0
        self._prev_hash = current_screenshot_hash
        return self._no_change_count >= 2

    def reset(self):
        self._prev_hash = ""
        self._no_change_count = 0

    def _focus_point(self) -> tuple[int | None, int | None]:
        if not self._chat_region:
            return None, None
        left, top, right, bottom = self._chat_region
        cx = (left + right) // 2
        # 点击消息区偏上方，避免误点输入框
        cy = top + int((bottom - top) * 0.35)
        return cx, cy
