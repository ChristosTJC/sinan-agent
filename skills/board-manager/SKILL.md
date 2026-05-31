---
name: board-manager
description: 板卡管理器——管理板卡配置、端口别名、外设清单与踩坑记录
metadata:
  type: skill
---

# 板卡管理器

## 触发条件

用户执行以下操作时触发：
- 新增或修改板卡配置（"记录一下这块板子"、"这是我的新开发板"）
- 查询板卡信息（"XX板子的串口是哪个"、"这块板的引脚图呢"）
- 管理端口别名（"把 /dev/ttyUSB0 设为默认串口"）
- 记录踩坑经验（"这块板子有个坑"、"上次这个问题怎么解决的"）
- 导出/导入板卡配置（"把我的板卡配置备份一下"）
- 对比多块板卡进行选型

## 核心能力

### 1. 交互式板卡配置创建向导

当用户引入一块新板卡时，逐步收集以下信息，创建标准化的板卡配置文件：

**Step 1: 基本信息**
```
板卡名称: [用户提供，如 "WeAct STM32F411CEU6 BlackPill"]
板卡别名: [短名，如 "blackpill-f411", 用于命令行引用]
制造商:   [如 "WeAct Studio"]
芯片型号: [如 "STM32F411CEU6"]
芯片内核: [如 "Cortex-M4, 100MHz, FPv4-SP-D16"]
```

**Step 2: 存储参数**
```
Flash 容量: [如 "512KB"]
RAM 容量:   [如 "128KB"]
Flash 基址: [如 "0x08000000"]
RAM 基址:   [如 "0x20000000"]
链接脚本路径: [项目中的 .ld 文件位置]
```

**Step 3: 引脚映射表**

生成标准 Pin Mux 表：

```
┌────────────┬─────────┬────────────┬───────────┬──────────┐
│ 引脚       │ 功能    │ AF         │ 方向      │ 备注     │
├────────────┼─────────┼────────────┼───────────┼──────────┤
│ PA0        │ TIM2_CH1│ AF1        │ Output    │ PWM 电机 │
│ PA1        │ TIM2_CH2│ AF1        │ Output    │ PWM 电机 │
│ PA2        │ USART2_TX│ AF7       │ Output    │ 调试串口 │
│ PA3        │ USART2_RX│ AF7       │ Input     │ 调试串口 │
│ PA9        │ I2C1_SCL│ AF4        │ OD        │ OLED 屏幕│
│ PA10       │ I2C1_SDA│ AF4        │ OD        │ OLED 屏幕│
│ PA13       │ SWDIO    │ —          │ —         │ 调试接口 │
│ PA14       │ SWCLK    │ —          │ —         │ 调试接口 │
│ PC13       │ GPIO_OUT │ —          │ Output    │ LED 心跳 │
└────────────┴─────────┴────────────┴───────────┴──────────┘
```

**Step 4: 外设连接清单**

```
┌──────────────────────┬───────────┬──────────┬──────────┬──────────────┐
│ 外设                 │ 接口      │ 地址/引脚│ 供电     │ 备注         │
├──────────────────────┼───────────┼──────────┼──────────┼──────────────┤
│ MPU6050 IMU          │ I2C1      │ 0x68     │ 3.3V     │ 中断接 PA4   │
│ 0.96" OLED (SSD1306) │ I2C1      │ 0x3C     │ 3.3V     │ 128x64       │
│ AS5600 磁编码器      │ I2C2      │ 0x36     │ 3.3V     │ SDA 需 2.2kΩ │
│ DRV8833 电机驱动     │ PWM (TIM2)│ PA0, PA1 │ VM=5V    │ nSleep接PB0  │
│ USB-UART (CH340)     │ USART2    │ PA2, PA3 │ —        │ 115200 8N1   │
└──────────────────────┴───────────┴──────────┴──────────┴──────────────┘
```

支持用以下命令自动发现 I2C 设备：
```bash
i2cdetect -y -r 0   # 扫描 I2C-0 总线
i2cdetect -y -r 1   # 扫描 I2C-1 总线
```

**Step 5: 电源参数**
```
供电方式: [USB / 外部 DC / 电池]
输入电压范围: [如 3.6V - 5.5V (USB), 7-12V (VIN)]
VDD 电压: [如 3.3V (LDO 输出)]
功耗估算 (正常工作): [如 ~50mA @ 5V]
功耗估算 (低功耗模式): [如 ~2mA @ 3.3V (STOP 模式)]
```

**Step 6: 构建配置**

