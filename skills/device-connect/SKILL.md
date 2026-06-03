---
name: device-connect
description: 设备交互智能体——扫描、连接、操纵物理开发板与嵌入式Linux板卡
metadata:
  type: skill
---

# 设备连接与交互

## 触发条件

用户执行以下任一操作时触发：
- 请求列出已连接设备（"扫描设备"、"有哪些板子连着"）
- 需要通过串口/SSH/JSONL-RPC 连接嵌入式设备
- 需要读取传感器数据或控制 GPIO
- 固件烧录或启动模式切换
- 设备连接诊断

## 核心能力

### 1. USB/串口设备自动扫描与识别

**Linux 下的 USB 设备枚举**：

```bash
# 列举所有 USB 设备（VID:PID:厂商:产品）
lsusb

# 列举 USB 转串口设备（真实开发板通常出现在这些节点）
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
ls -l /dev/serial/by-id/ 2>/dev/null   # 稳定设备路径（推荐使用）
ls -l /dev/serial/by-path/ 2>/dev/null  # 按物理端口路径

# 平台串口（ttyS*/ttyAMA*）通常是主板或 SoC 片上 UART，不一定是外接设备
# 仅当上述 USB 路径无结果时才作为备选检查
ls /dev/ttyS* /dev/ttyAMA* 2>/dev/null

# 获取 USB 设备详细信息
udevadm info --query=all --name=/dev/ttyUSB0

# 获取串口属性
stty -F /dev/ttyUSB0 -a
```

**常见 USB 转串口芯片 VID:PID 对照表**：

| 芯片 | VID:PID | 常见用途 |
|------|---------|----------|
| FT232R | 0403:6001 | 经典 USB-UART 转换器 |
| CH340/CH341 | 1A86:7523 | 低成本 Arduino 及国产开发板常用 |
| CP210x | 10C4:EA60 | Silicon Labs 方案，ESP32 开发板常见 |
| PL2303 | 067B:2303 | 老旧方案，Linux 下需注意驱动版本 |

**设备描述输出格式**：
```
[1] /dev/ttyUSB0 — FT232R (0403:6001) — 物理路径: bus-1.2
[2] /dev/ttyACM0 — STM32 Virtual COM Port (0483:5740) — 物理路径: bus-1.3
[3] /dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_XXXXXXXX-00
```

### 2. JSONL-RPC 设备节点桥接

**适用场景**：通过 JSONL 协议与机载 Linux 板卡（如 Jetson、Raspberry Pi）通信，代理执行 Shell 命令和外设操作。

**协议规范**：

```
请求帧（一行 JSON）:
{"id": 1, "method": "shell.exec", "params": {"cmd": "ls /dev/i2c*", "timeout_ms": 5000}}

响应帧:
{"id": 1, "ok": true, "data": {"stdout": "/dev/i2c-0\n/dev/i2c-1\n", "stderr": "", "exit_code": 0}}
```

**支持的方法**：

| Method | 功能 | 参数 | 安全限制 |
|--------|------|------|----------|
| `shell.exec` | 执行 Shell 命令 | `cmd`: 命令字符串, `timeout_ms`: 超时 | 禁止 `rm -rf`, `dd of=`, `mkfs`, `fdisk` 等破坏性命令；禁止 `curl | bash`, `wget -O -` 等管道执行 |
| `shell.exec_safe` | 安全白名单命令 | `cmd`: 命令 | 仅允许：ls, cat, echo, uname, dmesg, i2cdetect, gpioinfo, i2cget, i2cset 等只读/低风险操作 |
| `gpio.read` | 读取 GPIO 电平 | `pin`: 引脚号或名称 | 仅读取 |
| `gpio.write` | 设置 GPIO 输出 | `pin`, `value`: 0/1 | 禁止设置为输入的 UART TX/RX 引脚、SWD 引脚等 |
| `i2c.scan` | I2C 总线扫描 | `bus`: 总线号 | 无限制 |
| `i2c.read` | I2C 寄存器读 | `bus`, `addr`, `reg`, `len` | 每次最大读取 256 字节 |
| `i2c.write` | I2C 寄存器写 | `bus`, `addr`, `reg`, `data[]` | 禁止写电源管理/看门狗配置寄存器（需确认） |
| `spi.transfer` | SPI 收发 | `bus`, `cs`, `speed`, `tx_data[]` | 每次最大传输 4096 字节 |
| `sensor.read` | 传感器数据读取 | `sensor_type`, `params` | 每次最多返回 100 条数据点 |

