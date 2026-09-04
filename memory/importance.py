"""
记忆重要性计算器
根据类型、频率等因素计算综合重要性
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ImportanceCalculator:
    """重要性计算器

    综合: 类型基础分 + 重复出现 + 用户强调
    """

    def calculate(self, mem_type: str, content: str = "",
                  base_importance: float = 0.5, repeat_count: int = 0) -> float:
        """
        计算最终重要性

        Args:
            mem_type: 记忆类型
            content: 内容文本
            base_importance: 基础重要度（来自 quality_filter）
            repeat_count: 同样/类似内容出现次数

        Returns:
            0~1 的重要度
        """
        score = base_importance

        # 重复出现 +0.1
        if repeat_count >= 2:
            score += 0.10

        # 用户强调（含"很重要""关键"等词）+0.1
        emphatic_words = ["很关键", "很重要", "必须", "一定要", "千万"]
        if any(w in content for w in emphatic_words):
            score += 0.10

        # 情绪类型额外降权
        if mem_type == "emotion" and "废物" in content:
            score = min(score, 0.20)

        return min(max(score, 0.1), 1.0)
