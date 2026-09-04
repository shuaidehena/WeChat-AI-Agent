"""
记忆管理 CLI

用法:
  python tools/memory_admin.py list-friends
  python tools/memory_admin.py show yangchunhui
  python tools/memory_admin.py list-memories yangchunhui
  python tools/memory_admin.py search yangchunhui "喜欢什么"
  python tools/memory_admin.py delete yangchunhui <mem_id>
  python tools/memory_admin.py history yangchunhui --limit 20
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from memory.memory_store import MemoryStore


def _resolve(store: MemoryStore, name_or_id: str) -> tuple[str, str]:
    fid = store.resolve_friend_id(name_or_id)
    if not fid:
        print(f"❌ 未找到好友: {name_or_id}")
        raise SystemExit(1)
    name = store.resolve_display_name(fid)
    return fid, name


def cmd_list_friends(store: MemoryStore, _args):
    friends = store.list_friends()
    if not friends:
        print("（无好友）")
        return
    print(f"{'中文名':<12} {'friend_id':<20} {'向量':>4} {'历史':>4}")
    print("-" * 44)
    for f in friends:
        print(f"{f['name']:<12} {f['friend_id']:<20} {f['vector_count']:>4} {f['history_count']:>4}")


def cmd_show(store: MemoryStore, args):
    fid, name = _resolve(store, args.friend)
    print(f"好友: {name} ({fid})")
    meta = store.get_friend_meta(name) or {}
    if meta:
        print(f"  关系: {meta.get('relation') or '-'}")
        print(f"  标签: {', '.join(meta.get('tags') or []) or '-'}")
        notes = meta.get("notes") or []
        if notes:
            print("  notes:")
            for n in notes[-5:]:
                print(f"    - {n}")
    print(f"  向量记忆: {store.memory_count(fid)} 条")
    print(f"  聊天历史: {len(store.get_full_history(fid))} 条")
    profile = store.get_profile_text(fid, name)
    if profile:
        print("\n--- 画像 ---")
        print(profile)
    else:
        print("\n（暂无画像）")


def cmd_list_memories(store: MemoryStore, args):
    fid, name = _resolve(store, args.friend)
    mems = store.list_memories(fid, limit=args.limit)
    print(f"[{name}] 向量记忆 ({len(mems)} 条):")
    for m in mems:
        meta = m.get("metadata") or {}
        t = meta.get("type", "?")
        imp = meta.get("importance", "?")
        print(f"  [{m['id']}] ({t}, imp={imp}) {m['text'][:80]}")


def cmd_search(store: MemoryStore, args):
    fid, name = _resolve(store, args.friend)
    results = store.search_memories(fid, args.query, limit=args.limit)
    print(f"[{name}] 搜索 \"{args.query}\" ({len(results)} 条):")
    for r in results:
        score = r.get("score", 0)
        print(f"  [{score:.3f}] {r['text'][:80]}")


def cmd_delete(store: MemoryStore, args):
    fid, name = _resolve(store, args.friend)
    store.delete_memory(fid, args.mem_id)
    print(f"✅ 已删除 [{name}] 记忆 {args.mem_id}")


def cmd_history(store: MemoryStore, args):
    fid, name = _resolve(store, args.friend)
    rows = store.get_chat_history(fid, limit=args.limit)
    print(f"[{name}] 最近 {len(rows)} 条对话:")
    for r in rows:
        who = "我" if r.get("sender") == "me" else name
        print(f"  [{who}] {r.get('content', '')[:100]}")


def main():
    parser = argparse.ArgumentParser(description="WeChat AI Agent 记忆管理")
    parser.add_argument("--storage-dir", default="storage")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-friends", help="列出所有好友及记忆概况")

    p_show = sub.add_parser("show", help="查看好友详情")
    p_show.add_argument("friend", help="中文名或 friend_id")

    p_list = sub.add_parser("list-memories", help="列出向量记忆")
    p_list.add_argument("friend")
    p_list.add_argument("--limit", type=int, default=50)

    p_search = sub.add_parser("search", help="语义搜索记忆")
    p_search.add_argument("friend")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)

    p_del = sub.add_parser("delete", help="删除一条向量记忆")
    p_del.add_argument("friend")
    p_del.add_argument("mem_id")

    p_hist = sub.add_parser("history", help="查看 JSONL 聊天历史")
    p_hist.add_argument("friend")
    p_hist.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    store = MemoryStore(args.storage_dir)

    handlers = {
        "list-friends": cmd_list_friends,
        "show": cmd_show,
        "list-memories": cmd_list_memories,
        "search": cmd_search,
        "delete": cmd_delete,
        "history": cmd_history,
    }
    handlers[args.command](store, args)


if __name__ == "__main__":
    main()
