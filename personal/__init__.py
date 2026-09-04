"""
Personal Style Learning — 个人语言风格学习模块

用法:
    from personal.style_analyzer import StyleAnalyzer
    from personal.style_storage import StyleStorage

    analyzer = StyleAnalyzer()
    style = analyzer.analyze_from_history()
    StyleStorage().save(style)
"""

from personal.style_schema import PersonalStyle
from personal.style_analyzer import StyleAnalyzer
from personal.style_storage import StyleStorage
from personal.example_selector import ExampleSelector

__all__ = ["PersonalStyle", "StyleAnalyzer", "StyleStorage", "ExampleSelector"]
