"""
记忆服务
Pipeline 缓存 + 同步检索 + 异步提取 + 画像自动更新 + 上下文守卫
"""

import sys
import os
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from threading import Lock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.memory_store import MemoryStore
from memory.memory_pipeline import MemoryPipeline
from memory.ranker import MemoryRanker
from memory.profile_builder import ProfileBuilder
from memory.content_filter import clean_for_memory, is_memory_noise
from memory.style_context import StyleContextBuilder
from context.context_guard import ContextGuard


class MemoryService:
    """记忆系统统一入口"""

    def __init__(self, max_workers: int = 2, storage_dir: str = "storage"):
        self.store = MemoryStore(storage_dir)
        self._pipelines: dict[str, MemoryPipeline] = {}
        self._profile_builders: dict[str, ProfileBuilder] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="memory")
        self._pending = 0
        self._pending_lock = Lock()
        self._futures = set()
        self._session_id: str = ""
        self._session_name: str = ""

    # ========== 会话绑定（ContextGuard）==========

    def bind_friend(self, friend_id: str, friend_name: str = ""):
        """绑定当前活跃好友，后续读写均校验"""
        if not ContextGuard.require_friend_id(friend_id, "绑定好友"):
            return
        self._session_id = friend_id
        self._session_name = friend_name or self.store.resolve_display_name(friend_id)

    def clear_session(self):
        self._session_id = ""
        self._session_name = ""

    def _guard(self, friend_id: str, friend_name: str = "") -> bool:
        if not ContextGuard.require_friend_id(friend_id, "记忆访问"):
            return False
        if not self._session_id:
            print("🛑 [Guard] 未绑定当前会话，拒绝记忆访问")
            return False
        if not ContextGuard.verify_session(
            self._session_id, self._session_name, friend_id, friend_name
        ):
            return False
        if not ContextGuard.verify_memory(friend_id, friend_id):
            return False
        return True

    # ========== 同步：供回复路径使用 ==========

    def retrieve_and_rank(self, friend_id: str, query: str, limit: int = 10) -> list[str]:
        """检索并排序相关记忆（毫秒级，不阻塞）"""
        if not friend_id or not query.strip():
            return []
        if not self._guard(friend_id):
            return []
        try:
            if self.store.memory_count(friend_id) == 0:
                return []
            is_recall = MemoryRanker.is_recall_query(query)
            retrieve_limit = max(limit, 15) if is_recall else limit
            candidates = self.store.search_memories(friend_id, query, limit=retrieve_limit)
            return MemoryRanker.rank(query, candidates)
        except Exception as e:
            print(f"  ⚠️ 记忆检索异常: {e}")
            return []

    def get_profile_text(self, friend_id: str, friend_name: str = "") -> str:
        if not friend_id:
            return ""
        if not self._guard(friend_id, friend_name):
            return ""
        try:
            return self.store.get_profile_text(friend_id, friend_name)
        except Exception as e:
            print(f"  ⚠️ 画像读取异常: {e}")
            return ""

    def sync_friend_profile(
        self, friend_id: str, friend_name: str = "", force: bool = False
    ) -> bool:
        """从 storage/history 同步单个好友画像"""
        if not friend_id:
            return False
        try:
            pb = self._get_profile_builder(friend_id, friend_name)
            result = pb.sync_from_storage(force=force)
            return result is not None
        except Exception as e:
            print(f"  ⚠️ 好友画像同步失败 ({friend_id}): {e}")
            return False

    def sync_all_friend_profiles(self, force: bool = False) -> int:
        """
        扫描 storage/history/*.jsonl，为每个好友同步画像

        Returns:
            成功更新的好友数
        """
        import glob
        base = self.store.storage_dir
        history_dir = os.path.join(base, "history")
        if not os.path.isdir(history_dir):
            return 0

        updated = 0
        for path in glob.glob(os.path.join(history_dir, "*.jsonl")):
            friend_id = os.path.basename(path)[:-6]
            name = self.store.resolve_display_name(friend_id)
            try:
                pb = ProfileBuilder(friend_id, name)
                if force or pb.should_update():
                    if pb.sync_from_storage(force=force):
                        updated += 1
            except Exception as e:
                print(f"  ⚠️ 跳过 {friend_id}: {e}")
        if updated:
            print(f"  🖼 好友画像同步完成: {updated} 人")
        return updated

    def get_chat_history(self, friend_id: str, limit: int = 20) -> list[dict]:
        if not self._guard(friend_id):
            return []
        return self.store.get_chat_history(friend_id, limit)

    def get_style_context(
        self,
        friend_id: str,
        friend_name: str,
        history: list[dict],
        memories: list[str] = None,
        user_style: dict = None,
    ) -> dict:
        """构建双方风格 + 好友身份卡（供 Prompt 使用）"""
        if not friend_id or not self._guard(friend_id, friend_name):
            return {}
        try:
            friend_meta = self.store.get_friend_meta(friend_name) or {}
            builder = StyleContextBuilder()
            return builder.build(
                friend_id=friend_id,
                friend_name=friend_name,
                history=history,
                friend_meta=friend_meta,
                user_style=user_style or {},
                memories=memories,
            )
        except Exception as e:
            print(f"  ⚠️ 风格上下文异常: {e}")
            return {}

    # ========== 异步：提取 + 画像更新 ==========

    def submit_extract(self, friend_id: str, friend_name: str, messages: list):
        if not friend_id or not messages:
            return
        if not self._guard(friend_id, friend_name):
            return

        texts = []
        for msg in messages:
            content = self._get_content(msg)
            content = clean_for_memory(content)
            if content and not is_memory_noise(content):
                texts.append(content)

        if not texts:
            return

        with self._pending_lock:
            self._pending += 1
        try:
            future = self._executor.submit(
                self._extract_and_update, friend_id, friend_name, texts
            )
            self._futures.add(future)
            future.add_done_callback(self._futures.discard)
        except RuntimeError:
            with self._pending_lock:
                self._pending -= 1
            raise

    def shutdown(self, wait: bool = True, timeout: float = 10.0):
        unfinished = set(self._futures)
        if wait and unfinished:
            _, unfinished = wait_futures(unfinished, timeout=max(0.0, timeout))
        for future in unfinished:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._pending:
            print(f"  ⚠️ 记忆后台任务未全部完成 (pending={self._pending})")

    @property
    def pending_tasks(self) -> int:
        with self._pending_lock:
            return self._pending

    # ========== 内部 ==========

    def _get_pipeline(self, friend_id: str) -> MemoryPipeline:
        if friend_id not in self._pipelines:
            self._pipelines[friend_id] = MemoryPipeline(friend_id)
        return self._pipelines[friend_id]

    def _get_profile_builder(self, friend_id: str, friend_name: str = "") -> ProfileBuilder:
        if friend_id not in self._profile_builders:
            self._profile_builders[friend_id] = ProfileBuilder(friend_id, friend_name)
        elif friend_name and not self._profile_builders[friend_id].friend_name:
            self._profile_builders[friend_id].friend_name = friend_name
        return self._profile_builders[friend_id]

    def _extract_and_update(self, friend_id: str, friend_name: str, texts: list[str]):
        saved_count = 0
        try:
            pipeline = self._get_pipeline(friend_id)
            recent_chat = self.store.get_chat_history(friend_id, limit=12)
            context_lines = [
                f"{'TA' if m.get('sender') not in ('me', '我') else '我'}: {m.get('text', '')}"
                for m in recent_chat
                if m.get("text")
            ]
            for text in texts:
                try:
                    result = pipeline.process({
                        "friend_id": friend_id,
                        "friend_name": friend_name,
                        "text": text,
                        "sender": "friend",
                        "context": context_lines,
                    })
                    if result.get("saved"):
                        saved_count += 1
                        print(f"  💾 [后台] 记忆已保存: \"{text[:40]}\"")
                except Exception as e:
                    print(f"  ⚠️ [后台] 提取异常: {e}")

            if saved_count > 0:
                self._maybe_update_profile(friend_id, friend_name)

        except Exception as e:
            print(f"  ⚠️ [后台] 记忆任务异常: {e}")
        finally:
            with self._pending_lock:
                self._pending -= 1

    def _maybe_update_profile(self, friend_id: str, friend_name: str):
        try:
            pb = self._get_profile_builder(friend_id, friend_name)
            if pb.should_update():
                pb.sync_from_storage(force=False)
        except Exception as e:
            print(f"  ⚠️ [后台] 画像更新异常: {e}")

    @staticmethod
    def _get_content(msg) -> str:
        if hasattr(msg, "content"):
            return str(msg.content).strip()
        if isinstance(msg, dict):
            return str(msg.get("text") or msg.get("content", "")).strip()
        return str(msg).strip()
