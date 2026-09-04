"""
聊天样例选择器
从对话历史中提取 {question, answer} 代表性样例
"""

import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ExampleSelector:
    """选择代表性问答对"""

    SKIP_ANSWERS = {"哈哈", "嗯", "好的", "好", "ok", "OK", "收到", "👍", "在", "在的", "？"}

    # 无效问题（OCR 噪音）
    DATE_RE = re.compile(r"\d{4}年\d{1,2}月")
    TIME_RE = re.compile(r"^\d{1,2}:\d{2}")
    PURE_ASCII_RE = re.compile(r"^[a-zA-Z0-9\s\(\)\.,!?]+$")

    def select(
        self,
        history: list[dict],
        avg_length: float = 10.0,
        max_n: int = 5,
    ) -> list[dict]:
        """
        从历史中选取 question→answer 样例

        规则:
          1. friend 发问 → me 回答
          2. answer 有个人表达，非纯语气词
          3. answer 长度接近 avg_length
          4. 尽量覆盖不同场景
        """
        pairs = self._extract_pairs(history)
        if not pairs:
            return []

        scored = []
        for q, a in pairs:
            if len(a) < 3 or a in self.SKIP_ANSWERS:
                continue
            if len(a) > 80:
                continue
            length_score = 10 - abs(len(a) - avg_length) * 0.4
            express_score = 2 if any(c in a for c in "？?！!…") else 0
            express_score += 1 if len(a.split()) > 1 or len(a) > 6 else 0
            scored.append((length_score + express_score, q, a))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_answers = set()
        for _, q, a in scored:
            if a in seen_answers:
                continue
            seen_answers.add(a)
            results.append({"question": q[:60], "answer": a[:80]})
            if len(results) >= max_n:
                break

        return results

    def _is_valid_question(self, text: str) -> bool:
        if not text or len(text) < 2:
            return False
        if self.DATE_RE.search(text):
            return False
        if self.TIME_RE.match(text):
            return False
        if re.match(r"^[\d\(\)\[\]\s]+$", text):
            return False
        # 必须含中文，或长度足够的有意义英文
        has_cn = any("\u4e00" <= c <= "\u9fff" for c in text)
        if not has_cn and (len(text) < 8 or self.PURE_ASCII_RE.match(text)):
            return False
        return True

    @staticmethod
    def _extract_pairs(history: list[dict]) -> list[tuple[str, str]]:
        """遍历历史，friend 消息后紧跟 me 消息 → 问答对"""
        selector = ExampleSelector()
        pairs = []
        for i, msg in enumerate(history):
            sender = msg.get("sender", "")
            if sender not in ("friend",):
                continue
            question = str(msg.get("text") or msg.get("content", "")).strip()
            if not question or not selector._is_valid_question(question):
                continue
            # 找下一条 me 回复
            for j in range(i + 1, min(i + 4, len(history))):
                nxt = history[j]
                if nxt.get("sender") in ("me", "我"):
                    answer = str(nxt.get("text") or nxt.get("content", "")).strip()
                    if answer:
                        pairs.append((question, answer))
                    break
        return pairs
