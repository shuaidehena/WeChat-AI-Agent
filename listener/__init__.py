"""
消息监听模块
负责实时监听微信新消息，含去重机制与按好友游标追踪
"""

__all__ = ["ChatTracker", "MessageListener", "MessageDeduplicator"]


def __getattr__(name):
    """延迟导入，避免运行子模块测试时包初始化重复加载。"""
    if name == "ChatTracker":
        from listener.chat_tracker import ChatTracker
        return ChatTracker
    if name == "MessageListener":
        from listener.message_listener import MessageListener
        return MessageListener
    if name == "MessageDeduplicator":
        from listener.deduplicator import MessageDeduplicator
        return MessageDeduplicator
    raise AttributeError(name)
