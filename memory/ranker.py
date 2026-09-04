"""
记忆排序过滤模块
对召回的记忆进行相关性评分和过滤

评分公式: final = similarity*0.6 + importance*0.2 + decay*0.2
过滤规则: final < 0.55 删除, decay < 0.15 删除, 最多3条
回忆型查询（你知道/记得/我之前…）: 跳过短句过滤, 偏好/身份加权, 最多5条
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.decay import MemoryDecay
from memory.quality_filter import MemoryQualityFilter


class MemoryRanker:
    """记忆排序器

    对候选记忆评分、过滤、排序，只返回最相关的。
    """

    # 权重
    W_SIMILARITY = 0.6
    W_IMPORTANCE = 0.2
    W_DECAY = 0.2

    MIN_SCORE = 0.55           # 最低通过分
    RECALL_MIN_SCORE = 0.45    # 回忆型查询放宽阈值
    MIN_DECAY = 0.15           # 过期记忆阈值
    MAX_RESULTS = 3            # 普通查询最大返回数
    MAX_RECALL_RESULTS = 5     # 回忆型查询最大返回数

    # 回忆型查询中 preference/identity 额外加分
    RECALL_TYPE_BOOST = {
        "preference": 0.15,
        "identity": 0.12,
    }

    _decay = MemoryDecay()
    _type_defaults = MemoryQualityFilter.TYPE_DEFAULTS

    # 短消息/语气词 → 不需要记忆
    SHORT_SKIP = {"哈哈", "嗯", "嗯嗯", "哦", "好的", "收到", "ok", "OK", "在吗",
                  "?", "？", "。。。", "早", "晚安", "拜拜", "再见",
                  "吃饭了吗", "在干嘛", "干嘛呢", "睡了吗"}

    # 回忆型查询特征（子串匹配）
    RECALL_PATTERNS = ("你知道", "记得", "还记得", "我喜欢什么", "我之前", "有没有说过")

    @classmethod
    def is_recall_query(cls, query: str) -> bool:
        """判断是否为回忆型查询（如 你知道我喜欢什么吗 / 记得吗）"""
        q = query.strip()
        if not q:
            return False
        return any(p in q for p in cls.RECALL_PATTERNS)

    @classmethod
    def rank(cls, query: str, memories: list[dict]) -> list[str]:
        """对候选记忆评分并过滤"""
        if not memories:
            return []

        q = query.strip()
        is_recall = cls.is_recall_query(q)

        if not is_recall and (len(q) < 3 or q in cls.SHORT_SKIP):
            return []

        min_score = cls.RECALL_MIN_SCORE if is_recall else cls.MIN_SCORE
        max_results = cls.MAX_RECALL_RESULTS if is_recall else cls.MAX_RESULTS

        scored = []
        seen = set()

        for m in memories:
            text = m.get("text", "").strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)

            meta = m.get("metadata", {}) or {}
            mem_type = meta.get("type", "event")

            similarity = m.get("score", 0.5)

            importance = meta.get("importance", 0.5)
            if isinstance(importance, str):
                try:
                    importance = float(importance)
                except ValueError:
                    importance = 0.5

            decay = cls._calc_decay(meta)

            if decay < cls.MIN_DECAY:
                continue

            final = (
                similarity * cls.W_SIMILARITY +
                importance * cls.W_IMPORTANCE +
                decay * cls.W_DECAY
            )

            if is_recall:
                final += cls.RECALL_TYPE_BOOST.get(mem_type, 0.0)

            if final >= min_score:
                scored.append((final, text))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in scored[:max_results]]

    @classmethod
    def _calc_decay(cls, meta: dict) -> float:
        """根据 MemoryDecay + expire_days 计算衰减系数"""
        mem_type = meta.get("type", "event")
        time_str = meta.get("time", "")

        expire_raw = meta.get("expire_days")
        if expire_raw is None or expire_raw == "":
            defaults = cls._type_defaults.get(mem_type, cls._type_defaults["event"])
            expire_days = defaults.get("expire_days")
        elif expire_raw == -1 or expire_raw == "-1":
            expire_days = None
        else:
            try:
                expire_days = int(expire_raw)
            except (TypeError, ValueError):
                expire_days = cls._type_defaults.get(mem_type, {}).get("expire_days")

        return cls._decay.calculate(mem_type, expire_days, time_str)


# ========== 测试 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  MemoryRanker 测试")
    print("=" * 50)

    memories = [
        {"text": "喜欢打篮球", "score": 0.82,
         "metadata": {"importance": 0.7, "time": "2026-07-07", "type": "preference", "expire_days": 180}},
        {"text": "正在准备考研数学", "score": 0.76,
         "metadata": {"importance": 0.9, "time": "2026-07-06", "type": "goal", "expire_days": 90}},
        {"text": "临时吐槽", "score": 0.80,
         "metadata": {"importance": 0.25, "time": "2026-06-01", "type": "emotion", "expire_days": 14}},
    ]

    print("\n── 查询: '周末干嘛' ──")
    result = MemoryRanker.rank("周末干嘛", memories)
    print(f"  结果({len(result)}): {result}")
    assert len(result) <= 3, "普通查询最多3条"

    print("\n── 过期 emotion 应被过滤 ──")
    old_emotion = [{"text": "旧情绪", "score": 0.85,
                    "metadata": {"time": "2026-01-01", "type": "emotion", "expire_days": 14}}]
    r = MemoryRanker.rank("最近怎么样", old_emotion)
    print(f"  结果: {r} ({'过滤' if not r else '保留'})")
    assert not r, "过期 emotion 应被 MemoryDecay 过滤"

    print("\n── 短句 '嗯' 应跳过 ──")
    r = MemoryRanker.rank("嗯", memories)
    print(f"  结果: {r}")
    assert r == [], "普通短句应返回空"

    # ── 回忆型查询测试 ──
    recall_memories = [
        {"text": "喜欢科幻片", "score": 0.55,
         "metadata": {"importance": 0.65, "time": "2026-07-01", "type": "preference", "expire_days": 180}},
        {"text": "是计算机专业大三", "score": 0.52,
         "metadata": {"importance": 0.9, "time": "2026-06-01", "type": "identity", "expire_days": -1}},
        {"text": "昨天吃了火锅", "score": 0.70,
         "metadata": {"importance": 0.4, "time": "2026-07-09", "type": "event", "expire_days": 30}},
        {"text": "准备考雅思", "score": 0.58,
         "metadata": {"importance": 0.75, "time": "2026-07-05", "type": "goal", "expire_days": 90}},
        {"text": "每天跑步5公里", "score": 0.50,
         "metadata": {"importance": 0.7, "time": "2026-06-15", "type": "habit", "expire_days": 180}},
        {"text": "最近压力好大", "score": 0.60,
         "metadata": {"importance": 0.25, "time": "2026-07-08", "type": "emotion", "expire_days": 14}},
    ]

    print("\n── 回忆型: '你知道我喜欢什么吗' ──")
    assert MemoryRanker.is_recall_query("你知道我喜欢什么吗"), "应识别为回忆型"
    r = MemoryRanker.rank("你知道我喜欢什么吗", recall_memories)
    print(f"  结果({len(r)}): {r}")
    assert len(r) <= 5, "回忆型最多5条"
    assert "喜欢科幻片" in r, "preference 应被召回"
    if r:
        assert r[0] in ("喜欢科幻片", "是计算机专业大三"), "preference/identity 应优先"

    print("\n── 回忆型: '记得吗' 绕过短句过滤 ──")
    assert MemoryRanker.is_recall_query("记得吗"), "应识别为回忆型"
    r = MemoryRanker.rank("记得吗", recall_memories)
    print(f"  结果({len(r)}): {r}")
    assert r, "回忆型短句不应返回空"

    print("\n── 回忆型: '我之前说过什么' ──")
    assert MemoryRanker.is_recall_query("我之前说过什么"), "应识别为回忆型"
    r = MemoryRanker.rank("我之前说过什么", recall_memories)
    print(f"  结果({len(r)}): {r}")
    assert len(r) <= 5

    print("\n── 回忆型: preference 优先于高相似 event ──")
    r = MemoryRanker.rank("还记得吗", recall_memories)
    pref_idx = r.index("喜欢科幻片") if "喜欢科幻片" in r else -1
    event_idx = r.index("昨天吃了火锅") if "昨天吃了火锅" in r else 99
    print(f"  preference 排名={pref_idx}, event 排名={event_idx}")
    if "喜欢科幻片" in r and "昨天吃了火锅" in r:
        assert pref_idx < event_idx, "preference 应排在 event 前面"

    print("\n── 非回忆型模式不应误触发 ──")
    assert not MemoryRanker.is_recall_query("周末干嘛"), "普通查询不是回忆型"
    assert not MemoryRanker.is_recall_query("今天天气不错"), "普通查询不是回忆型"

    print("\n✅ 测试完成")
