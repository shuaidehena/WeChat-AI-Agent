"""
历史聊天采集器
自动滚动微信聊天窗口，采集全部历史消息
"""

import sys
import time
import hashlib
import warnings
from wechat.window import WeChatWindow
from wechat.screenshot import ScreenCapture
from wechat.ocr import OCRReader
from wechat.contact_switcher import ContactSwitcher
from wechat.contact_list import ContactList
from config.settings import CHAT_REGION, SCREENSHOT_DIR
from history.scroller import ChatScroller
from history.parser import HistoryParser
from history.deduplicator import HistoryDeduplicator
from history.storage import HistoryStorage

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.warn(
    "history.collector 已废弃；请使用 tools.history_collector",
    DeprecationWarning,
    stacklevel=2,
)


class HistoryCollector:
    """历史聊天采集器

    用法:
        collector = HistoryCollector("zhangsan", "张三")
        count = collector.collect(max_scrolls=200)
    """

    def __init__(self, friend_id: str, friend_name: str):
        self.friend_id = friend_id
        self.friend_name = friend_name

        self._wechat = WeChatWindow()
        self._capture = ScreenCapture()
        self._ocr = OCRReader()
        self._scroller = ChatScroller()
        self._parser = HistoryParser()
        self._dedup = HistoryDeduplicator()
        self._storage = HistoryStorage(friend_id)
        self._contact_list = ContactList()
        self._switcher = ContactSwitcher()

    def collect(self, max_scrolls: int = 300) -> int:
        """
        采集全部历史消息

        Returns:
            采集到的消息总数
        """
        print("=" * 50)
        print(f"  📜 采集历史: {self.friend_name} ({self.friend_id})")
        print("=" * 50)

        # 1. 找微信
        if not self._wechat.find():
            print("❌ 微信未启动")
            return 0
        self._wechat.activate()

        # 2. 切换到目标好友
        self._contact_list.set_window_rect(self._wechat.get_rectangle())
        self._switcher.set_window_rect(self._wechat.get_rectangle())
        contacts = self._contact_list.scan()
        if self.friend_name in contacts:
            self._switcher.switch_to(self.friend_name, contacts[self.friend_name]["y"])
        else:
            print(f"⚠️ 未在联系人列表找到 {self.friend_name}，使用当前窗口")

        # 3. 定位聊天区域
        window_rect = self._wechat.get_rectangle()
        chat_abs = ScreenCapture.get_absolute_region(window_rect, CHAT_REGION)
        chat_w = chat_abs[2] - chat_abs[0]
        self._parser = HistoryParser(chat_width=chat_w)

        # 聊天区域中心
        cx = (chat_abs[0] + chat_abs[2]) // 2
        cy = (chat_abs[1] + chat_abs[3]) // 2
        self._scroller.set_chat_center(cx, cy)
        self._scroller.reset()

        # 4. 循环采集
        self._wechat.activate()
        total = 0

        for page in range(1, max_scrolls + 1):
            # 截图
            img = self._capture.capture(chat_abs)
            img_hash = hashlib.md5(img.tobytes()).hexdigest()
            self._capture.save(f"{SCREENSHOT_DIR}/history/page_{page:03d}.png", img)

            # OCR
            ocr_raw = self._ocr.recognize_with_boxes(
                f"{SCREENSHOT_DIR}/history/page_{page:03d}.png"
            )
            if not ocr_raw:
                if self._scroller.is_top(img_hash):
                    break
                self._scroller.scroll_up()
                continue

            # 解析
            items = self._parser.parse(ocr_raw)
            merged = HistoryParser.merge_adjacent(items)

            # 去重
            new_msgs = [m for m in merged if self._dedup.is_new(m)]
            for m in new_msgs:
                self._dedup.add(m)

            # 保存
            if new_msgs:
                self._storage.save(new_msgs)
                total += len(new_msgs)
                print(f"  [{page:3d}] {len(merged)}条 → 新增{len(new_msgs)}条 | 累计{total}条")
            else:
                print(f"  [{page:3d}] {len(merged)}条 → 新增0条")

            # 检测到顶
            if self._scroller.is_top(img_hash):
                print("\n🏁 已到达聊天顶部")
                break

            # 向上滚动 + 等微信渲染
            self._scroller.scroll_up()
            time.sleep(0.5)

        print(f"\n✅ 采集完成: {total} 条消息")
        print(f"   保存至: storage/history/{self.friend_id}.jsonl")
        return total


# ========== 测试 ==========

if __name__ == "__main__":
    collector = HistoryCollector("test", "文件传输助手")
    collector.collect(max_scrolls=3)
