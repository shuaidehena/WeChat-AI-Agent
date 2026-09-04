"""控制台隐私显示。默认只显示长度，显式开启后才显示聊天正文。"""

import os


def display_text(text: str, preview: int = 80) -> str:
    value = str(text or "")
    if os.getenv("WECHAT_SHOW_CONTENT", "0") == "1":
        return value[:preview] + ("..." if len(value) > preview else "")
    return f"<内容已隐藏，{len(value)}字>"
