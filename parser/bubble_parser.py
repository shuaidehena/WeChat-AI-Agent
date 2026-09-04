"""
气泡分析模块
根据 OCR 坐标判断消息归属（friend / me），排序并合并文本

核心原理：
  优先: 气泡颜色 — 绿色=我，白色/灰色=对方（最可靠）
  兜底: X 坐标 — 左=friend，右=me
"""

import sys
import numpy as np
from PIL import Image
from parser.message import Message
from parser.system_filter import SystemMessageFilter
from utils.privacy import display_text
from wechat.sender import WeChatSender

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class BubbleParser:
    """气泡分析器

    输入: RapidOCR 原始结果（含坐标）
    输出: 结构化的 Message 列表

    处理流程:
      1. 提取 OCR 结果 → OcrItem 列表
      2. 根据 X 坐标判断 sender（左=friend, 右=me）
      3. 按 Y 坐标排序（从上到下）
      4. 合并同一 sender 的相邻文本（Y 间距 < 阈值）
    """

    # 同一发送者的文本合并阈值（Y 坐标差值，像素）
    MERGE_Y_THRESHOLD = 50

    # 固定尺寸微信窗口中，聊天截图两侧分别包含：
    # 左侧少量侧边栏残边 + 对方头像，右侧自己的头像。
    # 气泡正文位于中间的消息通道内；头像中的文字不属于聊天内容。
    MESSAGE_LANE_LEFT_RATIO = 0.22
    MESSAGE_LANE_RIGHT_RATIO = 0.86

    def __init__(self, chat_width: int = 780):
        """
        Args:
            chat_width: 聊天区域宽度（像素），用于计算左右分界线。
                        从截图宽度获取，或从配置读取。
        """
        self.chat_width = chat_width
        # 左右分界线：中线
        self._mid_x = chat_width / 2
        self._system_filter = SystemMessageFilter()

    # ========== 主入口 ==========

    def parse(self, ocr_result: list, screenshot: Image.Image = None) -> list[Message]:
        """
        解析 OCR 原始结果为 Message 列表

        Args:
            ocr_result: RapidOCR 返回的原始列表
            screenshot: 聊天区域截图（用于颜色检测，可选）

        Returns:
            list[Message]: 按 Y 坐标排序的结构化消息
        """
        if not ocr_result:
            print("⚠️ OCR 结果为空")
            return []

        print(f"\n🫧 气泡分析: {len(ocr_result)} 个 OCR 条目, 聊天区宽度={self.chat_width}px")

        # 1. 转换为 OcrItem
        items = self._extract_items(ocr_result)

        # 1.25 过滤聊天正文通道之外的 OCR（侧边栏残边、双方头像文字）
        if screenshot:
            raw_count = len(items)
            items = [
                item for item in items
                if self._is_in_message_lane(item, screenshot.width)
            ]
            skipped = raw_count - len(items)
            if skipped:
                print(f"   🖼️ 过滤头像/边缘文字: {skipped} 条")

        # 1.5 过滤系统消息 / 时间分隔符，并清理误拼接的时间
        raw_count = len(items)
        items = [
            item for item in items
            if not self._system_filter.should_skip(item, self.chat_width)
        ]
        for item in items:
            item["text"] = self._system_filter.clean_content(item["text"])
        items = [item for item in items if item["text"]]
        skipped = raw_count - len(items)
        if skipped:
            print(f"   🚫 过滤系统/时间: {skipped} 条")

        # 2. 判断 sender（颜色优先，坐标兜底）
        color_hits = 0
        for item in items:
            if screenshot:
                sender = self._classify_by_color(item, screenshot)
                if sender:
                    item["sender"] = sender
                    color_hits += 1
                    continue
            # 兜底：X 坐标
            item["sender"] = self._classify(item["x"])

        if color_hits > 0:
            print(f"   🎨 颜色识别: {color_hits}/{len(items)} 条")
        print(f"   中线 x={self._mid_x:.0f}px (兜底: 左=friend, 右=me)")

        # 3. 按 Y 排序
        items.sort(key=lambda it: it["y"])

        # 4. 合并同 sender 相邻文本
        messages = self._merge_adjacent(items)
        messages = self._fix_auto_reply_senders(messages)

        print(f"✅ 解析完成: {len(messages)} 条消息")
        for msg in messages:
            print(
                f"   [{msg.sender}] {display_text(msg.content)} "
                f"@ ({int(msg.x)}, {int(msg.y)})"
            )

        return messages

    # ========== 内部方法 ==========

    def _extract_items(self, ocr_result: list) -> list[dict]:
        """
        从 OCR 原始结果提取结构化条目

        Returns:
            [{"text": str, "x": float, "y": float, "w": float, "h": float, "conf": float}, ...]
        """
        items = []
        for entry in ocr_result:
            if not entry or len(entry) < 2:
                continue

            box = entry[0]     # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            text = entry[1]    # "文字内容"
            conf = entry[2] if len(entry) >= 3 else 0.0

            text = str(text).strip()
            if not text:
                continue

            # 提取左上角和右下角
            x1, y1 = box[0]  # 左上角
            x2, y2 = box[2]  # 右下角

            items.append({
                "text": text,
                "x": float(x1),
                "y": float(y1),
                "w": float(x2) - float(x1),
                "h": float(y2) - float(y1),
                "conf": float(conf),
            })

        return items

    @classmethod
    def _is_in_message_lane(cls, item: dict, screenshot_width: int) -> bool:
        """只保留气泡正文所在的横向通道，排除头像和截图边缘文字。"""
        if screenshot_width <= 0:
            return True

        center_x = item["x"] + item["w"] / 2
        left = screenshot_width * cls.MESSAGE_LANE_LEFT_RATIO
        right = screenshot_width * cls.MESSAGE_LANE_RIGHT_RATIO
        return left <= center_x <= right

    def _classify(self, x: float) -> str:
        """根据 X 坐标判断（兜底方案）"""
        return "friend" if x < self._mid_x else "me"

    def _classify_by_color(self, item: dict, screenshot: Image.Image) -> str | None:
        """
        根据气泡颜色判断消息归属

        微信规则:
          我发送的 → 绿色气泡  (RGB 中 G 通道偏高)
          对方发送 → 白色/灰色气泡 (RGB 三通道均衡)

        Args:
            item: {"x","y","w","h",...}
            screenshot: 聊天区域 PIL Image

        Returns:
            "friend" / "me" / None（颜色不明确时返回 None，走兜底）
        """
        try:
            x, y, w, h = int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"])

            # 采样区域：气泡内部（缩进几个像素避免边缘）
            margin = 3
            x1 = max(0, x + margin)
            y1 = max(0, y + margin)
            x2 = min(screenshot.width, x + w - margin)
            y2 = min(screenshot.height, y + h - margin)

            if x2 <= x1 or y2 <= y1 or (x2 - x1) * (y2 - y1) < 10:
                return None  # 区域太小，忽略

            # 裁剪并计算平均颜色
            crop = screenshot.crop((x1, y1, x2, y2))
            arr = np.array(crop, dtype=np.float32)

            if arr.size == 0:
                return None

            mean_rgb = arr.reshape(-1, 3).mean(axis=0)  # [R, G, B]

            r, g, b = mean_rgb[0], mean_rgb[1], mean_rgb[2]

            # 判断绿色气泡: G 通道明显高于 R 和 B
            if g > r * 1.08 and g > b * 1.05:
                return "me"

            # 判断白/灰色气泡: 三通道接近（差值小）
            max_diff = max(abs(r - g), abs(g - b), abs(r - b))
            avg_brightness = (r + g + b) / 3
            if max_diff < 20 and avg_brightness > 100:
                return "friend"

            return None  # 不确定，走兜底

        except Exception:
            return None

    def _merge_adjacent(self, items: list[dict]) -> list[Message]:
        """
        合并相邻的同 sender 文本

        规则:
          - sender 相同
          - Y 坐标间距 < MERGE_Y_THRESHOLD
          → 合并为一条消息（空格拼接）

        不允许合并:
          - sender 不同 → 保持独立消息
          - Y 间距过大 → 可能是不同时间的消息

        Args:
            items: 已排序的条目列表（含 sender）

        Returns:
            list[Message]: 合并后的消息列表
        """
        if not items:
            return []

        messages = []
        current = None

        for item in items:
            if current is None:
                # 第一条
                current = item
                continue

            # 判断是否可以合并
            same_sender = current["sender"] == item["sender"]
            y_gap = item["y"] - (current["y"] + current["h"])
            close_enough = y_gap < self.MERGE_Y_THRESHOLD

            if same_sender and close_enough:
                # 合并：追加文本
                current["text"] += " " + item["text"]
                # 更新高度（扩展到底部）
                new_bottom = max(
                    current["y"] + current["h"],
                    item["y"] + item["h"]
                )
                current["h"] = new_bottom - current["y"]
                # 置信度取最低值
                current["conf"] = min(current["conf"], item["conf"])
            else:
                # 保存当前，开始新的
                msg = self._build_message(current)
                if msg:
                    messages.append(msg)
                current = item

        # 最后一条
        if current:
            msg = self._build_message(current)
            if msg:
                messages.append(msg)

        return messages

    @staticmethod
    def _fix_auto_reply_senders(messages: list[Message]) -> list[Message]:
        """带自动回复前缀的一律视为自己发送（避免颜色/坐标误判）"""
        for msg in messages:
            if WeChatSender.is_auto_reply(msg.content):
                msg.sender = "me"
        return messages

    def _build_message(self, item: dict) -> Message:
        """从条目构建 Message 对象"""
        content = self._system_filter.clean_content(item["text"])
        if self._system_filter.is_noise_content(content):
            return None

        return Message(
            sender=item["sender"],
            content=content,
            x=item["x"],
            y=item["y"],
            width=item["w"],
            height=item["h"],
            confidence=item["conf"],
        )


