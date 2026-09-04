"""
好友身份解析器
根据微信标题栏 OCR 识别当前聊天对象
"""

import sys
import os
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from config.settings import TITLE_REGION
from context.name_mapper import FriendNameMapper
from context.title_name_validator import pick_valid_title

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class IdentityResolver:
    """身份解析器

    截图标题栏 → OCR → 中文名映射到英文 friend_id（拼音）
    """

    def __init__(self):
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._window_rect: dict | None = None
        self._name_mapper = FriendNameMapper()

    def set_window_rect(self, rect: dict):
        self._window_rect = rect

    def resolve(self) -> tuple[str, str]:
        """
        解析当前聊天对象

        Returns:
            (friend_id, friend_name) 如 ("yangchunhui", "杨春辉")
        """
        if not self._window_rect:
            return "", ""

        try:
            title_abs = ScreenCapture.get_absolute_region(
                self._window_rect, TITLE_REGION
            )
            img = self._capture.capture(title_abs)
            texts = self._ocr.recognize_image(img)

            candidates = [t.strip() for t in texts if 2 <= len(t.strip()) <= 24]
            name = pick_valid_title(candidates)
            if not name:
                return "", ""

            friend_id = self._name_mapper.get_id(name)
            if not friend_id:
                friend_id = self._name_mapper.to_pinyin_id(name)

            return friend_id, name

        except Exception as e:
            print(f"⚠️ 身份解析失败: {e}")
            return "", ""
