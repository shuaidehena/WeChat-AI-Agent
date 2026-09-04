"""
规则记忆提取器
不调 LLM，从明显句式中直接提取记忆（省 token、低延迟）

覆盖: 身份、偏好、目标、关系、习惯 等高频模式
"""

import re
import sys

from memory.memory_schema import MemoryItem

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class RuleExtractor:
    """基于规则的记忆提取（LLM 前置）"""

    def __init__(self):
        self._rules = self._build_rules()

    def extract(self, text: str, friend_id: str = "", friend_name: str = "") -> MemoryItem | None:
        text = text.strip()
        if len(text) < 4:
            return None

        subject = friend_name or "TA"

        for pattern, mem_type, importance, template_fn in self._rules:
            m = pattern.search(text)
            if not m:
                continue
            try:
                content = template_fn(m, subject, text).strip()
            except Exception:
                continue
            if len(content) < 4:
                continue
            return MemoryItem(
                friend_id=friend_id,
                type=mem_type,
                content=content,
                importance=importance,
                source="rule",
                source_quote=text[:200],
            )
        return None

    @staticmethod
    def _build_rules():
        return [
            (
                re.compile(r"我是(.{2,20}?)(?:专业|学院|公司|工作|学生)"),
                "identity", 0.90,
                lambda m, s, t: f"{s}是{m.group(1).strip()}相关",
            ),
            (
                re.compile(r"(?:最)?喜欢(.{2,15})"),
                "preference", 0.75,
                lambda m, s, t: f"{s}喜欢{m.group(1).strip('了过吧呢')}",
            ),
            (
                re.compile(r"(?:很)?(?:讨厌|不喜欢)(.{2,12})"),
                "preference", 0.72,
                lambda m, s, t: f"{s}不喜欢{m.group(1).strip('了过吧呢')}",
            ),
            (
                re.compile(r"(?:准备|打算|计划)(.{0,18}?(?:考研|考公|雅思|托福|比赛|面试))"),
                "goal", 0.82,
                lambda m, s, t: f"{s}{m.group(0)}",
            ),
            (
                re.compile(r"正在(.{2,15}?(?:考研|备考|复习|准备))"),
                "goal", 0.85,
                lambda m, s, t: f"{s}正在{m.group(1)}",
            ),
            (
                re.compile(r"(?:每天|经常|总是|习惯)(.{2,18})"),
                "habit", 0.70,
                lambda m, s, t: f"{s}{m.group(0)}",
            ),
            (
                re.compile(r"和(.{2,8}?)(?:是|做)(?:室友|同学|同事|闺蜜|兄弟)"),
                "relationship", 0.78,
                lambda m, s, t: f"{s}和{m.group(1)}是同学/同事",
            ),
        ]


if __name__ == "__main__":
    ex = RuleExtractor()
    cases = [
        "我喜欢吃火锅",
        "正在准备考研数学",
        "和室友是同学",
        "哈哈",
    ]
    for t in cases:
        r = ex.extract(t, "zhangsan", "张三")
        print(f"  {t!r} → {r.content if r else None}")
