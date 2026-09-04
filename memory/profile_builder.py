"""
好友画像生成器

数据来源（优先级）:
  1. storage/history/{friend_id}.jsonl  — 好友聊天记录（friend 消息）
  2. ChromaDB 向量记忆                    — 长期记忆
  3. LLM 归纳                             — 生成画像字段

触发更新:
  - 画像为空 且 (向量记忆>=3 或 历史friend消息>=10)
  - 向量记忆新增>=2 且 距上次>12h
  - 历史 friend 消息新增>=10 条
"""

import sys
import os
import json
import re
from collections import Counter
from datetime import datetime

from memory.profile import FriendProfile
from memory.vector_memory import VectorMemory
from memory.friend_history_reader import FriendHistoryReader
from llm.client import LLMClient
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PARTICLES = ("哈", "啊", "呢", "吧", "嘛", "哦", "嗯", "呗", "咯", "呀", "哇")


class ProfileBuilder:
    """好友画像生成器"""

    MIN_MEMORIES = 5
    MIN_NEW_MEMORIES = 2
    MIN_MEMORIES_EMPTY_PROFILE = 3
    MIN_HISTORY_EMPTY = 10          # 无画像时，历史 friend 消息阈值
    MIN_NEW_HISTORY = 10            # 历史新增多少条触发更新
    MIN_UPDATE_HOURS = 12

    MAX_LIST_ITEMS = 8

    UPDATE_PROMPT = """你是好友画像分析器。请根据以下【真实聊天记录和记忆】，生成一份详细的好友画像。

【已有画像】
{profile}

【程序统计 — TA 的说话习惯】
{friend_stats}

【TA 的真实消息样本（共{sample_count}条）】
{friend_samples}

【长期记忆】
{memories}

【近期对话记录】
{recent_chat}

输出 JSON（只输出 JSON，不要解释）:
{{
  "relationship": "和用户的关系（如大学室友/同事/发小，尽量具体）",
  "relationship_notes": "认识经过或关系细节（30字内，无则空）",
  "background": "背景：工作/学校/城市等（30字内，无则空）",
  "current_status": "TA 当前在忙什么（30字内）",
  "recent_summary": "最近动态概括（50字内）",
  "summary": "对 TA 的整体印象概括（80字内，像朋友描述朋友）",
  "interests": ["兴趣爱好，最多8项，要具体"],
  "personality": ["性格特点，最多8项"],
  "communication_style": ["说话风格，最多8项，如：爱反问/嘴毒/短句/爱吐槽"],
  "common_topics": ["常聊话题，最多8项"],
  "key_facts": ["关键事实：名字/工作/学校/重要经历，最多8项"],
  "dislikes": ["TA 讨厌或雷点，最多5项，无则空数组"],
  "how_to_talk": ["和 TA 聊天时要注意，最多5项，如：别说哈哈/别太长"]
}}

要求:
1. 只能基于提供的内容归纳，禁止编造聊天记录里没有的信息
2. 保留已有画像中的正确信息，补充新发现的细节
3. 越具体越好，避免「日常」「朋友」等空泛词
4. 从 TA 的消息样本中提炼真实说话风格"""

    def __init__(self, friend_id: str, friend_name: str = ""):
        self.friend_id = friend_id
        self.friend_name = friend_name
        self._vm = VectorMemory(friend_id)
        self._llm = LLMClient()
        self._history_reader = FriendHistoryReader(friend_id)

        profile_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "profiles"
        )
        os.makedirs(profile_dir, exist_ok=True)
        self._profile_path = os.path.join(profile_dir, f"{friend_id}.json")
        self.profile = self._load()

    def _load(self) -> FriendProfile:
        if os.path.exists(self._profile_path):
            try:
                with open(self._profile_path, "r", encoding="utf-8") as f:
                    return FriendProfile.from_dict(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass
        return FriendProfile(friend_id=self.friend_id, name=self.friend_name)

    def _save(self):
        self.profile.updated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.profile.memory_count = self._vm.count()
        if self.friend_name and not self.profile.name:
            self.profile.name = self.friend_name
        write_json_atomic(self._profile_path, self.profile.to_dict())

    # ========== 从 storage 同步 ==========

    def sync_from_storage(self, force: bool = False) -> FriendProfile | None:
        """
        从 storage/history/{friend_id}.jsonl 读取聊天记录，更新画像

        提取 sender=friend 消息 → 统计 + 样例 → 结合向量记忆 → LLM 分析
        """
        collected = self._history_reader.collect()
        friend_count = collected["unique_friend_count"]

        if friend_count == 0 and self._vm.count() == 0:
            return None

        if not force and not self.should_update(history_count=friend_count):
            return None

        return self.update_profile(
            recent_chat=collected["all_history"],
            collected=collected,
        )

    def should_update(self, history_count: int = None) -> bool:
        vm_count = self._vm.count()
        if history_count is None:
            history_count = self._history_reader.collect()["unique_friend_count"]

        new_memories = vm_count - self.profile.memory_count
        new_history = history_count - self.profile.history_count

        # 画像为空 → 有足够数据就更新
        if self.profile.is_empty():
            if vm_count >= self.MIN_MEMORIES_EMPTY_PROFILE:
                return True
            if history_count >= self.MIN_HISTORY_EMPTY:
                return True
            return False

        # 历史新增足够
        if new_history >= self.MIN_NEW_HISTORY:
            return self._hours_since_update() >= 1  # 历史更新间隔放宽到1h

        # 向量记忆新增
        if vm_count >= self.MIN_MEMORIES and new_memories >= self.MIN_NEW_MEMORIES:
            return self._hours_since_update() >= self.MIN_UPDATE_HOURS

        return False

    def _hours_since_update(self) -> float:
        try:
            last = datetime.strptime(self.profile.updated_time[:19], "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - last).total_seconds() / 3600
        except ValueError:
            return 999.0

    def update_profile(
        self,
        recent_chat: list[dict] = None,
        collected: dict = None,
    ) -> FriendProfile | None:
        if collected is None:
            collected = self._history_reader.collect()
        if recent_chat is None:
            recent_chat = collected.get("all_history", [])

        friend_msgs = collected.get("friend_messages", [])
        friend_texts = [m["text"] for m in friend_msgs]

        # 向量记忆
        all_items = self._vm.list_all(limit=80)
        memory_texts = list(dict.fromkeys(
            m["text"] for m in all_items if m.get("text")
        ))

        if not friend_texts and not memory_texts:
            return None

        # 程序统计 TA 说话习惯
        stats = self._analyze_friend_stats(friend_texts)
        friend_samples = self._pick_friend_samples(friend_texts, stats.get("avg_length", 10), max_n=20)

        try:
            old_profile = json.dumps(self.profile.to_dict(), ensure_ascii=False, indent=2)
            # 对话取更多：优先最近，也抽样早期
            chat_lines = collected.get("all_history", recent_chat)
            recent_part = chat_lines[-60:]
            early_part = chat_lines[:30] if len(chat_lines) > 90 else []
            chat_for_prompt = early_part + recent_part

            prompt = self.UPDATE_PROMPT.format(
                profile=old_profile,
                friend_stats=json.dumps(stats, ensure_ascii=False, indent=2),
                sample_count=len(friend_samples),
                friend_samples="\n".join(f"- {t}" for t in friend_samples[:25]),
                memories="\n".join(f"- {t}" for t in memory_texts[-40:]) or "（暂无）",
                recent_chat=self._format_recent_chat(chat_for_prompt) or "（暂无）",
            )
            response = self._llm.chat(prompt, task="profile")
            data = self._safe_json(response)
            if not data:
                return None

            list_fields = [
                "interests", "personality", "communication_style",
                "common_topics", "key_facts", "dislikes", "how_to_talk",
            ]
            for field in list_fields:
                new_items = data.get(field, [])
                if isinstance(new_items, list) and new_items:
                    existing = getattr(self.profile, field, [])
                    merged = list(dict.fromkeys(
                        existing + [str(x).strip() for x in new_items if x]
                    ))[: self.MAX_LIST_ITEMS]
                    setattr(self.profile, field, merged)

            str_fields = {
                "relationship": 40,
                "relationship_notes": 80,
                "background": 80,
                "current_status": 60,
                "recent_summary": 80,
                "summary": 120,
            }
            for field, max_len in str_fields.items():
                val = data.get(field, "")
                if isinstance(val, str) and val.strip():
                    setattr(self.profile, field, val.strip()[:max_len])

            # 保存统计-derived 字段
            self.profile.voice_samples = friend_samples[:8]
            self.profile.history_count = collected.get("unique_friend_count", 0)
            self.profile.data_source = "storage/history"

            # 程序层补充 communication_style（若 LLM 未给出）
            if stats.get("length_hint") and not self.profile.communication_style:
                self.profile.communication_style = [stats["length_hint"]]
            if stats.get("particles") and len(self.profile.communication_style) < 3:
                hint = f"爱用「{'」「'.join(stats['particles'][:2])}」"
                if hint not in self.profile.communication_style:
                    self.profile.communication_style.append(hint)

            self._save()
            print(
                f"🖼 画像更新: {self.friend_name or self.friend_id} "
                f"(历史{self.profile.history_count}条, 记忆{self.profile.memory_count}条)"
            )
            return self.profile

        except Exception as e:
            print(f"⚠️ 画像更新失败: {e}")
            return None

    def get_profile_text(self) -> str:
        p = self.profile
        if p.is_empty() and not p.voice_samples:
            return ""

        lines = ["【对 TA 的详细了解 — 基于真实聊天记录】"]
        name = p.name or self.friend_name
        if name:
            lines.append(f"姓名: {name}")

        if p.summary:
            lines.append(f"整体印象: {p.summary}")
        elif p.recent_summary:
            lines.append(f"最近: {p.recent_summary}")

        if p.relationship:
            lines.append(f"关系: {p.relationship}")
        if p.relationship_notes:
            lines.append(f"关系细节: {p.relationship_notes}")
        if p.background:
            lines.append(f"背景: {p.background}")
        if p.current_status:
            lines.append(f"当前状态: {p.current_status}")
        if p.key_facts:
            lines.append(f"关键信息: {'；'.join(p.key_facts)}")
        if p.interests:
            lines.append(f"兴趣: {'、'.join(p.interests)}")
        if p.personality:
            lines.append(f"性格: {'、'.join(p.personality)}")
        if p.communication_style:
            lines.append(f"说话风格: {'、'.join(p.communication_style)}")
        if p.common_topics:
            lines.append(f"常聊话题: {'、'.join(p.common_topics)}")
        if p.dislikes:
            lines.append(f"雷点/讨厌: {'、'.join(p.dislikes)}")
        if p.how_to_talk:
            lines.append(f"聊天注意: {'；'.join(p.how_to_talk)}")
        if p.voice_samples:
            lines.append("TA 真实说话举例:")
            for s in p.voice_samples[:4]:
                lines.append(f"  · {s}")
        lines.append("（以上信息聊天时自然带过，不要清单式罗列。）")
        return "\n".join(lines)

    # ========== 好友消息统计 ==========

    @staticmethod
    def _analyze_friend_stats(texts: list[str]) -> dict:
        if not texts:
            return {"message_count": 0}
        lengths = [len(t) for t in texts]
        avg = sum(lengths) / len(lengths)

        word_counter = Counter()
        particle_counter = Counter()
        for t in texts:
            for w in re.findall(r"[\u4e00-\u9fff]{2,4}", t):
                word_counter[w] += 1
            for p in PARTICLES:
                if p in t:
                    particle_counter[p] += t.count(p)

        return {
            "message_count": len(texts),
            "avg_length": round(avg, 1),
            "length_hint": (
                "短句为主" if avg < 12 else "中等长度" if avg < 28 else "有时发长消息"
            ),
            "common_words": [w for w, _ in word_counter.most_common(6)],
            "particles": [p for p, _ in particle_counter.most_common(4)],
        }

    @staticmethod
    def _pick_friend_samples(texts: list[str], avg_length: float, max_n: int = 8) -> list[str]:
        skip = {"哈哈", "嗯", "好的", "好", "在吗", "收到"}
        scored = []
        for t in texts:
            if t in skip or len(t) < 4:
                continue
            score = 10 - abs(len(t) - avg_length) * 0.3
            scored.append((score, t))
        scored.sort(key=lambda x: x[0], reverse=True)

        seen = set()
        samples = []
        for _, t in scored:
            if t not in seen:
                seen.add(t)
                samples.append(t)
            if len(samples) >= max_n:
                break
        return samples

    @staticmethod
    def _format_recent_chat(recent_chat: list[dict] | None) -> str:
        if not recent_chat:
            return ""
        lines = []
        for m in recent_chat:
            sender = m.get("sender", "")
            text = str(m.get("text") or m.get("content", "")).strip()
            if not text:
                continue
            who = "TA" if sender not in ("me", "我") else "我"
            lines.append(f"{who}: {text}")
        return "\n".join(lines)

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
