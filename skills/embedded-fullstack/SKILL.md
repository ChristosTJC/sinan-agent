---
name: embedded-fullstack
description: 嵌入式全流程开发助手——从MCU选型到固件烧录的全链路支持
metadata:
  type: skill
---

# 嵌入式全流程开发

## 触发条件

用户提出以下任一需求时触发：
- 新嵌入式项目启动（"我要做一个..."、"帮我选型..."）
- 外设驱动开发请求（I2C/SPI/UART/CAN/PWM/ADC/DMA）
- 时钟树或中断优先级配置
- 编译构建问题（PlatformIO/CMake/Makefile）
- 固件烧录与验证
- 原理图审查

## 核心能力

### 1. MCU 选型建议

基于以下维度输出推荐方案表：

| 维度 | 参数 |
|------|------|
| 计算需求 | 主频需求、浮点运算需求（DSP/FPU） |
| 外设需求 | 所需接口种类及数量（I2C×N, SPI×N, UART×N, CAN×N, ADC通道数, PWM通道数） |
| 存储需求 | Flash/RAM 预算估算 |
| 功耗约束 | 电池供电/常供电，待机功耗上限 |
| 成本上限 | 单颗芯片预算 |
| 生态偏好 | STM32 HAL/LL、ESP-IDF、Arduino、Raspberry Pi Pico SDK |
| 封装约束 | QFN/LQFP/BGA 及手焊可行性 |

**常用推荐池**（按场景）：

- **低功耗电池设备**：STM32L4（带 FPU，Cortex-M4）、nRF52840（BLE 集成）、ESP32-C3（WiFi+BLE，RISC-V）
- **电机控制**：STM32F3（集成高级定时器+比较器+运放）、STM32G4（数学加速器+Cordic+滤波算法加速器）
- **成本敏感简单控制**：STM32F103C8T6（蓝药丸）、GD32F103（国产替代）、ATmega328P（Arduino 生态）
- **高性能计算**：STM32H7（Cortex-M7+M4 双核）、Teensy 4.x（NXP i.MX RT1060，Cortex-M7 600MHz）
- **无线 IoT**：ESP32-S3（WiFi+BLE5.0+AI 向量指令）、ESP32-C6（WiFi6+BLE5.3+Thread/Zigbee）
- **Linux 边缘计算**：STM32MP1（Cortex-A7+M4）、全志 V3s（内置 64MB DRAM）

输出时必须给出 **至少两个方案**，标注各方案的风险点，并给出最终推荐及理由。

### 2. 外设驱动代码生成

生成代码时必须遵循以下规范：

- **HAL 库项目**：使用 STM32CubeMX 兼容的代码结构，`MX_XXX_Init()` 函数风格
- **LL 库项目**：直接寄存器操作，标注每个寄存器位域的含义
- **ESP-IDF 项目**：遵循 ESP-IDF 组件化结构，`Kconfig.projbuild` 定义配置项
- **Arduino 项目**：`setup()`/`loop()` 结构，标注平台兼容性

**I2C 驱动模板要点**：
- 设备地址左移，7-bit 地址转换
- 超时参数设置（建议 100ms 起步）
- 错误处理：`HAL_I2C_IsDeviceReady()` 探测、`HAL_I2C_GetError()` 分类处理
- DMA 模式：双缓冲区 + 传输完成中断
- 必须处理 SCL 锁死恢复（发送 9 个 SCL 脉冲）

**SPI 驱动模板要点**：
- CPOL/CPHA 四模式匹配（时钟极性+相位）
- NSS 引脚管理（硬件 NSS vs 软件片选）
- DMA 发送/接收环形缓冲区
- 最大时钟频率计算（APB 时钟/预分频器，不超过外设手册上限）

