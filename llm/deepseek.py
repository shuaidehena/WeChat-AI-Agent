"""
DeepSeek API 客户端（向后兼容）
实际调用已统一到 llm.client.LLMClient
"""

import sys

from llm.client import LLMClient, SYSTEM_PROMPTS

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class DeepSeekClient:
    """向后兼容包装，内部使用 LLMClient"""

    SYSTEM_PROMPT = SYSTEM_PROMPTS["chat"]

    def __init__(self):
        self._client = LLMClient()
        self.config = self._client.config.get("chat")

    def chat(self, prompt: str, system_prompt: str = None, task: str = "chat") -> str:
        return self._client.chat(prompt, system_prompt=system_prompt, task=task)


if __name__ == "__main__":
    client = DeepSeekClient()
    if client.config.is_configured():
        print(client.chat("好友说：在吗", task="chat"))
    else:
        print("未配置 API Key，请编辑 .env")
