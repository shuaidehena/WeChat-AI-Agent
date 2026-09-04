"""
系统消息 / 时间分隔符过滤器

微信聊天区域 OCR 常误识别：
  - 居中灰色时间戳（19:52、昨天 19:13）
  - 日期分隔行（2026年7月8日、星期一）
  - 系统提示（撤回了一条消息、[转账]、交易提醒等）
"""

import re


class SystemMessageFilter:
    """过滤非聊天消息，并清理 OCR 误拼接的时间前缀/后缀"""

    RE_PURE_TIME = re.compile(r"^(\d{1,2}:\d{2})(:\d{2})?$")
    RE_HAS_TIME = re.compile(r"(\d{1,2}:\d{2})(:\d{2})?")
    RE_DATE = re.compile(
        r"\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?"
        r"|^昨天$|^今天$|^前天$"
        r"|^星期[一二三四五六日天]$"
    )
    RE_DATE_TIME_LINE = re.compile(
        r"^(昨天|今天|前天)\s*\d{1,2}:\d{2}(:\d{2})?$"
    )
    RE_DATE_WITH_TIME = re.compile(
        r"^(昨天|今天|前天)\s*\d{1,2}:\d{2}"
    )
    RE_LEADING_TIME = re.compile(r"^(\d{1,2}:\d{2})(:\d{2})?\s+(.+)$", re.DOTALL)
    RE_TRAILING_TIME = re.compile(r"^(.+?)\s+(\d{1,2}:\d{2})$", re.DOTALL)

    # 纯噪音（OCR 碎片）
    RE_NOISE = re.compile(
        r"^[\d\.KkMmWw万\s]+$"
        r"|^[\(\)（）\[\]【】{}/\\\-—|•·,，。.、:：;；!！?？]+$"
    )

    SYSTEM_KEYWORDS = (
        "撤回了一条消息",
        "你撤回了一条消息",
        "以上是打招呼的内容",
        "开启了朋友验证",
        "发起了语音通话",
        "发起了视频通话",
        "通话时长",
        "交易提醒",
        "微信转账",
        "微信红包",
        "拍了拍",
        "@所有人",
        "复制",
        "放大阅读",
        "转发",
        "收藏",
        "多选",
        "GMT+08:00",
        "中国标准时间",
        "以下是新消息",
        "whereareyou",
    )

    SYSTEM_TAGS = (
        "[已收款]", "[转账]", "[红包]", "[文件]", "[图片]",
        "[视频]", "[语音]", "[链接]", "[小程序]", "[聊天记录]",
        "[表情]", "[位置]", "[名片]", "[合并转发]",
    )

    # 居中区域判定：气泡中心距聊天区中线不超过此比例
    CENTER_TOLERANCE = 0.10
    # 时间分隔符通常较窄
    MAX_TIME_DIVIDER_WIDTH_RATIO = 0.45

    def should_skip(self, item: dict, chat_width: int) -> bool:
        """判断 OCR 条目是否应丢弃（非用户消息）"""
        text = str(item.get("text", "")).strip()
        if not text:
            return True

        if self.RE_NOISE.match(text):
            return True

        if self._is_system_message(text):
            return True

        if self._is_pure_time_or_date(text):
            return True

        if self._is_centered_time_divider(item, chat_width):
            return True

        # 日期+时间行（无实质聊天内容）
        if self.RE_DATE_TIME_LINE.match(text):
            return True

        # 仅含日期/时间的短行
        if len(text) <= 20 and self.RE_DATE.search(text) and not self._has_chat_content(text):
            return True

        return False

    def clean_content(self, text: str) -> str:
        """清理误拼接在消息前后或中间的时间戳"""
        text = text.strip()
        if not text:
            return text

        # 去掉开头 "19:55 你好" 中的时间前缀
        m = self.RE_LEADING_TIME.match(text)
        if m:
            rest = m.group(3).strip()
            if len(rest) >= 2 and not self._is_pure_time_or_date(rest):
                text = rest

        # 去掉结尾 "hibabe 19:44" 中的时间后缀
        m = self.RE_TRAILING_TIME.match(text)
        if m:
            body, _time = m.group(1).strip(), m.group(2)
            if len(body) >= 2 and not self._is_pure_time_or_date(body):
                text = body

        return text.strip()

    @staticmethod
    def strip_new_message_marker(text: str) -> str:
        """去掉「以下是新消息」等 UI 分隔符"""
        from memory.content_filter import clean_for_memory
        return clean_for_memory(text)

    def is_noise_content(self, text: str) -> bool:
        """合并后的消息内容是否仍应丢弃"""
        text = text.strip()
        if not text:
            return True
        if self.RE_NOISE.match(text):
            return True
        if self._is_system_message(text):
            return True
        if self._is_pure_time_or_date(text):
            return True
        return False

    def _is_centered_time_divider(self, item: dict, chat_width: int) -> bool:
        if chat_width <= 0:
            return False

        center_x = item["x"] + item["w"] / 2
        mid_x = chat_width / 2
        is_centered = abs(center_x - mid_x) < chat_width * self.CENTER_TOLERANCE
        if not is_centered:
            return False

        text = item["text"].strip()
        is_narrow = item["w"] < chat_width * self.MAX_TIME_DIVIDER_WIDTH_RATIO

        if self._is_pure_time_or_date(text):
            return True

        if is_narrow and self.RE_HAS_TIME.search(text) and len(text) <= 24:
            if not self._has_chat_content(text):
                return True

        if is_narrow and self.RE_DATE.search(text) and len(text) <= 24:
            if not self._has_chat_content(text):
                return True

        return False

    def _is_pure_time_or_date(self, text: str) -> bool:
        text = text.strip()
        if self.RE_PURE_TIME.match(text):
            return True
        if self.RE_DATE_TIME_LINE.match(text):
            return True
        if self.RE_DATE.match(text) and not self.RE_HAS_TIME.search(text):
            return True
        return False

    def _is_system_message(self, text: str) -> bool:
        for tag in self.SYSTEM_TAGS:
            if tag in text:
                return True
        for kw in self.SYSTEM_KEYWORDS:
            if kw in text:
                return True
        return False

    @staticmethod
    def _has_chat_content(text: str) -> bool:
        """文本除日期/时间外是否还有聊天内容"""
        stripped = SystemMessageFilter.RE_HAS_TIME.sub("", text)
        stripped = SystemMessageFilter.RE_DATE.sub("", stripped)
        stripped = re.sub(r"(昨天|今天|前天)", "", stripped)
        stripped = stripped.strip("…．.· \t:：")
        return len(stripped) >= 2
