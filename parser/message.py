"""
消息实体模块
定义结构化消息对象
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    """一条微信消息

    Attributes:
        sender:     发送者，取值 "friend" 或 "me"
        content:    消息文本内容
        x:          气泡左上角 X 坐标（相对于聊天区域）
        y:          气泡左上角 Y 坐标（相对于聊天区域）
        width:      气泡宽度（像素）
        height:     气泡高度（像素）
        confidence: OCR 识别置信度 (0~1)
        timestamp:  消息时间（暂未实现）
    """

    sender: str                    # "friend" | "me"
    content: str                   # 消息文本
    x: float                       # 左上角 X
    y: float                       # 左上角 Y
    width: float = 0.0             # 气泡宽度
    height: float = 0.0            # 气泡高度
    confidence: float = 0.0        # OCR 置信度
    timestamp: Optional[str] = None  # 时间（后续扩展）

    def __str__(self) -> str:
        """方便调试输出"""
        pos = f"({int(self.x)}, {int(self.y)})"
        return f"[{self.sender}] {self.content} @ {pos}"

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "sender": self.sender,
            "content": self.content,
            "position": {"x": int(self.x), "y": int(self.y)},
        }
