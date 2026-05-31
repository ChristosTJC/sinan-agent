"""
串口监视器 —— 串口读写、数据采集、波特率自动检测。

提供面向硬件调试和传感器数据采集的串口交互能力：
- 打开/关闭串口，读/写数据
- 限时监控采集行数据
- 常用波特率自动检测（AT 命令探测）
- 硬性安全边界：最大字节数、最大监控时长 (从配置读取)
"""

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 波特率常量映射
# ---------------------------------------------------------------------------

BAUDRATE_MAP: dict[int, str] = {
    300: "B300",
    1200: "B1200",
    2400: "B2400",
    4800: "B4800",
    9600: "B9600",
    19200: "B19200",
    38400: "B38400",
    57600: "B57600",
    74880: "B74880",
    115200: "B115200",
    230400: "B230400",
    250000: "B250000",
    460800: "B460800",
    500000: "B500000",
    921600: "B921600",
    1000000: "B1000000",
    2000000: "B2000000",
    3000000: "B3000000",
}

# 自动检测波特率候选列表（按使用频率排序）
_AUTO_BAUD_CANDIDATES: list[int] = [
    115200,
    9600,
    921600,
    460800,
    230400,
    57600,
    38400,
    19200,
    74880,
    1000000,
    2000000,
]


# ---------------------------------------------------------------------------
# 安全边界 (从配置读取)
# ---------------------------------------------------------------------------

class _SafetyBounds:
    """串口监视器安全边界常量。
    
    默认值从 config.defaults.yaml 读取,硬编码值作为兜底。
    """

    # 硬编码兜底值
    MAX_BYTES = 10 * 1024 * 1024       # 10 MB 硬上限
    MAX_DURATION_SEC = 120             # 2 分钟硬上限

    @classmethod
    def get_defaults(cls) -> dict:
        """从配置获取默认安全边界值。
        
        Returns:
            {"max_bytes": int, "max_duration_sec": float}
        """
        try:
            from agent.config import get_tools_config
            tools_config = get_tools_config()
            serial_config = tools_config.get("serial", {})
            
            return {
                "max_bytes": serial_config.get("max_bytes", 10 * 1024),  # 默认 10 KB
                "max_duration_sec": serial_config.get("max_duration_sec", 30),  # 默认 30 秒
            }
        except Exception as e:
            logger.warning("无法加载工具配置,使用硬编码兜底值: %s", e)
            return {
                "max_bytes": 10 * 1024,
                "max_duration_sec": 30,
            }


# ---------------------------------------------------------------------------
# SerialMonitor
# ---------------------------------------------------------------------------


