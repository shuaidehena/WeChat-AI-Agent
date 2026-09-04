"""
键盘操作封装模块
对 pyautogui 键盘操作的简单封装，统一延迟和异常处理
"""

import time
import pyautogui
import pyperclip


class Keyboard:
    """键盘控制器

    封装键盘输入操作，使用剪贴板方式输入中文，
    避免 pyautogui typewrite 不支持中文的问题。
    """

    def __init__(self, interval: float = 0.05):
        """
        初始化键盘控制器

        Args:
            interval: 操作间隔（秒），太快可能导致输入丢失
        """
        self.interval = interval
        # 启用安全模式：鼠标移到屏幕四角会触发异常
        pyautogui.FAILSAFE = True

    def write(self, text: str) -> bool:
        """
        输入文本（支持中文）

        使用剪贴板粘贴方式，兼容中英文混合输入。
        流程：复制到剪贴板 → Ctrl+V → 等待

        Args:
            text: 要输入的文本内容

        Returns:
            bool: 是否成功
        """
        try:
            # 复制到剪贴板
            pyperclip.copy(text)
            time.sleep(self.interval)

            # Ctrl + V 粘贴
            pyautogui.hotkey("ctrl", "v")
            time.sleep(self.interval)

            return True
        except Exception as e:
            print(f"❌ 文本输入失败: {e}")
            return False

    def press_enter(self) -> bool:
        """
        按下 Enter 键（发送消息）

        Returns:
            bool: 是否成功
        """
        try:
            time.sleep(self.interval)
            pyautogui.press("enter")
            return True
        except Exception as e:
            print(f"❌ 按键失败: {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        """
        组合键

        Args:
            keys: 按键序列，如 ('ctrl', 'c')

        Returns:
            bool: 是否成功
        """
        try:
            time.sleep(self.interval)
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            print(f"❌ 组合键失败: {e}")
            return False


# ========== 快速测试 ==========

if __name__ == "__main__":
    """测试键盘输入"""
    print("3秒后输入测试文本...")
    time.sleep(3)
    kb = Keyboard()
    kb.write("测试消息")
    kb.press_enter()
    print("✅ 输入完成")
