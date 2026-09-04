"""
PersonalStyle 数据结构 — 个人语言风格 / 自我画像
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class PersonalStyle:
    """个人语言风格模型（从 storage/history 中 me 消息学习）"""

    # ---- 程序统计 ----
    avg_length: float = 0.0
    sentence_style: str = "short"       # short | medium | long
    common_words: list[str] = field(default_factory=list)
    emoji_usage: float = 0.0            # 0~1，含 emoji 的消息占比
    punctuation_style: str = ""
    particle_words: list[str] = field(default_factory=list)

    # ---- LLM 归纳（详细画像）----
    summary: str = ""                   # 整体说话风格概括（80字内）
    tone: list[str] = field(default_factory=list)
    personality: list[str] = field(default_factory=list)
    communication_style: list[str] = field(default_factory=list)
    reply_patterns: list[str] = field(default_factory=list)
    avoid_words: list[str] = field(default_factory=list)      # 应避免使用的词/腔调
    how_to_reply: list[str] = field(default_factory=list)     # 回复时注意点
    topics_often_mentioned: list[str] = field(default_factory=list)
    self_description_hints: str = ""    # 从聊天中推断的身份/生活状态

    # ---- 样例 ----
    examples: list[dict] = field(default_factory=list)        # [{question, answer}]
    voice_samples: list[str] = field(default_factory=list)    # 真实发言样例

    # ---- 元数据 ----
    message_count: int = 0
    sources: dict = field(default_factory=dict)
    raw_count: int = 0
    files_read: int = 0
    data_source: str = "storage/history"
    updated_time: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PersonalStyle":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in fields})

    def is_empty(self) -> bool:
        return self.message_count == 0 and not self.common_words and not self.examples

    def get_profile_text(self, include_samples: bool = False) -> str:
        """供 Prompt 注入的完整个人画像文本"""
        if self.is_empty() and not self.summary:
            return ""

        lines = ["【我的聊天风格 — 必须像本人说话】"]

        if self.summary:
            lines.append(f"整体印象: {self.summary}")

        length_map = {"short": "短句（1-2句）", "medium": "中等长度", "long": "有时稍长"}
        lines.append(
            f"句长: 平均约 {self.avg_length:.0f} 字，"
            f"{length_map.get(self.sentence_style, '短句')}。"
        )

        if self.personality:
            lines.append(f"性格体现: {'、'.join(self.personality[:6])}。")
        if self.tone:
            lines.append(f"语气: {'、'.join(self.tone[:6])}。")
        if self.communication_style:
            lines.append(f"说话方式: {'、'.join(self.communication_style[:6])}。")
        if self.common_words:
            lines.append(f"常用词: {'、'.join(self.common_words[:8])}。")
        if self.particle_words:
            lines.append(f"语气词: {'、'.join(self.particle_words[:5])}。")
        if self.punctuation_style:
            lines.append(f"标点习惯: {self.punctuation_style}。")
        if self.reply_patterns:
            lines.append(f"回复模式: {'、'.join(self.reply_patterns[:6])}。")
        if self.topics_often_mentioned:
            lines.append(f"常聊话题: {'、'.join(self.topics_often_mentioned[:6])}。")
        if self.self_description_hints:
            lines.append(f"身份/生活线索: {self.self_description_hints}")

        emoji_pct = self.emoji_usage
        if emoji_pct > 0.15:
            lines.append("表情: 偶尔会用。")
        elif emoji_pct < 0.05:
            lines.append("表情: 基本不用。")

        if self.avoid_words:
            lines.append(f"避免使用: {'、'.join(self.avoid_words[:8])}。")
        if self.how_to_reply:
            lines.append(f"回复注意: {'；'.join(self.how_to_reply[:5])}。")

        if include_samples and self.voice_samples:
            lines.append("我平时的原话（照着这个味）:")
            for s in self.voice_samples[:6]:
                lines.append(f"  - {s}")

        if include_samples and self.examples:
            lines.append("典型问答（问→答）:")
            for ex in self.examples[:5]:
                q = ex.get("question", "")
                a = ex.get("answer", "")
                if q and a:
                    lines.append(f"  问: {q}")
                    lines.append(f"  我: {a}")

        lines.extend([
            "",
            "【风格约束 — 必须遵守】",
            f"1. 句子长度接近 {self.avg_length:.0f} 字，不要突然写长文",
            "2. 使用我的语气词和常用词，不要换成书面语",
            "3. 禁止机器人表达：您好、很高兴、感谢您的消息、非常期待",
            "4. 禁止客服腔：当然可以、没问题、很高兴为您服务",
            "5. 像发微信，不像写邮件或作文",
        ])
        return "\n".join(lines)
