# agent/context/compactor.py
"""消息压缩器"""

from __future__ import annotations


class MessageCompactor:
    """消息压缩器 - 针对不同类型的消息进行智能压缩"""

    def compress_generic(self, text: str, max_lines: int = 100) -> str:
        """
        通用压缩策略：保留头尾

        Args:
            text: 原始文本
            max_lines: 最大保留行数

        Returns:
            压缩后的文本
        """
        lines = text.split("\n")

        if len(lines) <= max_lines:
            return text

        # 保留前后各一半
        head_lines = max_lines // 2
        tail_lines = max_lines - head_lines

        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])

        truncated_count = len(lines) - max_lines
        separator = f"\n... [已截断 {truncated_count} 行] ...\n"

        return head + separator + tail

    def compress_sensor_data(self, text: str, max_lines: int = 50) -> str:
        """
        传感器数据压缩：保留关键信息（ERROR、WARNING）+ 头尾

        Args:
            text: 传感器日志
            max_lines: 最大保留行数

        Returns:
            压缩后的文本
        """
        lines = text.split("\n")

        if len(lines) <= max_lines:
            return text

        # 提取关键行（ERROR、WARNING、INFO）
        important_lines = []
        normal_lines = []

        for line in lines:
            if any(keyword in line for keyword in ["[ERROR]", "[WARNING]", "[FATAL]"]):
                important_lines.append(line)
            elif "[INFO]" in line:
                important_lines.append(line)
            else:
                normal_lines.append(line)

        # 保留所有关键行 + 部分普通行
        remaining_quota = max_lines - len(important_lines)

        if remaining_quota > 0:
            # 保留头尾普通行
            head_count = remaining_quota // 2
            tail_count = remaining_quota - head_count

            selected_normal = (
                normal_lines[:head_count] + normal_lines[-tail_count:]
                if len(normal_lines) > remaining_quota
                else normal_lines
            )
        else:
            selected_normal = []

        # 重新组合
        result_lines = important_lines + selected_normal

        if len(lines) > len(result_lines):
            truncated_count = len(lines) - len(result_lines)
            result_lines.append(f"... [已截断 {truncated_count} 行数据] ...")

        return "\n".join(result_lines)

    def compress_build_log(self, text: str, max_lines: int = 100) -> str:
        """
        编译日志压缩：保留错误和警告

        Args:
            text: 编译日志
            max_lines: 最大保留行数

        Returns:
            压缩后的文本
        """
        lines = text.split("\n")

        if len(lines) <= max_lines:
            return text

        # 提取错误和警告行
        error_lines = []
        warning_lines = []
        normal_lines = []

        for line in lines:
            if "error:" in line.lower() or "fatal:" in line.lower():
                error_lines.append(line)
            elif "warning:" in line.lower():
                warning_lines.append(line)
            else:
                normal_lines.append(line)

        # 优先保留错误和警告
        important_lines = error_lines + warning_lines
        remaining_quota = max_lines - len(important_lines)

        if remaining_quota > 0:
            # 保留部分普通行（头尾）
            head_count = remaining_quota // 2
            tail_count = remaining_quota - head_count

            selected_normal = (
                normal_lines[:head_count] + normal_lines[-tail_count:]
                if len(normal_lines) > remaining_quota
                else normal_lines
            )
        else:
            # 配额不足，只保留错误和警告
            selected_normal = []

        # 重新组合
        result_lines = important_lines + selected_normal

        if len(lines) > len(result_lines):
            truncated_count = len(lines) - len(result_lines)
            result_lines.append(f"... [已截断 {truncated_count} 行构建日志] ...")

        return "\n".join(result_lines)

    def compress_file_content(self, text: str, max_lines: int = 200) -> str:
        """
        文件内容压缩：保留头尾代码

        Args:
            text: 文件内容
            max_lines: 最大保留行数

        Returns:
            压缩后的文本
        """
        return self.compress_generic(text, max_lines)
