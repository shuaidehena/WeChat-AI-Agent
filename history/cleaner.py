"""
历史聊天清洗器
过滤无价值消息（语气词、短文本、纯数字等）
"""

import sys
import re

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryCleaner:
    """清洗历史聊天，只保留有价值的内容"""

    # 无价值消息
    NOISE_EXACT = {
        "哈哈", "呵呵", "嘿嘿", "嘻嘻", "hhh", "哈哈哈",
        "嗯", "嗯嗯", "嗯呢", "哦", "哦哦", "噢",
        "好的", "好", "ok", "OK", "Ok", "okok",
        "收到", "知道了", "明白", "懂了",
        "1", "2", "3", "4", "5", "6",
        "?", "？", "。。。", "......", "..",
        "😂", "👍", "👌", "🙏",
    }

    # 只保留 friend 的消息（自己的消息不用于记忆提取）
    KEEP_SENDER = {"friend"}

    def clean(self, messages: list[dict]) -> list[dict]:
        """
        清洗消息列表

        Args:
            messages: [{"sender": "friend", "text": "..."}, ...]

        Returns:
            清洗后的有效消息列表
        """
        cleaned = []
        for msg in messages:
            text = msg.get("text", "").strip()
            sender = msg.get("sender", "")

            # 只保留 friend 的消息
            if sender not in self.KEEP_SENDER:
                continue

            # 空消息
            if not text:
                continue

            # 精确匹配噪音
            if text in self.NOISE_EXACT:
                continue

            # 短于2字
            if len(text) < 2:
                continue

            # 纯数字/符号
            if re.match(r'^[\d\s\.\,\;\:\!\?\+\-\(\)\[\]【】\\/\@\#\$\%\^\&\*]+$', text):
                continue

            # 纯表情/特殊字符
            if re.match(r'^[😂👍👌🙏😊😁❤️🔥🎉💪]+$', text):
                continue

            cleaned.append(msg)

        return cleaned
