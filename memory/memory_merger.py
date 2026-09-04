"""
记忆合并与冲突处理
处理相似记忆的更新、强化与矛盾 supersede

规则:
  similarity >= 0.90  → 跳过（重复）
  similarity 0.75~0.90 + 矛盾信号 → supersede 旧记忆
  similarity 0.75~0.90            → 强化（提升重要度 / 合并文本）
  similarity < 0.75               → 新增
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryMerger:
    """相似记忆合并决策（纯规则，无 LLM）"""

    DUPLICATE_THRESHOLD = 0.90
    SIMILAR_THRESHOLD = 0.75
    IMPORTANCE_BOOST = 0.08

    # 矛盾/反转信号词
    CONTRADICTION_KEYWORDS = [
        "不再", "不喜欢了", "不想", "不爱了", "不去了", "讨厌了", "换成", "改吃",
    ]

    def find_action(
        self,
        new_content: str,
        new_importance: float,
        candidates: list[dict],
    ) -> dict:
        """
        根据相似候选记忆决定操作

        Returns:
            {"action": "skip"|"supersede"|"reinforce"|"add", "match": dict|None, ...}
        """
        if not candidates:
            return {"action": "add"}

        best = candidates[0]
        score = best.get("score", 0)

        if score >= self.DUPLICATE_THRESHOLD:
            return {"action": "skip", "score": score, "match": best}

        if score >= self.SIMILAR_THRESHOLD:
            old_text = best.get("text", "")
            if self._is_contradiction(new_content, old_text):
                return {"action": "supersede", "score": score, "match": best}

            merged_text = self._merge_text(old_text, new_content)
            new_imp = self._boost_importance(best, new_importance)
            return {
                "action": "reinforce",
                "score": score,
                "match": best,
                "merged_text": merged_text,
                "new_importance": new_imp,
            }

        return {"action": "add"}

    # ========== 内部 ==========

    def _is_contradiction(self, new_text: str, old_text: str) -> bool:
        """检测新记忆是否 contradict 旧记忆"""
        if any(kw in new_text for kw in self.CONTRADICTION_KEYWORDS):
            return True
        # "已经" + 否定语境，如 "已经不喜欢了"
        if "已经" in new_text and any(kw in new_text for kw in ["不", "没", "别"]):
            return True
        return False

    def _merge_text(self, old: str, new: str) -> str:
        """合并相似记忆文本，保留更完整表述"""
        if not old:
            return new
        if not new:
            return old
        if new in old:
            return old
        if old in new:
            return new
        return new if len(new) >= len(old) else old

    def _boost_importance(self, match: dict, new_importance: float) -> float:
        """强化时提升重要度"""
        old_imp = match.get("metadata", {}).get("importance", 0.5)
        try:
            old_imp = float(old_imp)
        except (TypeError, ValueError):
            old_imp = 0.5
        boosted = old_imp + self.IMPORTANCE_BOOST
        return min(max(boosted, new_importance), 1.0)


# ========== 测试 ==========

if __name__ == "__main__":
    merger = MemoryMerger()

    cases = [
        ("add", [], "全新记忆"),
        ("skip", [{"text": "喜欢火锅", "score": 0.95}], "喜欢火锅"),
        ("reinforce", [{"text": "喜欢打篮球", "score": 0.82, "metadata": {"importance": 0.5}}], "经常周末打篮球"),
        ("supersede", [{"text": "喜欢吃火锅", "score": 0.85}], "不再喜欢吃火锅了"),
    ]

    print("MemoryMerger 测试")
    for expected, cands, content in cases:
        r = merger.find_action(content, 0.6, cands)
        ok = r["action"] == expected
        print(f"  {'✅' if ok else '❌'} {expected}: {content[:20]} → {r['action']}")
        assert ok, f"expected {expected}, got {r['action']}"

    print("  全部 PASS")
