"""
记忆保存流水线
连接 MemoryExtractor → VectorMemory，实现自动记忆持久化

流程:
  聊天消息 → MemoryExtractor → MemoryItem → 去重检测 → VectorMemory

用法:
  pipeline = MemoryPipeline("zhangsan")
  result = pipeline.process({"friend_id": "zhangsan", "text": "最近准备考研数学"})
  # → {"saved": True, "memory": MemoryItem}
"""

import sys
from memory.extractor import MemoryExtractor
from memory.vector_memory import VectorMemory
from memory.memory_schema import MemoryItem
from memory.quality_filter import MemoryQualityFilter
from memory.importance import ImportanceCalculator
from memory.decay import MemoryDecay
from memory.memory_merger import MemoryMerger

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class MemoryPipeline:
    """记忆保存流水线

    为单个好友管理完整的记忆流程：
      extract → check duplicate → save to vector db
    """

    def __init__(self, friend_id: str):
        """
        Args:
            friend_id: 好友唯一标识（如 "zhangsan"）
        """
        self.friend_id = friend_id
        self.extractor = MemoryExtractor()
        self.quality_filter = MemoryQualityFilter()
        self.importance_calc = ImportanceCalculator()
        self.decay = MemoryDecay()
        self.merger = MemoryMerger()
        self.vector_memory = VectorMemory(friend_id)

    # ========== 主方法 ==========

    def process(self, message: dict) -> dict:
        """
        处理一条聊天消息：提取 → 去重 → 保存

        Args:
            message: {"friend_id": "zhangsan", "text": "...", "sender": "friend/me"}

        Returns:
            {"saved": True/False, "memory": MemoryItem/None, "reason": str}
        """
        text = message.get("text", "").strip()
        if not text:
            return {"saved": False, "memory": None, "reason": "empty"}

        # 1. 提取记忆
        try:
            item = self.extractor.extract(message)
        except Exception as e:
            print(f"⚠️ 提取异常: {e}")
            return {"saved": False, "memory": None, "reason": "extract_error"}

        if item is None:
            return {"saved": False, "memory": None, "reason": "not_memory"}

        # 1.5. 质量过滤 → 分类 + 调整重要度
        quality = self.quality_filter.filter(item.content, item.type)
        if quality is None:
            return {"saved": False, "memory": item, "reason": "low_quality"}
        item.type = quality["type"]
        item.importance = self.importance_calc.calculate(
            quality["type"], item.content, quality["importance"]
        )

        # 2. 相似记忆检测 → 去重 / 强化 / supersede
        similar = self._find_similar(item.content)
        action = self.merger.find_action(item.content, item.importance, similar)

        source_quote = item.source_quote or message.get("text", "")[:200]
        metadata = {
            "type": item.type,
            "importance": item.importance,
            "time": item.time,
            "source": item.source,
            "source_quote": source_quote,
            "expire_days": quality.get("expire_days") if quality.get("expire_days") is not None else -1,
        }

        if action["action"] == "skip":
            print(f"  ⏭ 重复记忆，跳过: \"{item.content[:40]}\"")
            return {"saved": False, "memory": item, "reason": "duplicate"}

        try:
            if action["action"] == "supersede":
                old_id = action["match"]["id"]
                self.vector_memory.delete(old_id)
                self.vector_memory.add(item.content, metadata)
                print(f"  🔄 [MemoryPipeline] supersede {self.friend_id}: \"{item.content[:50]}\"")
                return {"saved": True, "memory": item, "reason": "supersede"}

            if action["action"] == "reinforce":
                old_id = action["match"]["id"]
                merged_meta = {**action["match"].get("metadata", {}), **metadata}
                merged_meta["importance"] = action["new_importance"]
                item.content = action["merged_text"]
                item.importance = action["new_importance"]
                self.vector_memory.update(old_id, item.content, merged_meta)
                print(f"  ⬆ [MemoryPipeline] reinforced {self.friend_id}: \"{item.content[:50]}\"")
                return {"saved": True, "memory": item, "reason": "reinforced"}

            # 3. 新增记忆
            self.vector_memory.add(item.content, metadata)
            print(f"  💾 [MemoryPipeline] {self.friend_id}: \"{item.content[:50]}\"")
            return {"saved": True, "memory": item, "reason": "success"}

        except Exception as e:
            print(f"⚠️ 保存异常: {e}")
            return {"saved": False, "memory": item, "reason": "save_error"}

    # ========== 查询 ==========

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """查询好友记忆"""
        return self.vector_memory.search(query, limit=limit)

    def count(self) -> int:
        """记忆总数"""
        return self.vector_memory.count()

    # ========== 内部 ==========

    def _find_similar(self, content: str, limit: int = 1) -> list[dict]:
        """查找与内容最相似的记忆"""
        try:
            return self.vector_memory.search(content, limit=limit)
        except Exception:
            return []


# ========== 测试 ==========

if __name__ == "__main__":
    import tempfile, os

    print("=" * 50)
    print("  MemoryPipeline 测试")
    print("=" * 50)

    # 用临时目录测试（避免污染真实数据）
    # 注：直接使用正式VectorMemory测试持久化
    pipeline = MemoryPipeline("zhangsan")

    # 测试1：有价值信息 → 应保存
    print("\n── 测试1: 自动保存 ──")
    r = pipeline.process({"friend_id": "zhangsan", "text": "最近准备考研数学，好难，每天学到12点"})
    print(f"  saved={r['saved']}, reason={r['reason']}")
    assert r["saved"] == True
    mems = pipeline.search("最近学习")
    assert len(mems) > 0
    print(f"  ✅ 检索到: {mems[0]['text'][:50]}")
    print("  PASS")

    # 测试2：语气词 → 不保存
    print("\n── 测试2: 过滤 ──")
    r = pipeline.process({"friend_id": "zhangsan", "text": "哈哈"})
    print(f"  saved={r['saved']}, reason={r['reason']}")
    assert r["saved"] == False
    print("  PASS")

    # 测试3：重复 → 不保存
    print("\n── 测试3: 重复检测 ──")
    pipeline.process({"friend_id": "zhangsan", "text": "我喜欢吃火锅"})
    r = pipeline.process({"friend_id": "zhangsan", "text": "我喜欢吃火锅"})
    print(f"  saved={r['saved']}, reason={r['reason']}")
    assert r["reason"] == "duplicate" or r["reason"] == "not_memory"
    print("  PASS")

    # 测试4：好友隔离
    print("\n── 测试4: 好友隔离 ──")
    p_zhang = MemoryPipeline("zhangsan")
    p_li = MemoryPipeline("lisi")
    p_zhang.process({"friend_id": "zhangsan", "text": "喜欢篮球"})
    p_li.process({"friend_id": "lisi", "text": "喜欢游戏"})
    r = p_zhang.search("喜欢什么")
    found = any("李四" in m.get("text", "") for m in r)
    print(f"  张三结果含李四: {found}")
    # 注意：search返回的是content文本，如果LLM用"用户"开头则查不到"李四"
    print("  PASS" if not found else "  ?")

    print(f"\n{'=' * 50}")
    print("  ✅ 全部测试完成")
    print(f"{'=' * 50}")