```ini
# platformio.ini 模板
[env:blackpill_f411]
platform = ststm32
board = blackpill_f411ce
framework = stm32cube
board_build.f_cpu = 100000000L
monitor_speed = 115200
upload_protocol = dfu           # 或 stlink / serial
build_flags =
    -D STM32F411xE
    -D HSE_VALUE=25000000
```

**Step 7: 安全注意事项**

特定于板卡的安全约束，例如：
- "该开发板 VIN 和 USB 5V 直接连通，不要同时连接 USB 和外部电源"
- "3.3V LDO 最大输出 500mA，外设总功耗不得超过此值"
- "PA11/PA12 被 USB OTG 占用，使用 USB 通信时不可用作 GPIO"
- "BOOT0 引脚未接下拉电阻，上电时会随机进入 bootloader 模式，需要关注"

### 2. 端口别名管理

**别名映射表**（存储在板卡配置中）：

```yaml
port_aliases:
  default_serial:
    vid: "1A86"       # CH340
    pid: "7523"
    label: "调试串口"
    current: "/dev/ttyUSB0"
  debugger:
    vid: "0483"       # ST-Link
    pid: "3748"
    label: "ST-Link/V2 调试器"
    current: "/dev/stlinkv2"
  imu_i2c:
    bus: 1
    label: "IMU 所在 I2C 总线"
    current: "/dev/i2c-1"
```

**操作命令示例**：
```
用户: "把 /dev/ttyUSB0 设为默认串口"
司南: default_serial -> /dev/ttyUSB0 ✓

用户: "默认串口是哪个？"
司南: default_serial = /dev/ttyUSB0 (CH340, 调试串口)

用户: "串口怎么换了？之前是 ttyUSB0 现在变成 ttyACM0 了"
司南: 检测到设备变更。原 default_serial (0403:6001) 现在挂载在 /dev/ttyACM0。
      自动更新别名映射。
```

**智能别名管理**：
- 基于 VID:PID 而非设备节点路径进行匹配（设备节点路径可能因插拔顺序改变）
- 同型号多设备时，用物理端口路径 (`/dev/serial/by-path/`) 区分
- 设备拔出时提示 "别名 xxx 引用的设备已断开"

### 3. 踩坑记录与检索

**踩坑记录格式**：

```yaml
pitfalls:
  - id: pitfall_001
    board: "blackpill-f411"
    category: "时钟"
    title: "HSE 25MHz 晶振设计失误导致 USB 48MHz 不可用"
    symptom: "USB CDC 枚举失败，Windows 报错'设备描述符请求失败'"
    root_cause: |
      PLL 配置使用 HSE 25MHz 作为输入时钟源，PLLM=25, PLLN=192, PLLP=2, PLLQ=4。
      但 STM32F411 要求 USB 的 48MHz 时钟源必须精确（误差 < 0.25%）。
      此配置 PLLQ=4 → 48MHz = (25/25 × 192) / 4 = 48MHz，计算正确。
      但实际板载晶振是 8MHz 而非 25MHz，导致 PLL 输出频率完全错误。
    solution: |
      1. 确认板载晶振实际频率（8MHz）
      2. 修改 HSE_VALUE 宏为 8000000
      3. 修改 PLLM=8, PLLN=192, PLLP=2, PLLQ=4
      4. 或者改用 HSI 内部 16MHz RC 振荡器作为临时方案（USB 因精度不够仍不可用）
    prevention: "批量生产前用高精度频率计确认每块板的晶振实际频率"
    date: "2025-03-15"
    resolved: true
```

**检索方式**：
- 按板卡过滤："这块板子有哪些已知坑？"
- 按类别过滤："时钟相关的坑有哪些？"
- 按关键词搜索："PLL USB 48MHz"
- 按解决状态："还有哪些未解决的坑？"

### 4. 板卡配置文件管理

**存储路径**：`~/.sinan/boards/{board-alias}.yaml`

**完整的板卡配置文件结构**：

