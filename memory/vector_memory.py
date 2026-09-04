"""
好友向量记忆库
每个好友一个独立的 ChromaDB Collection，实现语义记忆

用法:
    memory = VectorMemory("zhangsan")
    memory.add("张三正在准备考研数学", {"type": "fact"})
    results = memory.search("最近学习怎么样")
"""

import sys
import os
import chromadb
from chromadb.config import Settings
from memory.embedding import EmbeddingModel, get_embedding_model
from context.context_guard import ContextGuard

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_logged_collections: set[str] = set()


def _get_embedding():
    return get_embedding_model()


class VectorMemory:
    """好友独立向量记忆库

    每个好友一个 ChromaDB Collection，向量隔离。
    持久化到 storage/vector_db/chroma/

    用法:
        vm = VectorMemory("zhangsan")
        vm.add("张三喜欢打篮球", {"type": "interest"})
        results = vm.search("喜欢什么运动")
    """

    def __init__(self, friend_id: str, persist_dir: str = None):
        """
        Args:
            friend_id: 好友唯一标识（拼音或英文，如 "zhangsan"）
            persist_dir: 持久化目录，默认 storage/vector_db/chroma
        """
        if not ContextGuard.require_friend_id(friend_id, "向量记忆"):
            raise ValueError("invalid friend_id")
        self.friend_id = friend_id
        self.collection_name = self._safe_name(f"friend_{friend_id}")

        # 持久化目录
        if persist_dir is None:
            persist_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "storage", "vector_db", "chroma"
            )
        self._persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        # 初始化 ChromaDB 客户端
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        # 获取或创建 collection
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"friend_id": friend_id},
        )

        # 嵌入模型
        self._embedding = _get_embedding()

        if self.collection_name not in _logged_collections:
            _logged_collections.add(self.collection_name)
            print(f"📂 向量库: {self.collection_name} ({self._collection.count()} 条记忆)")

    # ========== 添加记忆 ==========

    def add(self, text: str, metadata: dict = None) -> str:
        """
        添加一条记忆

        Args:
            text: 记忆文本
            metadata: 附加信息 {"type": "fact", "time": "2026-07-08"}

        Returns:
            记忆 ID
        """
        if metadata is None:
            metadata = {}

        # 生成唯一 ID（基于内容哈希）
        import hashlib
        mem_id = hashlib.md5(text.encode()).hexdigest()[:12]

        # 向量化 + 存储
        embedding = self._embedding.encode(text)

        self._collection.add(
            ids=[mem_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

        return mem_id

    def add_batch(self, texts: list[str], metadatas: list[dict] = None):
        """批量添加记忆"""
        if not texts:
            return

        import hashlib
        ids = [hashlib.md5(t.encode()).hexdigest()[:12] for t in texts]

        embeddings = self._embedding.encode_batch(texts)

        if metadatas is None:
            metadatas = [{}] * len(texts)

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    # ========== 查询 ==========

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        语义搜索记忆

        Args:
            query: 查询文本
            limit: 返回条数

        Returns:
            [{"text": "...", "metadata": {...}, "score": 0.85}, ...]
        """
        query_embedding = self._embedding.encode(query)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
        )

        # 格式化结果
        items = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                item = {
                    "id": results["ids"][0][i] if results["ids"] else None,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                }
                if results["distances"]:
                    # ChromaDB 距离 → 相似度分数（余弦距离越小 = 越相似）
                    dist = results["distances"][0][i]
                    item["score"] = round(1.0 - dist / 2, 3)  # 映射到 0~1
                items.append(item)

        return items

    @staticmethod
    def _safe_name(name: str) -> str:
        """将中文名转为 ASCII 安全的 collection 名"""
        import hashlib
        # 如果已经是ASCII → 直接用
        if name.isascii():
            return name
        # 含中文 → 用 hash 后缀
        prefix = "friend_"
        h = hashlib.md5(name.encode()).hexdigest()[:8]
        return f"{prefix}{h}"

    # ========== 更新 / 删除 ==========

    def update(self, mem_id: str, text: str, metadata: dict = None) -> None:
        """更新已有记忆（文本变更时重新向量化）"""
        if metadata is None:
            metadata = {}
        embedding = self._embedding.encode(text)
        self._collection.update(
            ids=[mem_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def delete(self, mem_id: str) -> None:
        """删除单条记忆"""
        self._collection.delete(ids=[mem_id])

    def list_all(self, limit: int = 100) -> list[dict]:
        """列出全部记忆（管理员工具用）"""
        try:
            raw = self._collection.get(limit=limit, include=["documents", "metadatas"])
        except Exception:
            return []
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []
        items = []
        for i, doc in enumerate(docs):
            if not doc:
                continue
            items.append({
                "id": ids[i] if i < len(ids) else "",
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
            })
        return items

    # ========== 管理 ==========

    def count(self) -> int:
        """记忆总数"""
        return self._collection.count()

    def clear(self):
        """清空记忆（慎用）"""
        self._collection.delete(where={})
        print(f"🗑 {self.collection_name} 已清空")

    def delete_collection(self):
        """删除整个 collection"""
        self._client.delete_collection(self.collection_name)
        print(f"🗑 已删除: {self.collection_name}")


# ========== 独立测试 ==========

if __name__ == "__main__":
    import tempfile

    # 用临时目录测试
    tmp = tempfile.mkdtemp()
    vm = VectorMemory("test_friend", persist_dir=tmp)

    vm.add("张三喜欢打篮球", {"type": "interest"})
    vm.add("张三正在准备考研数学", {"type": "fact"})
    vm.add("张三上周去了长沙旅游", {"type": "event"})

    print("\n查询: 喜欢什么运动")
    for r in vm.search("喜欢什么运动"):
        print(f"  [{r['score']}] {r['text']}")

    print("\n查询: 最近学习怎么样")
    for r in vm.search("最近学习怎么样"):
        print(f"  [{r['score']}] {r['text']}")

    print("\n查询: 最近去了哪里")
    for r in vm.search("最近去了哪里"):
        print(f"  [{r['score']}] {r['text']}")