**连接流程**：

```
1. 探测端口：尝试对候选 IP:port 发送 {"id": 0, "method": "ping"}
   等待响应 {"id": 0, "ok": true, "data": {"version": "1.0", "hostname": "jetson-nx", "platform": "aarch64"}}
2. 能力协商：{"id": 1, "method": "capabilities"}
3. 执行操作
4. 优雅关闭：{"id": -1, "method": "disconnect"}
```

### 3. 传感器数据读取与可视化

**支持的传感器及读取方法**：

| 传感器型号 | 接口 | 关键寄存器/指令 | 数据转换公式 |
|-----------|------|----------------|-------------|
| MPU6050 (6轴 IMU) | I2C 0x68 | ACCEL_XOUT_H (0x3B), GYRO_XOUT_H (0x43) | accel = raw / LSB_sensitivity (g), gyro = raw / 65.5 (deg/s, ±500dps) |
| MPU9250 (9轴 IMU) | I2C 0x68 | 同 MPU6050 + AK8963 磁力计 (I2C 0x0C) | mag = raw × mag_sensitivity_adj × 0.15 (μT) |
| VL53L0X (ToF 测距) | I2C 0x29 | RESULT_RANGE_STATUS (0x14+0x0096) | distance_mm = raw / 4 (若 unit=1) |
| BME280 (温湿压) | I2C 0x76/0x77 | 补偿参数从 0x88-0xA1 和 0xE1-0xF0 | 使用 Bosch 补偿公式（整型运算版本，无浮点） |
| SHT3x (温湿度) | I2C 0x44/0x45 | 单次测量命令 0x2C06 + 读数 6 字节 | T(°C) = -45 + 175 × ST / (2^16-1), RH(%) = 100 × SRH / (2^16-1) |
| ADS1115 (16位 ADC) | I2C 0x48/0x49/0x4A/0x4B | 转换寄存器 0x00, 配置寄存器 0x01 | voltage = raw × FS / 32768 (FS=4.096/2.048/1.024/0.512/6.144V 取决于 PGA) |
| AS5600 (磁编码器) | I2C 0x36 | RAW_ANGLE (0x0C) | angle_deg = raw × 360 / 4096 |

**数据输出格式**：
```
时间戳(ms) | 传感器 | 温度(°C) | 湿度(%) | 压力(hPa)
001234     | BME280 | 25.3     | 48.7    | 1013.25
001364     | BME280 | 25.4     | 48.9    | 1013.28
...
```

对于周期性采样，输出 ASCII 时序图（终端文本画图）。

### 4. GPIO 控制

**操作规范**：

```bash
# 导出 GPIO（sysfs 方式，Linux 4.x 及之前）
echo 17 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio17/direction
echo 1 > /sys/class/gpio/gpio17/value

# GPIO 字符设备方式（Linux 4.8+ 推荐）
gpioset gpiochip0 17=1    # 设置输出高
gpioget gpiochip0 18      # 读取输入

# libgpiod 工具集
gpiodetect                 # 列出所有 gpiochip
gpioinfo                   # 列出所有 GPIO 线的状态
gpioset --mode=time -s 2 gpiochip0 17=1  # 持续 2 秒的高脉冲（用于 LED 闪烁）
gpioset --mode=exit gpiochip0 17=0      # 设置后退出（维持电平）
```

**安全约束**：
- 操作前确认该 GPIO 未被内核驱动占用
- 检查 GPIO 电压域（1.8V / 3.3V），不得将 1.8V GPIO 直接驱动到 3.3V 外设
- 大电流负载（继电器、电机）不直接用 GPIO 驱动，必须通过三极管/光耦/MOSFET
- 关键总线引脚（I2C SDA/SCL, SPI MOSI/MISO/SCK/CS, UART TX/RX, SWD SWCLK/SWDIO）禁止通过 sysfs export 手动控制

### 5. 固件烧录与启动模式切换

完整流程参见 `embedded-fullstack` skill 的第 5 节。本 skill 侧重烧录前的连接准备和启动模式控制：

**STM32 启动模式控制**：
| BOOT0 | BOOT1 | 启动源 |
|-------|-------|--------|
| 0 | x | Main Flash（正常运行模式） |
| 1 | 0 | System Memory（内置 bootloader，用于串口/USB DFU 烧录） |
| 1 | 1 | SRAM（调试用） |

