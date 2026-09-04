"""
历史聊天分析器
调用 DeepSeek 从历史聊天中提取长期记忆 + 画像信息
"""

import sys
import json
import re
from llm.client import LLMClient

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryAnalyzer:
    """历史聊天分析器

    批量分析聊天记录，提取结构化记忆和画像。
    每批最多500条，避免 token 超限。
    """

    CHUNK_SIZE = 500

    ANALYZE_PROMPT = """你是一个好友长期记忆分析器。

根据以下聊天记录，提取这个人的信息。只基于聊天内容，不要编造。

聊天记录:
{chats}

输出JSON（只输出JSON，不要解释）:
{{
  "memories": [
    {{"type": "fact/preference/event/relationship", "content": "简洁总结(第三人称)", "importance": 0.7}}
  ],
  "profile": {{
    "interests": ["兴趣1"],
    "personality": ["性格特点"],
    "communication_style": ["聊天风格"]
  }}
}}

要求:
- memories: 每批最多15条，importance 0.3~1.0
- profile: 每条不超过8个字，每类最多3项
- 无相关信息时返回空数组"""

    def __init__(self):
        self._llm = LLMClient()

    def analyze(self, messages: list[dict]) -> dict:
        """
        分析聊天记录

        Args:
            messages: [{"sender": "friend", "text": "..."}, ...]

        Returns:
            {"memories": [...], "profile": {...}}
        """
        if not messages:
            return {"memories": [], "profile": {}}

        all_memories = []
        profile = {"interests": [], "personality": [], "communication_style": []}

        # 分批处理
        for i in range(0, len(messages), self.CHUNK_SIZE):
            chunk = messages[i:i + self.CHUNK_SIZE]
            chat_text = "\n".join(
                f"- {m['text']}" for m in chunk
            )[:8000]  # 限制长度

            try:
                prompt = self.ANALYZE_PROMPT.format(chats=chat_text)
                response = self._llm.chat(prompt, task="memory")
                data = self._safe_json(response)

                if data:
                    if "memories" in data and isinstance(data["memories"], list):
                        for m in data["memories"]:
                            if m.get("content"):
                                all_memories.append({
                                    "type": m.get("type", "fact"),
                                    "content": m["content"].strip(),
                                    "importance": float(m.get("importance", 0.5)),
                                })

                    if "profile" in data and isinstance(data["profile"], dict):
                        p = data["profile"]
                        for key in ["interests", "personality", "communication_style"]:
                            if key in p and isinstance(p[key], list):
                                existing = set(profile.get(key, []))
                                for item in p[key]:
                                    if isinstance(item, str) and item.strip():
                                        existing.add(item.strip())
                                profile[key] = list(existing)[:5]

                print(f"  📊 分析第{i//self.CHUNK_SIZE+1}批: {len(chunk)}条 → {len(all_memories)}条记忆")

            except Exception as e:
                print(f"  ⚠️ 分析批次异常: {e}")
                continue

        # 去重记忆
        seen = set()
        unique_memories = []
        for m in all_memories:
            if m["content"] not in seen:
                seen.add(m["content"])
                unique_memories.append(m)

        return {"memories": unique_memories, "profile": profile}

    @staticmethod
    def _safe_json(text: str) -> dict | None:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None
