"""
清理 OCR 误识别产生的好友脏数据

用法:
  python tools/cleanup_identity_data.py --dry-run
  python tools/cleanup_identity_data.py --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from context.title_name_validator import TitleNameValidator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

STORAGE = os.path.join(_ROOT, "storage")
CHROMA = os.path.join(STORAGE, "vector_db", "chroma")

# chat_tracker 脏 key → 正确 friend_id（None 表示直接删除）
TRACKER_MERGES: dict[str, str | None] = {
    "昨天20:42": "yangchunhui",
    "我玩完了": "xushiqian",
    "weixinzhifu": "yangchunhui",
    "中南大学ITS": None,
    "复历史）": None,
    "xingqitian2246": "xushiqian",
}

# name_map 删除项 + 新增正确映射
REMOVE_NAME_MAP_KEYS = ("星期天22:46",)
ADD_NAME_MAP = {"徐世乾": "xushiqian"}

# friends.json 删除显示名 + 新增
REMOVE_FRIEND_NAMES = ("星期天22:46",)
ADD_FRIEND = {
    "徐世乾": {
        "relation": "",
        "tags": [],
        "notes": ["由 OCR 误识别「星期天22:46」修正"],
        "first_met": "2026-07-09",
        "friend_id": "xushiqian",
        "name": "徐世乾",
    }
}

# chroma collection 重命名
CHROMA_RENAMES = {
    "friend_xingqitian2246": "friend_xushiqian",
}


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _merge_tracker_state(target: dict, source: dict) -> dict:
    """合并两个 ChatTracker 状态"""
    for key in ("seen", "seen_contents", "last_replied"):
        merged: list = list(target.get(key, []))
        seen_set = set(merged)
        for item in source.get(key, []):
            if item not in seen_set:
                merged.append(item)
                seen_set.add(item)
        target[key] = merged

    target["initialized"] = bool(
        target.get("initialized") or source.get("initialized")
    )
    target["version"] = max(
        int(target.get("version", 2)),
        int(source.get("version", 2)),
    )
    return target


def cleanup_name_map(apply: bool) -> list[str]:
    path = os.path.join(STORAGE, "name_map.json")
    mapping = _load_json(path)
    actions = []

    for key in REMOVE_NAME_MAP_KEYS:
        if key in mapping:
            actions.append(f"name_map 删除: {key} → {mapping[key]}")
            if apply:
                mapping.pop(key, None)

    for name, fid in ADD_NAME_MAP.items():
        old = mapping.get(name)
        if old != fid:
            actions.append(f"name_map 新增: {name} → {fid}" + (f" (原 {old})" if old else ""))
            if apply:
                mapping[name] = fid

    validator = TitleNameValidator(STORAGE)
    validator._reload_known()
    for name in list(mapping.keys()):
        if name in REMOVE_NAME_MAP_KEYS or name in ADD_NAME_MAP:
            continue
        ok, reason = validator.validate(name)
        if not ok and name not in validator.known_names():
            actions.append(f"name_map 删除无效: {name} ({reason})")
            if apply:
                mapping.pop(name, None)

    if apply and actions:
        _save_json(path, mapping)
    return actions


def cleanup_friends(apply: bool) -> list[str]:
    path = os.path.join(STORAGE, "friends.json")
    friends = _load_json(path)
    actions = []

    for name in REMOVE_FRIEND_NAMES:
        if name in friends:
            actions.append(f"friends 删除: {name}")
            if apply:
                friends.pop(name, None)

    for name, info in ADD_FRIEND.items():
        if name not in friends or friends.get(name, {}).get("friend_id") != info["friend_id"]:
            actions.append(f"friends 新增/更新: {name} → {info['friend_id']}")
            if apply:
                friends[name] = info

    validator = TitleNameValidator(STORAGE)
    for name in list(friends.keys()):
        if name in REMOVE_FRIEND_NAMES or name in ADD_FRIEND:
            continue
        ok, reason = validator.validate(name)
        if not ok:
            fid = friends[name].get("friend_id", "?")
            actions.append(f"friends 标记无效(保留): {name} ({reason}) → {fid}")

    if apply and any("friends" in a for a in actions):
        _save_json(path, friends)
    return actions


def cleanup_chat_tracker(apply: bool) -> list[str]:
    path = os.path.join(STORAGE, "chat_tracker.json")
    tracker = _load_json(path)
    actions = []

    for from_key, to_key in TRACKER_MERGES.items():
        if from_key not in tracker:
            continue
        if to_key is None:
            actions.append(f"chat_tracker 删除: {from_key}")
            if apply:
                tracker.pop(from_key, None)
            continue

        src = tracker[from_key]
        if to_key not in tracker:
            tracker[to_key] = src
            actions.append(f"chat_tracker 迁移: {from_key} → {to_key}")
        else:
            tracker[to_key] = _merge_tracker_state(tracker[to_key], src)
            actions.append(f"chat_tracker 合并: {from_key} → {to_key}")
        if apply:
            tracker.pop(from_key, None)

    # 中文显示名 key → 已有 friend_id key
    name_map = _load_json(os.path.join(STORAGE, "name_map.json"))
    for chinese, fid in name_map.items():
        if chinese in tracker and fid in tracker and chinese != fid:
            tracker[fid] = _merge_tracker_state(tracker[fid], tracker[chinese])
            actions.append(f"chat_tracker 合并中文key: {chinese} → {fid}")
            if apply:
                tracker.pop(chinese, None)
        elif chinese in tracker and fid not in tracker:
            tracker[fid] = tracker.pop(chinese)
            actions.append(f"chat_tracker 重命名: {chinese} → {fid}")
            if apply:
                pass

    if apply and actions:
        _save_json(path, tracker)
    return actions


def cleanup_chroma(apply: bool) -> list[str]:
    actions = []
    if not os.path.isdir(CHROMA):
        return actions

    for old_name, new_name in CHROMA_RENAMES.items():
        old_path = os.path.join(CHROMA, old_name)
        new_path = os.path.join(CHROMA, new_name)
        if not os.path.isdir(old_path):
            continue
        if os.path.isdir(new_path):
            actions.append(f"chroma 跳过(目标已存在): {old_name} → {new_name}")
            if apply:
                shutil.rmtree(old_path, ignore_errors=True)
        else:
            actions.append(f"chroma 重命名: {old_name} → {new_name}")
            if apply:
                shutil.move(old_path, new_path)
    return actions


def main():
    parser = argparse.ArgumentParser(description="清理 OCR 误识别好友脏数据")
    parser.add_argument("--dry-run", action="store_true", help="仅预览")
    parser.add_argument("--apply", action="store_true", help="执行清理")
    args = parser.parse_args()

    if not args.apply:
        args.dry_run = True

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("=== 身份脏数据清理 [%s] ===", mode)

    all_actions: list[str] = []
    all_actions.extend(cleanup_name_map(args.apply))
    all_actions.extend(cleanup_friends(args.apply))
    all_actions.extend(cleanup_chat_tracker(args.apply))
    all_actions.extend(cleanup_chroma(args.apply))

    if not all_actions:
        logger.info("无需清理")
    else:
        for line in all_actions:
            logger.info("  %s", line)

    logger.info("=== 完成: %d 项 ===", len(all_actions))
    if args.dry_run and not args.apply:
        logger.info("使用 --apply 执行")


if __name__ == "__main__":
    main()
