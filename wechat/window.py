"""
微信窗口管理模块
负责检测、激活微信窗口，以及获取 UI 控件结构
"""

import sys
import pygetwindow as gw
from pywinauto import Desktop

# 修复 Windows 终端 GBK 编码问题，避免特殊字符导致崩溃
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class WeChatWindow:
    """微信窗口管理器

    使用 Windows UI Automation (UIA) 接口操作微信窗口，
    不涉及任何 hook、注入或协议逆向。
    """

    # 微信窗口标题关键词（支持中文/英文微信）
    WECHAT_KEYWORDS = ["微信", "WeChat"]

    def __init__(self, window_title: str = "微信"):
        """
        初始化微信窗口管理器

        Args:
            window_title: 微信窗口标题关键词，默认 "微信"
        """
        self.window_title = window_title
        self._window = None          # pygetwindow 窗口对象
        self._uia_window = None      # pywinauto UIA 窗口对象

    def _is_wechat_window(self, title: str) -> bool:
        """
        判断窗口标题是否为微信窗口

        避免误匹配到包含 "WeChat" 的开发工具窗口
        （如 "WeChat-AI-Agent"、VSCode、终端等）。

        Args:
            title: 窗口标题

        Returns:
            bool: 是否为微信窗口
        """
        # 开发工具黑名单：这些窗口可能包含 "WeChat" 但不是微信
        DEV_KEYWORDS = [
            "Visual Studio Code", "VS Code", "Visual Studio",
            "Terminal", "终端", "PowerShell", "Cmd",
            "Chrome", "Edge", "Firefox",
        ]

        # 中文版微信：标题为 "微信" 或以 "微信" 开头
        if title == "微信" or title.startswith("微信"):
            return True

        # 英文版微信：标题为 "WeChat" 或以 "WeChat" 开头
        # 但要排除 "WeChat-AI-Agent" 这类项目名称
        if title == "WeChat" or title.startswith("WeChat "):
            return True

        # 如果标题包含 "WeChat"（如 "WeChat (3.9.9)"），排除开发工具
        if "WeChat" in title:
            for dev_kw in DEV_KEYWORDS:
                if dev_kw in title:
                    return False
            # 进一步检查：微信窗口标题通常较短
            if len(title) <= 30:
                return True

        return False

    def find(self) -> bool:
        """
        检测当前运行中的微信窗口，列出所有窗口标题。

        遍历所有可见窗口，匹配包含 "微信" 或 "WeChat" 的标题。
        找到后将窗口对象缓存到 self._window。

        Returns:
            bool: 是否找到微信窗口
        """
        print("\n" + "=" * 60)
        print("正在检测所有运行中的窗口...")
        print("=" * 60)

        # 获取所有窗口并打印标题
        all_windows = gw.getAllWindows()
        found_wechat = False

        for i, win in enumerate(all_windows):
            title = win.title.strip()
            if title:  # 只输出有标题的窗口
                # 过滤不可打印字符，避免编码崩溃
                safe_title = title.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                print(f"  [{i}] {safe_title}")
                # 检查是否是微信窗口
                if not found_wechat and self._is_wechat_window(title):
                    self._window = win
                    found_wechat = True

        print("=" * 60)

        if found_wechat:
            print(f"✅ 检测到微信窗口: \"{self._window.title}\"")
        else:
            print("❌ 未检测到微信，请启动微信后再运行")
            # 列出可能的窗口供排查
            print("\n提示: 请确认微信窗口标题包含 '微信' 或 'WeChat'")
            print("如果微信是英文版，请使用: WeChatWindow(window_title='WeChat')")

        return found_wechat

    # ========== 窗口激活 ==========

    def activate(self) -> bool:
        """
        激活微信窗口（置于前台）

        需要先调用 find() 找到窗口。

        Returns:
            bool: 是否成功激活
        """
        if self._window is None:
            print("❌ 请先调用 find() 找到微信窗口")
            return False

        try:
            # 如果窗口最小化，先恢复
            if self._window.isMinimized:
                self._window.restore()
            self._window.activate()
            print(f"✅ 已激活微信窗口: \"{self._window.title}\"")
            return True
        except Exception as e:
            print(f"❌ 激活窗口失败: {e}")
            return False

    # ========== UI 控件树 ==========

    def dump_controls(self, max_depth: int = 3) -> None:
        """
        打印微信窗口的 UI Automation 控件树。

        使用 pywinauto Desktop(backend="uia") 获取控件结构，
        帮助开发者了解微信的 UI 布局，定位输入框、消息区域等控件。

        Args:
            max_depth: 控件树最大打印深度，默认 3 层
        """
        if self._window is None:
            print("❌ 请先调用 find() 找到微信窗口")
            return

        print("\n" + "=" * 60)
        print(f"正在获取微信 UI 控件树...")
        print("=" * 60)

        try:
            # 使用 UIA backend 连接到微信窗口
            desktop = Desktop(backend="uia")
            wechat_uia = desktop.window(title=self._window.title)

            # 等待窗口就绪
            wechat_uia.wait("exists", timeout=5)

            # 递归打印控件树
            self._print_control_tree(wechat_uia, depth=0, max_depth=max_depth)

            self._uia_window = wechat_uia

        except Exception as e:
            print(f"❌ 获取控件树失败: {e}")
            print("可能原因:")
            print("  1. 微信窗口权限不足（尝试以管理员运行）")
            print("  2. 微信版本过旧，不支持 UIA")
            print("  3. 微信使用了自定义渲染，控件树可能为空")

        print("=" * 60)

    def _print_control_tree(self, element, depth: int, max_depth: int):
        """
        递归打印控件树

        Args:
            element: pywinauto 控件元素
            depth: 当前深度
            max_depth: 最大深度
        """
        if depth > max_depth:
            return

        try:
            # 获取控件基本信息
            ctrl_type = element.element_info.control_type or "Unknown"
            name = element.element_info.name or ""
            class_name = element.element_info.class_name or ""
            automation_id = element.element_info.automation_id or ""

            # 缩进表示层级
            indent = "  " * depth

            # 构建控件描述
            parts = [f"[{ctrl_type}]"]
            if name:
                parts.append(f"name='{name}'")
            if automation_id:
                parts.append(f"id='{automation_id}'")
            if class_name:
                parts.append(f"class='{class_name}'")

            print(f"{indent}{' '.join(parts)}")

            # 递归打印子控件
            children = element.children()
            for child in children:
                self._print_control_tree(child, depth + 1, max_depth)

        except Exception:
            # 某些控件可能无法访问，跳过
            pass

    # ========== 窗口坐标 ==========

    def get_rectangle(self) -> dict:
        """
        获取微信窗口的屏幕坐标

        需要先调用 find() 找到窗口。

        Returns:
            dict: {
                "left": 窗口左上角 X 坐标,
                "top": 窗口左上角 Y 坐标,
                "right": 窗口右下角 X 坐标,
                "bottom": 窗口右下角 Y 坐标,
                "width": 窗口宽度,
                "height": 窗口高度,
            }
            如果窗口未找到，所有值为 0
        """
        if self._window is None:
            # 尝试静默查找
            if not self.is_running():
                print("❌ 请先调用 find() 找到微信窗口")
                return {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}

        try:
            # 确保窗口不是最小化状态（否则坐标可能不准确）
            if self._window.isMinimized:
                self._window.restore()

            left = self._window.left
            top = self._window.top
            right = self._window.right
            bottom = self._window.bottom
            width = self._window.width
            height = self._window.height

            print(f"📐 微信窗口坐标:")
            print(f"   left={left}, top={top}, right={right}, bottom={bottom}")
            print(f"   尺寸: {width} x {height}")

            return {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": width,
                "height": height,
            }
        except Exception as e:
            print(f"❌ 获取窗口坐标失败: {e}")
            return {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}

    # ========== 工具方法 ==========

    def is_running(self) -> bool:
        """检查微信是否在运行（不打印详细信息）"""
        for win in gw.getAllWindows():
            title = (win.title or "").strip()
            if title and self._is_wechat_window(title):
                self._window = win
                return True
        return False

    def get_uia_window(self):
        """
        获取 pywinauto UIA 窗口对象，供 sender 等模块使用

        Returns:
            pywinauto 窗口对象，未初始化返回 None
        """
        if self._uia_window is None:
            desktop = Desktop(backend="uia")
            self._uia_window = desktop.window(title=self._window.title)
            self._uia_window.wait("exists", timeout=5)
        return self._uia_window


# ========== 快速测试入口 ==========

if __name__ == "__main__":
    """直接运行此文件可以测试窗口检测功能"""
    wechat = WeChatWindow()

    # Step 3: 检测微信窗口
    if wechat.find():
        # Step 3: 激活微信窗口
        wechat.activate()

        # Step 4: 打印控件树
        wechat.dump_controls(max_depth=2)
    else:
        print("\n请启动微信后重试。")
