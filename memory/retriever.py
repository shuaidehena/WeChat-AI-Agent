"""
记忆召回模块
从好友向量库获取候选记忆

用法:
    retriever = MemoryRetriever("zhangsan")
    candidates = retriever.retrieve("周末干嘛", limit=10)
    # → [{"text": "喜欢篮球", "score": 0.82, "metadata": {...}}, ...]
"""

import sys
from memory.vector_memory import VectorMemory

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryRetriever:
    """记忆召回器

    从指定好友的向量库中召回候选记忆。
    """

    def __init__(self, friend_id: str):
        self.friend_id = friend_id
        self._vm = VectorMemory(friend_id)

    def retrieve(self, query: str, limit: int = 10) -> list[dict]:
        """
        召回候选记忆

        Args:
            query: 查询文本（当前聊天内容）
            limit: 召回数量

        Returns:
            [{"text": "...", "score": 0.82, "metadata": {...}}, ...]
        """
        if self._vm.count() == 0:
            return []

        results = self._vm.search(query, limit=limit)
        return results

    def count(self) -> int:
        return self._vm.count()
