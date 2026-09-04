"""个人知识库管理命令。"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from knowledge.base import PersonalKnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="个人知识库管理")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="创建资料目录和默认拒绝的权限配置")
    sub.add_parser("import", help="导入/重新索引全部资料")
    query = sub.add_parser("search", help="模拟指定联系人检索")
    query.add_argument("query")
    query.add_argument("--friend-id", required=True)
    query.add_argument("--friend-name", default="")
    query.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()

    kb = PersonalKnowledgeBase()
    if args.command == "init":
        kb.ensure_layout()
        print(f"资料目录: {kb.source_dir}")
        print(f"权限配置: {kb.policy_path}")
    elif args.command == "import":
        result = kb.import_all()
        print(f"导入完成: {result['files']} 个文件, {result['chunks']} 个分段")
    else:
        items = kb.search(args.query, args.friend_id, args.friend_name, args.limit)
        if not items:
            print("无获准且相关的知识片段")
        for item in items:
            print(f"[{item['score']}] {item['source']}: {item['text']}")


if __name__ == "__main__":
    main()
