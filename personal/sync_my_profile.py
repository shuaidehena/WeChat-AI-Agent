"""从全部 storage/history 强制更新个人画像 (my_style.json)"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from personal.history_reader import HistoryReader
from personal.style_analyzer import StyleAnalyzer


def main():
    collected = HistoryReader().collect()
    print("=" * 50)
    print("  聊天记录扫描")
    print("=" * 50)
    print(f"  文件数: {collected['files_read']}")
    print(
        f"  我的消息: {collected['unique_count']} 条 "
        f"(去重前 {collected['raw_count']})"
    )
    for fid, cnt in sorted(collected["sources"].items(), key=lambda x: -x[1]):
        print(f"    {fid}: {cnt}")

    print()
    style = StyleAnalyzer().sync_from_storage(force=True)

    print()
    print("=" * 50)
    print("  我的详细画像 (storage/personal/my_style.json)")
    print("=" * 50)
    if style.summary:
        print(f"  整体印象: {style.summary}")
    print(f"  消息样本: {style.message_count} 条")
    print(f"  句长: {style.sentence_style} (avg {style.avg_length})")
    if style.personality:
        print(f"  性格体现: {style.personality}")
    print(f"  语气: {style.tone}")
    print(f"  说话方式: {style.communication_style}")
    print(f"  常用词: {style.common_words[:8]}")
    print(f"  回复模式: {style.reply_patterns}")
    if style.topics_often_mentioned:
        print(f"  常聊话题: {style.topics_often_mentioned}")
    if style.self_description_hints:
        print(f"  身份线索: {style.self_description_hints}")
    if style.avoid_words:
        print(f"  避免使用: {style.avoid_words}")
    if style.how_to_reply:
        print(f"  回复注意: {style.how_to_reply}")
    if style.voice_samples:
        print(f"  原话样例 ({len(style.voice_samples)} 条):")
        for s in style.voice_samples[:4]:
            print(f"    - {s[:50]}")
    print(f"  更新时间: {style.updated_time}")


if __name__ == "__main__":
    main()
