"""
记忆质量过滤器
判断记忆是否值得保存，分类并调整重要性
"""

import sys
import re

from memory.content_filter import is_memory_noise, clean_for_memory

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryQualityFilter:
    """记忆质量过滤器

    过滤垃圾内容，对不同类型的记忆分级处理。
    """

    # 垃圾内容 → 直接丢弃
    GARBAGE = {
        "哈哈", "呵呵", "嗯", "嗯嗯", "好的", "收到", "ok", "OK",
        "不知道", "不知道呀", "不清楚",
        "今天吃饭了", "吃了吗", "睡了吗",
    }

    # 系统工具类记忆 → 无个人信息价值，丢弃
    SYSTEM_TOOLS = ["百度网盘", "腾讯会议", "微信转账", "微信支付",
                    "已收款", "零钱", "转账给", "已支付", "文件",
                    "复制", "放大阅读", "入会"]

    # 记忆类型关键词映射
    TYPE_KEYWORDS = {
        "identity": ["我是", "我在", "我的专业", "我的学校", "我的工作是", "我学"],
        "relationship": ["室友", "同学", "同事", "朋友", "老师", "兄弟", "闺蜜", "男朋友", "女朋友"],
        "preference": ["喜欢", "爱", "最爱", "偏好", "感兴趣"],
        "habit": ["每天", "经常", "总是", "习惯", "一直", "坚持"],
        "goal": ["准备", "打算", "计划", "目标", "想考", "考研", "备考", "参加比赛"],
        "emotion": ["难受", "压力", "焦虑", "崩溃", "废物", "想死", "难过", "伤心", "开心", "高兴"],
        "event": ["参加", "去了", "买了", "吃了", "看了", "做了", "收到", "发了"],
    }

    # 类型的默认重要度和有效期
    TYPE_DEFAULTS = {
        "identity":     {"importance": 0.90, "expire_days": None},
        "relationship": {"importance": 0.80, "expire_days": 365},
        "goal":         {"importance": 0.75, "expire_days": 90},
        "habit":        {"importance": 0.70, "expire_days": 180},
        "preference":   {"importance": 0.65, "expire_days": 180},
        "event":        {"importance": 0.40, "expire_days": 30},
        "emotion":      {"importance": 0.25, "expire_days": 14},
    }

    # 情绪降权模式
    EMOTION_DOWNGRADE = ["废物", "想死", "崩溃", "死了算了", "不想活", "垃圾"]

    def filter(self, content: str, existing_type: str = None) -> dict | None:
        """
        过滤并分类记忆

        Args:
            content: 记忆文本
            existing_type: 已有的类型（从 extractor 传入）

        Returns:
            {"type": "preference", "importance": 0.7, "expire_days": 180} 或 None
        """
        text = content.strip()

        # 规则0: 记忆噪音（OCR/UI）
        if is_memory_noise(text):
            return None

        # 规则1: 垃圾过滤
        if self._is_garbage(text):
            return None

        # 规则2: 分类
        mem_type = existing_type or self._classify(text)

        # 规则3: 情绪降权
        if self._is_emotion_downgrade(text):
            mem_type = "emotion"

        # 规则4: 获取默认参数
        defaults = self.TYPE_DEFAULTS.get(mem_type, self.TYPE_DEFAULTS["event"])
        importance = defaults["importance"]
        expire_days = defaults["expire_days"]

        # 情绪降权：降低 importance
        if mem_type == "emotion" and self._is_emotion_downgrade(text):
            importance = 0.20
            expire_days = 7

        return {"type": mem_type, "importance": importance, "expire_days": expire_days}

    def _is_garbage(self, text: str) -> bool:
        if text in self.GARBAGE:
            return True
        if len(text) < 3:
            return True
        if re.match(r'^[\d\s\.\,\;\:\!\?]+$', text):
            return True
        # 系统工具类无价值
        if any(tool in text for tool in self.SYSTEM_TOOLS):
            return True
        return False

    def _classify(self, text: str) -> str:
        scores = {}
        for mem_type, keywords in self.TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[mem_type] = score
        if not scores:
            return "event"
        return max(scores, key=scores.get)

    def _is_emotion_downgrade(self, text: str) -> bool:
        return any(w in text for w in self.EMOTION_DOWNGRADE)


# ========== 测试 ==========

if __name__ == "__main__":
    f = MemoryQualityFilter()

    tests = [
        ("哈哈", None),
        ("我喜欢篮球", "preference"),
        ("最近压力很大", "emotion"),
        ("我是软件工程学生", "identity"),
        ("我是废物", "emotion"),
        ("室友关系", "relationship"),
        ("准备考研", "goal"),
    ]

    for text, expected_type in tests:
        r = f.filter(text)
        if r:
            print(f"  \"{text}\" → type={r['type']} imp={r['importance']} expire={r['expire_days']}d")
            if r['type'] == expected_type:
                print(f"    ✅")
            else:
                print(f"    ⚠️ expected {expected_type}")
        else:
            print(f"  \"{text}\" → None (过滤)")
