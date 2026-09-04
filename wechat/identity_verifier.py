"""
聊天身份验证器
点击联系人后，OCR标题栏确认是否真正切换到了目标聊天

防止点错人、点空、微信卡顿等导致的回复错人
"""

import sys
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from config.settings import TITLE_REGION

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatIdentityVerifier:
    """聊天身份验证器

    截图标题栏 → OCR → 确认当前聊天对象是否为目标联系人
    """

    def __init__(self):
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._window_rect: dict | None = None

    def set_window_rect(self, rect: dict):
        self._window_rect = rect

    def verify(self, expected_name: str) -> bool:
        """
        验证当前聊天对象是否为目标联系人

        Args:
            expected_name: 期望的联系人名称

        Returns:
            True: 标题栏包含该名称，确认身份
            False: 不匹配，需要重试
        """
        if not self._window_rect:
            return False

        try:
            title_abs = ScreenCapture.get_absolute_region(
                self._window_rect, TITLE_REGION
            )
            img = self._capture.capture(title_abs)
            texts = self._ocr.recognize_image(img)

            for t in texts:
                t = t.strip()
                if expected_name == t:
                    return True

            print(f"⚠️ 身份验证失败: 标题栏={texts}, 期望={expected_name}")
            return False

        except Exception as e:
            print(f"⚠️ 身份验证异常: {e}")
            return False
