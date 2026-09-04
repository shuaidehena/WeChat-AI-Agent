"""
个人语言风格分析器

两层分析:
  1. 程序统计（长度、高频词、语气词、标点、emoji）
  2. LLM 归纳（基于统计结果，禁止凭空生成）

支持:
  - analyze(messages)         全量分析
  - analyze_from_history()    从所有 JSONL 历史采集
  - update_style(message)     增量更新
"""

import sys
import os
import re
import json
from collections import Counter

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from personal.style_schema import PersonalStyle
from personal.style_storage import StyleStorage
from personal.example_selector import ExampleSelector


# 过滤噪音消息
NOISE_EXACT = {
    "哈哈", "呵呵", "嗯", "嗯嗯", "哦", "好的", "好", "ok", "OK",
    "收到", "👍", "在", "在的", "？", "?", "。", "…", "...",
}
MIN_TEXT_LEN = 2
PARTICLES = ("哈", "啊", "呢", "吧", "嘛", "哦", "嗯", "呗", "咯", "呀", "哇", "勒")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")


class StyleAnalyzer:
    """个人风格分析器"""

    LLM_PROMPT = """你是个人聊天风格分析器。根据以下【程序统计】和【用户真实消息】，生成一份详细的「个人说话画像」。

【程序统计】
{stats_json}

【用户真实消息样本（共{sample_count}条，仅 me 发送）】
{samples}

【对话上下文片段（friend 问 → me 答）】
{context_pairs}

要求:
1. 只能基于上面提供的内容归纳，禁止编造样本里没有的特征
2. 越具体越好，避免「友好」「正常」等空泛词
3. 从消息样本中提炼真实口癖、句式和雷点
4. 只输出 JSON，不要解释

输出格式:
{{
  "summary": "对用户说话风格的整体概括（80字内，像朋友描述TA怎么聊天）",
  "tone": ["语气特点，最多6项"],
  "personality": ["从聊天中体现的性格，最多6项"],
  "communication_style": ["说话方式，最多8项，如：短句/爱反问/口语化/带调侃"],
  "patterns": ["回复模式，最多6项"],
  "avoid_words": ["用户明显少用或应避免的词/腔调，最多8项，如：当然/确实/您好"],
  "how_to_reply": ["代用户回微信时要注意，最多6项，如：别太长/别用哈哈/别像客服"],
  "topics_often_mentioned": ["用户常聊的话题，最多6项"],
  "self_description_hints": "从聊天推断的身份/工作/生活状态（50字内，无则空）",
  "voice_samples": ["从样本中摘选8条最有代表性的原话，必须逐字来自样本"]
}}"""

    def __init__(self, storage: StyleStorage = None, use_llm: bool = True):
        self._storage = storage or StyleStorage()
        self._selector = ExampleSelector()
        self._llm = None  # 延迟加载
        self._use_llm = use_llm

    # ========== 全量分析 ==========

    def analyze(self, messages: list[dict], history_for_examples: list[dict] = None) -> PersonalStyle:
        """
        分析用户消息列表，生成 PersonalStyle

        Args:
            messages: [{"sender":"me","text":"..."}, ...] 或纯 me 消息
            history_for_examples: 完整对话历史（含 friend），用于提取问答样例
        """
        texts = self._filter_my_messages(messages)
        if not texts:
            return PersonalStyle()

        stats = self._compute_stats(texts)
        style = PersonalStyle(
            avg_length=stats["avg_length"],
            sentence_style=stats["sentence_style"],
            common_words=stats["common_words"],
            emoji_usage=stats["emoji_usage"],
            punctuation_style=stats["punctuation_style"],
            particle_words=stats["particle_words"],
            message_count=len(texts),
        )

        # LLM 第二层（基于统计 + 更多样本）
        llm_result = self._llm_analyze(stats, texts, history_for_examples or messages)
        style.summary = llm_result.get("summary", "")
        style.tone = llm_result.get("tone", [])
        style.personality = llm_result.get("personality", [])
        style.communication_style = llm_result.get("communication_style", [])
        style.reply_patterns = llm_result.get("patterns", llm_result.get("reply_patterns", []))
        style.avoid_words = llm_result.get("avoid_words", [])
        style.how_to_reply = llm_result.get("how_to_reply", [])
        style.topics_often_mentioned = llm_result.get("topics_often_mentioned", [])
        style.self_description_hints = llm_result.get("self_description_hints", "")

        # 问答样例 + 真实发言样例
        hist = history_for_examples or messages
        style.examples = self._selector.select(hist, avg_length=style.avg_length, max_n=8)
        style.voice_samples = self._pick_voice_samples(
            texts,
            llm_result.get("voice_samples", []),
            max_n=8,
        )

        return style

    def analyze_from_history(self, history_dir: str = None, force: bool = False) -> PersonalStyle:
        """从 storage/history/*.jsonl 采集全部 me 消息并分析"""
        return self.sync_from_storage(history_dir=history_dir, force=force)

    def sync_from_storage(self, history_dir: str = None, force: bool = False) -> PersonalStyle:
        """
        从 storage 聊天记录同步个人风格

        扫描 storage/history/ 下每个好友的 jsonl，
        提取 sender=me 的消息 → 去重 → 分析 → 保存
        """
        from personal.history_reader import HistoryReader

        reader = HistoryReader(history_dir)
        collected = reader.collect()

        my_msgs = collected["my_messages"]
        if not my_msgs:
            print("⚠️ storage/history 中未找到 me 消息")
            return self._storage.load()

        current = self._storage.load()
        if not force and collected["unique_count"] <= current.message_count:
            print(
                f"  🎭 个人风格已是最新 "
                f"({current.message_count}条, 来源 {len(current.sources)} 个好友)"
            )
            return current

        style = self.analyze(
            my_msgs,
            history_for_examples=collected["all_history"],
        )
        style.sources = collected["sources"]
        style.raw_count = collected["raw_count"]
        style.files_read = collected["files_read"]
        style.data_source = "storage/history"

        self._storage.save(style)

        top_sources = sorted(collected["sources"].items(), key=lambda x: -x[1])[:5]
        src_str = ", ".join(f"{k}({v})" for k, v in top_sources)
        print(
            f"✅ 个人风格已从 storage 分析: "
            f"{collected['unique_count']}条(去重前{collected['raw_count']}) "
            f"来自{collected['files_read']}个好友 [{src_str}]"
        )
        return style

    def bootstrap_if_needed(self, min_messages: int = 5) -> PersonalStyle:
        """启动时同步：storage 有数据则分析，否则加载已有"""
        collected = __import__(
            "personal.history_reader", fromlist=["HistoryReader"]
        ).HistoryReader().collect()

        if collected["unique_count"] >= min_messages:
            return self.sync_from_storage(force=False)

        style = self._storage.load()
        if style.message_count >= min_messages:
            return style

        if collected["unique_count"] > 0:
            return self.sync_from_storage(force=True)

        return style

    def update_style(self, message: dict) -> PersonalStyle:
        """
        实时增量更新（sender=me 的新消息）

        Args:
            message: {"sender":"me", "text":"..."}
        """
        sender = message.get("sender", "")
        if sender not in ("me", "我"):
            return self._storage.load()

        text = str(message.get("text") or message.get("content", "")).strip()
        if not self._is_valid_message(text):
            return self._storage.load()

        style = self._storage.load()

        # 增量更新平均长度
        n = style.message_count
        style.avg_length = (style.avg_length * n + len(text)) / (n + 1)
        style.message_count = n + 1

        # 更新 sentence_style
        style.sentence_style = self._length_to_style(style.avg_length)

        # 增量更新 common_words（简单分词 + 2字词）
        words = self._extract_words(text)
        word_counter = Counter(style.common_words)
        for w in words:
            word_counter[w] = word_counter.get(w, 0) + 1
        style.common_words = [w for w, _ in word_counter.most_common(8)]

        # emoji 增量
        if EMOJI_RE.search(text):
            style.emoji_usage = (
                style.emoji_usage * n + 1.0
            ) / style.message_count

        # 每积累 10 条重新 LLM 分析 + 样例（避免频繁调 API）
        if style.message_count % 10 == 0:
            self._refresh_llm_and_examples(style)

        self._storage.save(style)
        return style

    # ========== 统计层 ==========

    def _compute_stats(self, texts: list[str]) -> dict:
        lengths = [len(t) for t in texts]
        avg = sum(lengths) / len(lengths)

        # 高频词
        word_counter = Counter()
        for t in texts:
            for w in self._extract_words(t):
                word_counter[w] += 1

        # 语气词
        particle_counter = Counter()
        for t in texts:
            for p in PARTICLES:
                if p in t:
                    particle_counter[p] += t.count(p)

        # 标点风格
        period_ratio = sum(t.count("。") + t.count(".") for t in texts) / len(texts)
        ellipsis_ratio = sum(t.count("…") + t.count("...") for t in texts) / len(texts)
        question_ratio = sum(t.count("？") + t.count("?") for t in texts) / len(texts)

        if ellipsis_ratio > 0.3:
            punct_style = "爱用省略号，句子常不完整"
        elif question_ratio > 0.4:
            punct_style = "爱反问"
        elif period_ratio < 0.2:
            punct_style = "很少用句号，口语断句"
        else:
            punct_style = "正常标点"

        emoji_msgs = sum(1 for t in texts if EMOJI_RE.search(t))

        return {
            "avg_length": round(avg, 1),
            "sentence_style": self._length_to_style(avg),
            "common_words": [w for w, _ in word_counter.most_common(8)],
            "particle_words": [p for p, _ in particle_counter.most_common(5)],
            "emoji_usage": round(emoji_msgs / len(texts), 3),
            "punctuation_style": punct_style,
            "message_count": len(texts),
        }

    def _llm_analyze(
        self,
        stats: dict,
        sample_texts: list[str],
        history: list[dict] | None = None,
    ) -> dict:
        """第二层 LLM 分析（必须基于统计和真实样本）"""
        if not self._use_llm:
            return self._fallback_profile(stats, sample_texts)
        try:
            llm = self._get_llm()
            if not llm.config.is_configured("profile"):
                return self._fallback_profile(stats, sample_texts)

            samples = "\n".join(f"- {t}" for t in sample_texts[:30])
            context_pairs = self._format_context_pairs(history or [], limit=12)
            prompt = self.LLM_PROMPT.format(
                stats_json=json.dumps(stats, ensure_ascii=False, indent=2),
                sample_count=len(sample_texts),
                samples=samples,
                context_pairs=context_pairs or "（无）",
            )
            response = llm.chat(prompt, task="profile")
            data = self._safe_json(response)
            if data:
                return {
                    "summary": str(data.get("summary", ""))[:120],
                    "tone": (data.get("tone") or [])[:6],
                    "personality": (data.get("personality") or [])[:6],
                    "communication_style": (data.get("communication_style") or [])[:8],
                    "patterns": (data.get("patterns") or data.get("reply_patterns") or [])[:6],
                    "avoid_words": (data.get("avoid_words") or [])[:8],
                    "how_to_reply": (data.get("how_to_reply") or [])[:6],
                    "topics_often_mentioned": (data.get("topics_often_mentioned") or [])[:6],
                    "self_description_hints": str(data.get("self_description_hints", ""))[:80],
                    "voice_samples": (data.get("voice_samples") or [])[:8],
                }
        except Exception as e:
            print(f"  ⚠️ 风格 LLM 分析跳过: {e}")

        return self._fallback_profile(stats, sample_texts)

    @staticmethod
    def _format_context_pairs(history: list[dict], limit: int = 12) -> str:
        pairs = []
        for i, msg in enumerate(history):
            if msg.get("sender") not in ("friend",):
                continue
            q = str(msg.get("text") or msg.get("content", "")).strip()
            if not q or len(q) < 2:
                continue
            for j in range(i + 1, min(i + 4, len(history))):
                nxt = history[j]
                if nxt.get("sender") in ("me", "我"):
                    a = str(nxt.get("text") or nxt.get("content", "")).strip()
                    if a and len(a) >= 2:
                        pairs.append(f"问: {q[:50]}\n答: {a[:60]}")
                    break
            if len(pairs) >= limit:
                break
        return "\n".join(pairs)

    @staticmethod
    def _pick_voice_samples(
        texts: list[str],
        llm_samples: list[str],
        max_n: int = 8,
    ) -> list[str]:
        """从真实消息中选取代表性发言（LLM 摘选 + 程序兜底）"""
        text_set = set(texts)
        picked: list[str] = []
        seen: set[str] = set()

        for s in llm_samples:
            s = str(s).strip()
            if s in text_set and s not in seen:
                seen.add(s)
                picked.append(s[:80])
            if len(picked) >= max_n:
                return picked

        # 程序兜底：按长度/多样性选取
        candidates = sorted(set(texts), key=len)
        buckets = [
            candidates[: max(1, len(candidates) // 4)],
            candidates[len(candidates) // 3: len(candidates) // 3 + 3] if candidates else [],
            candidates[-max(1, len(candidates) // 4):],
        ]
        for bucket in buckets:
            for s in bucket:
                if s not in seen and len(s) >= 3:
                    seen.add(s)
                    picked.append(s[:80])
                if len(picked) >= max_n:
                    return picked

        for s in texts:
            if s not in seen:
                seen.add(s)
                picked.append(s[:80])
            if len(picked) >= max_n:
                break
        return picked

    @staticmethod
    def _fallback_profile(stats: dict, sample_texts: list[str]) -> dict:
        """无 LLM 时用统计结果推断"""
        tone = []
        patterns = []
        comm = []
        if stats["sentence_style"] == "short":
            tone.append("随意")
            patterns.append("短回复")
            comm.append("短句为主")
        elif stats["sentence_style"] == "long":
            patterns.append("有时发长消息")
        if stats.get("particle_words"):
            patterns.append(f"爱用「{'」「'.join(stats['particle_words'][:2])}」")
            comm.append("口语语气词多")
        if stats.get("emoji_usage", 0) > 0.1:
            patterns.append("会用表情")
        if not tone:
            tone.append("口语")

        summary = f"平均{stats.get('avg_length', 0):.0f}字左右，{'、'.join(tone)}的聊天风格"
        return {
            "summary": summary,
            "tone": tone,
            "personality": [],
            "communication_style": comm,
            "patterns": patterns,
            "avoid_words": ["当然", "确实", "您好", "很高兴"],
            "how_to_reply": ["别太长", "别像客服"],
            "topics_often_mentioned": [],
            "self_description_hints": "",
            "voice_samples": sample_texts[:8],
        }

    def _refresh_llm_and_examples(self, style: PersonalStyle):
        """增量时周期性刷新 LLM 归纳和样例"""
        from personal.history_reader import HistoryReader
        collected = HistoryReader().collect()
        texts = [m["text"] for m in collected["my_messages"]]
        if not texts:
            return
        stats = self._compute_stats(texts)
        llm_result = self._llm_analyze(stats, texts, collected["all_history"])
        style.summary = llm_result.get("summary", style.summary)
        style.tone = llm_result.get("tone", style.tone)
        style.personality = llm_result.get("personality", style.personality)
        style.communication_style = llm_result.get("communication_style", style.communication_style)
        style.reply_patterns = llm_result.get("patterns", style.reply_patterns)
        style.avoid_words = llm_result.get("avoid_words", style.avoid_words)
        style.how_to_reply = llm_result.get("how_to_reply", style.how_to_reply)
        style.topics_often_mentioned = llm_result.get("topics_often_mentioned", style.topics_often_mentioned)
        style.self_description_hints = llm_result.get("self_description_hints", style.self_description_hints)
        style.examples = self._selector.select(
            collected["all_history"], avg_length=style.avg_length, max_n=8
        )
        style.voice_samples = self._pick_voice_samples(
            texts, llm_result.get("voice_samples", []), max_n=8
        )
        style.sources = collected["sources"]
        style.message_count = len(texts)

    # ========== 历史采集（兼容旧接口）==========

    def _collect_all_history(self, history_dir: str = None) -> tuple[list[dict], list[dict]]:
        from personal.history_reader import HistoryReader
        collected = HistoryReader(history_dir).collect()
        return collected["my_messages"], collected["all_history"]

    # ========== 工具 ==========

    def _filter_my_messages(self, messages: list[dict]) -> list[str]:
        texts = []
        for m in messages:
            if m.get("sender") not in ("me", "我"):
                continue
            text = str(m.get("text") or m.get("content", "")).strip()
            if self._is_valid_message(text):
                texts.append(text)
        return texts

    @staticmethod
    def _is_valid_message(text: str) -> bool:
        if not text or len(text) < MIN_TEXT_LEN:
            return False
        if text in NOISE_EXACT:
            return False
        if text.strip() in NOISE_EXACT:
            return False
        return True

    @staticmethod
    def _length_to_style(avg: float) -> str:
        if avg < 12:
            return "short"
        if avg < 28:
            return "medium"
        return "long"

    @staticmethod
    def _extract_words(text: str) -> list[str]:
        """提取 2~4 字的常见词片段"""
        words = []
        # 2-3 字中文片段
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                seg = text[i:i + n]
                if all("\u4e00" <= c <= "\u9fff" for c in seg):
                    words.append(seg)
        # 整句中的明显词
        for w in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
            words.append(w)
        return words

    def _get_llm(self):
        if self._llm is None:
            from llm.client import LLMClient
            self._llm = LLMClient()
        return self._llm

    @staticmethod
    def _safe_json(text: str) -> dict | None:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None
