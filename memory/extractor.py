"""
聊天记忆提取器
规则预提取 → LLM 结构化提取（带上下文）

流程:
  1. 规则过滤（语气词、短文本）
  2. RuleExtractor（不调 LLM）
  3. LLM 提取（memory 任务，可用便宜模型）
"""

import sys
import json
import re

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.memory_schema import MemoryItem
from memory.content_filter import clean_for_memory, is_memory_noise
from memory.rule_extractor import RuleExtractor
from llm.client import LLMClient


class MemoryExtractor:
    """聊天长期记忆提取器"""

    SKIP_KEYWORDS = [
        "哈哈", "呵呵", "嘿嘿", "嘻嘻",
        "嗯", "嗯嗯", "哦", "哦哦", "噢",
        "好的", "好", "ok", "OK",
        "收到", "知道了", "明白",
        "在吗", "在不在", "在干嘛", "干嘛呢",
        "吃饭了吗", "吃了吗", "睡了吗",
        "早", "晚安", "拜拜", "再见",
        "?", "？", "。。。", "......",
    ]

    EXTRACT_PROMPT = """你是聊天长期记忆提取器。判断消息是否值得长期保存，并提取结构化记忆。

{context_block}【当前消息】
{message}

不值得记住（语气词、寒暄、无信息量）返回:
{{"need_memory": false}}

值得记住则返回:
{{"need_memory": true, "type": "identity|preference|goal|habit|event|relationship|emotion", "content": "第三人称总结", "importance": 0.85}}

要求:
- content 用第三人称，如「张三正在准备考研」
- 只基于消息内容，不要编造
- 只返回 JSON"""

    def __init__(self):
        self._llm = LLMClient()
        self._rules = RuleExtractor()

    def extract(self, message: dict) -> MemoryItem | None:
        text = message.get("text", "").strip()
        friend_id = message.get("friend_id", "")
        friend_name = message.get("friend_name", "")
        sender = message.get("sender", "friend")
        context = message.get("context") or []

        text = clean_for_memory(text)
        if not text:
            return None

        if sender in ("me", "我"):
            return None

        if self._should_skip(text):
            print(f"  🚫 规则过滤: \"{text[:30]}\"")
            return None

        # 规则预提取（不调 LLM）
        rule_item = self._rules.extract(text, friend_id, friend_name)
        if rule_item:
            print(f"  📋 规则提取: {rule_item}")
            return rule_item

        # LLM 提取
        try:
            context_block = self._format_context(context)
            prompt = self.EXTRACT_PROMPT.format(
                context_block=context_block,
                message=text,
            )
            response = self._llm.chat(prompt, task="memory")

            data = self._safe_json(response)
            if not data or not data.get("need_memory", False):
                return None

            mem_type = data.get("type", "fact")
            content = data.get("content", "").strip()
            importance = float(data.get("importance", 0.5))

            if not content:
                return None

            item = MemoryItem(
                friend_id=friend_id,
                type=mem_type,
                content=content,
                importance=min(max(importance, 0), 1),
                source="llm",
                source_quote=text[:200],
            )
            print(f"  🧠 LLM 提取: {item}")
            return item

        except Exception as e:
            print(f"  ⚠️ 提取失败: {e}")
            return None

    @staticmethod
    def _format_context(context: list) -> str:
        if not context:
            return ""
        lines = ["【最近对话（供理解语境）】"]
        for line in context[-6:]:
            lines.append(f"- {line}")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _should_skip(self, text: str) -> bool:
        if is_memory_noise(text):
            return True
        if len(text) < 5:
            return True
        if text in self.SKIP_KEYWORDS:
            return True
        if re.match(r'^[\d\s\.\,\;\:\!\?\-\+\(\)\[\]【】\\/\@\#\$\%\^\&\*]+$', text):
            return True
        return False

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
