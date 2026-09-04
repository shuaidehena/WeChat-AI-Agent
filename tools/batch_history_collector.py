"""批量采集微信侧边栏当前可见会话，并为个人联系人生成画像。

用法:
  python tools/batch_history_collector.py
  python tools/batch_history_collector.py --max-scrolls 100
  python tools/batch_history_collector.py --limit 1 --max-scrolls 3  # 小范围验证
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pygetwindow as gw
import pyautogui

from config.settings import SIDEBAR_REGION
from context.title_name_validator import TitleNameValidator
from memory.friend_history_reader import FriendHistoryReader
from memory.profile_builder import ProfileBuilder
from tools.history_collector import HistoryCollector
from utils.atomic_io import write_json_atomic
from wechat.contact_list import ContactList
from wechat.contact_switcher import ContactSwitcher
from wechat.ocr import OCRReader
from wechat.screenshot import ScreenCapture
from wechat.window import WeChatWindow


PROGRESS_PATH = os.path.join("storage", "batch_history_progress.json")
INVENTORY_PATH = os.path.join("storage", "sidebar_conversations.json")


def _load_progress() -> dict:
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_progress(progress: dict) -> None:
    write_json_atomic(PROGRESS_PATH, progress)


def _hide_codex_window():
    for window in gw.getAllWindows():
        if (window.title or "").strip() == "ChatGPT" and not window.isMinimized:
            window.minimize()
            time.sleep(0.4)
            return window
    return None


def _is_group(name: str) -> bool:
    return bool(
        "群" in name
        or "班级" in name
        or re.search(r"[（(]\d+[）)]$", name)
    )


def _scroll_sidebar(rect: dict, *, upward: bool, times: int) -> None:
    """在会话列表内滚动，避免误滚聊天正文。"""
    sidebar = ScreenCapture.get_absolute_region(rect, SIDEBAR_REGION)
    x = sidebar[0] + int((sidebar[2] - sidebar[0]) * 0.72)
    y = sidebar[1] + int((sidebar[3] - sidebar[1]) * 0.55)
    pyautogui.moveTo(x, y, duration=0.1)
    amount = 120 if upward else -80
    for _ in range(max(1, times)):
        pyautogui.scroll(amount)
        time.sleep(0.06)
    time.sleep(0.7)


def _conversation_key(name: str, preview: str) -> str:
    """跨侧边栏页面保持稳定的会话键；Y 坐标会随滚动变化，不能参与。"""
    return f"{name.strip()}|{preview.strip()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="批量采集侧边栏可见聊天并生成画像")
    parser.add_argument("--max-scrolls", type=int, default=300)
    parser.add_argument("--scroll-amount", type=int, default=240)
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个，0=全部")
    parser.add_argument(
        "--sidebar-pages", type=int, default=50,
        help="最多扫描多少屏侧边栏，默认 50",
    )
    parser.add_argument(
        "--sidebar-scroll-steps", type=int, default=3,
        help="每屏向下滚动次数，默认 3",
    )
    parser.add_argument("--force", action="store_true", help="重新处理已完成会话")
    parser.add_argument("--no-profiles", action="store_true", help="只采集，不生成画像")
    args = parser.parse_args()

    codex_window = _hide_codex_window()
    progress = _load_progress()
    try:
        wechat = WeChatWindow()
        if not wechat.find() or not wechat.activate():
            print("❌ 无法激活微信窗口")
            return 1
        rect = wechat.get_rectangle()

        contact_list = ContactList()
        contact_list.set_window_rect(rect)
        switcher = ContactSwitcher()
        switcher.set_window_rect(rect)
        shared_ocr = OCRReader()
        validator = TitleNameValidator()
        success = profiles = skipped = failed = 0

        # 从侧边栏顶部开始，逐屏处理；相邻屏幕会重叠，用稳定键去重。
        _scroll_sidebar(rect, upward=True, times=12)
        seen_pages: set[tuple] = set()
        seen_conversations: set[str] = set()
        inventory: list[dict] = []
        handled = 0
        stop_requested = False

        for sidebar_page in range(1, args.sidebar_pages + 1):
            contacts = contact_list.scan()
            if not contacts:
                if sidebar_page == 1:
                    print("❌ 侧边栏未识别到会话")
                    return 2
                print("🏁 侧边栏无更多可识别会话")
                break

            ordered = sorted(contacts.items(), key=lambda pair: pair[1]["y"])
            fingerprint = tuple(
                (name, info.get("preview", ""), round(float(info["y"]), -1))
                for name, info in ordered
            )
            if fingerprint in seen_pages:
                print("🏁 侧边栏已到底（页面不再变化）")
                break
            seen_pages.add(fingerprint)
            print(f"\n📋 侧边栏第 {sidebar_page} 屏: {len(ordered)} 个可见会话")

            for ocr_name, info in ordered:
                if args.limit > 0 and handled >= args.limit:
                    stop_requested = True
                    break
                preview = info.get("preview", "")
                stable_key = _conversation_key(ocr_name, preview)
                if stable_key in seen_conversations:
                    continue
                seen_conversations.add(stable_key)
                handled += 1
                inventory.append({
                    "sidebar_page": sidebar_page,
                    "ocr_name": ocr_name,
                    "y": info["y"],
                    "preview": preview,
                })
                write_json_atomic(INVENTORY_PATH, inventory)

                row_key = stable_key
                legacy_key = f"{int(info['y'])}:{ocr_name}"
                prior = progress.get(row_key) or progress.get(legacy_key, {})
                if not args.force and prior.get("status") == "done":
                    print(f"\n[{handled}] ⏭ 已完成: {prior.get('name', ocr_name)}")
                    skipped += 1
                    continue

                print(f"\n[{handled}] 🔄 处理侧边栏行: {ocr_name}")
                if ocr_name in validator.NO_AUTO_REPLY:
                    print(f"  ⏭ 系统/服务会话跳过: {ocr_name}")
                    progress[row_key] = {
                        "status": "done",
                        "ocr_name": ocr_name,
                        "name": ocr_name,
                        "history_lines": 0,
                        "profile": "system_skipped",
                        "time": datetime.now().isoformat(timespec="seconds"),
                    }
                    _save_progress(progress)
                    skipped += 1
                    continue

                try:
                    switcher.switch_to(ocr_name, info["y"])
                    collector = HistoryCollector(
                        max_scrolls=args.max_scrolls,
                        scroll_amount=args.scroll_amount,
                        ocr_reader=shared_ocr,
                    )
                    collector.collect()
                    actual_name = collector.chat_partner
                    friend_id = collector.friend_id
                    total = collector.file_count()
                    complete = collector.reached_top
                except Exception as exc:
                    print(f"  ❌ 会话采集异常: {exc}")
                    actual_name = friend_id = ""
                    total = 0
                    complete = False

                if not actual_name or not friend_id or total == 0:
                    progress[row_key] = {
                        "status": "failed",
                        "ocr_name": ocr_name,
                        "time": datetime.now().isoformat(timespec="seconds"),
                    }
                    _save_progress(progress)
                    failed += 1
                    continue

                profile_status = "not_requested"
                valid_name = validator.validate(actual_name)[0]
                if not complete:
                    profile_status = "history_partial"
                elif args.no_profiles:
                    profile_status = "disabled"
                elif not valid_name or not validator.is_auto_reply_allowed(actual_name):
                    profile_status = "system_skipped"
                elif _is_group(actual_name):
                    profile_status = "group_skipped"
                else:
                    stats = FriendHistoryReader(friend_id).collect()
                    if stats["unique_friend_count"] < 5:
                        profile_status = "too_few_messages"
                    else:
                        result = ProfileBuilder(friend_id, actual_name).sync_from_storage(force=True)
                        profile_status = "generated" if result else "generation_failed"
                        if result:
                            profiles += 1

                progress[row_key] = {
                    "status": "done" if complete else "partial",
                    "ocr_name": ocr_name,
                    "name": actual_name,
                    "friend_id": friend_id,
                    "history_lines": total,
                    "profile": profile_status,
                    "time": datetime.now().isoformat(timespec="seconds"),
                }
                _save_progress(progress)
                success += 1

            if stop_requested or (args.limit > 0 and handled >= args.limit):
                break
            _scroll_sidebar(
                rect,
                upward=False,
                times=args.sidebar_scroll_steps,
            )

        print("\n" + "=" * 60)
        print(
            f"批量完成: 侧边栏会话={min(handled, args.limit) if args.limit else handled}, "
            f"历史成功={success}, 画像生成={profiles}, "
            f"已跳过={skipped}, 失败={failed}"
        )
        print(f"历史目录: {os.path.abspath(os.path.join('storage', 'history'))}")
        print(f"画像目录: {os.path.abspath(os.path.join('storage', 'profiles'))}")
        print("=" * 60)
        return 0 if failed == 0 else 3
    except KeyboardInterrupt:
        print("\n⚠️ 已中断，当前进度已保存，下次运行会续采")
        return 130
    finally:
        if codex_window is not None:
            try:
                codex_window.restore()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
