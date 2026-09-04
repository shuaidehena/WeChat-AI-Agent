"""
LLM 接入模块
统一客户端: llm.client.LLMClient

分任务配置（.env）:
  LLM_CHAT_PROVIDER=qwen       # 拟人回复推荐 qwen / moonshot
  LLM_CHAT_API_KEY=sk-xxx
  LLM_MEMORY_PROVIDER=deepseek # 记忆提取可用便宜模型
  LLM_PROFILE_PROVIDER=deepseek
"""

from llm.client import LLMClient
from llm.config import llm_config, PROVIDER_PRESETS

__all__ = ["LLMClient", "llm_config", "PROVIDER_PRESETS"]