# ========== 模拟测试 ==========

if __name__ == "__main__":
    """用模拟 OCR 数据测试 BubbleParser"""
    print("=" * 60)
    print("  BubbleParser 模拟测试")
    print("=" * 60)

    # 模拟 OCR 数据: [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "text", confidence]
    mock_ocr = [
        [[[100, 100], [200, 100], [200, 150], [100, 150]], "你好", 0.99],
        [[[100, 160], [250, 160], [250, 200], [100, 200]], "最近怎么样", 0.98],
        [[[600, 250], [700, 250], [700, 300], [600, 300]], "还不错", 0.97],
        [[[340, 220], [440, 220], [440, 250], [340, 250]], "19:52", 0.95],
        [[[100, 350], [300, 350], [300, 400], [100, 400]], "今天晚上", 0.99],
        [[[100, 410], [280, 410], [280, 450], [100, 450]], "一起吃饭吗", 0.98],
        [[[600, 480], [680, 480], [680, 520], [600, 520]], "好的", 0.99],
        [[[330, 520], [450, 520], [450, 550], [330, 550]], "昨天 19:13", 0.94],
        [[[100, 560], [420, 560], [420, 600], [100, 600]], "19:55 你知道我喜欢啥吗", 0.93],
    ]

    parser = BubbleParser(chat_width=780)

    messages = parser.parse(mock_ocr)

    print("\n" + "=" * 60)
    print("最终输出:")
    print("-" * 60)
    for msg in messages:
        print(f"  {msg}")
    print("-" * 60)

    print("\nJSON 格式:")
    import json
    print(json.dumps([m.to_dict() for m in messages], ensure_ascii=False, indent=2))

    # 验证
    print("\n验证:")
    assert len(messages) == 5, f"应有5条消息, 实际{len(messages)}"
    assert messages[0].sender == "friend", "第1条应为friend"
    assert messages[0].content == "你好 最近怎么样", f"合并错误: {messages[0].content}"
    assert messages[1].sender == "me", "第2条应为me"
    assert messages[2].sender == "friend", "第3条应为friend"
    assert messages[2].content == "今天晚上 一起吃饭吗", f"合并错误: {messages[2].content}"
    assert messages[3].sender == "me", "第4条应为me"
    assert messages[4].content == "你知道我喜欢啥吗", f"时间前缀未清理: {messages[4].content}"
    assert all("19:52" not in m.content for m in messages), "不应包含纯时间戳"
    print("✅ 所有断言通过！")
