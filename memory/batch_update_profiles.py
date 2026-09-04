"""Batch force-update all friend profiles from storage/history."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.friend_history_reader import FriendHistoryReader
from memory.memory_store import MemoryStore
from memory.profile_builder import ProfileBuilder

SKIP_IDS = {"test", "test2"}
MIN_MESSAGES = 5


def main():
    store = MemoryStore()
    history_dir = os.path.join("storage", "history")
    files = sorted(glob.glob(os.path.join(history_dir, "*.jsonl")))

    print("=" * 50)
    print("  批量更新好友画像（详细版）")
    print("=" * 50)

    ok, skip_count, fail = 0, 0, 0
    for path in files:
        fid = os.path.basename(path)[:-6]
        if fid in SKIP_IDS:
            print(f"  skip test: {fid}")
            skip_count += 1
            continue

        name = store.resolve_display_name(fid)
        stats = FriendHistoryReader(fid).collect()
        count = stats["unique_friend_count"]
        if count < MIN_MESSAGES:
            print(f"  skip too few: {name or fid} ({count} msgs)")
            skip_count += 1
            continue

        print(f"\n>> {name or fid} ({fid}) — {count} friend msgs")
        try:
            pb = ProfileBuilder(fid, name)
            result = pb.sync_from_storage(force=True)
            if result:
                ok += 1
                print(f"  OK relationship: {result.relationship}")
                if result.summary:
                    print(f"     summary: {result.summary[:80]}")
                print(f"     interests: {result.interests[:4]}")
                print(f"     personality: {result.personality[:3]}")
            else:
                fail += 1
                print("  FAIL: sync returned None")
        except Exception as e:
            fail += 1
            print(f"  ERROR: {e}")

    print(f"\n{'=' * 50}")
    print(f"  done: ok={ok} skip={skip_count} fail={fail}")
    print("=" * 50)


if __name__ == "__main__":
    main()
