"""
聊天日志模块
记录所有对话和 AI 回复，方便回溯
"""

import os
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatLogger:
    """聊天日志记录器

    记录格式:
      时间 | 好友 | 收到/发送 | 内容 | 状态
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        # 按日期分文件
        date_str = datetime.now().strftime("%Y-%m-%d")
        self._log_file = os.path.join(log_dir, f"chat_{date_str}.log")
        self._log_content = os.getenv("WECHAT_LOG_CONTENT", "0") == "1"

    def log_received(self, friend: str, content: str):
        """记录收到的消息"""
        shown = content if self._log_content else f"<内容已隐藏，{len(content)}字>"
        self._write(f"[收到] {friend}: {shown}")

    def log_reply(self, friend: str, reply: str, status: str = "sent"):
        """记录 AI 回复"""
        icon = {"sent": "✅", "blocked": "🛑", "failed": "❌"}.get(status, "?")
        shown = reply if self._log_content else f"<内容已隐藏，{len(reply)}字>"
        self._write(f"[回复] {icon} {friend}: {shown}")

    def log_info(self, msg: str):
        """记录通用信息"""
        self._write(f"[信息] {msg}")

    def _write(self, line: str):
        """写入日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{timestamp} {line}\n"

        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except IOError:
            pass  # 日志写入失败不应影响主流程

        # 同时打印到控制台
        print(f"  📝 {line}")
