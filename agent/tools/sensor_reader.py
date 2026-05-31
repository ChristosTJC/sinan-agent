"""
传感器数据读取器 —— 从串口/传感器采集数据，自动探测数据格式。

支持通过串口连接传感器设备，自动识别数据格式（NMEA-like, CSV, JSONL, key=value），
并支持数据采集、CSV 导出、统计摘要等功能。

典型传感器格式示例::

    NMEA-like:  $TEMP,25.3,HUM,62.1*CK
    CSV:        timestamp,temp,humidity\\n0.1,25.3,62.1
    JSONL:      {"ts": 0.1, "temp": 25.3, "humidity": 62.1}
    key=value:  temp=25.3 humidity=62.1
"""

import csv
import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 格式自动检测
# ---------------------------------------------------------------------------

_NMEA_PATTERN = re.compile(r"^\$[\w]+(?:,[\w.\-\s]*)*\*?[0-9A-Fa-f]*$")
_CSV_PATTERN = re.compile(r"^[\w.\-\s]+(?:,[\w.\-\s]+)+$")
_KV_PATTERN = re.compile(r"^[\w]+\s*=\s*[\w.\-]+(?:\s+[\w]+\s*=\s*[\w.\-]+)*$")
_JSON_PATTERN = re.compile(r"^\s*\{.*\}\s*$")


def auto_detect_format(line: str) -> str:
    """自动检测单行传感器数据的格式。

    检测优先级（从高到低）:
        1. NMEA-like（以 ``$`` 开头，逗号分隔，有可选校验和 ``*XX``）
        2. JSON（以 ``{`` 开头 ``}`` 结尾的合法 JSON 对象）
        3. key=value（空格分隔的 ``key=value`` 对）
        4. CSV（逗号分隔的纯数字/字符串值）
        5. binary（十六进制/二进制数据）
        6. unknown（无法归类）

    Args:
        line: 原始数据行字符串。

    Returns:
        格式标识字符串: ``"nmea"`` / ``"json"`` / ``"kv"`` / ``"csv"`` / ``"binary"`` / ``"unknown"``。
    """
    stripped = line.strip()
    if not stripped:
        return "unknown"

    # NMEA: $HEADER,val1,val2,...*CK
    if _NMEA_PATTERN.match(stripped):
        return "nmea"

    # JSON: {...}
    if _JSON_PATTERN.match(stripped):
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass

    # key=value pairs
    if _KV_PATTERN.match(stripped):
        # 进一步验证: 不能是 URL 查询字符串之类的
        parts = stripped.split("=")
        if len(parts) >= 2:
            return "kv"

    # CSV: 逗号分隔的字段
    if _CSV_PATTERN.match(stripped):
        return "csv"

    # 尝试检测是否为二进制数据（含不可见字符）
    try:
        # 检查是否包含大量控制字符
        control_count = sum(1 for ch in stripped if ord(ch) < 32 and ord(ch) not in (9, 10, 13))
        if control_count > len(stripped) * 0.3:
            return "binary"
    except Exception:
        pass

    return "unknown"


def parse_line(line: str) -> Optional[dict]:
    """解析一行传感器数据为结构化字典（独立函数版本）。

    自动检测格式并提取字段。

    Args:
        line: 原始数据行。

    Returns:
        解析后的数据字典，或 None 表示无法解析。
    """
    stripped = line.strip()
    if not stripped:
        return None

    fmt = auto_detect_format(stripped)

    if fmt == "json":
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return {"raw": stripped}

    if fmt == "csv":
        parts = stripped.split(",")
        fields = []
        for p in parts:
            p = p.strip()
            try:
                fields.append(float(p) if "." in p else int(p))
            except ValueError:
                fields.append(p)
        return {"format": "csv", "fields": fields}

    if fmt == "kv":
        result: dict = {}
        for pair in stripped.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                try:
                    result[k] = float(v) if "." in v else int(v)
                except ValueError:
                    result[k] = v
        return result if result else None

    if fmt == "nmea":
        parts = stripped.lstrip("$").rstrip(f"*{stripped.split('*')[-1]}" if "*" in stripped else "").split(",")
        return {"format": "nmea", "talker": parts[0][:2] if parts else "", "fields": parts[1:]}

    return {"raw": stripped, "format": fmt}


# ---------------------------------------------------------------------------
# SensorReader
# ---------------------------------------------------------------------------


