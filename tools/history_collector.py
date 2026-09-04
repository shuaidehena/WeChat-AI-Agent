"""
聊天历史采集器
模拟真人操作：滚动聊天窗口 → 截图 → OCR → 解析 → 保存到 storage/history/{friend_id}.jsonl

流程:
  1. 检测 & 激活微信窗口
  2. 识别标题栏聊天对象 → 解析 friend_id
  3. 点击聊天消息区获取焦点
  4. 循环: 截图 → OCR → 解析 → 去重 → 增量写入 → 向上滚动
  5. Ctrl+C 中断时保留已采集内容

用法:
  python tools/history_collector.py
  python tools/history_collector.py --max-scrolls 300
"""

import sys
import os
import time
import json
import hashlib
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wechat.window import WeChatWindow
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from parser.bubble_parser import BubbleParser
from config.settings import CHAT_REGION, TITLE_REGION, SCREENSHOT_DIR
from context.name_mapper import FriendNameMapper
from context.title_name_validator import TitleNameValidator
from history.scroller import ChatScroller
from utils.atomic_io import write_text_atomic


class HistoryCollector:
    """聊天历史采集器（当前窗口）"""

    # 截图最上方可能只露出上一条气泡的一小截；这类 OCR 片段会破坏跨页重叠。
    TOP_CLIP_Y = 12

    def __init__(
        self,
        max_scrolls: int = 300,
        scroll_amount: int = 240,
        ocr_reader=None,
    ):
        self.max_scrolls = max_scrolls
        self.scroll_amount = scroll_amount

        self._wechat = WeChatWindow()
        self._capture = ScreenCapture()
        self._ocr = ocr_reader or OCRReader()
        self._scroller = ChatScroller()
        self._name_mapper = FriendNameMapper()
        self._title_validator = TitleNameValidator()

        self._window_rect = None
        self._chat_partner = ""
        self._friend_id = ""
        self._parser: BubbleParser | None = None
        self._jsonl_path = ""
        self._existing_tail: list[dict] = []
        self._previous_page: list[dict] = []
        self._session_count = 0
        self._interrupted = False
        self._reached_top = False

    def collect(self) -> list[dict]:
        print("=" * 60)
        print("  📜 聊天历史采集器")
        print("=" * 60)

        if not self._wechat.find():
            print("❌ 请先启动微信！")
            return []
        self._wechat.activate()
        time.sleep(0.5)

        self._window_rect = self._wechat.get_rectangle()
        self._chat_partner = self._read_chat_partner()
        if not self._chat_partner:
            print("❌ 未能识别当前聊天对象，请打开某个好友的聊天窗口后重试")
            return []

        self._friend_id = self._name_mapper.resolve_or_create(self._chat_partner)
        self._jsonl_path = self._history_path(self._friend_id)
        self._seed_from_existing_file()

        print(f"👤 采集对象: {self._chat_partner} ({self._friend_id})")
        print(f"💾 保存路径: {self._jsonl_path}")
        if self._existing_tail:
            print(f"   已有历史记录，将继续追加/补采")

        chat_abs = self._get_chat_region()
        chat_width = chat_abs[2] - chat_abs[0]
        self._parser = BubbleParser(chat_width=chat_width)
        self._scroller.set_chat_region(*chat_abs)
        self._scroller.reset()

        self._click_chat_area(chat_abs)
        # 无论上次停在何处，都先回到最新消息，再从底部向上完整采集。
        self._scroller.scroll_to_bottom(times=12)

        all_messages: list[dict] = []
        print(f"\n⏳ 开始采集（最多 {self.max_scrolls} 次滚动）...")
        print(f"   每次截图后向上滚动约 {self.scroll_amount}px")
        print("   按 Ctrl+C 可随时停止，已采集内容会自动保留\n")

        try:
            for page in range(1, self.max_scrolls + 1):
                save_path = f"{SCREENSHOT_DIR}/history_{page:03d}.png"
                img = self._capture.capture(chat_abs)
                self._capture.save(save_path, img)
                img_hash = hashlib.md5(img.tobytes()).hexdigest()

                messages = self._parse_screenshot(save_path, img)
                new_records = self._filter_new_messages(messages)

                if new_records:
                    new_records.sort(key=lambda m: m["y"])
                    written = self._persist_batch(new_records, first_batch=(page == 1))
                    all_messages = new_records + all_messages
                    print(
                        f"  [{page:3d}] 截图 {len(messages)}条 → "
                        f"新增 {written}条 | 本次 {self._session_count}条 | "
                        f"文件 {self._file_count()}条"
                    )
                else:
                    print(f"  [{page:3d}] 截图 {len(messages)}条 → 新增 0条")

                if self._scroller.is_top(img_hash):
                    self._reached_top = True
                    print("\n🏁 已到达聊天顶部（连续两屏无变化）")
                    break

                self._scroller.scroll_up(amount=self.scroll_amount)

        except KeyboardInterrupt:
            self._interrupted = True
            print("\n\n⚠️ 采集已手动停止，已采集内容已保留")

        self._print_summary()
        return all_messages

    def save_path(self) -> str:
        return self._jsonl_path

    def file_count(self) -> int:
        return self._file_count()

    @property
    def chat_partner(self) -> str:
        return self._chat_partner

    @property
    def friend_id(self) -> str:
        return self._friend_id

    @property
    def reached_top(self) -> bool:
        """本轮是否确认到达聊天顶部；False 表示文件仍可能只是部分历史。"""
        return self._reached_top

    # ========== 持久化 ==========

    def _history_path(self, friend_id: str) -> str:
        history_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "history",
        )
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, f"{friend_id}.jsonl")

    def _seed_from_existing_file(self):
        """保留已有文件尾部序列，用屏幕重叠而不是正文全局去重。"""
        self._existing_tail = self._load_jsonl(self._jsonl_path)[-200:]
        self._previous_page = []

    def _persist_batch(self, new_records: list[dict], first_batch: bool) -> int:
        """增量写入：首屏追加（较新），后续 prepend（更旧）"""
        to_write: list[dict] = []
        for msg in new_records:
            record = {
                "time": msg.get("time", datetime.now().strftime("%H:%M:%S")),
                "sender": msg.get("sender", "friend"),
                "text": msg.get("text", ""),
            }
            to_write.append(record)

        if not to_write:
            return 0

        lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in to_write]

        if first_batch:
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.writelines(lines)
        else:
            existing = ""
            if os.path.exists(self._jsonl_path):
                with open(self._jsonl_path, "r", encoding="utf-8") as f:
                    existing = f.read()
            write_text_atomic(self._jsonl_path, "".join(lines) + existing)

        self._session_count += len(to_write)
        return len(to_write)

    def _file_count(self) -> int:
        return len(self._load_jsonl(self._jsonl_path))

    def _print_summary(self):
        total = self._file_count()
        print(f"\n{'=' * 60}")
        if self._interrupted:
            print("  采集中断（部分完成）")
        elif not self._reached_top:
            print("  已达到滚动上限（部分完成）")
        else:
            print("  采集完成！")
        print(f"  聊天对象: {self._chat_partner}")
        print(f"  friend_id: {self._friend_id}")
        print(f"  本次新增: {self._session_count} 条")
        print(f"  文件总计: {total} 条")
        print(f"  保存路径: {self._jsonl_path}")
        print(f"{'=' * 60}")

    # ========== 内部方法 ==========

    def _parse_screenshot(self, save_path: str, img) -> list[dict]:
        ocr_raw = self._ocr.recognize_with_boxes(save_path)
        if not ocr_raw:
            return []

        parsed = self._parser.parse(ocr_raw, screenshot=img)
        records = []
        for msg in parsed:
            sender = "me" if msg.sender == "me" else "friend"
            records.append({
                "sender": sender,
                "text": msg.content.strip(),
                "y": int(msg.y),
            })
        records = [r for r in records if r["text"]]
        visible = [r for r in records if r["y"] >= self.TOP_CLIP_Y]
        clipped = len(records) - len(visible)
        if clipped:
            print(f"   ✂️ 忽略顶部截断片段: {clipped} 条")
        return visible

    def _filter_new_messages(self, messages: list[dict]) -> list[dict]:
        current = [
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "sender": msg["sender"],
                "text": msg["text"],
                "y": msg["y"],
            }
            for msg in messages
        ]
        if not current:
            return []

        if not self._previous_page:
            overlap = self._sequence_overlap(self._existing_tail, current)
            self._previous_page = current
            return current[overlap:]

        # 向上滚动后：当前页的后缀与上一页的前缀重叠，前部才是更旧的新记录。
        overlap = self._reverse_page_overlap(current, self._previous_page)
        self._previous_page = current
        return current[:-overlap] if overlap else current

    @staticmethod
    def _record_key(msg: dict) -> tuple[str, str]:
        return msg.get("sender", "friend"), str(msg.get("text", "")).strip()

    @classmethod
    def _sequence_overlap(cls, existing: list[dict], current: list[dict]) -> int:
        limit = min(len(existing), len(current))
        for size in range(limit, 0, -1):
            if [cls._record_key(m) for m in existing[-size:]] == [
                cls._record_key(m) for m in current[:size]
            ]:
                return size
        return 0

    @classmethod
    def _reverse_page_overlap(cls, current: list[dict], previous: list[dict]) -> int:
        """返回当前页末尾与上一页任意连续片段的最长重叠长度。

        上一页第一条有时是截图顶部的残片，因此不能只和 ``previous`` 的
        严格前缀比较；正文重叠可能从第二条或更后面开始。
        """
        limit = min(len(current), len(previous))
        for size in range(limit, 0, -1):
            current_suffix = [cls._record_key(m) for m in current[-size:]]
            for start in range(0, len(previous) - size + 1):
                previous_slice = [
                    cls._record_key(m)
                    for m in previous[start:start + size]
                ]
                if current_suffix == previous_slice:
                    return size
        return 0

    def _click_chat_area(self, chat_abs: tuple):
        left, top, right, bottom = chat_abs
        cx = (left + right) // 2
        cy = top + int((bottom - top) * 0.35)
        import pyautogui
        pyautogui.moveTo(cx, cy, duration=0.15)
        pyautogui.click()
        time.sleep(0.2)
        pyautogui.click()
        time.sleep(0.3)

    def _get_chat_region(self) -> tuple:
        return ScreenCapture.get_absolute_region(self._window_rect, CHAT_REGION)

    def _read_chat_partner(self) -> str:
        try:
            title_abs = ScreenCapture.get_absolute_region(
                self._window_rect, TITLE_REGION
            )
            title_img = self._capture.capture(title_abs)
            texts = self._ocr.recognize_image(title_img)
            candidates = [t.strip() for t in texts if 2 <= len(t.strip()) <= 30]
            return self._title_validator.pick_best(candidates)
        except Exception:
            return ""

    @staticmethod
    def _load_jsonl(path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows


def main():
    parser = argparse.ArgumentParser(description="采集当前微信聊天窗口的历史消息")
    parser.add_argument("--max-scrolls", type=int, default=300, help="最大滚动次数")
    parser.add_argument("--scroll-amount", type=int, default=240, help="每次滚动像素")
    args = parser.parse_args()

    collector = HistoryCollector(
        max_scrolls=args.max_scrolls,
        scroll_amount=args.scroll_amount,
    )

    try:
        messages = collector.collect()
    except KeyboardInterrupt:
        messages = []

    if collector.file_count() == 0:
        print("\n⚠️ 未采集到任何消息。请确保已打开微信聊天窗口。")
        return

    print(f"\n💾 数据已保存: {collector.save_path()}")

    if messages:
        print("\n📋 本次采集预览（最早 5 条 → 最新 5 条）:")
        preview = messages[:5] + (["..."] if len(messages) > 10 else []) + messages[-5:]
        for m in preview:
            if m == "...":
                print("  ...")
                continue
            who = "我" if m.get("sender") == "me" else collector._chat_partner
            print(f"  [{m.get('time', '?')}] {who}: {m.get('text', '')[:60]}")


if __name__ == "__main__":
    main()
