"""
文本向量化模块
优先使用中文 ONNX 嵌入模型（fastembed + BAAI/bge-small-zh-v1.5）
回退: ChromaDB DefaultEmbeddingFunction（all-MiniLM-L6-v2）

模型:
  主: BAAI/bge-small-zh-v1.5 (ONNX, ~90MB, 512维)
  备: all-MiniLM-L6-v2 (ONNX, ~80MB, 384维)
"""

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHINESE_MODEL = "BAAI/bge-small-zh-v1.5"
CHINESE_DIM = 512
FALLBACK_DIM = 384
_shared_model = None


class _ChromaFallbackBackend:
    """ChromaDB 内置 MiniLM ONNX 嵌入（英文为主）"""

    def __init__(self):
        from chromadb.utils import embedding_functions

        self._model = embedding_functions.DefaultEmbeddingFunction()
        self.dim = FALLBACK_DIM
        self.name = "all-MiniLM-L6-v2"

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return self._model(texts)


class _FastEmbedBackend:
    """fastembed ONNX 中文嵌入"""

    def __init__(self):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=CHINESE_MODEL)
        self.dim = CHINESE_DIM
        self.name = CHINESE_MODEL

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [emb.tolist() for emb in self._model.embed(texts)]


class EmbeddingModel:
    """文本嵌入模型（中文 ONNX 优先，失败时回退 MiniLM）

    用法:
        model = EmbeddingModel()
        vec = model.encode("张三喜欢打篮球")  # → [0.12, -0.34, ...]
    """

    def __init__(self):
        print("⏳ 加载中文 ONNX 嵌入模型...")
        self._backend = None
        self._dim = None
        try:
            self._backend = _FastEmbedBackend()
            self._dim = self._backend.dim
            print(f"✅ 中文模型就绪 ({self._backend.name}), 维度: {self._dim}")
        except Exception as e:
            print(f"⚠️ 中文模型加载失败: {e}")
            print("⏳ 回退到 MiniLM 嵌入模型...")
            self._backend = _ChromaFallbackBackend()
            self._dim = self._backend.dim
            print(f"✅ 回退模型就绪 ({self._backend.name}), 维度: {self._dim}")

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, text: str) -> list[float]:
        """单条文本 → 向量"""
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码"""
        if not texts:
            return []
        return self._backend.encode_batch(texts)


def get_embedding_model() -> EmbeddingModel:
    """返回进程级共享模型，避免记忆库与知识库重复加载 ONNX 模型。"""
    global _shared_model
    if _shared_model is None:
        _shared_model = EmbeddingModel()
    return _shared_model


# ========== 测试 ==========

if __name__ == "__main__":
    model = EmbeddingModel()
    vec = model.encode("张三喜欢打篮球")
    print(f"\n向量维度: {len(vec)}")
    print(f"前5个值: {[round(v, 4) for v in vec[:5]]}")
