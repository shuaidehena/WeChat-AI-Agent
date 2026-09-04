"""
聊天游标追踪器（方案一）

按好友维护「已见 / 已回复」游标，通过 发送者+内容 指纹做增量对比。
不使用 Y 坐标（发送后消息滚动会导致 Y 变化，从而重复触发回复）。
"""

import hashlib
import json
import os
import re
import sys
import time
import uuid
from difflib import SequenceMatcher

from memory.content_filter import clean_for_memory
from wechat.sender import WeChatSender
from utils.atomic_io import write_json_atomic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ChatTracker:
    """按好友追踪聊天游标

    每个好友独立状态:
      - seen:           已见过的消息指纹
      - seen_contents:  已见过的消息正文（用于 OCR 碎片去重）
      - last_replied:   已回复过的 friend 消息指纹
      - initialized:    是否已完成首次快照
    """

    MAX_SEEN_PER_FRIEND = 500
    TRACKER_VERSION = 3
    RETRY_DELAY_SEC = 10.0
    MAX_RETRY_ATTEMPTS = 3

    # OCR 滚动后轻微错字/改字：与已见内容相似度 ≥ 此阈值视为同一条
    OCR_VARIANT_MIN_LEN = 8
    OCR_VARIANT_THRESHOLD = 0.82
    OCR_VARIANT_LEN_RATIO_MIN = 0.72

    def __init__(self, cache_path: str = "storage/chat_tracker.json"):
        self.cache_path = cache_path
        self._states: dict[str, dict] = {}
        self._load()

    # ========== 主入口 ==========

    def diff(self, friend_id: str, messages: list) -> list:
        """
        对比当前屏幕消息，返回真正新增的消息（按 Y 排序）

        首次见到该好友：记录当前屏幕为基准，返回空（不回复历史消息）
        """
        if not friend_id:
            return []

        state = self._get_state(friend_id)
        seen: list[str] = state.setdefault("seen", [])
        seen_contents: list[str] = state.setdefault("seen_contents", [])
        current_friend = [
            msg for msg in messages
            if self.normalize_content(self._get_content(msg)) and not self.is_me_message(msg)
        ]
        current_records = [self._message_record(msg) for msg in current_friend]

        if not state.get("initialized"):
            for msg in messages:
                self._remember(msg, seen, seen_contents)
            self._trim_seen(seen)
            self._trim_seen(seen_contents)
            state["initialized"] = True
            state["visible"] = current_records
            state["pending"] = []
            self._save()
            print(f"  📌 [{friend_id}] 首次快照: {len(messages)} 条（不回复历史）")
            return []

        pending_before = len(state.setdefault("pending", []))
        new_msgs = self._collect_due_retries(state)
        retry_state_changed = pending_before != len(state.get("pending", [])) or bool(new_msgs)
        previous_visible = state.get("visible", [])
        overlap = self._find_screen_overlap(previous_visible, current_records)
        screen_candidates = current_friend[overlap:] if overlap > 0 else []

        # 完全没有重叠时可能是窗口切换、滚动或 OCR 大幅变化，回退到长期指纹。
        if not previous_visible:
            screen_candidates = current_friend
        elif overlap == 0:
            screen_candidates = []

        for msg in messages:
            content = self.normalize_content(self._get_content(msg))
            if not content:
                continue

            # 自动回复前缀 → 一律视为自己，不参与增量回复
            if self.is_me_message(msg):
                self._remember(msg, seen, seen_contents)
                continue

            if self._is_ocr_fragment(content, seen_contents):
                print(f"  ⏭ OCR碎片跳过: \"{content[:40]}\"")
                self._remember(msg, seen, seen_contents)
                continue

            variant_match = self._find_ocr_variant(content, seen_contents)
            if variant_match:
                print(
                    f"  ⏭ OCR变体跳过: \"{content[:40]}\" "
                    f"(≈ \"{variant_match[:40]}\")"
                )
                self._remember(msg, seen, seen_contents)
                continue

            fp = self.fingerprint(msg)
            if fp not in seen:
                seen.append(fp)
                seen_contents.append(content)

        for msg in screen_candidates:
            record = self._message_record(msg)
            record.update({
                "event_id": uuid.uuid4().hex,
                "attempts": 1,
                "last_attempt": time.time(),
            })
            state.setdefault("pending", []).append(record)
            new_msgs.append(msg)

        state["visible"] = current_records

        self._trim_seen(seen)
        self._trim_seen(seen_contents)
        if new_msgs or previous_visible != current_records or retry_state_changed:
            self._save()
        return new_msgs

    def get_unreplied_friend_msgs(self, friend_id: str, friend_msgs: list) -> list:
        """从 friend 新消息中筛出尚未回复的"""
        if not friend_msgs:
            return []

        # diff() 返回的是带事件语义的新消息/待重试消息，不能再按正文永久去重。
        return list(friend_msgs)

    def mark_replied(self, friend_id: str, messages: list):
        """标记一批 friend 消息为已回复"""
        if not friend_id or not messages:
            return

        state = self._get_state(friend_id)
        replied: list[str] = state.setdefault("last_replied", [])

        for msg in messages:
            fp = self.fingerprint(msg)
            if fp not in replied:
                replied.append(fp)
            pending = state.setdefault("pending", [])
            for i, record in enumerate(pending):
                if self._record_matches_message(record, msg):
                    del pending[i]
                    break

        self._trim_seen(replied, limit=200)
        self._save()

    @staticmethod
    def merge_contents(messages: list) -> str:
        """合并多条 friend 消息为一条输入"""
        parts = []
        for msg in messages:
            content = ChatTracker.normalize_content(ChatTracker._get_content(msg))
            if content:
                parts.append(content)
        return "\n".join(parts)

    @staticmethod
    def is_friend_message(msg) -> bool:
        return not ChatTracker.is_me_message(msg)

    @staticmethod
    def is_me_message(msg) -> bool:
        if ChatTracker._get_sender(msg) in ("me", "我"):
            return True
        content = ChatTracker.normalize_content(ChatTracker._get_content(msg))
        return WeChatSender.is_auto_reply(content)

    def all_marked_replied(self, friend_id: str, messages: list) -> bool:
        """检查消息是否全部已标记为已回复"""
        if not messages:
            return True
        replied = set(self._get_state(friend_id).get("last_replied", []))
        return all(self.fingerprint(m) in replied for m in messages)

    def reset_friend(self, friend_id: str):
        """切换好友或需要重新同步时重置游标"""
        if friend_id in self._states:
            del self._states[friend_id]
            self._save()

    @staticmethod
    def _message_record(msg) -> dict:
        return {
            "sender": ChatTracker._get_sender(msg),
            "content": ChatTracker.normalize_content(ChatTracker._get_content(msg)),
            "x": float(getattr(msg, "x", 0) or 0),
            "y": float(getattr(msg, "y", 0) or 0),
            "width": float(getattr(msg, "width", 0) or 0),
            "height": float(getattr(msg, "height", 0) or 0),
            "confidence": float(getattr(msg, "confidence", 0) or 0),
        }

    @staticmethod
    def _record_matches_message(record: dict, msg) -> bool:
        return (
            record.get("sender", "") == ChatTracker._get_sender(msg)
            and record.get("content", "")
            == ChatTracker.normalize_content(ChatTracker._get_content(msg))
        )

    @staticmethod
    def _find_screen_overlap(previous: list[dict], current: list[dict]) -> int:
        """返回上一屏后缀在当前屏中的结束位置，兼容向上/向下轻微滚动。"""
        max_len = min(len(previous), len(current))
        for size in range(max_len, 0, -1):
            old = [(r.get("sender"), r.get("content")) for r in previous[-size:]]
            for start in range(0, len(current) - size + 1):
                new = [
                    (r.get("sender"), r.get("content"))
                    for r in current[start:start + size]
                ]
                if old == new:
                    return start + size
        return 0

    def _collect_due_retries(self, state: dict) -> list:
        from parser.message import Message

        now = time.time()
        due = []
        kept = []
        for record in state.setdefault("pending", []):
            attempts = int(record.get("attempts", 1))
            elapsed = now - float(record.get("last_attempt", 0))
            if attempts >= self.MAX_RETRY_ATTEMPTS and elapsed >= self.RETRY_DELAY_SEC:
                print(f"  ⚠️ 回复重试已达上限，放弃: {record.get('content', '')[:40]}")
                continue
            if elapsed >= self.RETRY_DELAY_SEC:
                record["attempts"] = attempts + 1
                record["last_attempt"] = now
                due.append(Message(
                    sender=record.get("sender", "friend"),
                    content=record.get("content", ""),
                    x=record.get("x", 0),
                    y=record.get("y", 0),
                    width=record.get("width", 0),
                    height=record.get("height", 0),
                    confidence=record.get("confidence", 0),
                ))
            kept.append(record)
        state["pending"] = kept
        return due

    # ========== 指纹 ==========

    @staticmethod
    def normalize_content(content: str) -> str:
        content = str(content).strip()
        content = clean_for_memory(content)
        content = re.sub(r"\s+", " ", content)
        return content

    @staticmethod
    def fingerprint(msg) -> str:
        """消息指纹: 发送者 + 内容 hash（不含 Y，避免滚动后重复触发）"""
        sender = ChatTracker._get_sender(msg)
        content = ChatTracker.normalize_content(ChatTracker._get_content(msg))
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        return f"{sender}_{content_hash}"

    @staticmethod
    def _is_ocr_fragment(content: str, seen_contents: list[str]) -> bool:
        """判断是否为已见过消息的 OCR 截断片段"""
        if not content or len(content) < 6:
            return False

        for prev in seen_contents:
            if content == prev:
                return True
            # 新内容是旧内容的子串（滚动/截断后 OCR 变短）
            if len(content) < len(prev) and content in prev:
                return True
        return False

    @staticmethod
    def _compact_for_fuzzy(text: str) -> str:
        """去掉空白后比较，减少 OCR 随机空格干扰"""
        return re.sub(r"\s+", "", str(text or ""))

    @classmethod
    def _content_similarity(cls, a: str, b: str) -> float:
        a = cls._compact_for_fuzzy(a)
        b = cls._compact_for_fuzzy(b)
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    @classmethod
    def _find_ocr_variant(cls, content: str, seen_contents: list[str]) -> str | None:
        """
        判断 content 是否为已见过消息的 OCR 变体（错字/改字，非截断）。

        典型场景: 「什么时候」→「什公的候」滚动后指纹变化，但语义相同。
        """
        if not content or len(content) < cls.OCR_VARIANT_MIN_LEN:
            return None

        compact = cls._compact_for_fuzzy(content)
        if len(compact) < cls.OCR_VARIANT_MIN_LEN:
            return None

        best_prev = None
        best_ratio = 0.0

        for prev in seen_contents:
            if not prev:
                continue
            prev_compact = cls._compact_for_fuzzy(prev)
            if len(prev_compact) < cls.OCR_VARIANT_MIN_LEN:
                continue
            if content == prev:
                return prev

            len_ratio = min(len(compact), len(prev_compact)) / max(
                len(compact), len(prev_compact)
            )
            if len_ratio < cls.OCR_VARIANT_LEN_RATIO_MIN:
                continue

            ratio = cls._content_similarity(content, prev)
            if ratio >= cls.OCR_VARIANT_THRESHOLD and ratio > best_ratio:
                best_ratio = ratio
                best_prev = prev

        return best_prev

    def _remember(self, msg, seen: list, seen_contents: list):
        content = self.normalize_content(self._get_content(msg))
        fp = self.fingerprint(msg)
        if fp not in seen:
            seen.append(fp)
        if content and content not in seen_contents:
            seen_contents.append(content)

    # ========== 持久化 ==========

    def save(self):
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            write_json_atomic(self.cache_path, self._states)
        except IOError as e:
            print(f"⚠️ ChatTracker 保存失败: {e}")

    def _load(self):
        if not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self._states = json.load(f)
            # 旧版 y 坐标指纹 → 重置，避免格式不一致
            for fid, state in self._states.items():
                if state.get("version", 1) < self.TRACKER_VERSION:
                    state["seen"] = []
                    state["seen_contents"] = []
                    state["last_replied"] = []
                    state["initialized"] = False
                    state["version"] = self.TRACKER_VERSION
            print(f"📂 ChatTracker 已加载: {len(self._states)} 个好友游标")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ ChatTracker 读取失败: {e}，使用空状态")
            self._states = {}

    def _get_state(self, friend_id: str) -> dict:
        if friend_id not in self._states:
            self._states[friend_id] = {
                "version": self.TRACKER_VERSION,
                "initialized": False,
                "seen": [],
                "seen_contents": [],
                "last_replied": [],
                "visible": [],
                "pending": [],
            }
        return self._states[friend_id]

    @staticmethod
    def _trim_seen(seen: list, limit: int = None):
        limit = limit or ChatTracker.MAX_SEEN_PER_FRIEND
        if len(seen) > limit:
            del seen[: len(seen) - limit]

    @staticmethod
    def _get_content(msg) -> str:
        if hasattr(msg, "content"):
            return msg.content
        if isinstance(msg, dict):
            return msg.get("content", "")
        return str(msg)

    @staticmethod
    def _get_sender(msg) -> str:
        if hasattr(msg, "sender"):
            return msg.sender
        if isinstance(msg, dict):
            return msg.get("sender", "")
        return ""


