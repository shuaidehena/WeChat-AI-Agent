"""
联系人列表模块
解析微信左侧联系人列表，保存每个联系人的名称和屏幕位置

数据格式:
  {
    "张三": {"y": 160, "preview": "在吗"},
    "李四": {"y": 256, "preview": "晚上吃饭"},
  }
"""

import sys
from statistics import median
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from config.settings import SIDEBAR_REGION

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ContactList:
    """联系人列表

    截图左侧 → OCR → 解析出联系人名 + Y坐标 + 消息预览
    """

    def __init__(self):
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._window_rect: dict | None = None
        self._contacts: dict[str, dict] = {}  # name → {y, preview}

    def set_window_rect(self, rect: dict):
        self._window_rect = rect

    # ========== 扫描 ==========

    def scan(self) -> dict[str, dict]:
        """扫描联系人列表，返回 {name: {y, preview}}"""
        img = self._capture_sidebar()
        if img is None:
            return {}

        ocr_raw = self._ocr.ocr(img)
        if isinstance(ocr_raw, tuple):
            ocr_raw = ocr_raw[0]
        if not ocr_raw:
            return {}

        items = self._extract_items(ocr_raw)
        self._contacts = self._merge_rows(items)
        return self._contacts

    def get_contact(self, name: str) -> dict | None:
        """获取指定联系人的信息"""
        return self._contacts.get(name)

    def get_all(self) -> dict:
        return self._contacts

    # ========== 内部 ==========

    def _capture_sidebar(self):
        try:
            abs_r = ScreenCapture.get_absolute_region(self._window_rect, SIDEBAR_REGION)
            return self._capture.capture(abs_r)
        except Exception as e:
            print(f"⚠️ 联系人列表截图失败: {e}")
            return None

    @staticmethod
    def _extract_items(ocr_result: list) -> list[dict]:
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
            items.append({
                "text": text,
                "x": float(x1),
                "y": float(y1),
                "w": float(x2) - float(x1),
                "h": float(y2) - float(y1),
            })
        items.sort(key=lambda it: it["y"])
        return items

    @staticmethod
    def _merge_rows(items: list[dict]) -> dict[str, dict]:
        """从侧边栏 OCR 行提取会话。

        微信新版会显示星期、日期或被裁切的时间，不能再依赖完整 HH:MM。
        名称/预览文字位于 x>=150，名称行之间约 90px；同一会话的预览
        位于名称下方约 30px。按 60px 最小行距取锚点可兼容这些格式。
        """
        if not items:
            return {}

        # 搜索框以下、名称/预览文字列以内；排除头像内 OCR 和右侧时间列。
        text_items = [
            item for item in items
            if item["y"] >= 35 and 150 <= item["x"] < 320
        ]
        text_items.sort(key=lambda item: (item["y"], item["x"]))

        # 名称行右侧通常有时间/星期/日期。侧边栏滚动后，最上方可能只
        # 露出上一行的消息预览；仅按“每隔 60px 取一项”会把预览当名字。
        # 先用右侧时间列确定名称行相位，再以约 96px 的行距补齐时间未被
        # OCR 识别的名称行。
        time_y = sorted(
            item["y"] for item in items
            if item["y"] >= 35 and item["x"] >= 320
        )
        if not time_y:
            return {}

        normalized_gaps = []
        for first, second in zip(time_y, time_y[1:]):
            gap = second - first
            if gap >= 70:
                rows = max(1, round(gap / 96))
                per_row = gap / rows
                if 85 <= per_row <= 105:
                    normalized_gaps.append(per_row)
        row_pitch = median(normalized_gaps) if normalized_gaps else 96.0

        def is_name_row(item: dict) -> bool:
            for anchor_y in time_y:
                offset = item["y"] - anchor_y
                nearest_rows = round(offset / row_pitch)
                if abs(offset - nearest_rows * row_pitch) <= 12:
                    return True
            return False

        anchors = [item for item in text_items if is_name_row(item)]

        contacts = {}
        for index, anchor in enumerate(anchors):
            name = anchor["text"].strip()
            if len(name) < 2 or name.isdigit():
                name = f"会话_{index + 1}"
            preview_parts = [
                item["text"] for item in text_items
                if 18 <= item["y"] - anchor["y"] <= 55
            ]
            key = name
            if key in contacts:
                key = f"{name}#{int(anchor['y'])}"
            contacts[key] = {
                "y": anchor["y"],
                "preview": " ".join(preview_parts),
            }
        return contacts

    @staticmethod
    def _build(row: list[dict], is_time_fn) -> tuple[str, dict]:
        # 同行有时间戳才是联系人
        has_time = any(is_time_fn(it["text"]) for it in row)
        if not has_time:
            return "", {}

        # 选最像人名的文字作为联系人名
        # 排除: 纯数字(未读计数)、单字
        candidates = [it for it in row if not it["text"].isdigit() and len(it["text"]) >= 2]
        if not candidates:
            return "", {}

        # 优先选中文最多的
        def chinese_ratio(s):
            ch = sum(1 for c in s if '一' <= c <= '鿿')
            return ch / len(s) if s else 0
        candidates.sort(key=lambda it: chinese_ratio(it["text"]), reverse=True)
        name_item = candidates[0]

        preview = " ".join(
            it["text"] for it in row
            if it != name_item and not is_time_fn(it["text"])
        )
        return name_item["text"], {"y": name_item["y"], "preview": preview}


# ========== 测试 ==========

if __name__ == "__main__":
    from wechat.window import WeChatWindow

    w = WeChatWindow()
    if w.find():
        w.activate()
        cl = ContactList()
        cl.set_window_rect(w.get_rectangle())
        contacts = cl.scan()
        print(f"\n联系人 ({len(contacts)}):")
        for name, info in contacts.items():
            print(f"  {name:16s} y={info['y']:4.0f}  {info['preview'][:30]}")
