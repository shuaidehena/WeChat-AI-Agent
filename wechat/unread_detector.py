"""
未读消息检测模块
扫描侧边栏红点 + 数字，判断哪个联系人有未读消息

检测策略:
  1. 截图侧边栏
  2. 在头像角标区域 (x:35~68) 扫描紧凑红色像素簇
  3. 过滤过大/过宽的红色区域（预览文字、头像装饰等误报）
  4. 匹配到联系人行
"""

import sys
import numpy as np
from PIL import Image
from wechat.screenshot import ScreenCapture
from wechat.contact_list import ContactList
from config.settings import SIDEBAR_REGION

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class UnreadDetector:
    """未读消息检测器"""

    # 未读角标通常在头像右缘，比整列头像区更窄
    RED_DOT_X1, RED_DOT_X2 = 35, 68
    RED_R_MIN, RED_G_MAX, RED_B_MAX = 165, 95, 95
    MIN_CONSECUTIVE_ROWS = 3
    MAX_CONSECUTIVE_ROWS = 22
    MIN_RED_PER_ROW = 2
    MIN_CLUSTER_SIZE = 18
    MAX_CLUSTER_SIZE = 180

    def __init__(self):
        self._capture = ScreenCapture()
        self._window_rect: dict | None = None
        self._contact_list = ContactList()

    def set_window_rect(self, rect: dict):
        self._window_rect = rect
        self._contact_list.set_window_rect(rect)

    def detect_unread(self) -> list[dict]:
        """检测未读联系人"""
        img = self._capture_sidebar()
        if img is None:
            return []

        red_clusters = self._find_red_dots(img)
        if not red_clusters:
            return []

        contacts = self._contact_list.scan()
        if not contacts:
            return []

        unread = []
        matched = set()

        sorted_contacts = sorted(contacts.items(), key=lambda x: x[1]["y"])
        row_ranges = {}
        for i, (name, info) in enumerate(sorted_contacts):
            prev_y = sorted_contacts[i - 1][1]["y"] if i > 0 else 0
            next_y = (
                sorted_contacts[i + 1][1]["y"]
                if i < len(sorted_contacts) - 1
                else 999
            )
            row_top = (prev_y + info["y"]) / 2
            row_bottom = (info["y"] + next_y) / 2
            row_ranges[name] = (row_top, row_bottom)

        for cluster in red_clusters:
            ry = cluster["y"]
            best = None
            for name, info in contacts.items():
                if name in matched:
                    continue
                top, bottom = row_ranges[name]
                if top <= ry < bottom:
                    best = name
                    break
            if best:
                matched.add(best)
                unread.append({
                    "name": best,
                    "unread_count": 1,
                    "y": contacts[best]["y"],
                    "red_dot_y": ry,
                    "preview": contacts[best].get("preview", ""),
                })

        return unread

    def _find_red_dots(self, image: Image.Image) -> list[dict]:
        """扫描紧凑红色角标（排除预览文字等大面积红色）"""
        try:
            arr = np.array(image, dtype=np.int32)
            strip = arr[:, self.RED_DOT_X1:self.RED_DOT_X2, :]
            r_s, g_s, b_s = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
            red = (r_s > self.RED_R_MIN) & (g_s < self.RED_G_MAX) & (b_s < self.RED_B_MAX)
            row_red = red.sum(axis=1)

            clusters = []
            i = 0
            while i < len(row_red):
                if row_red[i] >= self.MIN_RED_PER_ROW:
                    start = i
                    total = 0
                    while i < len(row_red) and row_red[i] >= self.MIN_RED_PER_ROW:
                        total += int(row_red[i])
                        i += 1
                    height = i - start
                    if (
                        self.MIN_CONSECUTIVE_ROWS <= height <= self.MAX_CONSECUTIVE_ROWS
                        and self.MIN_CLUSTER_SIZE <= total <= self.MAX_CLUSTER_SIZE
                    ):
                        clusters.append({
                            "y": float((start + i) / 2),
                            "size": total,
                            "height": height,
                        })
                i += 1

            clusters.sort(key=lambda c: c["size"], reverse=True)
            return clusters
        except Exception:
            return []

    def _capture_sidebar(self):
        try:
            abs_r = ScreenCapture.get_absolute_region(
                self._window_rect, SIDEBAR_REGION
            )
            return self._capture.capture(abs_r)
        except Exception:
            return None
