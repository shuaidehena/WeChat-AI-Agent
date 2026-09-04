"""
微信聊天区域手动选择工具
========================

功能：
  1. 截取当前微信窗口 → 显示在窗口中
  2. 鼠标拖动选择矩形区域（聊天消息区域）
  3. 自动保存坐标为 config/chat_region.json
  4. 后续截图模块自动读取该配置

用法：
  python tools/region_selector.py

操作：
  - 鼠标拖动：选择区域（红色矩形框）
  - 重新拖动：更新选择
  - 按 Enter 键：确认保存并退出
  - 按 Esc 键：取消退出
"""

import sys
import os
import json
import tkinter as tk
from PIL import Image, ImageTk

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wechat.window import WeChatWindow
from wechat.screenshot import ScreenCapture
from utils.atomic_io import write_json_atomic


class RegionSelector:
    """区域选择器 — 在微信截图上拖动选择聊天区域"""

    def __init__(self, image: Image.Image, save_path: str):
        """
        Args:
            image: 微信窗口的完整截图 (PIL Image)
            save_path: 坐标保存路径
        """
        self.image = image
        self.save_path = save_path

        # 选择状态
        self.start_x = None
        self.start_y = None
        self.current_rect = None   # canvas 上的矩形 id
        self.selection = None       # (x1, y1, x2, y2)

        # 创建窗口
        self.root = tk.Tk()
        self.root.title("微信聊天区域选择器 — 拖动选择后按 Enter 确认")
        self.root.resizable(False, False)

        # 窗口居中
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # 限制窗口不超过屏幕
        w = min(image.width, screen_w - 100)
        h = min(image.height, screen_h - 100)
        self.root.geometry(f"{w}x{h}+{(screen_w-w)//2}+{(screen_h-h)//2}")

        # 缩放图片以适应窗口
        self.scale_x = image.width / w
        self.scale_y = image.height / h
        self.display_image = image.resize((w, h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.display_image)

        # Canvas
        self.canvas = tk.Canvas(self.root, width=w, height=h, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

        # 提示标签
        self.label = tk.Label(
            self.root,
            text="🖱 拖动鼠标选择聊天区域  |  Enter = 确认保存  |  Esc = 取消",
            font=("Microsoft YaHei", 11),
            pady=8,
        )
        self.label.pack()

        # 绑定事件
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Return>", self._on_confirm)
        self.root.bind("<Escape>", self._on_cancel)

    # ========== 鼠标事件 ==========

    def _on_press(self, event):
        """鼠标按下 — 开始选择"""
        self.start_x = event.x
        self.start_y = event.y
        # 删除旧矩形
        if self.current_rect:
            self.canvas.delete(self.current_rect)
            self.current_rect = None

    def _on_drag(self, event):
        """鼠标拖动 — 绘制矩形"""
        if self.start_x is None:
            return
        # 重绘矩形
        if self.current_rect:
            self.canvas.delete(self.current_rect)
        self.current_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline="red", width=3, dash=(8, 4),
        )

    def _on_release(self, event):
        """鼠标释放 — 完成选择"""
        if self.start_x is None:
            return
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        # 转换回原始图片坐标
        self.selection = (
            int(x1 * self.scale_x),
            int(y1 * self.scale_y),
            int(x2 * self.scale_x),
            int(y2 * self.scale_y),
        )

        w = self.selection[2] - self.selection[0]
        h = self.selection[3] - self.selection[1]
        self.label.config(
            text=f"✅ 已选择区域: left={self.selection[0]}, top={self.selection[1]}, "
                 f"right={self.selection[2]}, bottom={self.selection[3]}  "
                 f"({w}x{h})  |  Enter 确认保存  |  重新拖动可修改"
        )
        self.start_x = None

    # ========== 确认 / 取消 ==========

    def _on_confirm(self, event=None):
        """Enter — 保存坐标并退出"""
        if self.selection is None:
            self.label.config(text="⚠️ 请先拖动鼠标选择区域！")
            return

        # 保存配置
        config = {
            "left": self.selection[0],
            "top": self.selection[1],
            "right": self.selection[2],
            "bottom": self.selection[3],
            "description": "聊天消息区域坐标（相对于微信窗口左上角）",
            "window_size": f"{self.image.width}x{self.image.height}",
        }

        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        write_json_atomic(self.save_path, config)

        print(f"\n✅ 坐标已保存到: {self.save_path}")
        print(f"   left={config['left']}, top={config['top']}, "
              f"right={config['right']}, bottom={config['bottom']}")
        print(f"   区域尺寸: {config['right']-config['left']}x{config['bottom']-config['top']}")
        self.root.destroy()

    def _on_cancel(self, event=None):
        """Esc — 取消"""
        print("\n❌ 已取消")
        self.root.destroy()

    # ========== 运行 ==========

    def run(self):
        """启动选择器窗口"""
        self.root.mainloop()


def main():
    """主函数"""
    print("=" * 60)
    print("  微信聊天区域选择器")
    print("=" * 60)
    print()

    # 1. 找微信
    wechat = WeChatWindow()
    if not wechat.find():
        print("❌ 请先启动微信！")
        return
    wechat.activate()

    # 2. 获取窗口坐标
    rect = wechat.get_rectangle()
    if rect["width"] == 0:
        print("❌ 无法获取微信窗口坐标")
        return

    # 3. 截取整个微信窗口
    print("\n📷 正在截取微信窗口...")
    capture = ScreenCapture()
    window_region = (rect["left"], rect["top"], rect["right"], rect["bottom"])
    image = capture.capture(window_region)
    print(f"✅ 截图完成: {image.width}x{image.height}")

    # 4. 打开选择器
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )
    save_path = os.path.join(config_dir, "chat_region.json")

    selector = RegionSelector(image, save_path)
    selector.run()


if __name__ == "__main__":
    main()
