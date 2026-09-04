"""
WeChat AI Agent — 程序入口
============================

启动即运行: 自动监听微信 → AI回复 → 自动发送

用法:
  python main.py              # 安全预览模式（只生成，不发送）
  python main.py --send        # 明确启用自动发送
  python main.py --interval 5  # 每5秒轮询一次

按 Ctrl+C 停止
"""

import sys
import argparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    def positive_interval(value: str) -> float:
        number = float(value)
        if not 0.2 <= number <= 3600:
            raise argparse.ArgumentTypeError("轮询间隔必须在 0.2 到 3600 秒之间")
        return number

    parser = argparse.ArgumentParser(description="WeChat AI Agent")
    parser.add_argument("--send", action="store_true", help="明确启用自动发送")
    parser.add_argument("--no-send", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--interval", type=positive_interval, default=2.0)
    args = parser.parse_args()
    auto_send = args.send and not args.no_send

    # 启动
    from system.runner import AgentRunner

    runner = AgentRunner(auto_send=auto_send, listen_interval=args.interval)
    runner.start()


if __name__ == "__main__":
    main()
