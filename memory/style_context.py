"""
对话风格上下文构建器
从 JSONL 聊天历史 + 好友画像，提取：
  - 对方是谁、有什么特点
  - TA 的说话风格样本
  - 你（用户）的说话风格样本

供 PromptBuilder 生成更精准的拟人回复。
"""

import sys
import re
from collections import Counter

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.profile import FriendProfile
from memory.profile_builder import ProfileBuilder


class StyleContextBuilder:
    """从历史和画像构建双方风格上下文"""

    PARTICLES = ("哈", "啊", "呢", "吧", "嘛", "哦", "嗯", "呗", "咯", "呀", "哇")
    MIN_MSG_LEN = 2
    MAX_SAMPLE_LEN = 100

    def build(
        self,
        friend_id: str,
        friend_name: str,
        history: list[dict],
        friend_meta: dict | None = None,
        user_style: dict | None = None,
        memories: list[str] | None = None,
    ) -> dict:
        """
        Returns:
            {
              friend_name, friend_card,
              user_voice: {samples, stats, hint},
              friend_voice: {samples, stats, hint},
            }
        """
        mine, theirs = self._split_messages(history or [])
        profile = self._load_profile(friend_id, friend_name)

        user_voice = self._analyze_side(mine, user_style or {}, role="me")
        friend_voice = self._analyze_side(theirs, {}, role="friend")

        friend_card = self._build_friend_card(
            friend_name, profile, friend_meta, friend_voice, memories
        )

        return {
            "friend_name": friend_name,
            "friend_card": friend_card,
            "user_voice": user_voice,
            "friend_voice": friend_voice,
        }

    # ========== 好友身份卡 ==========

    def _build_friend_card(
        self,
        name: str,
        profile: FriendProfile | None,
        meta: dict | None,
        friend_voice: dict,
        memories: list[str] | None,
    ) -> str:
        lines = ["【此刻聊天对象 — 先认清 TA 再回】", f"姓名: {name or '未知'}"]

        relation = ""
        if meta and meta.get("relation"):
            relation = meta["relation"]
        elif profile and profile.relationship:
            relation = profile.relationship
        lines.append(f"关系: {relation or '（未标注，按普通朋友处理）'}")

        if profile:
            if profile.summary:
                lines.append(f"整体印象: {profile.summary}")
            elif profile.recent_summary:
                lines.append(f"最近动态: {profile.recent_summary}")
            if profile.background:
                lines.append(f"背景: {profile.background}")
            if profile.current_status:
                lines.append(f"当前状态: {profile.current_status}")
            if profile.relationship_notes:
                lines.append(f"关系细节: {profile.relationship_notes}")
            if profile.key_facts:
                lines.append(f"关键信息: {'；'.join(profile.key_facts)}")
            if profile.interests:
                lines.append(f"爱好/兴趣: {'、'.join(profile.interests)}")
            if profile.personality:
                lines.append(f"性格: {'、'.join(profile.personality)}")
            if profile.communication_style:
                lines.append(f"已知聊天风格: {'、'.join(profile.communication_style)}")
            if profile.common_topics:
                lines.append(f"常聊话题: {'、'.join(profile.common_topics)}")
            if profile.dislikes:
                lines.append(f"雷点: {'、'.join(profile.dislikes)}")
            if profile.how_to_talk:
                lines.append(f"聊天注意: {'；'.join(profile.how_to_talk)}")

        if meta and meta.get("tags"):
            lines.append(f"标签: {'、'.join(meta['tags'])}")

        fv_hint = friend_voice.get("hint", "")
        if fv_hint:
            lines.append(f"从聊天记录看 TA 说话: {fv_hint}")

        if memories:
            lines.append("关于 TA 你记得:")
            for m in memories[:4]:
                lines.append(f"  · {m}")

        lines.append(
            f"⚠️ 你现在是在和【{name}】私聊，不要当成别人，"
            f"回复要贴合 TA 的性格和说话方式。"
        )
        return "\n".join(lines)

    # ========== 风格分析 ==========

    def _analyze_side(
        self,
        messages: list[dict],
        base_style: dict,
        role: str,
    ) -> dict:
        texts = [
            str(m.get("text") or m.get("content", "")).strip()
            for m in messages
            if str(m.get("text") or m.get("content", "")).strip()
        ]
        texts = [t for t in texts if len(t) >= self.MIN_MSG_LEN]

        stats = self._compute_stats(texts)
        samples = self._pick_samples(texts, max_n=5)

        hint_parts = []
        if stats.get("length_hint"):
            hint_parts.append(stats["length_hint"])
        if stats.get("particles"):
            hint_parts.append(f"爱用「{'」「'.join(stats['particles'])}」")
        if stats.get("uses_emoji"):
            hint_parts.append("会用表情")
        elif role == "me" and base_style.get("emoji_frequency") == "low":
            hint_parts.append("少用表情")

        if base_style.get("tone") == "casual":
            hint_parts.append("口语随意")
        if base_style.get("common_words"):
            hint_parts.append(f"口头禅: {'、'.join(base_style['common_words'][:4])}")
        if base_style.get("avoid_words"):
            hint_parts.append(f"避免: {'、'.join(base_style['avoid_words'][:4])}")

        return {
            "samples": samples,
            "stats": stats,
            "hint": "，".join(hint_parts) if hint_parts else "",
        }

    def _compute_stats(self, texts: list[str]) -> dict:
        if not texts:
            return {}
        lengths = [len(t) for t in texts]
        avg = sum(lengths) / len(lengths)

        particle_counts = Counter()
        for t in texts:
            for p in self.PARTICLES:
                if p in t:
                    particle_counts[p] += t.count(p)

        top_particles = [p for p, _ in particle_counts.most_common(3)]
        emoji_re = re.compile(
            r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]"
        )
        emoji_msgs = sum(1 for t in texts if emoji_re.search(t))

        return {
            "avg_length": round(avg),
            "length_hint": (
                "短句为主" if avg < 12 else "中等长度" if avg < 28 else "有时发长消息"
            ),
            "particles": top_particles,
            "uses_emoji": emoji_msgs > max(1, len(texts) * 0.08),
            "msg_count": len(texts),
        }

    def _pick_samples(self, texts: list[str], max_n: int = 5) -> list[str]:
        """选取有代表性的消息样本（优先中等长度、非纯语气词）"""
        skip_exact = {"嗯", "好", "好的", "哈哈", "ok", "OK", "收到", "在", "在的"}

        scored = []
        for t in texts:
            if t in skip_exact or len(t) < 3:
                continue
            # 中等长度消息更有代表性
            score = 10 - abs(len(t) - 15) * 0.3
            if len(t) > self.MAX_SAMPLE_LEN:
                t = t[: self.MAX_SAMPLE_LEN] + "…"
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

        # 不足则从末尾补
        if len(samples) < max_n:
            for t in reversed(texts):
                if t not in seen and t not in skip_exact:
                    seen.add(t)
                    samples.insert(0, t[: self.MAX_SAMPLE_LEN])
                if len(samples) >= max_n:
                    break

        return samples[-max_n:]

    @staticmethod
    def _split_messages(history: list[dict]) -> tuple[list, list]:
        mine, theirs = [], []
        for m in history:
            sender = m.get("sender", "")
            if sender in ("me", "我"):
                mine.append(m)
            else:
                theirs.append(m)
        return mine, theirs

    @staticmethod
    def _load_profile(friend_id: str, friend_name: str) -> FriendProfile | None:
        if not friend_id:
            return None
        try:
            return ProfileBuilder(friend_id, friend_name).profile
        except Exception:
            return None


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from memory.style_context import StyleContextBuilder
    builder = StyleContextBuilder()
    history = [
        {"sender": "friend", "text": "卧槽今天球赛太刺激了"},
        {"sender": "me", "text": "是吧 我也看了"},
        {"sender": "friend", "text": "下次一起去看呗"},
        {"sender": "me", "text": "行啊 到时候喊我"},
        {"sender": "me", "text": "可以"},
    ]
    ctx = builder.build("yangchunhui", "杨春辉", history, user_style={
        "tone": "casual", "common_words": ["可以", "行"], "emoji_frequency": "low"
    })
    print(ctx["friend_card"])
    print("\n我的口吻:", ctx["user_voice"])
    print("\nTA的口吻:", ctx["friend_voice"])
