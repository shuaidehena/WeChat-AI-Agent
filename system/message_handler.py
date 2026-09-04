"""
消息处理总入口
协调 MemoryService + ChatAgent，实现完整处理链路
"""

import sys
from memory.memory_service import MemoryService
from knowledge.base import PersonalKnowledgeBase
from agent.agent import ChatAgent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MessageHandler:
    """消息处理总入口"""

    def __init__(self, profile: dict = None, style: dict = None):
        self.agent = ChatAgent(
            profile=profile or {},
            style=style or {},
            auto_send=False,
        )
        self._memory_service = MemoryService()
        self._knowledge = PersonalKnowledgeBase()

    def handle(self, message: dict) -> dict:
        friend_id = message.get("friend_id", "")
        friend_name = message.get("friend_name", "")
        text = message.get("text", "").strip()

        print(f"\n📨 [Handler] {friend_name}: \"{text[:50]}\"")

        # 同步检索
        self._memory_service.bind_friend(friend_id, friend_name)
        memories = self._memory_service.retrieve_and_rank(friend_id, text, limit=10)
        try:
            knowledge = self._knowledge.search(text, friend_id, friend_name, limit=4)
        except Exception as e:
            print(f"  ⚠️ 个人知识检索跳过: {e}")
            knowledge = []

        # 生成回复
        try:
            self.agent.set_friend_info(friend_name, {
                "name": friend_name,
                "relation": "",
                "tags": [],
            })
            agent_result = self.agent.process_message(
                {"sender": "friend", "content": text},
                memories=memories,
                knowledge=knowledge,
            )
            reply = agent_result.get("reply", "")
        except Exception as e:
            print(f"  ⚠️ Agent异常: {e}")
            reply = ""

        # 后台提取
        self._memory_service.submit_extract(
            friend_id, friend_name,
            [{"content": text, "sender": "friend"}],
        )

        print(f"  💬 回复: \"{reply[:50]}\"")
        return {
            "reply": reply,
            "memory_saved": False,  # 异步，此处不等待
            "memories_used": len(memories),
            "knowledge_used": len(knowledge),
        }

    def shutdown(self):
        self._memory_service.shutdown()
