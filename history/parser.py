"""
历史消息解析
从OCR结果解析消息内容、发送者、时间
"""

import sys
from parser.system_filter import SystemMessageFilter

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryParser:
    """历史消息解析器

    输入OCR原始结果 → 输出结构化消息列表
    """

    def __init__(self, chat_width: int = 665):
        """
        Args:
            chat_width: 聊天区域宽度，用于判断左右气泡
        """
        self.chat_width = chat_width
        self._mid_x = chat_width / 2
        self._system_filter = SystemMessageFilter()

    def parse(self, ocr_result: list) -> list[dict]:
        """
        解析OCR结果为消息列表

        Args:
            ocr_result: RapidOCR原始输出 [[[box], "text", conf], ...]

        Returns:
            [{"text": "...", "sender": "friend/me", "y": 100}, ...]
        """
        if not ocr_result:
            return []

        items = []
        for entry in ocr_result:
            if not entry or len(entry) < 2:
                continue
            box = entry[0]
            text = str(entry[1]).strip()
            if not text:
                continue

            x1, y1 = box[0]
            x2, y2 = box[2]
            item = {
                "text": text,
                "x": float(x1),
                "y": float(y1),
                "w": float(x2) - float(x1),
                "h": float(y2) - float(y1),
            }
            if self._system_filter.should_skip(item, self.chat_width):
                continue
            item["text"] = self._system_filter.clean_content(item["text"])
            if not item["text"]:
                continue
            items.append(item)

        # 按Y排序
        items.sort(key=lambda it: it["y"])

        # 判断发送者
        for item in items:
            item["sender"] = "friend" if item["x"] < self._mid_x else "me"

        return items

    @staticmethod
    def merge_adjacent(items: list[dict], gap: int = 30) -> list[dict]:
        """
        合并相邻的同sender消息（同一句话被OCR拆成多行）
        """
        if not items:
            return []

        merged = [dict(items[0])]
        for item in items[1:]:
            last = merged[-1]
            if (item["sender"] == last["sender"]
                    and abs(item["y"] - last["y"]) < gap):
                last["text"] += " " + item["text"]
            else:
                merged.append(dict(item))
        return merged
