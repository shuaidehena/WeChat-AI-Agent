"""
截图模块
负责截取微信聊天消息区域的屏幕截图
"""

import os
from PIL import Image
import pyautogui


class ScreenCapture:
    """屏幕截图器

    负责截取屏幕指定区域并保存为图片文件。
    配合 WeChatWindow.get_rectangle() 使用，可精确定位聊天区域。
    """

    def __init__(self):
        """初始化截图器"""
        self._last_image: Image.Image | None = None

    def capture(self, region: tuple[int, int, int, int]) -> Image.Image:
        """
        截取指定屏幕区域

        Args:
            region: 截图区域 (left, top, right, bottom) 屏幕绝对坐标

        Returns:
            PIL Image 对象

        Example:
            # 截取从 (100, 200) 到 (800, 600) 的区域
            img = capture.capture((100, 200, 800, 600))
        """
        try:
            # pyautogui.screenshot 接受 (left, top, width, height)
            left, top, right, bottom = region
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                raise ValueError(f"截图区域无效: width={width}, height={height}")

            print(f"📷 正在截图... 区域: ({left}, {top}) → ({right}, {bottom})")
            print(f"   尺寸: {width} x {height}")

            self._last_image = pyautogui.screenshot(region=(left, top, width, height))
            print(f"✅ 截图成功: {width}x{height} 像素")
            return self._last_image

        except Exception as e:
            print(f"❌ 截图失败: {e}")
            raise

    def save(self, filepath: str, image: Image.Image | None = None) -> bool:
        """
        保存截图到文件

        Args:
            filepath: 保存路径（如 debug/chat_area.png）
            image: 要保存的图片，默认使用最近一次截图

        Returns:
            bool: 是否保存成功
        """
        img = image or self._last_image
        if img is None:
            print("❌ 没有可保存的截图，请先调用 capture()")
            return False

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

            img.save(filepath)
            print(f"💾 截图已保存: {filepath}")
            return True

        except Exception as e:
            print(f"❌ 保存截图失败: {e}")
            return False

    @staticmethod
    def get_absolute_region(
        window_rect: dict,
        chat_region: dict,
    ) -> tuple[int, int, int, int]:
        """
        根据窗口坐标和区域偏移量，计算屏幕绝对坐标（裁剪到屏幕范围）
        """
        left = max(0, window_rect["left"] + chat_region["left"])
        top = max(0, window_rect["top"] + chat_region["top"])
        right = max(0, window_rect["left"] + chat_region["right"])
        bottom = max(0, window_rect["top"] + chat_region["bottom"])
        return (left, top, right, bottom)


# ========== 快速测试入口 ==========

if __name__ == "__main__":
    """独立测试截图功能"""
    from wechat.window import WeChatWindow
    from config.settings import CHAT_REGION

    # 找微信窗口
    wechat = WeChatWindow()
    if not wechat.find():
        print("请先启动微信！")
        exit(1)

    wechat.activate()

    # 获取窗口坐标
    window_rect = wechat.get_rectangle()

    # 计算聊天区域屏幕绝对坐标
    region = ScreenCapture.get_absolute_region(window_rect, CHAT_REGION)

    # 截图并保存
    capture = ScreenCapture()
    img = capture.capture(region)
    capture.save("debug/chat_area.png", img)
