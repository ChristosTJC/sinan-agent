"""
硬件串口扫描器 —— USB 设备枚举、串口端口发现、板卡识别。

提供跨平台的 USB/串口设备发现能力，核心功能包括：
- USB 设备枚举（基于 ``lsusb`` 或 pyusb）
- 串口端口扫描（``/dev/ttyUSB*``、``/dev/ttyACM*``、``/dev/ttyS*``）
- 板卡自动识别（通过串口探测引导加载程序响应）
- USB VID/PID 数据库查询
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内置 USB VID/PID 数据库 —— 覆盖常用嵌入式 MCU 与 USB-UART 桥接芯片
# ---------------------------------------------------------------------------

_VENDOR_DB: dict[str, dict[str, str]] = {
    "0483": {"name": "STMicroelectronics", "url": "https://www.st.com"},
    "1a86": {"name": "QinHeng Electronics (CH340)", "url": "https://www.wch.cn"},
    "10c4": {"name": "Silicon Labs (CP210x)", "url": "https://www.silabs.com"},
    "0403": {"name": "FTDI (FT232/FT4232)", "url": "https://ftdichip.com"},
    "2341": {"name": "Arduino SA", "url": "https://www.arduino.cc"},
    "2e8a": {"name": "Raspberry Pi", "url": "https://www.raspberrypi.com"},
    "303a": {"name": "Espressif", "url": "https://www.espressif.com"},
    "1366": {"name": "SEGGER (J-Link)", "url": "https://www.segger.com"},
    "15ba": {"name": "Olimex (ARM-USB-OCD)", "url": "https://www.olimex.com"},
    "067b": {"name": "Prolific (PL2303)", "url": "https://www.prolific.com.tw"},
    "04d8": {"name": "Microchip Technology", "url": "https://www.microchip.com"},
    "0d28": {"name": "ARM mbed (DAPLink)", "url": "https://os.mbed.com"},
    "c251": {"name": "Keil Software (ULINK)", "url": "https://www.keil.com"},
}

_PID_DB: dict[str, dict[str, str]] = {
    # STM32 DFU / Virtual COM Port
    "0483:df11": {"device": "STM32 BOOTLOADER (DFU)", "family": "STM32"},
    "0483:5740": {"device": "STM32 Virtual COM Port", "family": "STM32"},
    "0483:3748": {"device": "STM32 ST-LINK V2", "family": "STM32"},
    "0483:374b": {"device": "STM32 ST-LINK V2.1", "family": "STM32"},
    "0483:374e": {"device": "STM32 ST-LINK V3", "family": "STM32"},
    "0483:374f": {"device": "STM32 ST-LINK V3 (Bridge)", "family": "STM32"},
    "0483:3752": {"device": "STM32 ST-LINK V3 (COM)", "family": "STM32"},
    "0483:3753": {"device": "STM32 ST-LINK V3 MINIE", "family": "STM32"},
    # CH340
    "1a86:7523": {"device": "CH340 USB-Serial", "family": "CH340"},
    "1a86:7522": {"device": "CH340/CH341 USB-Serial", "family": "CH340"},
    "1a86:55d4": {"device": "CH343 USB-Serial", "family": "CH343"},
    # CP210x
    "10c4:ea60": {"device": "CP2102 USB-UART", "family": "CP210x"},
    "10c4:ea70": {"device": "CP2105 USB-UART", "family": "CP210x"},
    "10c4:ea71": {"device": "CP2108 USB-UART", "family": "CP210x"},
    "10c4:ea60": {"device": "CP2102 USB-UART", "family": "CP210x"},
    # FTDI
    "0403:6001": {"device": "FT232 USB-Serial", "family": "FT232"},
    "0403:6010": {"device": "FT2232 USB-Serial", "family": "FT2232"},
    "0403:6011": {"device": "FT4232 USB-Serial", "family": "FT4232"},
    "0403:6014": {"device": "FT232H USB-Serial", "family": "FT232H"},
    "0403:6015": {"device": "FT230X USB-Serial", "family": "FT230X"},
    # Arduino
    "2341:0043": {"device": "Arduino Uno R3", "family": "ATmega328P"},
    "2341:0042": {"device": "Arduino Mega 2560", "family": "ATmega2560"},
    "2341:003e": {"device": "Arduino Leonardo", "family": "ATmega32U4"},
    "2341:8037": {"device": "Arduino Due", "family": "ATSAM3X8E"},
    # ESP32
    "303a:1001": {"device": "ESP32-S3 USB-OTG", "family": "ESP32-S3"},
    "303a:0002": {"device": "ESP32-S2 USB-Serial", "family": "ESP32-S2"},
    "10c4:ea60": {"device": "ESP32 (CP210x bridge)", "family": "ESP32"},
    # SEGGER J-Link
    "1366:0101": {"device": "SEGGER J-Link", "family": "J-Link"},
    "1366:0105": {"device": "SEGGER J-Link EDU", "family": "J-Link"},
    "1366:1015": {"device": "SEGGER J-Link OB", "family": "J-Link"},
    # Prolific PL2303
    "067b:2303": {"device": "PL2303 USB-Serial", "family": "PL2303"},
    # DAPLink
    "0d28:0204": {"device": "ARM mbed DAPLink", "family": "DAPLink"},
}

# ---------------------------------------------------------------------------
# USB 设备扫描
# ---------------------------------------------------------------------------


def _try_pyusb_scan() -> list[dict]:
    """使用 pyusb 库扫描 USB 设备。

    Returns:
        USB 设备信息列表。

    Raises:
        ImportError: pyusb 未安装时抛出。
    """
    try:
        import usb.core
        import usb.util
    except ImportError:
        raise ImportError("pyusb 未安装，请执行: pip install pyusb") from None

    devices: list[dict] = []
    for dev in usb.core.find(find_all=True):
        try:
            manufacturer = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
        except (ValueError, usb.core.USBError):
            manufacturer = ""
        try:
            product = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
        except (ValueError, usb.core.USBError):
            product = ""
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else ""
        except (ValueError, usb.core.USBError):
            serial = ""

        devices.append({
            "bus": dev.bus,
            "device": dev.address,
            "vid": f"{dev.idVendor:04x}",
            "pid": f"{dev.idProduct:04x}",
            "manufacturer": manufacturer,
            "product": product,
            "serial": serial,
        })

    return devices


def _try_lsusb_scan() -> list[dict]:
    """使用系统 ``lsusb`` 命令扫描 USB 设备。

    Returns:
        USB 设备信息列表。

    Raises:
        ImportError / FileNotFoundError: lsusb 不可用时抛出。
    """
    try:
        result = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"lsusb 命令不可用: {exc}") from None

    if result.returncode != 0:
        raise RuntimeError(f"lsusb 执行失败: {result.stderr.strip()}")

    devices: list[dict] = []
    # 典型的 lsusb 输出格式:
    # Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
    # 某些设备可能缺少描述字符串
    pattern = re.compile(
        r"^Bus\s+(\d{3})\s+Device\s+(\d{3}):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*)$"
    )

    for line in result.stdout.strip().splitlines():
        m = pattern.match(line)
        if not m:
            continue
        bus = int(m.group(1))
        device = int(m.group(2))
        vid = m.group(3).lower()
        pid = m.group(4).lower()
        description = m.group(5).strip() if m.group(5) else ""

        # 尝试从描述中分离厂商和产品
        manufacturer = ""
        product = description
        serial = ""

        devices.append({
            "bus": bus,
            "device": device,
            "vid": vid,
            "pid": pid,
            "manufacturer": manufacturer,
            "product": product,
            "serial": serial,
        })

    return devices


def scan_usb_devices() -> list[dict]:
    """扫描并返回所有 USB 设备信息。

    按优先级尝试:
        1. pyusb（信息更完整，包含 manufacturer/product/serial 字符串）
        2. ``lsusb`` 命令解析（系统级可用，信息量有限）

    Returns:
        USB 设备信息列表，每条包含::

            {
                "bus": int,
                "device": int,
                "vid": str,       # 4 位十六进制小写
                "pid": str,       # 4 位十六进制小写
                "manufacturer": str,
                "product": str,
                "serial": str,
            }

        所有扫描方式均失败时返回空列表。
    """
    # 优先 pyusb（信息更丰富）
    try:
        devices = _try_pyusb_scan()
        if devices:
            logger.debug("pyusb 扫描到 %d 个 USB 设备", len(devices))
            return devices
    except (ImportError, Exception) as exc:
        logger.debug("pyusb 扫描不可用: %s", exc)

    # 回退到 lsusb
    try:
        devices = _try_lsusb_scan()
        logger.debug("lsusb 扫描到 %d 个 USB 设备", len(devices))
        return devices
    except (RuntimeError, Exception) as exc:
        logger.warning("USB 设备扫描失败: %s", exc)

    return []


# ---------------------------------------------------------------------------
# 串口端口扫描
# ---------------------------------------------------------------------------


def _try_pyserial_ports() -> list[dict]:
    """使用 pyserial 扫描串口端口。

    Returns:
        端口信息列表。

    Raises:
        ImportError: pyserial 未安装时抛出。
    """
    try:
        import serial.tools.list_ports
    except ImportError:
        raise ImportError("pyserial 未安装，请执行: pip install pyserial") from None

    ports: list[dict] = []
    for port_info in serial.tools.list_ports.comports():
        ports.append({
            "port": port_info.device,
            "device": port_info.device,
            "description": port_info.description,
            "hwid": port_info.hwid or "",
        })
    return ports


def _try_glob_ports() -> list[dict]:
    """通过扫描 ``/dev`` 下的标准串口设备节点发现端口。

    Returns:
        端口信息列表。
    """
    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyS*",
        "/dev/ttyAMA*",
        "/dev/tty.usb*",
        "/dev/cu.usb*",
    ]

    ports: list[dict] = []
    seen: set[str] = set()

    for pattern in patterns:
        for path in sorted(Path("/").glob(pattern.lstrip("/"))):
            port = str(path)
            if port in seen:
                continue
            seen.add(port)

            # 尝试读取设备符号链接信息
            description = ""
            hwid = ""
            try:
                # 检查是否为符号链接
                if path.is_symlink():
                    description = f"symlink → {os.readlink(port)}"
            except OSError:
                pass

            ports.append({
                "port": port,
                "device": port,
                "description": description,
                "hwid": hwid,
            })

    return ports


def scan_serial_ports() -> list[dict]:
    """扫描系统所有串口端口。

    按优先级尝试:
        1. pyserial ``list_ports``（提供 description/hwid 等详细信息）
        2. 文件系统 glob ``/dev/ttyUSB*``、``/dev/ttyACM*``、``/dev/ttyS*`` 等

    Returns:
        串口端口信息列表，每条包含::

            {
                "port": str,        # 端口路径 (e.g. "/dev/ttyUSB0")
                "device": str,      # 同上
                "description": str, # 描述信息（pyserial 提供时更详细）
                "hwid": str,        # 硬件 ID（pyserial 提供时更详细）
            }

        无可用端口或扫描失败时返回空列表。
    """
    try:
        ports = _try_pyserial_ports()
        if ports:
            logger.debug("pyserial 扫描到 %d 个串口", len(ports))
            return ports
    except (ImportError, Exception) as exc:
        logger.debug("pyserial 串口扫描不可用: %s", exc)

    ports = _try_glob_ports()
    logger.debug("glob 扫描到 %d 个串口", len(ports))
    return ports


# ---------------------------------------------------------------------------
# 板卡识别
# ---------------------------------------------------------------------------


def _probe_serial_response(port: str, baudrate: int = 115200, timeout: float = 2.0) -> Optional[str]:
    """向串口发送探测命令并等待响应。

    Args:
        port: 串口端口路径。
        baudrate: 波特率。
        timeout: 超时秒数。

    Returns:
        设备回应的字符串，失败返回 None。
    """
    try:
        import serial
    except ImportError:
        logger.warning("pyserial 未安装，无法探测串口")
        return None

    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
    except (serial.SerialException, OSError) as exc:
        logger.debug("无法打开串口 %s: %s", port, exc)
        return None

    try:
        # 发送 break 信号唤醒引导加载程序
        ser.send_break(0.1)
        # 尝试 AT 命令
        ser.write(b"AT\r\n")
        ser.flush()

        # 读取直到超时
        response_lines: list[str] = []
        while True:
            line = ser.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                response_lines.append(decoded)

        if response_lines:
            return "\n".join(response_lines)
        return None
    finally:
        ser.close()


# 引导加载程序识别模式
_BOOTLOADER_PATTERNS: list[tuple[str, str]] = [
    ("STM32", r"(STM32|stm32)"),
    ("ESP32 ROM", r"(waiting for download|ets\s+\w+\s+.*rom)"),
    ("Arduino", r"(Arduino|avrdude)"),
    ("U-Boot", r"(U-Boot|uboot)"),
    ("Raspberry Pi Pico", r"(Picoprobe|UF2 Boot|RP2 Boot)"),
    ("nRF52 DFU", r"(DFU|nRF5)"),
    ("AVR ISP", r"(AVRISP|STK500)"),
]


def _match_bootloader_pattern(response: str) -> Optional[str]:
    """根据设备响应匹配引导加载程序模式。

    Args:
        response: 设备回应的文本。

    Returns:
        匹配到的引导加载程序名称，未匹配返回 None。
    """
    for name, pattern in _BOOTLOADER_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            return name
    return None


def identify_board(port: str) -> Optional[str]:
    """尝试通过串口探测识别板卡型号。

    方法: 打开串口 → 发送 break + AT 命令 → 检查引导加载程序/固件响应。

    Args:
        port: 串口端口路径。

    Returns:
        板卡标识字符串（如 ``"STM32"``、``"ESP32 ROM"``），
        无法识别时返回 None。
    """
    response = _probe_serial_response(port)
    if response is None:
        return None

    board = _match_bootloader_pattern(response)
    if board:
        logger.info("板卡识别 %s → %s", port, board)
    else:
        logger.debug("板卡识别 %s → 无法匹配响应: %s", port, response[:80])

    return board


def get_device_info(vid: str, pid: str) -> Optional[dict]:
    """根据 USB VID/PID 查询设备信息。

    从内置数据库中查找厂商和设备型号。
    数据库覆盖: STM32、ESP32、Arduino、FTDI、CH340、CP210x、PL2303、J-Link、DAPLink 等常见芯片。

    Args:
        vid: 4 位十六进制 Vendor ID。
        pid: 4 位十六进制 Product ID。

    Returns:
        设备信息 dict::

            {
                "vendor": str,      # 厂商名
                "vendor_url": str,  # 厂商网址
                "device": str,      # 设备名
                "family": str,      # 芯片系列
                "vid": str,
                "pid": str,
            }

        VID/PID 不在数据库中时返回 None。
    """
    vid = vid.lower().strip()
    pid = pid.lower().strip()

    vendor_info = _VENDOR_DB.get(vid)
    pid_info = _PID_DB.get(f"{vid}:{pid}")

    if vendor_info is None and pid_info is None:
        return None

    result = {
        "vid": vid,
        "pid": pid,
        "vendor": vendor_info["name"] if vendor_info else "",
        "vendor_url": vendor_info["url"] if vendor_info else "",
        "device": pid_info["device"] if pid_info else f"VID:{vid} PID:{pid}",
        "family": pid_info["family"] if pid_info else "",
    }
    return result