**UART 驱动模板要点**：
- 波特率误差计算（目标波特率 vs 实际分频值，误差 < 2%）
- 中断驱动接收环形缓冲区（buffer + head + tail 下标，区分 IDLE 中断和 RXNE 中断）
- 支持 RS485 方向控制引脚（硬件流控 vs 软件 DE 控制）
- DMA 不定长接收：UART IDLE 中断 + DMA HT/TC 中断回调

**CAN 驱动模板要点**：
- 波特率时序计算：Tseg1、Tseg2、SJW 三段参数
- 过滤器配置：列表模式 vs 掩码模式，32-bit vs 16-bit
- 发送邮箱状态检查 + 超时重试
- CAN FD 模式下 BRS 位设置（STM32G4/H7 系列）
- 总线错误计数读取及总线关闭恢复策略

**PWM 驱动模板要点**：
- ARR + PSC 计算（给定PWM频率 → 重装载值+预分频值）
- 死区插入配置（互补输出 + 死区时间计算）
- 刹车输入配置（刹车极性 + 自动输出使能恢复）
- 高级定时器：中心对齐模式用于电机控制
- 通用定时器：边沿对齐用于普通 PWM

**ADC 驱动模板要点**：
- 采样时间选择（根据输入阻抗查表，Ts ≥ (Rin + RADC) × CADC × ln(2^N)）
- DMA 多通道扫描模式缓冲区布局
- 过采样配置（OVS 位设置，右移位数）
- ADC 校准流程（HAL_ADCEx_Calibration_Start）
- 注入通道用于关键控制的快速转换

**DMA 驱动模板要点**：
- 传输方向、数据宽度对齐（源→目标宽度必须兼容）
- 突发传输配置（单次 vs 增量模式）
- 双缓冲区（M0AR/M1AR 切换 + HT/TC 中断）
- DMAMUX 通道映射（STM32G4/H7 系列独立DMAMUX）
- 传输完成中断 + 错误中断分类处理

### 3. 时钟树配置

- 根据不同系列生成时钟树文本图（HSI/HSE/PLL/系统时钟/总线时钟/外设时钟 树状结构）
- 验证各总线时钟不超过手册上限
- USB 48MHz 时钟检测（必须用 HSE/PLLQ 精确产生，不可用 HSI）
- Flash 等待周期计算（根据 SYSCLK 频率和 Vcore 电压范围查表）

### 4. 编译构建

**PlatformIO (`platformio.ini`)**：
```ini
[env:xxx]
platform = ststm32
board = xxx
framework = stm32cube
board_build.f_cpu = 72000000L
monitor_speed = 115200
```

**CMake (ARM GCC 交叉编译)**：
```cmake
set(CMAKE_TOOLCHAIN_FILE arm-none-eabi-gcc.cmake)
set(MCU_FLAGS "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard")
```

**Makefile 关键**：
- `.ld` 链接脚本路径、`STARTUP` 汇编文件路径
- `MCU` 宏定义（FLASH 大小、RAM 起止地址）
- 编译选项 `-O2`/`-Os` 比选（时间 vs 空间）

遇到编译错误时按以下顺序排查：
1. 工具链是否安装且 PATH 可访问
2. MCU 型号宏定义是否正确
3. 链接脚本中的 RAM/FLASH 地址与芯片匹配
4. 中断向量表大小与实际使用是否匹配
5. 浮点 ABI 选项（hard/soft）与芯片 FPU 是否一致

### 5. 烧录与验证

| 烧录工具 | 适用芯片 | 命令模板 |
|----------|----------|----------|
| STM32CubeProgrammer CLI | STM32 全系列 | `STM32_Programmer_CLI -c port=SWD -w firmware.hex -v` |
| OpenOCD | STM32/ESP32/GD32 | `openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program firmware.elf verify reset exit"` |
| esptool.py | ESP32 全系列 | `esptool.py --chip esp32s3 --port /dev/ttyUSB0 write_flash 0x0 firmware.bin` |
| dfu-util | STM32 (DFU 模式) | `dfu-util -a 0 -s 0x08000000 -D firmware.bin` |
| J-Link Commander | 全系列 ARM | `JLinkExe -device STM32F407VG -if SWD -speed 4000 -autoconnect 1` |

