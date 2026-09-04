"""
聊天风格模块
管理 AI Agent 的聊天风格偏好
"""

import json
import os
import sys
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatStyle:
    """聊天风格管理器

    从 storage/style.json 读取聊天风格配置，
    供 AI Agent 生成回复时参考。

    数据字段:
      sentence_length — 句子长度偏好 ("short" / "medium" / "long")
      tone            — 语气 ("casual" / "formal" / "humorous")
      common_words    — 常用口头禅
      emoji_frequency — 表情使用频率 ("low" / "medium" / "high")
    """

    def __init__(self, filepath: str = "storage/style.json"):
        self.filepath = filepath
        self._data: dict = {}
        self.load()

    def load(self) -> dict:
        """从文件加载聊天风格"""
        if not os.path.exists(self.filepath):
            print(f"⚠️ 聊天风格文件不存在: {self.filepath}")
            self._data = {}
            return self._data

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            print(f"💬 聊天风格已加载: tone={self._data.get('tone', '?')}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 聊天风格读取失败: {e}")
            self._data = {}
        return self._data

    def save(self) -> bool:
        """保存聊天风格到文件"""
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            write_json_atomic(self.filepath, self._data)
            return True
        except IOError as e:
            print(f"❌ 聊天风格保存失败: {e}")
            return False

    def get_style(self) -> dict:
        """返回聊天风格"""
        return self._data.copy()

    def update(self, key: str, value) -> bool:
        """更新单个字段"""
        self._data[key] = value
        return self.save()

    # ========== 便捷属性 ==========

    @property
    def tone(self) -> str:
        return self._data.get("tone", "casual")

    @property
    def sentence_length(self) -> str:
        return self._data.get("sentence_length", "short")

    @property
    def common_words(self) -> list:
        return self._data.get("common_words", [])

    @property
    def emoji_frequency(self) -> str:
        return self._data.get("emoji_frequency", "low")


# ========== 测试 ==========

if __name__ == "__main__":
    style = ChatStyle()
    data = style.get_style()
    print(f"\n聊天风格:")
    for k, v in data.items():
        print(f"  {k}: {v}")
