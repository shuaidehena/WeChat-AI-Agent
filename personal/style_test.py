"""
Personal Style Learning 测试
执行: python -m personal.style_test
"""

import sys
import os
import tempfile
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保项目根目录在 path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from personal.style_schema import PersonalStyle
from personal.style_analyzer import StyleAnalyzer
from personal.style_storage import StyleStorage
from personal.example_selector import ExampleSelector
from agent.prompt import PromptBuilder


def test_length_analysis():
    """测试1: 长度分析"""
    msgs = [
        {"sender": "me", "text": "行啊"},
        {"sender": "me", "text": "可以没问题"},
        {"sender": "me", "text": "晚上见"},
        {"sender": "me", "text": "我也觉得"},
        {"sender": "me", "text": "到时候喊我"},
        {"sender": "me", "text": "嗯嗯好的"},
        {"sender": "me", "text": "不太行"},
        {"sender": "me", "text": "再说吧"},
        {"sender": "me", "text": "刚下课"},
        {"sender": "me", "text": "在路上了"},
    ]
    analyzer = StyleAnalyzer(use_llm=False)
    style = analyzer.analyze(msgs)
    assert style.message_count == 10, f"expected 10, got {style.message_count}"
    assert 3 < style.avg_length < 15, f"avg_length={style.avg_length}"
    assert style.sentence_style == "short", f"style={style.sentence_style}"
    print("长度分析 PASS")


def test_common_words():
    """测试2: 高频词"""
    msgs = [
        {"sender": "me", "text": "哈哈行啊"},
        {"sender": "me", "text": "可以"},
        {"sender": "me", "text": "行吧"},
        {"sender": "me", "text": "哈哈可以"},
        {"sender": "me", "text": "行了"},
    ]
    analyzer = StyleAnalyzer(use_llm=False)
    style = analyzer.analyze(msgs)
    words = set(style.common_words)
    # 至少包含「行」或「可以」相关
    assert words, f"common_words empty: {style.common_words}"
    has_key = any(w in words for w in ("行", "可以", "行啊", "哈哈"))
    assert has_key, f"common_words={style.common_words}"
    print("关键词分析 PASS")


def test_example_selection():
    """测试3: 样例提取"""
    history = [
        {"sender": "friend", "text": "晚上吃饭吗"},
        {"sender": "me", "text": "行啊几点"},
        {"sender": "friend", "text": "六点怎么样"},
        {"sender": "me", "text": "可以"},
        {"sender": "friend", "text": "明天有空吗"},
        {"sender": "me", "text": "应该有 咋了"},
    ]
    selector = ExampleSelector()
    examples = selector.select(history, avg_length=6.0, max_n=5)
    assert len(examples) >= 1, f"examples={examples}"
    assert "question" in examples[0] and "answer" in examples[0]
    # 应包含吃饭相关样例
    has_dinner = any("吃饭" in e["question"] for e in examples)
    assert has_dinner, f"examples={examples}"
    print("样例生成 PASS")


def test_prompt_privacy_boundary():
    """测试4: Prompt 隐私边界"""
    style = PersonalStyle(
        avg_length=8.0,
        sentence_style="short",
        tone=["随意", "直接"],
        common_words=["行", "可以", "哈哈"],
        emoji_usage=0.05,
        punctuation_style="很少用句号",
        reply_patterns=["短回复", "常用语气词"],
        examples=[
            {"question": "晚上吃饭吗", "answer": "行啊几点"},
            {"question": "在吗", "answer": "在 咋了"},
        ],
        message_count=50,
    )

    class M:
        def __init__(self, s, c):
            self.sender, self.content = s, c

    prompt = PromptBuilder().build(
        message=M("friend", "晚上吃饭吗"),
        profile={"name": "小明"},
        personal_style=style,
    )

    assert "我的聊天风格" in prompt, "缺少【我的聊天风格】"
    assert "行啊几点" not in prompt, "跨聊天原话样例不应进入 Prompt"
    assert "短回复" in prompt or "随意" in prompt
    assert "晚上吃饭吗" in prompt
    print("Prompt接入 PASS")


def test_reply_style_prompt():
    """测试5: 回复风格约束（检查 Prompt 是否引导短回复）"""
    style = PersonalStyle(
        avg_length=6.0,
        sentence_style="short",
        tone=["随意"],
        common_words=["行", "可以"],
        reply_patterns=["短回复"],
        examples=[{"question": "晚上吃饭吗", "answer": "行啊几点"}],
        message_count=20,
    )

    class M:
        def __init__(self, s, c):
            self.sender, self.content = s, c

    prompt = PromptBuilder().build(
        message=M("friend", "晚上吃饭吗"),
        profile={"name": "小明"},
        personal_style=style,
    )

    # 不应引导正式回复
    assert "您好" not in prompt or "禁止" in prompt or "不要" in prompt
    assert "行啊几点" not in prompt
    assert "短" in prompt or "6" in prompt or "6.0" in prompt
    assert "<current_message>" in prompt
    print("回复风格 PASS")


def test_storage_roundtrip():
    """额外: 持久化往返"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "my_style.json")
        storage = StyleStorage(filepath=path)
        style = PersonalStyle(
            avg_length=8.5,
            tone=["随意"],
            common_words=["行", "哈哈"],
            message_count=10,
        )
        storage.save(style)
        loaded = storage.load()
        assert loaded.avg_length == 8.5
        assert loaded.common_words == ["行", "哈哈"]
    print("持久化 PASS")


def test_update_style_incremental():
    """额外: 增量更新"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "my_style.json")
        storage = StyleStorage(filepath=path)
        analyzer = StyleAnalyzer(storage=storage, use_llm=False)

        analyzer.update_style({"sender": "me", "text": "行啊"})
        analyzer.update_style({"sender": "me", "text": "可以没问题"})
        style = storage.load()
        assert style.message_count == 2
        assert style.avg_length > 0
    print("增量更新 PASS")


def main():
    print("===== Personal Style Test =====\n")
    test_length_analysis()
    test_common_words()
    test_example_selection()
    test_prompt_privacy_boundary()
    test_reply_style_prompt()
    test_storage_roundtrip()
    test_update_style_incremental()
    print("\n===== 全部 PASS =====")


if __name__ == "__main__":
    main()