# ========== 测试 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  ChatTracker 测试")
    print("=" * 50)

    class FakeMsg:
        def __init__(self, sender, content, y=0):
            self.sender = sender
            self.content = content
            self.y = y

    import tempfile
    cache = os.path.join(tempfile.mkdtemp(prefix="wechat_tracker_test_"), "tracker.json")
    tracker = ChatTracker(cache_path=cache)

    fid = "test_friend"

    r1 = [
        FakeMsg("张三", "你好", 100),
        FakeMsg("我", "嗨", 200),
        FakeMsg("张三", "在吗", 300),
    ]
    new1 = tracker.diff(fid, r1)
    assert new1 == [], f"首次应返回空, 实际 {new1}"
    print("✅ 首次快照不触发")

    r2 = r1 + [FakeMsg("张三", "帮我个忙", 400)]
    new2 = tracker.diff(fid, r2)
    assert len(new2) == 1 and new2[0].content == "帮我个忙"
    print("✅ 增量识别新消息")

    r3 = r2 + [FakeMsg("张三", "有空吗", 500), FakeMsg("张三", "急事", 600)]
    new3 = tracker.diff(fid, r3)
    assert len(new3) == 2
    print("✅ 连发两条均识别")

    unreplied = tracker.get_unreplied_friend_msgs(fid, new2 + new3)
    assert len(unreplied) == 3
    tracker.mark_replied(fid, unreplied)
    assert tracker._get_state(fid).get("pending") == []
    print("✅ 已回复标记生效")

    # 同内容 Y 坐标变化（发送后滚动）→ 不应重复
    r4 = [FakeMsg("张三", "帮我个忙", 50)]
    new4 = tracker.diff(fid, r4)
    assert new4 == [], f"滚动后同内容应跳过, 实际 {new4}"
    print("✅ 滚动后同内容不重复")

    # OCR 截断片段
    r5 = [FakeMsg("张三", "下班就去拿 以下是新消息 期待期待", 100)]
    tracker.diff(fid, r5)
    r6 = [FakeMsg("张三", "以下是新消息 期待期待", 50)]
    new6 = tracker.diff(fid, r6)
    assert new6 == [], f"OCR片段应跳过, 实际 {new6}"
    print("✅ OCR 截断片段跳过")

    # OCR 错字变体（滚动后 OCR 改字，指纹不同但语义相同）
    fid2 = "test_variant"
    base = [FakeMsg("小冯", "你知道我们什么时候认识的吗", 100)]
    tracker.diff(fid2, base)
    tracker.mark_replied(fid2, base)
    variant = [FakeMsg("小冯", "你知道我们什公的候认识的吗", 50)]
    new_var = tracker.diff(fid2, variant)
    assert new_var == [], f"OCR变体应跳过, 实际 {new_var}"
    print("✅ OCR 错字变体跳过")

    #  genuinely 不同的新消息不应被误杀
    r7 = base + variant + [FakeMsg("小冯", "你说话不要带哈哈两个字", 200)]
    new7 = tracker.diff(fid2, r7)
    assert len(new7) == 1 and "哈哈" in new7[0].content
    print("✅ 不同新消息仍正常识别")

    merged = tracker.merge_contents(new3)
    assert merged == "有空吗\n急事"
    print("✅ 消息合并")

    if os.path.exists(cache):
        os.remove(cache)
    os.rmdir(os.path.dirname(cache))
    print("\n✅ 全部测试通过")
