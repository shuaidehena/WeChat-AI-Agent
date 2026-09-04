"""
历史数据初始化器
读取 JSONL 历史聊天 → 清洗 → 分析 → 保存记忆 + 生成画像
"""

import sys
import os
import json
from datetime import datetime
from history.cleaner import HistoryCleaner
from history.analyzer import HistoryAnalyzer
from memory.vector_memory import VectorMemory
from memory.profile_builder import ProfileBuilder
from memory.profile import FriendProfile
from memory.memory_schema import MemoryItem

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class HistoryInitializer:
    """历史数据初始化器

    用法:
        init = HistoryInitializer("zhangsan", "张三")
        init.initialize()
    """

    def __init__(self, friend_id: str, friend_name: str = ""):
        self.friend_id = friend_id
        self.friend_name = friend_name
        self._cleaner = HistoryCleaner()
        self._analyzer = HistoryAnalyzer()
        self._vm = VectorMemory(friend_id)

        # 数据路径
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._history_path = os.path.join(base, "storage", "history", f"{friend_id}.jsonl")

    # ========== 主方法 ==========

    def initialize(self) -> dict:
        """
        执行完整初始化流程

        Returns:
            {"total": 总消息, "cleaned": 有效, "memories": 记忆数}
        """
        print("=" * 50)
        print(f"  🚀 初始化: {self.friend_name or self.friend_id}")
        print("=" * 50)

        # 1. 读取历史
        messages = self._load_history()
        if not messages:
            print("❌ 无历史数据")
            return {"total": 0, "cleaned": 0, "memories": 0}
        print(f"📖 读取: {len(messages)} 条聊天")

        # 2. 清洗
        cleaned = self._cleaner.clean(messages)
        print(f"🧹 清洗: {len(cleaned)} 条有效 (过滤 {len(messages)-len(cleaned)} 条)")

        if not cleaned:
            print("⚠️ 清洗后无有效消息")
            return {"total": len(messages), "cleaned": 0, "memories": 0}

        # 3. 分析
        result = self._analyzer.analyze(cleaned)
        memories = result.get("memories", [])
        profile_data = result.get("profile", {})
        print(f"🧠 提取: {len(memories)} 条长期记忆")

        # 4. 保存记忆到向量库
        saved = 0
        for m in memories:
            try:
                metadata = {
                    "type": m.get("type", "fact"),
                    "importance": m.get("importance", 0.5),
                    "time": datetime.now().strftime("%Y-%m-%d"),
                    "source": "history_init",
                }
                self._vm.add(m["content"], metadata)
                saved += 1
            except Exception as e:
                print(f"  ⚠️ 保存失败: {e}")

        print(f"💾 保存: {saved}/{len(memories)} 条记忆")

        # 5. 更新画像
        try:
            builder = ProfileBuilder(self.friend_id, self.friend_name)
            # 直接设置画像字段（不调LLM，因为analyzer已经分析过了）
            p = builder.profile
            if profile_data.get("interests"):
                p.interests = list(set(p.interests + profile_data["interests"]))[:5]
            if profile_data.get("personality"):
                p.personality = list(set(p.personality + profile_data["personality"]))[:5]
            if profile_data.get("communication_style"):
                p.communication_style = list(set(p.communication_style + profile_data["communication_style"]))[:5]
            builder._save()
            print(f"🖼 画像更新: interests={p.interests}, personality={p.personality}")
        except Exception as e:
            print(f"⚠️ 画像更新失败: {e}")

        print(f"\n✅ 初始化完成: {saved}条记忆, {self._vm.count()}条总量")
        return {"total": len(messages), "cleaned": len(cleaned), "memories": saved}

    # ========== 内部 ==========

    def _load_history(self) -> list[dict]:
        if not os.path.exists(self._history_path):
            print(f"❌ 文件不存在: {self._history_path}")
            return []
        messages = []
        with open(self._history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return messages


# ========== 入口 ==========

if __name__ == "__main__":
    import sys
    friend_id = sys.argv[1] if len(sys.argv) > 1 else "jiajiechao"
    friend_name = sys.argv[2] if len(sys.argv) > 2 else friend_id

    init = HistoryInitializer(friend_id, friend_name)
    init.initialize()
