"""
记忆内容过滤器
清理 OCR/系统噪音，供记忆提取、质量过滤、历史存储复用
"""

import re

# 微信 UI 分隔符 / OCR 常见误识别
MEMORY_NOISE_PREFIXES = (
    "以下是新消息",
    "以上是打招呼的内容",
)

MEMORY_NOISE_KEYWORDS = (
    "以下是新消息",
    "以上是打招呼的内容",
    "撤回了一条消息",
    "你撤回了一条消息",
    "微信转账",
    "微信红包",
    "交易提醒",
    "复制",
    "放大阅读",
    "百度网盘",
    "腾讯会议",
)

# 纯 UI 分隔符行（整行匹配则丢弃）
MEMORY_NOISE_EXACT = {
    "以下是新消息",
    "以上是打招呼的内容",
    "whereareyou",
}


def clean_for_memory(text: str) -> str:
    """清理文本，去掉系统/UI 前缀，供存储和提取使用"""
    text = str(text or "").strip()
    if not text:
        return ""

    # 去掉「以下是新消息 xxx」前缀（可重复出现）
    changed = True
    while changed:
        changed = False
        for prefix in MEMORY_NOISE_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                changed = True
        # 行内前缀：「下班就去拿 以下是新消息 期待」
        for prefix in MEMORY_NOISE_PREFIXES:
            idx = text.find(prefix)
            if idx > 0:
                before = text[:idx].strip()
                after = text[idx + len(prefix):].strip()
                text = f"{before} {after}".strip() if after else before
                changed = True
            elif idx == 0:
                text = text[len(prefix):].strip()
                changed = True

    # 去掉首尾孤立时间戳（与 system_filter 互补）
    text = re.sub(r"^(\d{1,2}:\d{2})(:\d{2})?\s+", "", text)
    text = re.sub(r"\s+(\d{1,2}:\d{2})$", "", text)

    return text.strip()


def is_memory_noise(text: str) -> bool:
    """判断是否应跳过记忆提取/存储"""
    text = str(text or "").strip()
    if not text:
        return True

    if text in MEMORY_NOISE_EXACT:
        return True

    cleaned = clean_for_memory(text)
    if not cleaned:
        return True
    if cleaned in MEMORY_NOISE_EXACT:
        return True
    if len(cleaned) < 2:
        return True

    for kw in MEMORY_NOISE_KEYWORDS:
        if kw in text and len(cleaned) <= len(kw) + 4:
            return True

    return False
