"""
标题栏 / 联系人名称校验

过滤 OCR 误识别：时间戳、聊天正文片段、标点垃圾等，
避免为「昨天20:42」「我玩完了」等创建好友档案或污染 ChatTracker。
"""

from __future__ import annotations

import json
import os
import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


class TitleNameValidator:
    """微信标题栏 / 侧边栏联系人名称校验"""

    RE_PURE_TIME = re.compile(r"^(\d{1,2}:\d{2})(:\d{2})?$")
    RE_TIME_IN_TEXT = re.compile(r"\d{1,2}:\d{2}")
    RE_WEEKDAY = re.compile(r"^星期[一二三四五六日天]")
    RE_WEEKDAY_TIME = re.compile(r"星期[一二三四五六日天].*\d{1,2}:\d{2}")
    RE_RELATIVE_TIME = re.compile(r"^(昨天|今天|前天)\s*\d")
    RE_DATE_LINE = re.compile(
        r"^\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?$"
        r"|^(昨天|今天|前天)$"
    )
    RE_UNBALANCED = re.compile(r"^[）)\]】>]+|^[（(\[【<]+.*[）)\]】>]$")
    RE_MOSTLY_DIGITS = re.compile(r"^[\d\s:：./\-年月日天]+$")

    # 明显是聊天正文而非联系人名
    MESSAGE_FRAGMENTS = (
        "我玩完了", "我们也玩完了", "以下是新消息", "以上是打招呼的内容",
        "复历史", "检测/激活", "环境要求", "功能列表",
    )

    # 不应自动回复的系统/服务号（可存在于 friends.json，但不建档、不扫描）
    NO_AUTO_REPLY = frozenset({
        "微信支付", "文件传输助手", "中国建设银行", "中南大学TS", "中南大学ITS",
    })

    def __init__(self, storage_dir: str = "storage"):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.join(base, storage_dir)
        self.storage_dir = storage_dir
        self._known_names: set[str] = set()
        self._reload_known()

    def _reload_known(self):
        names: set[str] = set()
        map_path = os.path.join(self.storage_dir, "name_map.json")
        friends_path = os.path.join(self.storage_dir, "friends.json")

        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
                names.update(str(k).strip() for k in mapping if str(k).strip())
            except (json.JSONDecodeError, OSError):
                pass

        if os.path.exists(friends_path):
            try:
                with open(friends_path, "r", encoding="utf-8") as f:
                    friends = json.load(f)
                for name, info in friends.items():
                    n = str(name).strip()
                    if n:
                        names.add(n)
                    if isinstance(info, dict):
                        alt = str(info.get("name", "")).strip()
                        if alt:
                            names.add(alt)
            except (json.JSONDecodeError, OSError):
                pass

        self._known_names = names

    def known_names(self) -> set[str]:
        return set(self._known_names)

    def is_known(self, name: str) -> bool:
        return name.strip() in self._known_names

    def is_auto_reply_allowed(self, name: str) -> bool:
        """是否允许对该联系人自动回复"""
        name = (name or "").strip()
        if not name:
            return False
        if name in self.NO_AUTO_REPLY:
            return False
        return self.validate(name)[0]

    def validate(self, name: str) -> tuple[bool, str]:
        """
        校验是否为可信的联系人显示名。

        Returns:
            (is_valid, reason)
        """
        name = (name or "").strip()
        if not name:
            return False, "empty"

        if len(name) < 2:
            return False, "too_short"
        if len(name) > 24:
            return False, "too_long"

        for frag in self.MESSAGE_FRAGMENTS:
            if frag in name:
                return False, "message_fragment"

        if self.RE_PURE_TIME.match(name):
            return False, "time_only"
        if self.RE_RELATIVE_TIME.match(name):
            return False, "relative_time"
        if self.RE_WEEKDAY_TIME.search(name):
            return False, "weekday_time"
        if self.RE_WEEKDAY.match(name) and self.RE_TIME_IN_TEXT.search(name):
            return False, "weekday_time"
        if self.RE_DATE_LINE.match(name):
            return False, "date_line"
        if self.RE_MOSTLY_DIGITS.match(name):
            return False, "mostly_digits"

        # 「昨天20:42」「星期天22:46」
        if re.match(r"^(昨天|今天|前天)", name) and self.RE_TIME_IN_TEXT.search(name):
            return False, "relative_time"
        if name.startswith("星期") and (
            self.RE_TIME_IN_TEXT.search(name) or re.search(r"\d{1,2}", name)
        ):
            return False, "weekday_time"

        # 括号/标点垃圾，如「复历史）」
        if self.RE_UNBALANCED.match(name):
            return False, "punctuation_garbage"
        if name.count("）") + name.count(")") != name.count("（") + name.count("("):
            if re.search(r"[）)]$", name) and not re.search(r"[（(]", name):
                return False, "unbalanced_bracket"

        # 标题栏候选应含中文，或是已注册的 ASCII 昵称
        if not _has_cjk(name):
            if not re.match(r"^[A-Za-z0-9_\-\(\)（）\u4e00-\u9fff\s]{2,24}$", name):
                return False, "invalid_chars"
            # 纯 ASCII 且无已知映射 → 可能是 OCR 英文垃圾
            if not name.replace(" ", "").isalnum():
                return False, "ascii_noise"

        # 过长且无中文姓名特征：更像消息正文
        if len(name) >= 8 and _has_cjk(name):
            verb_hints = ("了", "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "哈")
            if name.endswith(verb_hints) and not re.search(
                r"[\u4e00-\u9fff]{2,4}$", name[:6]
            ):
                return False, "looks_like_message"

        if name in self._known_names:
            return True, "known"

        return True, "ok"

    def pick_best(self, candidates: list[str]) -> str:
        """从 OCR 候选中选择最可信的联系人名"""
        self._reload_known()
        cleaned = []
        for raw in candidates:
            name = str(raw or "").strip()
            if not name:
                continue
            ok, _ = self.validate(name)
            if ok:
                cleaned.append(name)
        if not cleaned:
            return ""
        return max(cleaned, key=len)


# 模块级单例，供 listener / resolver 快速使用
_default_validator: TitleNameValidator | None = None


def get_validator(storage_dir: str = "storage") -> TitleNameValidator:
    global _default_validator
    if _default_validator is None:
        _default_validator = TitleNameValidator(storage_dir)
    return _default_validator


def validate_title_name(name: str, storage_dir: str = "storage") -> tuple[bool, str]:
    return get_validator(storage_dir).validate(name)


def pick_valid_title(candidates: list[str], storage_dir: str = "storage") -> str:
    return get_validator(storage_dir).pick_best(candidates)


if __name__ == "__main__":
    v = TitleNameValidator()

    cases = [
        ("杨春辉", True),
        ("张玉萍", True),
        ("昨天20:42", False),
        ("星期天22:46", False),
        ("我玩完了", False),
        ("复历史）", False),
        ("19:52", False),
        ("铁三鱼(3)", True),
        ("以下是新消息", False),
    ]
    print("TitleNameValidator 测试")
    for name, expected in cases:
        ok, reason = v.validate(name)
        status = "✅" if ok == expected else "❌"
        print(f"  {status} {name!r} -> {ok} ({reason})")
        assert ok == expected, name
    print("全部通过")
