"""
OCR 文字识别模块
使用 RapidOCR（基于 ONNX Runtime）识别聊天截图中的文字

依赖: rapidocr-onnxruntime
优点: 无需 PaddlePaddle/Torch，轻量级，纯 ONNX 推理
"""

import sys
from PIL import Image
from typing import Optional

# 修复 Windows 终端 GBK 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class OCRReader:
    """OCR 文字识别器

    使用 RapidOCR 识别图片中的中文文字。
    基于 ONNX Runtime，无需安装 PaddlePaddle 或 PyTorch。

    当前阶段只输出文字列表，不解析发送者/时间等结构化信息。
    """

    def __init__(self):
        """初始化 OCR 识别器"""
        self._ocr = None  # 懒加载

    @property
    def ocr(self):
        """懒加载 RapidOCR 实例"""
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                print("⏳ 正在加载 RapidOCR 模型（首次加载需要下载模型）...")
                self._ocr = RapidOCR()
                print("✅ RapidOCR 模型加载完成")
            except ImportError:
                raise ImportError(
                    "RapidOCR 未安装，请运行: pip install rapidocr-onnxruntime"
                )
            except Exception as e:
                raise RuntimeError(f"RapidOCR 初始化失败: {e}")
        return self._ocr

    def recognize(self, image_path: str) -> list[str]:
        """
        识别图片中的文字

        Args:
            image_path: 图片文件路径

        Returns:
            list[str]: 识别出的文字列表，按从上到下、从左到右排列

        Example:
            >>> reader = OCRReader()
            >>> texts = reader.recognize("debug/chat_area.png")
            >>> print(texts)
            ['张三', '最近怎么样啊', '挺好的，你呢']
        """
        print(f"\n🔍 正在识别图片文字: {image_path}")

        try:
            # 调用 RapidOCR
            result, _ = self.ocr(image_path)

            # 解析结果
            texts = self._extract_texts(result)
            print(f"✅ 识别完成，共 {len(texts)} 段文字")

            for i, text in enumerate(texts):
                print(f"  [{i+1}] {text}")

            return texts

        except Exception as e:
            print(f"❌ OCR 识别失败: {e}")
            return []

    def recognize_image(self, image: Image.Image) -> list[str]:
        """
        识别 PIL Image 对象中的文字

        Args:
            image: PIL Image 对象

        Returns:
            list[str]: 识别出的文字列表
        """
        import numpy as np

        print(f"\n🔍 正在识别图片文字 (PIL Image, {image.size})")

        try:
            img_array = np.array(image)
            result, _ = self.ocr(img_array)

            texts = self._extract_texts(result)
            print(f"✅ 识别完成，共 {len(texts)} 段文字")

            for i, text in enumerate(texts):
                print(f"  [{i+1}] {text}")

            return texts

        except Exception as e:
            print(f"❌ OCR 识别失败: {e}")
            return []

    def recognize_with_boxes(self, image_path: str) -> list:
        """
        识别图片中的文字，返回包含坐标的原始数据

        RapidOCR 原始格式:
        [
            [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "文字", 置信度],
            ...
        ]

        Args:
            image_path: 图片文件路径

        Returns:
            list: RapidOCR 原始结果（含坐标和置信度）
        """
        try:
            result, _ = self.ocr(image_path)
            return result if result else []
        except Exception as e:
            print(f"❌ OCR 识别失败: {e}")
            return []

    def _extract_texts(self, ocr_result) -> list[str]:
        """
        从 RapidOCR 结果中提取文字列表

        RapidOCR 返回格式:
        [
            [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],  # 四点坐标
            "文字内容",                           # 识别的文字
            置信度                                 # 置信度分数
        ]
        或返回 (result, elapse) 元组。

        Args:
            ocr_result: RapidOCR 识别结果（list 或 None）

        Returns:
            list[str]: 文字列表
        """
        texts = []

        if ocr_result is None:
            return texts

        # 按 Y 坐标排序（从上到下），方便阅读
        if isinstance(ocr_result, list) and len(ocr_result) > 0:
            # 每条记录: [box, text, score]
            valid_items = []
            for item in ocr_result:
                if not item or len(item) < 2:
                    continue
                # item 格式: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "文字", score
                box = item[0]
                text = item[1]
                # 取左上角 Y 坐标作为排序依据
                y = box[0][1] if box and len(box) > 0 else 0
                valid_items.append((y, text))

            # 按 Y 坐标排序
            valid_items.sort(key=lambda x: x[0])

            for y, text in valid_items:
                text = str(text).strip()
                if text:
                    texts.append(text)

        return texts


# ========== 快速测试入口 ==========

if __name__ == "__main__":
    """独立测试 OCR 识别"""
    import sys

    test_image = "debug/chat_area.png"
    if len(sys.argv) > 1:
        test_image = sys.argv[1]

    print(f"测试图片: {test_image}")
    print("=" * 50)

    reader = OCRReader()
    texts = reader.recognize(test_image)

    print("\n" + "=" * 50)
    print("识别结果:")
    print("-" * 50)
    for i, t in enumerate(texts):
        print(f"  [{i+1}] {t}")
    print("-" * 50)
    print(f"共识别 {len(texts)} 段文字")
