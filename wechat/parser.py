"""
消息解析模块
将 OCR 识别的文字列表转换为结构化的消息对象

输入:  OCR 文字列表（聊天区域截图）
输出:  [{"sender": "张三", "content": "最近怎么样"}, ...]

解析策略:
  遍历 OCR 行 → 判断每行是"人名"还是"消息内容"
  → 人名开启新消息 → 后续内容归属该人名
"""

import re
import sys
import warnings

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.warn(
    "wechat.parser 已废弃；实时消息请使用 parser.bubble_parser",
    DeprecationWarning,
    stacklevel=2,
)


class Message:
    """一条结构化消息"""
    def __init__(self, sender: str, content: str):
        self.sender = sender
        self.content = content

    def __repr__(self):
        return f'Message(sender="{self.sender}", content="{self.content}")'


class MessageParser:
    """消息解析器

    将 OCR 文字列表解析为结构化消息，适配微信聊天对话视图。

    Args:
        chat_partner: 聊天对象名称（从标题栏 OCR 获取）。
                      在 1v1 聊天中，消息气泡不显示发送者名称，
                      此参数作为所有消息的默认发送者。
    """

    # 包含时间标记的行: "11:41", "智..．10:57", "昨天 19:13", "0:21"
    RE_HAS_TIME = re.compile(r'(\d{1,2}:\d{2})(:\d{2})?')
    # 日期: "2026年6月30日", "昨天", "星期一"
    RE_DATE = re.compile(
        r'\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?|昨天|今天|星期[一二三四五六日天]'
    )
    # "名字+时间" 合并: "助手16:29"
    RE_NAME_TIME = re.compile(r'^(.{1,8}?)\s*(\d{1,2}:\d{2})$')
    # 纯噪音
    RE_NOISE = re.compile(r'^[\d\.KkMmWw万\s]+$|^[\(\)（）\[\]【】{}/\\\-—|•·,，。.、:：;；!！?？]+$')
    # 纯时间行
    RE_PURE_TIME = re.compile(r'^(\d{1,2}:\d{2})(:\d{2})?$')

    def __init__(self, chat_partner: str | None = None):
        """
        Args:
            chat_partner: 聊天对象名称，从标题栏 OCR 获取
        """
        self.chat_partner = chat_partner

    def parse(self, ocr_texts: list[str]) -> list[Message]:
        """
        解析 OCR 文字为结构化消息

        Args:
            ocr_texts: OCR 文字列表，按从上到下排列

        Returns:
            list[Message]: 结构化消息
        """
        print(f"\n📝 正在解析 {len(ocr_texts)} 段文字...")

        # ===== 第1步：清洗（只过滤噪音，保留时间/日期作为消息边界）=====
        lines = []
        for t in ocr_texts:
            t = t.strip()
            if not t:
                continue
            if self.RE_NOISE.match(t):
                continue
            # 纯日期（不含时间）且无实质内容 → 跳过
            if self.RE_DATE.match(t) and not self.RE_HAS_TIME.search(t):
                continue
            lines.append(t)

        if not lines:
            print("⚠️ 清洗后无有效文本")
            return []

        # ===== 决定解析模式 =====
        # 有关联聊天对象名 → 1v1 聊天模式：所有文字都是消息内容
        if self.chat_partner:
            return self._parse_conversation(lines)

        # 无关联聊天对象名 → 聊天列表模式：识别 sender + content
        return self._parse_chat_list(lines)

    def _parse_conversation(self, lines: list[str]) -> list[Message]:
        """
        聊天对话模式：以时间戳为消息边界分割多条消息。
        """
        messages: list[Message] = []
        current_parts: list[str] = []

        for text in lines:
            # 判断是否为时间边界
            if self._is_time_boundary(text):
                if current_parts:
                    content = "".join(current_parts).strip()
                    if content:
                        messages.append(Message(sender=self.chat_partner, content=content))
                    current_parts = []
                # 如果行中有纯内容部分（如 "智..．10:57"），提取内容
                content_part = self._strip_time(text)
                if content_part:
                    current_parts.append(content_part)
                continue

            current_parts.append(text)

        # 最后一条
        if current_parts:
            content = "".join(current_parts).strip()
            if content:
                messages.append(Message(sender=self.chat_partner, content=content))

        messages = self._post_process(messages)

        print(f"✅ 解析完成（对话模式），共 {len(messages)} 条消息")
        for i, m in enumerate(messages):
            print(f"  [{i+1}] {m.sender}: {m.content}")

        return messages

    def _is_time_boundary(self, text: str) -> bool:
        """判断是否为时间标记（消息边界）"""
        # 纯时间: "11:41", "0:21"
        if self.RE_PURE_TIME.match(text):
            return True
        # 含日期: "昨天", "昨天 19:13", "2026年1月..."
        if self.RE_DATE.search(text):
            return True
        # 含时间: "智..10:57" — 只要行中有 HH:MM 就作为边界
        if self.RE_HAS_TIME.search(text):
            return True
        return False

    def _strip_time(self, text: str) -> str:
        """从含时间的行中剥离时间部分，返回剩余内容"""
        # 移除时间部分 "10:57"
        result = self.RE_HAS_TIME.sub("", text)
        # 移除日期部分
        result = self.RE_DATE.sub("", result)
        # 清理多余符号
        result = result.strip("…．.· \t")
        return result

    def _parse_chat_list(self, lines: list[str]) -> list[Message]:
        """
        聊天列表模式：识别联系人名 + 消息预览配对。
        """
        messages: list[Message] = []
        current_sender: str | None = None
        current_content: list[str] = []

        for text in lines:
            if self.RE_PURE_TIME.match(text):
                continue

            name = self._extract_name(text)
            if name:
                self._flush(messages, current_sender, current_content)
                current_sender = name
                current_content = []
                continue

            current_content.append(text)

        self._flush(messages, current_sender, current_content)
        messages = self._post_process(messages)

        print(f"✅ 解析完成（列表模式），共 {len(messages)} 条消息")
        for i, m in enumerate(messages):
            print(f"  [{i+1}] {m.sender}: {m.content}")

        return messages

    def to_dict_list(self, messages: list[Message]) -> list[dict]:
        """转为字典列表"""
        return [{"sender": m.sender, "content": m.content} for m in messages]

    # ========== 内部方法 ==========

    @staticmethod
    def _flush(messages: list, sender: str | None, content: list[str]):
        """保存一条消息"""
        if sender and content:
            messages.append(Message(sender=sender, content="".join(content)))
        elif sender and not content:
            # 只有名字没有内容 → 可能是误判，跳过
            pass

    def _extract_name(self, text: str) -> str | None:
        """
        判断文本是否为发送者名称
        """
        t = text.strip()
        if len(t) == 0 or len(t) > 12:
            return None

        # 明显是消息内容的特征 → 不是人名
        if self._looks_like_content(t):
            return None

        # "名字+时间"
        m = self.RE_NAME_TIME.match(t)
        if m:
            name = m.group(1).strip()
            if self._looks_like_name(name):
                return name

        # 短中文名
        if self._looks_like_name(t):
            return t

        return None

    @staticmethod
    def _looks_like_content(text: str) -> bool:
        """判断是否明显是消息内容（而非人名）"""
        # 长句 → 消息
        if len(text) > 15:
            return True
        # 含完整标点（句号、感叹号、问号在末尾）→ 消息
        if text.endswith(("。", "！", "？", "…", ".", "!", "?", "~")):
            return True
        # 含 @ 开头 → @某人消息
        if text.startswith("@"):
            return True
        # 含典型消息词汇
        msg_keywords = ["欢迎", "各位", "大家", "注意", "提醒", "通知", "请", "收到", "确认"]
        for kw in msg_keywords:
            if text.startswith(kw) and len(text) > 4:
                return True
        return False

    @staticmethod
    def _looks_like_name(text: str) -> bool:
        """判断是否像人名/昵称"""
        if len(text) > 8:
            return False

        # 系统消息标签 → 不是人名
        sys_tags = [
            "[已收款]", "[转账]", "[红包]", "[文件]", "[图片]",
            "[视频]", "[语音]", "[链接]", "[小程序]", "[聊天记录]",
            "撤回了一条消息", "@所有人", "http", "www.", ".com",
            "欢迎", "提醒", "通知", "确认", "收到",
        ]
        for tag in sys_tags:
            if tag in text:
                return False

        # 以 [] 包裹的 → 不是人名
        if text.startswith("[") and text.endswith("]"):
            return False

        # 包含手机号特征的 → 不是人名
        if any(c.isdigit() for c in text) and len([c for c in text if c.isdigit()]) >= 5:
            return False

        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        alpha = sum(1 for c in text if c.isalpha())
        digit = sum(1 for c in text if c.isdigit())
        total = len(text)

        if total == 0:
            return False

        # 纯中文 1-6字 → 人名
        if chinese == total and 1 <= chinese <= 6:
            return True

        # 中文+数字 (如 "张三123", "426陶嘉义") → 可能是联系人备注
        if chinese >= 1 and digit >= 1 and chinese + digit == total and 2 <= total <= 8:
            return True

        # 中英混合但中文为主
        if chinese > 0 and chinese >= total * 0.3:
            return True

        # 纯英文昵称 2-10字符
        if text.isascii() and alpha >= 2 and digit == 0 and 2 <= total <= 10:
            return True

        return False

    @staticmethod
    def _post_process(messages: list[Message]) -> list[Message]:
        """后处理: 去重、清理空白"""
        if not messages:
            return messages

        cleaned = []
        for m in messages:
            sender = m.sender.rstrip("….").rstrip(".")
            content = m.content.strip()

            # 跳过空内容
            if not content:
                continue

            # 跳过 sender 和 content 相同的情况 (OCR 重复)
            if sender == content:
                continue

            cleaned.append(Message(sender=sender, content=content))

        return cleaned


# ========== 快速测试 ==========

if __name__ == "__main__":
    from wechat.ocr import OCRReader

    reader = OCRReader()
    texts = reader.recognize("debug/chat_area.png")

    parser = MessageParser()
    messages = parser.parse(texts)

    print("\n" + "=" * 50)
    print("结构化输出（供 AI Agent 使用）:")
    print("-" * 50)
    for m in messages:
        print(f'  {{sender: "{m.sender}", content: "{m.content}"}}')