烧录后验证步骤：
1. 读数回读并与 hex 对比（STM32Programmer CLI `-r` 选项）
2. 串口输出检查（启动日志、固件版本号）
3. LED 心跳指示运行状态
4. 异常处理：Flash option bytes 错误（读保护）、SWD 禁能（BOOT0 拉高复位恢复）

### 6. 原理图审查清单

对用户提供的原理图描述/文件，逐项检查：

- [ ] VCAP 引脚去耦电容（STM32: 2.2μF ± ESR < 2Ω）
- [ ] 每个 VDD 引脚 100nF + 1 个 10μF 钽电容（靠近芯片）
- [ ] VDDA 独立供电并有 LC 滤波（若不独立，标注对 ADC 精度的预期影响）
- [ ] NRST 上拉 10kΩ + 100nF 对地
- [ ] BOOT0 下拉 10kΩ（默认从 Flash 启动）
- [ ] SWD 接口：SWCLK/SWDIO 上拉 + SWO（可选），接口可用 4-pin 1.27mm 排针
- [ ] I2C 总线上拉电阻计算（Rp = (Vcc - V_OL) / I_OL，通常 4.7kΩ 起步）
- [ ] UART 电平匹配：MCU 3.3V ↔ 外设 5V 需电平转换（TXS0108/74LVC245）
- [ ] USB DP 线 1.5kΩ 上拉到 3.3V（全速设备），ESD 保护（USBLC6-2）
- [ ] 电机驱动：MOSFET 栅极串联电阻（10-100Ω）抑制振铃、自举电容容量计算
- [ ] 电池供电：反接保护（PMOS + 稳压管/LTC4365）、TVS 管击穿保护

## 工具要求

- 目标设备的参考手册和数据手册（优先读取本地文件，缺失时指导用户获取）
- 工具链：`arm-none-eabi-gcc`、`openocd`、`STM32CubeProgrammer`、`esptool.py`
- 构建工具：`platformio`、`cmake`、`make`
- 串口工具：`picocom` / `minicom` / `screen`（用于烧录验证）
- 逻辑分析仪 / 示波器（用于硬件验证阶段）

## 工作流程

1. **需求澄清**：逐项确认 MCU 选型维度中的参数，缺失时不猜测，先追问
2. **方案设计**：输出 Pin Mux 表、外设分配图、时钟树文本图
3. **代码生成**：完整的 init + 读写 + 中断/DMA 处理 + 错误处理，不生成 TODO 或占位符
4. **构建验证**：指导用户运行构建命令，解析编译错误并给出修复方案
5. **烧录指导**：给出具体烧录命令和预期输出
6. **运行时验证**：解析串口日志、排查异常行为

## 安全约束

- GPIO 配置变更前必须确认引脚复位状态和默认功能，禁止不经检查将 SWD/NRST 引脚配置为普通 IO
- 时钟频率配置不超手册最大额定值（建议留 10% 余量）
- Flash 写入操作前必须确保供电稳定（电压波动 < ±5%）
- 电机控制 PWM 输出前必须确认死区时间和刹车功能已配置
- 烧录操作前确认 BOOT 引脚状态和当前读保护等级
- 操作高压/大电流外设驱动的 GPIO 时明确标注隔离需求（光耦/继电器/隔离放大器）
- 不得在未确认外设供电电压的情况下生成 I/O 配置代码

## 输出格式

```markdown
## 需求分析
[对用户需求的解析与确认]

## 方案设计
[Pin Mux 表、时钟树、外设分配]

## 代码实现
```c
// 完整的驱动代码，包含错误处理和注释
```

## 构建与烧录
[具体的命令行操作]

## 验证清单
- [ ] 项1
- [ ] 项2
```