class SerialMonitor:
    """串口监视器 —— 封装 pyserial 的读写与数据采集。

    典型用法::

        monitor = SerialMonitor("/dev/ttyUSB0", baudrate=115200)
        if monitor.open():
            lines = monitor.monitor(duration_sec=5.0)
            msg = "\\n".join(lines)
            print(f"收到 {len(lines)} 行数据，共 {len(msg)} 字节")
            monitor.close()

    Attributes:
        port: 串口端口路径。
        baudrate: 波特率。
        timeout: 读取超时秒数。
        max_bytes: 单次读取最大字节数限制。
        max_duration_sec: 单次监控最大时长限制。
        serial: 底层 pyserial 对象（未打开时为 None）。
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
        max_bytes: Optional[int] = None,
        max_duration_sec: Optional[float] = None,
    ) -> None:
        """初始化串口监视器。

        Args:
            port: 串口端口路径（如 ``"/dev/ttyUSB0"``）。
            baudrate: 波特率，默认 115200。
            timeout: 读取超时（秒），默认 1.0。
            max_bytes: 单次最大读取字节数，超限截断，默认从配置读取 (10 KB)。
            max_duration_sec: 单次监控最大时长（秒），超限截断，默认从配置读取 (30)。

        Note:
            max_bytes 和 max_duration_sec 都有硬性上限保护:
            - max_bytes 上限 10 MB
            - max_duration_sec 上限 120 秒
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        
        # 从配置读取默认值 (如果未显式指定)
        defaults = _SafetyBounds.get_defaults()
        if max_bytes is None:
            max_bytes = defaults["max_bytes"]
        if max_duration_sec is None:
            max_duration_sec = defaults["max_duration_sec"]
        
        # 安全边界约束
        self.max_bytes = min(max_bytes, _SafetyBounds.MAX_BYTES)
        self.max_duration_sec = min(max_duration_sec, _SafetyBounds.MAX_DURATION_SEC)
        self._serial = None

    @property
    def serial(self):
        """底层 pyserial.Serial 对象，未打开时返回 None。"""
        return self._serial

    @property
    def is_open(self) -> bool:
        """是否已打开。"""
        return self._serial is not None and self._serial.is_open

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """打开串口连接。

        Returns:
            True 表示打开成功，False 表示失败（pyserial 不可用、端口不存在等）。
        """
        if self.is_open:
            logger.debug("串口 %s 已打开，跳过", self.port)
            return True

        try:
            import serial
        except ImportError:
            logger.error("pyserial 未安装，无法打开串口 %s。请执行: pip install pyserial", self.port)
            return False

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
            logger.info("串口已打开: %s @ %d baud", self.port, self.baudrate)
            return True
        except (serial.SerialException, OSError) as exc:
            logger.error("无法打开串口 %s: %s", self.port, exc)
            self._serial = None
            return False

    def close(self) -> None:
        """关闭串口连接，释放资源。"""
        if self._serial is not None:
            try:
                self._serial.close()
                logger.info("串口已关闭: %s", self.port)
            except Exception as exc:
                logger.warning("关闭串口 %s 时出错: %s", self.port, exc)
            finally:
                self._serial = None

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def read_line(self) -> Optional[str]:
        """读取一行（以 ``\\n`` 结尾）。

        Returns:
            解码后的字符串（不含行尾换行符），
            超时/无数据时返回 None。
        """
        if not self.is_open or self._serial is None:
            logger.warning("读取失败: 串口未打开")
            return None

        try:
            line = self._serial.readline()
            if not line:
                return None
            return line.decode("utf-8", errors="replace").rstrip("\r\n")
        except (OSError, Exception) as exc:
            logger.error("串口读取错误: %s", exc)
            return None

    def read_all(self) -> str:
        """读取所有当前可用的数据。

        Returns:
            解码后的字符串。无数据返回空字符串 ``""``。
            数据量受 ``max_bytes`` 限制，超出部分被截断。
        """
        if not self.is_open or self._serial is None:
            logger.warning("读取失败: 串口未打开")
            return ""

        try:
            # 先查询缓冲区大小
            in_waiting = self._serial.in_waiting
            bytes_to_read = min(in_waiting, self.max_bytes)
            if bytes_to_read <= 0:
                return ""
            data = self._serial.read(bytes_to_read)
            return data.decode("utf-8", errors="replace")
        except (OSError, Exception) as exc:
            logger.error("串口读取错误: %s", exc)
            return ""

    def monitor(
        self,
        duration_sec: float,
        callback: Optional[Callable[[str], None]] = None,
    ) -> list[str]:
        """在限定时间内监控串口输出，收集所有行。

        Args:
            duration_sec: 监控时长（秒），受 ``max_duration_sec`` 约束。
            callback: 可选回调函数，每读到一行回调 ``callback(line)``。

        Returns:
            读取到的所有行（每条为去除换行符的字符串）。

        Note:
            - 监控时长有硬性上限保护（默认 120 秒，构造函数配置上限）。
            - 总读取字节数受 ``max_bytes`` 约束。
        """
        if not self.is_open or self._serial is None:
            logger.warning("监控失败: 串口未打开")
            return []

        duration = min(duration_sec, self.max_duration_sec)
        collected_lines: list[str] = []
        total_bytes = 0
        start_time = time.monotonic()

        logger.info("开始监控 %s，时长 %0.1f 秒...", self.port, duration)

        while (time.monotonic() - start_time) < duration:
            # 检查字节限制
            if total_bytes >= self.max_bytes:
                logger.warning("监控截断: 已达字节上限 %d", self.max_bytes)
                break

            line = self.read_line()
            if line is not None:
                collected_lines.append(line)
                total_bytes += len(line.encode("utf-8", errors="replace"))
                if callback is not None:
                    try:
                        callback(line)
                    except Exception as exc:
                        logger.warning("回调函数异常: %s", exc)
            else:
                # 超时，稍等一小段时间避免忙等
                time.sleep(0.01)

        elapsed = time.monotonic() - start_time
        logger.info(
            "监控结束: %s，耗时 %0.1f 秒，收到 %d 行，%d 字节",
            self.port,
            elapsed,
            len(collected_lines),
            total_bytes,
        )
        return collected_lines

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def write(self, data: bytes) -> int:
        """向串口写入原始字节。

        Args:
            data: 要写入的字节数据。

        Returns:
            实际写入的字节数。写入失败返回 0。
        """
        if not self.is_open or self._serial is None:
            logger.warning("写入失败: 串口未打开")
            return 0

        try:
            written = self._serial.write(data)
            self._serial.flush()
            return written
        except (OSError, Exception) as exc:
            logger.error("串口写入错误: %s", exc)
            return 0

    def write_command(self, cmd: str) -> int:
        """向串口写入命令字符串并追加换行符 ``\\n``。

        Args:
            cmd: 命令字符串（不含换行符）。

        Returns:
            实际写入的字节数（含换行符）。
        """
        return self.write((cmd + "\n").encode("utf-8"))

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self) -> "SerialMonitor":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 波特率自动检测
# ---------------------------------------------------------------------------


def auto_detect_baud(port: str) -> Optional[int]:
    """自动检测串口波特率。

    方法：以候选波特率依次打开串口，发送 ``AT\\r\\n``，检查是否收到
    ``OK``（不区分大小写）响应。优先使用常用波特率。

    Args:
        port: 串口端口路径。

    Returns:
        检测到的波特率，检测失败返回 None。

    Note:
        依赖 pyserial，若未安装则直接返回 None。
    """
    try:
        import serial
    except ImportError:
        logger.warning("pyserial 未安装，无法自动检测波特率")
        return None

    logger.info("开始自动检测波特率: %s", port)

    for baudrate in _AUTO_BAUD_CANDIDATES:
        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        except (serial.SerialException, OSError) as exc:
            logger.debug("波特率 %d 无法打开端口: %s", baudrate, exc)
            continue

        try:
            # 清空缓冲区
            ser.reset_input_buffer()
            # 发送 AT 命令
            ser.write(b"AT\r\n")
            ser.flush()

            # 等待响应（最多 1 秒）
            deadline = time.monotonic() + 1.0
            response_chunks: list[bytes] = []
            while time.monotonic() < deadline:
                chunk = ser.read(128)
                if not chunk:
                    break
                response_chunks.append(chunk)

            response = b"".join(response_chunks).decode("utf-8", errors="replace").strip()
            if response and ("OK" in response.upper() or "ok" in response.lower()):
                logger.info("波特率检测成功: %s @ %d baud", port, baudrate)
                return baudrate
        except (OSError, Exception) as exc:
            logger.debug("波特率 %d 通信错误: %s", baudrate, exc)
        finally:
            ser.close()

    logger.warning("波特率检测失败: 所有候选波特率均无响应")
    return None
