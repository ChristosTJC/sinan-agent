# agent/context/manager.py
"""上下文管理器"""

from __future__ import annotations

from typing import Any, Literal, Optional


class ContextManager:
    """上下文管理器 - 负责对话历史的压缩和管理"""

    def __init__(
        self,
        max_tokens: int = 100000,
        window_size: int = 20,
        compression_strategy: Literal["sliding_window", "summarize"] = "sliding_window",
    ):
        """
        初始化上下文管理器

        Args:
            max_tokens: 最大 token 数
            window_size: 滑动窗口大小（保留最近 N 轮对话）
            compression_strategy: 压缩策略（sliding_window 或 summarize）
        """
        self.max_tokens = max_tokens
        self.window_size = window_size
        self.compression_strategy = compression_strategy
        self.messages: list[dict[str, Any]] = []

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """添加消息"""
        message = {"role": role, "content": content, **kwargs}
        self.messages.append(message)

        # 自动压缩
        self._compress_if_needed()

    def get_messages(self) -> list[dict[str, Any]]:
        """获取所有消息"""
        return self.messages.copy()

    def clear(self) -> None:
        """清空上下文"""
        self.messages.clear()

    def estimate_tokens(self) -> int:
        """估算 token 数（简单估算：1 token ≈ 1 字符）"""
        total = 0
        for msg in self.messages:
            content = msg.get("content", "")
            total += len(str(content))
        return total

    def _compress_if_needed(self) -> None:
        """根据策略压缩上下文"""
        if self.compression_strategy == "sliding_window":
            self._sliding_window_compress()
        elif self.compression_strategy == "summarize":
            # 暂不实现 LLM 摘要压缩
            pass

    def _sliding_window_compress(self) -> None:
        """滑动窗口压缩：保留系统消息 + 最近 N 轮对话"""
        # 分离系统消息和对话消息
        system_messages = [msg for msg in self.messages if msg["role"] == "system"]
        conversation_messages = [msg for msg in self.messages if msg["role"] != "system"]

        # 计算轮数（user + assistant = 1 轮）
        # 简单策略：保留最近 window_size * 2 条消息
        max_conversation_messages = self.window_size * 2

        if len(conversation_messages) > max_conversation_messages:
            # 只保留最近的消息
            conversation_messages = conversation_messages[-max_conversation_messages:]

        # 重新组合：系统消息 + 对话消息
        self.messages = system_messages + conversation_messages

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """压缩消息列表（外部调用接口）

        Args:
            messages: 原始消息列表

        Returns:
            压缩后的消息列表
        """
        # 分离系统消息和对话消息
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        conversation_messages = [msg for msg in messages if msg.get("role") != "system"]

        # 估算 token 数
        total_tokens = sum(len(str(msg.get("content", ""))) // 4 for msg in messages)

        # 如果超过阈值，执行压缩
        if total_tokens > self.max_tokens or len(conversation_messages) > self.window_size * 2:
            max_conversation_messages = self.window_size * 2
            if len(conversation_messages) > max_conversation_messages:
                conversation_messages = conversation_messages[-max_conversation_messages:]

        # 重新组合
        return system_messages + conversation_messages

    def compress_with_summary(self, summarizer: Optional[Any] = None) -> None:
        """使用 LLM 摘要压缩（可选功能）"""
        # 预留接口，暂不实现
        pass
