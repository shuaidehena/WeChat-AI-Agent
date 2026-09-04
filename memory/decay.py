"""
记忆衰减计算器
根据记忆类型和创建时间计算当前有效程度
"""

import sys
from datetime import datetime, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryDecay:
    """记忆衰减计算器"""

    def calculate(self, mem_type: str, expire_days: int | None,
                  created_time: str = None) -> float:
        """
        计算衰减后的有效值

        Args:
            mem_type: 记忆类型
            expire_days: 过期天数（None=永不过期）
            created_time: 创建时间字符串

        Returns:
            0~1 之间，1=完全有效，0=已过期
        """
        # 永不过期
        if expire_days is None:
            return 1.0

        # 无创建时间 → 默认 1.0
        if not created_time:
            return 1.0

        try:
            t = datetime.strptime(created_time[:10], "%Y-%m-%d")
            days_passed = (datetime.now() - t).days

            if days_passed <= 0:
                return 1.0

            # 线性衰减：days_passed / expire_days
            if days_passed >= expire_days:
                return 0.1  # 不完全归零，保留微弱信号

            return 1.0 - (days_passed / expire_days) * 0.9

        except (ValueError, TypeError):
            return 1.0


# ========== 测试 ==========

if __name__ == "__main__":
    d = MemoryDecay()

    print("一周前的情绪(7天过期):", d.calculate("emotion", 7, (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")))
    print("90天前的goal(90天):", d.calculate("goal", 90, (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")))
    print("永不过期的identity:", d.calculate("identity", None, "2025-01-01"))
    print("今天的event(30天):", d.calculate("event", 30, datetime.now().strftime("%Y-%m-%d")))
