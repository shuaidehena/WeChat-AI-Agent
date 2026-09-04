"""
PersonalStyle 持久化
保存至 storage/personal/my_style.json
"""

import os
import sys
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from personal.style_schema import PersonalStyle
from utils.atomic_io import write_json_atomic


class StyleStorage:
    """个人风格存储"""

    DEFAULT_DIR = "storage/personal"
    DEFAULT_FILE = "my_style.json"

    def __init__(self, filepath: str = None):
        if filepath is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(base, self.DEFAULT_DIR, self.DEFAULT_FILE)
        self.filepath = filepath

    def load(self) -> PersonalStyle:
        if not os.path.exists(self.filepath):
            return PersonalStyle()
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PersonalStyle.from_dict(data)
        except (json.JSONDecodeError, IOError, TypeError):
            return PersonalStyle()

    def save(self, style: PersonalStyle) -> bool:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            style.updated_time = __import__("datetime").datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            write_json_atomic(self.filepath, style.to_dict())
            return True
        except IOError:
            return False

    def exists(self) -> bool:
        return os.path.exists(self.filepath)
