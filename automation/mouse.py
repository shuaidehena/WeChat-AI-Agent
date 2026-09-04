"""
鼠标坐标调试工具
用于确定微信聊天区域坐标，辅助配置 CHAT_REGION
"""

import time
import pyautogui


def track_mouse():
    """
    实时显示当前鼠标位置。

    运行方式：
        python automation/mouse.py

    用法：
        1. 运行此脚本
        2. 将鼠标移动到微信聊天区域的左上角
        3. 记录输出的 (x, y) 坐标
        4. 将鼠标移动到聊天区域右下角
        5. 记录输出的 (x, y) 坐标
        6. 将坐标填入 config/settings.py 的 CHAT_REGION
        7. 按 Ctrl+C 退出
    """
    print("=" * 50)
    print("  鼠标坐标跟踪器")
    print("=" * 50)
    print()
    print("用法:")
    print("  1. 将鼠标移到聊天区域 → 左上角 → 记录坐标")
    print("  2. 将鼠标移到聊天区域 → 右下角 → 记录坐标")
    print("  3. 填入 config/settings.py 的 CHAT_REGION")
    print()
    print("按 Ctrl+C 退出")
    print("-" * 50)

    try:
        last_pos = None
        while True:
            x, y = pyautogui.position()
            # 只在位置变化时输出，避免刷屏
            if (x, y) != last_pos:
                print(f"  鼠标位置: x={x:4d}  y={y:4d}", end="\r")
                last_pos = (x, y)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print(f"\n\n✅ 最后位置: x={last_pos[0]}, y={last_pos[1]}")


if __name__ == "__main__":
    track_mouse()