class SensorReader:
    """传感器数据读取器 —— 串口连接的通用传感器采集工具。

    通过串口读取传感器行数据，自动探测格式并解析为结构化字典。
    支持受控采集（按样本数/间隔）、CSV 导出、统计摘要等。

    Attributes:
        port: 串口端口路径。
        baudrate: 波特率。
        timeout: 读取超时秒数。
        _monitor: 内部 SerialMonitor 实例。
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
    ) -> None:
        """初始化传感器读取器。

        Args:
            port: 串口端口路径。
            baudrate: 波特率，默认 115200。
            timeout: 读取超时秒数。
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._monitor = None

    def open(self) -> bool:
        """打开串口连接。

        Returns:
            True 表示打开成功，False 表示 pyserial 不可用或端口不存在。
        """
        # 惰性导入以避免顶层 ImportError
        from agent.tools.serial_monitor import SerialMonitor

        if self._monitor is not None and self._monitor.is_open:
            logger.debug("串口已打开: %s", self.port)
            return True

        self._monitor = SerialMonitor(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )
        return self._monitor.open()

    def close(self) -> None:
        """关闭串口连接。"""
        if self._monitor is not None:
            self._monitor.close()
            self._monitor = None

    def is_open(self) -> bool:
        """检查串口是否已打开。"""
        return self._monitor is not None and self._monitor.is_open

    # ------------------------------------------------------------------
    # 数据解析
    # ------------------------------------------------------------------

    def parse_line(self, line: str) -> Optional[dict]:
        """解析一行传感器数据为结构化字典。

        自动检测格式并提取字段。

        Args:
            line: 原始数据行。

        Returns:
            解析后的数据字典。解析失败或空行时返回 None。

            示例:
                - ``"temp=25.3 humidity=62.1"`` → ``{"temp": 25.3, "humidity": 62.1}``
                - ``"25.3,62.1,0.5"`` → ``{"field_0": 25.3, "field_1": 62.1, "field_2": 0.5}``
        """
        fmt = auto_detect_format(line)
        if fmt == "unknown":
            logger.debug("无法识别的数据格式: %s", line[:80])
            return None

        try:
            if fmt == "json":
                return json.loads(line.strip())

            elif fmt == "nmea":
                return self._parse_nmea(line)

            elif fmt == "kv":
                return self._parse_kv(line)

            elif fmt == "csv":
                return self._parse_csv(line)

            elif fmt == "binary":
                return {
                    "_format": "binary",
                    "_length": len(line),
                    "_hex": line.strip().encode("utf-8", errors="replace").hex()[:64],
                }
        except Exception as exc:
            logger.debug("数据解析异常: %s (格式=%s)", exc, fmt)
            return None

        return None

    @staticmethod
    def _parse_nmea(line: str) -> Optional[dict]:
        """解析 NMEA-like 格式数据。

        示例: ``$TEMP,25.3,HUM,62.1*3F``
        """
        stripped = line.strip()
        # 去除开头的 $ 和末尾的 *CK
        body = stripped.lstrip("$")
        checksum_sep = body.rfind("*")
        if checksum_sep > 0:
            body = body[:checksum_sep]

        fields = body.split(",")
        if len(fields) < 2:
            return None

        result: dict = {"_format": "nmea", "_header": fields[0]}

        # 将 header 与其后的值交替解析为键值对
        # 例如 TEMP,25.3,HUM,62.1 → {"TEMP": 25.3, "HUM": 62.1}
        header = fields[0]
        idx = 1
        while idx < len(fields):
            key = f"{header}_{(idx - 1) // 2 + 1}" if (len(fields) - 1) % 2 != 0 and idx == len(fields) - 1 else fields[idx] if idx + 1 < len(fields) else f"val_{(idx - 1) // 2}"
            val_str = fields[idx] if idx + 1 >= len(fields) else fields[idx + 1]

            # 如果相邻字段像键值（交替出现文字和数字），做如下尝试
            if idx + 1 < len(fields):
                key = fields[idx]
                val_str = fields[idx + 1]
                idx += 2
            else:
                val_str = fields[idx]
                key = f"val_{(idx - 1) // 2}"
                idx += 1

            # 尝试转换为数字
            try:
                if "." in val_str:
                    result[key] = float(val_str)
                else:
                    result[key] = int(val_str)
            except (ValueError, TypeError):
                result[key] = val_str

        return result

    @staticmethod
    def _parse_kv(line: str) -> Optional[dict]:
        """解析 key=value 格式数据。

        示例: ``temp=25.3 humidity=62.1 pressure=1013.25``
        """
        parts = line.strip().split()
        result: dict = {"_format": "kv"}
        for part in parts:
            if "=" not in part:
                continue
            key, val_str = part.split("=", 1)
            key = key.strip()
            val_str = val_str.strip()
            try:
                if "." in val_str:
                    result[key] = float(val_str)
                elif re.match(r"^[+-]?\d+$", val_str):
                    result[key] = int(val_str)
                else:
                    result[key] = val_str
            except (ValueError, TypeError):
                result[key] = val_str
        return result if len(result) > 1 else None

    @staticmethod
    def _parse_csv(line: str) -> Optional[dict]:
        """解析 CSV 格式数据。

        示例: ``25.3,62.1,0.5``
        """
        fields = line.strip().split(",")
        result: dict = {"_format": "csv"}
        for i, field in enumerate(fields):
            val = field.strip()
            try:
                if "." in val:
                    result[f"field_{i}"] = float(val)
                elif re.match(r"^[+-]?\d+$", val):
                    result[f"field_{i}"] = int(val)
                else:
                    result[f"field_{i}"] = val
            except (ValueError, TypeError):
                result[f"field_{i}"] = val
        return result

    # ------------------------------------------------------------------
    # 数据采集
    # ------------------------------------------------------------------

    def read_sample(self) -> Optional[dict]:
        """读取单次传感器数据样本。

        从串口读取一行并解析。会自动附加采集时间戳 ``_timestamp``。

        Returns:
            解析后的数据字典（含 ``_timestamp``），无数据返回 None。
        """
        if not self.is_open() or self._monitor is None:
            logger.warning("读取失败: 串口未打开")
            return None

        line = self._monitor.read_line()
        if line is None:
            return None

        parsed = self.parse_line(line)
        if parsed is not None:
            parsed["_timestamp"] = time.time()
            logger.debug("传感器样本: %s", {k: v for k, v in parsed.items() if not k.startswith("_")})
        return parsed

    def collect_samples(
        self,
        count: int,
        interval_sec: float = 0.1,
    ) -> list[dict]:
        """按指定数量和间隔采集传感器数据样本。

        Args:
            count: 要采集的样本数量（正整数）。
            interval_sec: 两次采样之间的间隔秒数。

        Returns:
            解析后的样本列表。串口断开或出错时可能少于 count。
        """
        if count <= 0:
            logger.warning("采集数量必须为正整数，当前 %d", count)
            return []

        if not self.is_open():
            logger.warning("采集失败: 串口未打开")
            return []

        samples: list[dict] = []
        logger.info("开始采集 %d 个样本，间隔 %0.1f 秒...", count, interval_sec)

        for i in range(count):
            if not self.is_open():
                logger.warning("采集中断: 串口已断开（已采集 %d/%d）", i, count)
                break

            sample = self.read_sample()
            if sample is not None:
                samples.append(sample)

            if i < count - 1:
                time.sleep(interval_sec)

        logger.info("采集完成: %d/%d 个样本", len(samples), count)
        return samples

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    @staticmethod
    def export_csv(samples: list[dict], filepath: str) -> bool:
        """将样本列表导出为 CSV 文件。

        自动从第一行样本中推断 CSV 列头（排除 ``_format`` 等内部字段）。
        数值精度保留 6 位小数。

        Args:
            samples: 样本列表。
            filepath: 输出 CSV 文件路径。

        Returns:
            True 表示导出成功，False 表示失败。
        """
        if not samples:
            logger.warning("无样本数据，跳过 CSV 导出")
            return False

        try:
            # 推断列头: 取所有样本中出现的字段（排除下划线开头的内部字段）
            headers: list[str] = []
            seen: set[str] = set()
            for sample in samples:
                for key in sample:
                    if not key.startswith("_") and key not in seen:
                        headers.append(key)
                        seen.add(key)

            if not headers:
                headers = list(samples[0].keys())

            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                for sample in samples:
                    writer.writerow(sample)

            logger.info("CSV 已导出: %s (%d 行, %d 列)", filepath, len(samples), len(headers))
            return True
        except (OSError, Exception) as exc:
            logger.error("CSV 导出失败: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 统计摘要
    # ------------------------------------------------------------------

    @staticmethod
    def summary(samples: list[dict]) -> dict:
        """对采集到的传感器样本集合做统计摘要。

        对于每个数值字段计算: min、max、mean、std、count。
        跳过 ``_`` 开头的内部字段和非数值字段。

        Args:
            samples: 解析后的样本列表。

        Returns:
            统计摘要字典::

                {
                    "field_name": {
                        "min": float,
                        "max": float,
                        "mean": float,
                        "std": float,
                        "count": int,
                    },
                    ...
                }
        """
        if not samples:
            return {}

        # 收集所有字段
        all_fields: dict[str, list[float]] = {}
        for sample in samples:
            for key, value in sample.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, (int, float)):
                    all_fields.setdefault(key, []).append(float(value))

        result: dict = {}
        for field, values in all_fields.items():
            n = len(values)
            if n == 0:
                continue

            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n
            std = math.sqrt(variance)

            result[field] = {
                "min": min(values),
                "max": max(values),
                "mean": round(mean, 6),
                "std": round(std, 6),
                "count": n,
            }

        return result

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self) -> "SensorReader":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