- BOOT0 拉高后复位（NRST 拉低 1ms 再释放）进入 bootloader 模式
- 退出 bootloader 模式需将 BOOT0 拉低再复位

**ESP32 启动模式控制**：
| GPIO0 | 模式 |
|-------|------|
| 低（按住 BOOT 键） | 下载模式（等待 esptool 连接） |
| 高（默认） | Flash 启动（正常运行） |

- 自动下载电路：DTR → EN（复位），RTS → GPIO0。esptool 通过控制 RTS/DTR 时序自动进入下载模式
- 若自动下载失败：手动按住 BOOT → 点按 EN → 释放 BOOT

### 6. 设备连接诊断

**诊断决策树**：

```
连接失败
├─ 物理层
│   ├─ lsusb 能看到设备吗？→ 否 → 换 USB 线、换端口、检查设备上电
│   ├─ dmesg | grep tty 有设备挂载日志吗？→ 否 → 驱动缺失（linux-firmware 更新）
│   ├─ 设备挂载但有 "device descriptor read/64 error -71"？→ USB 供电不足或线缆质量问题
│   └─ /dev/ttyUSB0 存在但无法打开？→ 权限问题（用户需加入 dialout 组）
├─ 网络层（SSH/TCP 设备）
│   ├─ ping 通吗？→ 否 → 检查 IP、子网掩码、路由
│   ├─ 端口开放吗？→ nc -zv IP PORT → 否 → 防火墙或服务未启动
│   └─ SSH 连接被拒 → 检查 sshd 是否运行、用户名是否正确、密钥是否已授权
├─ 协议层（JSONL-RPC）
│   ├─ 能 TCP 连接但无响应？→ 检查 JSONL 格式（每行一个 JSON）
│   ├─ 返回 {"ok": false, "error": "..."} → 按错误信息调试
│   └─ 返回乱码 → 波特率或编码不匹配
└─ 应用层（MCU 下载模式）
    ├─ STM32CubeProgrammer 连接失败 → BOOT0 是否拉高？RESET 后是否过快尝试连接？
    ├─ OpenOCD 无法连接 SWD → 检查 SWCLK/SWDIO/GND 三线是否正确；目标板是否上电；ST-Link 固件版本
    └─ esptool 连接超时 → 进入下载模式后再执行 esptool；检查 EN/GPIO0 时序
```

## 工具要求

- 宿主机：`lsusb`, `udevadm`, `stty`, `picocom`, `screen`
- 串口工具：`dmesg`（查看设备挂载日志）
- 网络工具：`ping`, `nc`, `ssh`, `curl`
- 目标设备：JSONL-RPC 守护进程运行中
- GPIO 工具：`gpiodetect`, `gpioinfo`, `gpioset`, `gpioget`（libgpiod 套件）
- I2C 工具：`i2cdetect`, `i2cdump`, `i2cget`, `i2cset`（i2c-tools 套件）
- 烧录工具：`STM32_Programmer_CLI`, `openocd`, `esptool.py`

## 工作流程

1. **环境探测**：扫描宿主机所有可用的 USB 和串口设备
2. **设备识别**：通过 VID/PID 识别设备类型，输出设备清单
3. **连接建立**：根据设备类型选择串口/SSH/JSONL-RPC 建立连接
4. **能力确认**：确认可执行的操作范围
5. **操作执行**：执行用户请求的具体操作
6. **结果反馈**：格式化输出结果

## 安全约束

- **串口操作有界**：单次监听最长 30 秒，单次采集不超过 64KB
- **Shell 命令白名单**：破坏性命令黑名单在每次执行前检查
- **GPIO 保护**：禁止操作已被内核驱动占用的关键总线引脚
- **传感器操作**：单次读取不超过 100 条数据点，防止过量采集
- **烧录保护**：执行烧录前备份当前 flash 内容（若技术支持）；确认目标设备型号后再操作
- **网络边界**：不主动发起端口扫描或网络嗅探
- 所有对硬件有副作用的操作（GPIO 输出、寄存器写入、电机控制等）必须在执行前向用户确认

## 输出格式

```markdown
## 设备清单
[扫描结果，按端口排列]

## 连接状态
设备 [名称] @ [端口] — [✓ 已连接 / ✗ 连接失败: 原因]

## 操作结果
```
[命令输出 / 传感器数据表格 / GPIO 状态]
```

## 异常与建议
[连接失败时的诊断建议]
```