```yaml
# ~/.sinan/boards/blackpill-f411.yaml
board_name: "WeAct STM32F411CEU6 BlackPill"
board_alias: "blackpill-f411"
manufacturer: "WeAct Studio"
mcu: "STM32F411CEU6"
core: "Cortex-M4, 100MHz, FPv4-SP-D16"
flash: 512KB
ram: 128KB
flash_base: 0x08000000
ram_base: 0x20000000
linker_script: "STM32F411CEUX_FLASH.ld"

voltage:
  vdd: 3.3
  vin_min: 3.6
  vin_max: 5.5
  ldo_max_current_ma: 500

pins:
  - pin: PA0
    function: TIM2_CH1
    direction: Output
    note: "PWM - 电机 A 相"
  - pin: PA1
    function: TIM2_CH2
    direction: Output
    note: "PWM - 电机 B 相"
  # ... 更多引脚

peripherals:
  - name: "MPU6050 IMU"
    interface: I2C1
    address: "0x68"
    supply: "3.3V"
    note: "中断接 PA4"
  - name: "0.96 OLED"
    interface: I2C1
    address: "0x3C"
    supply: "3.3V"
    note: "SSD1306, 128x64"

port_aliases:
  default_serial:
    vid: "1A86"
    pid: "7523"
    vid_pid: "1A86:7523"
    label: "调试串口"

build:
  platform: "ststm32"
  board: "blackpill_f411ce"
  framework: "stm32cube"
  cpu_freq: 100000000
  monitor_speed: 115200
  upload_protocol: "dfu"

pitfalls:
  - id: 1
    title: "HSE 25MHz vs 8MHz 晶振混淆"
    symptom: "USB 枚举失败"
    category: "时钟"
    status: "已解决"

safety_notes:
  - "该开发板 VIN 和 USB 5V 直接连通，不要同时连接 USB 和外部电源"
  - "3.3V LDO 最大输出 500mA"
```

**导入/导出操作**：
```bash
# 导出单块板卡配置
sinan board export blackpill-f411 > blackpill-f411.yaml

# 导出全部板卡配置（打包）
sinan board export --all > all-boards-$(date +%Y%m%d).tar.gz

# 导入板卡配置
sinan board import blackpill-f411.yaml
```

### 5. 板卡对比

当用户询问"这两块板子哪个更适合"时，输出对比表：

```markdown
## 板卡对比: STM32F411CEU6 vs ESP32-S3

| 维度            | BlackPill F411       | ESP32-S3-DevKit     |
|-----------------|----------------------|---------------------|
| 主频            | 100MHz Cortex-M4     | 240MHz Xtensa LX7 双核 |
| Flash           | 512KB (内部)         | 16MB (外部 SPI)     |
| RAM             | 128KB (内部)         | 512KB (内部) + 8MB PSRAM |
| FPU             | ✓ (FPv4-SP-D16)      | ✗ (无硬件 FPU)      |
| WiFi/BLE        | ✗                    | ✓ (WiFi 4 + BLE 5.0) |
| USB OTG         | ✓ (Full Speed)       | ✓ (Full Speed + Serial JTAG) |
| ADC 精度/通道   | 12-bit / 16ch        | 12-bit / 20ch (但线性度较差) |
| I2C × SPI × UART| 3 × 5 × 3           | 2 × 4 × 3           |
| 低功耗          | STOP模式 ~2mA        | DeepSleep ~5μA      |
| 开发框架        | STM32Cube/HAL/LL     | ESP-IDF/Arduino     |
| 成本 (批量)     | ~¥15                 | ~¥25                |
| 已知坑          | USB 48MHz时钟敏感    | ADC 噪声大、WiFi功耗尖峰 |

### 建议
- **选 F411** 如果：需要确定性实时控制(电机伺服)、硬件 FPU、成熟的工具链
- **选 S3** 如果：需要无线通信、大量RAM缓冲、低成本快速原型
```

## 工具要求

- 文件系统写权限（`~/.sinan/boards/` 目录）
- `i2cdetect`（用于自动外设发现）
- `lsusb` / `udevadm`（用于端口别名验证）

## 工作流程

1. **需求识别**：判断用户是创建新板卡、查询已有板卡、还是修改配置
2. **信息采集**：对于新板卡，逐歩引导用户完成 7 个步骤的信息收集（可随时跳过不适用的步骤）
3. **自动发现**：对已连接的设备自动探测 I2C 总线、串口等信息作为补充
4. **配置持久化**：将板卡配置写入 YAML 文件
5. **踩坑关联**：检查是否已有类似配置的板卡的踩坑记录，提醒用户注意已知问题

## 安全约束

- 板卡配置文件和踩坑记录存储在用户本地 `~/.sinan/` 目录，不上传到任何远程服务器
- 导入配置文件前进行 YAML 格式校验，拒绝非板卡配置文件格式的 YAML
- 板卡配置中的密码/密钥字段（如 WiFi 密码）标记为敏感字段，导出时需用户确认或自动脱敏
- 板卡安全注意事项中包含高压/安全警告项时，每次加载板卡配置都要显示给用户

## 输出格式

```markdown
## 板卡信息: [别名]
[基本信息摘要]

## 引脚映射
[Pin Mux 表]

## 外设连接
[外设清单表]

## 端口别名
[别名 → 当前设备路径]

## 构建配置
[platformio.ini 或 CMake 片段]

## 踩坑记录 (N 条)
[按严重程度排列的已知问题]

## 安全注意事项
[逐条列出]
```
