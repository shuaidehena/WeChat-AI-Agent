"""
全局配置文件
所有可调整参数集中管理，避免硬编码

坐标获取方式：
  1. 运行 python tools/region_selector.py 可视化选择（推荐）
  2. 或运行 python automation/mouse.py 手动记录坐标

优先级: chat_region.json > 下方默认值
"""

import os
import json

# ============================================================
# 自动加载可视化选择器保存的坐标
# ============================================================

def _load_chat_region():
    """尝试从 chat_region.json 加载坐标，不存在则使用默认值"""
    config_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(config_dir, "chat_region.json")

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            values = {key: data[key] for key in ("left", "top", "right", "bottom")}
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values.values()):
                raise ValueError("坐标必须是数字")
            if values["left"] < 0 or values["top"] < 0:
                raise ValueError("left/top 不能为负数")
            if values["right"] <= values["left"] or values["bottom"] <= values["top"]:
                raise ValueError("right/bottom 必须大于 left/top")
            return values
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            print(f"坐标文件读取失败: {e}，使用默认值")

    # 默认值
    return {
        "left": 260,
        "top": 55,
        "right": 1030,
        "bottom": 500,
    }


CHAT_REGION = _load_chat_region()

# ============================================================
# 输入框区域（聊天区下方，用于点击获取焦点）
# ============================================================

INPUT_REGION = {
    "left": CHAT_REGION["left"] + 30,
    "top": CHAT_REGION["bottom"] + 15,
    "right": CHAT_REGION["right"] - 30,
    "bottom": CHAT_REGION["bottom"] + 130,
}

# ============================================================
# 标题栏区域（用于获取聊天对象名称）
# ============================================================

TITLE_REGION = {
    "left": CHAT_REGION["left"],
    "top": 0,
    "right": CHAT_REGION["right"],
    "bottom": 55,
}

# ============================================================
# 截图配置
# ============================================================

SCREENSHOT_DIR = "debug"
SCREENSHOT_FILENAME = "chat_area.png"

# ============================================================
# 微信窗口配置
# ============================================================

WECHAT_WINDOW_TITLE = "微信"

# ============================================================
# 侧边栏联系人列表区域（用于检测未读消息）
# ============================================================
# left:   窗口左边缘
# top:    搜索栏下方（约50px）
# right:  聊天区域左边界（与 CHAT_REGION.left 一致）
# bottom: 窗口底部

SIDEBAR_REGION = {
    "left": 0,
    "top": 50,
    "right": CHAT_REGION["left"],
    "bottom": CHAT_REGION["bottom"] + 100,  # 比聊天区长一点
}

# 未读红点检测阈值（微信红点颜色: R很高, G/B很低，约 #FA5151）
UNREAD_RED_THRESHOLD = {
    "r_min": 150,    # R 通道最低值（放宽）
    "g_max": 100,    # G 通道最高值（放宽，因为红点中有白色数字）
    "b_max": 100,    # B 通道最高值
    "min_pixels": 3,  # 最少红色像素数（红点很小，约10px直径=~80px面积）
}
