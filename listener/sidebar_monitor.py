"""
侧边栏监控模块
定时扫描微信左侧联系人列表，检测未读消息

检测方式:
  1. 截图侧边栏
  2. OCR 识别联系人名称
  3. 像素检测红点（未读标记）
  4. 返回未读联系人列表

微信红点特征: 红色小圆点，RGB 中 R 通道显著偏高
"""

import sys
import time
import warnings
import numpy as np
from PIL import Image
from typing import Optional

sys.path.insert(0, "")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.warn(
    "listener.sidebar_monitor 已废弃；请使用 wechat.unread_detector",
    DeprecationWarning,
    stacklevel=2,
)

import pyautogui
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from config.settings import SIDEBAR_REGION, UNREAD_RED_THRESHOLD


class SidebarMonitor:
    """侧边栏监控器

    扫描联系人列表，通过红点 + OCR 发现未读消息。
    """

    def __init__(self):
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._window_rect: dict | None = None
        self._last_contact: str = ""  # 上一次回复的联系人

    def set_window_rect(self, rect: dict):
        """设置微信窗口坐标"""
        self._window_rect = rect

    # ========== 主方法 ==========

    def scan_unread(self) -> list[dict]:
        """
        扫描侧边栏，返回有未读消息的联系人

        Returns:
            [{"name": "张三", "has_red_dot": True, "preview": "在吗"}, ...]
            按列表顺序排列
        """
        if not self._window_rect:
            return []

        # 1. 截侧边栏
        sidebar_img = self._capture_sidebar()
        if sidebar_img is None:
            return []

        # 2. OCR 识别联系人名和预览
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        sidebar_img.save(tmp.name)
        ocr_raw = self._ocr.recognize_with_boxes(tmp.name)
        os.unlink(tmp.name)
        contacts = self._parse_contacts(ocr_raw)

        # 3. 红点检测——扫描整个侧边栏找红点区域
        red_y_positions = self._find_red_dots(sidebar_img)

        # 4. 匹配红点与联系人
        for c in contacts:
            c["has_red_dot"] = any(
                abs(c["y"] - ry) < 50 for ry in red_y_positions
            )

        # 5. 筛选未读（排除空名和纯数字）
        unread = [c for c in contacts if c["has_red_dot"] and c["name"]]
        if unread:
            names = [c["name"] for c in unread]
            print(f"🔴 发现未读: {names}")
        return unread

    # ========== 内部方法 ==========

    def _capture_sidebar(self) -> Optional[Image.Image]:
        """截取侧边栏"""
        try:
            abs_region = ScreenCapture.get_absolute_region(
                self._window_rect, SIDEBAR_REGION
            )
            return self._capture.capture(abs_region)
        except Exception as e:
            print(f"⚠️ 侧边栏截图失败: {e}")
            return None

    def _parse_contacts(self, ocr_result: list) -> list[dict]:
        """
        从 OCR 结果提取联系人列表

        OCR 会识别到: 联系人名、最后消息预览、时间
        按 Y 坐标排序，相近的 Y 归为同一个联系人行
        """
        if not ocr_result:
            return []

        items = []
        for entry in ocr_result:
            if not entry or len(entry) < 2:
                continue
            box = entry[0]
            text = str(entry[1]).strip()
            if not text or len(text) < 1:
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

        if not items:
            return []

        # 按 Y 排序
        items.sort(key=lambda it: it["y"])

        # 合并同一行的文本
        contacts = []
        row = []
        ROW_Y_GAP = 20  # 同一行的 Y 最大差距

        for item in items:
            if not row:
                row.append(item)
            elif abs(item["y"] - row[0]["y"]) < ROW_Y_GAP:
                row.append(item)
            else:
                contacts.append(self._build_contact(row))
                row = [item]

        if row:
            contacts.append(self._build_contact(row))

        return contacts

    def _build_contact(self, row: list[dict]) -> dict:
        """从一行 OCR 项构建联系人信息"""
        row.sort(key=lambda it: it["x"])
        name = row[0]["text"]
        # 过滤明显不是联系人的条目
        if len(name) <= 1 or name.isdigit():
            name = ""
        preview = " ".join(it["text"] for it in row[1:])
        y = row[0]["y"]
        h = max(it["y"] + it["h"] for it in row) - y
        return {"name": name, "preview": preview, "y": y, "h": h}

    def _find_red_dots(self, image: Image.Image) -> list[float]:
        """
        在头像列扫描红点——划定每个联系人头像右上角 40×25px 区域，
        有 3+ 个红像素(R>180,G<80,B<80) 即为未读。

        返回红点 Y 坐标列表
        """
        try:
            arr = np.array(image, dtype=np.int32)
            # 红点在头像右上角: x=45~70（实测 x=52~65, y=93~95）
            strip = arr[:, 45:70, :]
            r_s, g_s, b_s = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
            red = (r_s > 180) & (g_s < 80) & (b_s < 80)
            row_red = red.sum(axis=1)

            # 连续3行各有>=2红像素 → 红点
            positions = []
            i = 0
            while i < len(row_red):
                if row_red[i] >= 2:
                    start = i
                    while i < len(row_red) and row_red[i] >= 2:
                        i += 1
                    if i - start >= 3:
                        positions.append(float((start + i) / 2))
                i += 1
            return positions
        except Exception:
            return []

    # ========== 联系人操作 ==========

    def click_contact(self, name: str, contact_y: float = 80):
        """
        在侧边栏点击联系人，切换到该聊天

        Args:
            name: 联系人名称
            contact_y: 联系人在侧边栏截图中的 Y 坐标
        """
        if not self._window_rect:
            return

        sidebar_abs = ScreenCapture.get_absolute_region(
            self._window_rect, SIDEBAR_REGION
        )
        # 屏幕绝对坐标 = 窗口坐标 + 侧边栏偏移 + 联系人Y
        click_x = sidebar_abs[0] + 80   # 名称区域中央
        click_y = sidebar_abs[1] + contact_y + 15  # 行中央

        pyautogui.moveTo(click_x, click_y, duration=0.1)
        pyautogui.click()
        time.sleep(0.8)  # 等聊天加载
        self._last_contact = name
        print(f"👆 已点击: {name} @ ({click_x}, {click_y})")


# ========== 测试 ==========

if __name__ == "__main__":
    from wechat.window import WeChatWindow

    wechat = WeChatWindow()
    if not wechat.find():
        print("请先启动微信")
        exit(1)
    wechat.activate()

    monitor = SidebarMonitor()
    monitor.set_window_rect(wechat.get_rectangle())

    print("扫描侧边栏...")
    unread = monitor.scan_unread()

    print(f"\n未读联系人: {len(unread)}")
    for c in unread:
        print(f"  🔴 {c['name']}: {c.get('preview', '')}")
