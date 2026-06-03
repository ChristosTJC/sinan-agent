# SWD 调试协议详解

## 概述

SWD（Serial Wire Debug）是 ARM Cortex-M 系列处理器的标准双线调试接口，由 ARM 公司定义，作为传统 5 线 JTAG 的替代方案。SWD 仅需两根信号线即可完成调试和编程，引脚复用少，特别适合空间受限的嵌入式场景。

与 JTAG 的对比：

| 特性 | JTAG | SWD |
|------|------|-----|
| 信号线数 | 5 (TDI/TDO/TMS/TCK/nTRST) | 2 (SWDIO/SWCLK) |
| 最小引脚占用 | TCK + TMS = 2 (仅边界扫描) | SWDIO + SWCLK = 2 (全功能) |
| 调试功能 | 完整 | 完整 |
| 传输效率 | 每次传输可多位 | 每次传输 32 位 + 奇偶校验 |
| 常用调试器 | J-Link, ULINK | ST-Link, J-Link, DAPLink |

## 信号线定义

| 信号 | 全称 | 方向 | 说明 |
|------|------|------|------|
| SWDIO | Serial Wire Data I/O | 双向 | 数据线，由调试器驱动或目标响应 |
| SWCLK | Serial Wire Clock | 调试器→目标 | 时钟线，由调试器驱动 |
| SWO | Serial Wire Output | 目标→调试器 | 可选，用于 ITM/printf 重定向输出 |
| nRESET | Reset | 调试器→目标 | 可选，目标复位信号 |

> **注意**：SWDIO 和 SWCLK 分别复用 JTAG 的 TMS 和 TCK 引脚。在 STM32 上，SWDIO = PA13，SWCLK = PA14。

## 电气特性

- **电平标准**：通常 3.3V（部分支持 1.8V，如 STM32L 系列和 nRF52）
- **SWDIO 上拉**：内部或外部 100 kΩ 上拉至 VCC，防止浮空
- **SWCLK 上拉**：内部或外部 100 kΩ 下拉至 GND，确保空闲时为低
- **SWCLK 频率**：典型 1-5 MHz，高端调试器可达 50 MHz
- **输入阈值**：VIH ≥ 0.7 × VCC，VIL ≤ 0.3 × VCC

实际应用中，若 PCB 走线较长或排线质量不佳，建议在 SWDIO 和 SWCLK 上各串联 22-33 Ω 电阻以抑制信号反射。

## 协议层

### 数据包格式

SWD 事务由调试器发起，每包包含以下字段（按位序排列）：

```
[Start] [APnDP] [RnW] [A[2:3]] [Parity] [Stop] [Park] [Trn] [Data 32bit + Parity] [Trn]
|<---           8-bit 请求头            --->|                           |<-- 数据阶段 -->|
```

### 请求头各字段说明

| 字段 | 位数 | 值 | 说明 |
|------|------|-----|------|
| Start | 1 | 1 | 起始位，固定为 1 |
| APnDP | 1 | 0/1 | 0=DP 寄存器访问, 1=AP 寄存器访问 |
| RnW | 1 | 0/1 | 0=写操作, 1=读操作 |
| A[2:3] | 2 | 00/01/10/11 | DP/AP 寄存器地址 |
| Parity | 1 | 0/1 | 对 APnDP、RnW、A[2:3] 的奇校验（偶数个 1 时 Parity=1） |
| Stop | 1 | 0 | 停止位，固定为 0 |
| Park | 1 | 1 | 驻留位，固定为 1（调试器驱动为高） |
| Trn | 1 | - | 周转周期，此时 SWDIO 切换驱动方向（读操作时为高阻） |

### 数据阶段

- 32 位数据（LSB 优先），后跟 1 位奇偶校验（对 32 位数据做偶校验）
- 读操作：数据阶段由目标驱动 SWDIO
- 写操作：数据阶段由调试器驱动 SWDIO
- 数据阶段前后各有 1 个 Trn 周期（周转周期）

### 时序示意

```
SWCLK: _/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_/‾\_   _/‾\_/‾\_/‾\_ ... _/‾\_/‾\_
         S  AP  R  A2 A3 P  St Pk Tn         D0   D1      D31  P  Tn
SWDIO: ---[1]-[x]-[x]-[x]-[x]-[x]-[0]-[1]---[x]---[x]--...--[x]-[x]------
          |<----- 请求头 8 bit ----->| Trn   |<--- 数据 33 bit --->|
          调试器驱动                                      读:目标驱动 / 写:调试器驱动
```

## DP（Debug Port）寄存器

DP 寄存器通过 A[2:3] 字段寻址，以下是 ARM CoreSight 标准 DP 寄存器：

| A[2:3] | 读操作 | 写操作 | 寄存器名称 | 说明 |
|--------|--------|--------|-----------|------|
| 00 | IDCODE | ABORT | IDCODE / ABORT | 读：获取调试器识别码；写：中止当前传输 |
| 01 | CTRL/STAT | CTRL/STAT | Control/Status | **关键寄存器**，控制上电请求和传输模式 |
| 10 | RESEND | SELECT | AP Select | 选择目标 AP 的 APSEL 和 APBANKSEL |
| 11 | RDBUFF | - | Read Buffer | 读操作结果缓冲（读 AP 数据后从此寄存器取回） |

### CTRL/STAT 寄存器关键位

```
CTRL/STAT (0x4) 位定义:
  bit[0]  : ORUNDETECT — 上电检测标志
  bit[28] : CDBGPWRUPREQ — 调试域电源请求 (写 1 使能)
  bit[29] : CDBGPWRUPACK — 调试域电源确认 (读, 硬件置 1 表示已上电)
  bit[30] : CSYSPWRUPREQ — 系统域电源请求 (写 1 使能)
  bit[31] : CSYSPWRUPACK — 系统域电源确认 (读, 硬件置 1 表示已上电)
```

**关键操作**：上电后必须先写 CTRL/STAT 的 CDBGPWRUPREQ (bit 28) 和 CSYSPWRUPREQ (bit 30)，然后轮询对应的 ACK 位直到两者均为 1，才能访问 AP 寄存器。

## AP（Access Port）寄存器

AP 通过 DP SELECT 寄存器切换。常见 AP 类型：

| APSEL 值 | AP 类型 | 说明 |
|----------|---------|------|
| 0x0 | AHB-AP / AHB3-AP | 通过 AHB 总线访问目标内存和外设 |
| 0x1 | APB-AP | 通过 APB 总线访问（部分 Cortex-M0/M0+ 使用） |
| 0xF | JTAG-AP | 切换到 JTAG 模式（用于支持 JTAG 的器件） |

### AHB-AP 寄存器（APBANKSEL 子地址）

| APBANKSEL | 偏移 | 寄存器 | 说明 |
|-----------|------|--------|------|
| 0x0 | 0x00 | CSW | Control/Status Word — 配置传输大小 (8/16/32 bit) 和地址自增 |
| 0x0 | 0x04 | TAR | Transfer Address Register — 目标内存地址 |
| 0x0 | 0x0C | DRW | Data Read/Write — 读写目标内存数据 |
| 0x1 | 0x00 | BD0-3 | Banked Data 0-3（批量地址传输模式） |
| 0xF | 0xFC | IDR | AP Identification Register — 确认 AP 类型和版本 |

### CSW 寄存器关键位

```
CSW 关键位:
  bit[2:0] SIZE: 传输宽度 — 0x0=8bit, 0x1=16bit, 0x2=32bit
  bit[4]   AddrInc: 地址自增 — 0=固定地址, 1=单次自增, 2=打包模式
  bit[7]   HPROT1: 用户/特权模式
```

## 连接序列

上电或复位后，标准 SWD 连接序列如下：

1. **SWD 模式切换（JTAG-to-SWD）**：发送至少 50 个 SWCLK 周期，SWDIO 保持高电平，然后发送 SWD 连接序列（0xE79E 按特定时序），将 JTAG 接口切换为 SWD 模式
2. **读取 IDCODE**：通过 DP 读 A[2:3]=00，确认调试器与目标连接正常。STM32F4 的 IDCODE 典型值为 0x2BA01477
3. **使能调试电源**：写 CTRL/STAT (A[2:3]=01)，置 CDBGPWRUPREQ 和 CSYSPWRUPREQ 为 1，轮询 ACK 位确认上电完成
4. **配置传输参数**：通过 SELECT (A[2:3]=10) 选择 APSEL=0(AHB-AP)，设置 APBANKSEL=0(CSW/TAR/DRW)
5. **配置 CSW**：通过 AP 写 CSW 寄存器，设置 SIZE=32bit, AddrInc=1(自增)
6. **设置目标地址**：通过 AP 写 TAR 寄存器，指定要访问的 Flash/SRAM/外设地址
7. **读写数据**：通过 AP 读写 DRW 寄存器，完成实际数据传输

### 连接序列伪代码

```
// 1. 切换至 SWD 模式
for (i = 0; i < 50; i++) SWD_WriteBit(1);       // 50+ SWCLK, SWDIO=1
SWD_WriteSequence(0xE79E);                       // JTAG-to-SWD 切换序列

// 2. 读取 IDCODE
uint32_t idcode = SWD_DP_Read(DP_IDCODE);        // APnDP=0, RnW=1, A[2:3]=00

// 3. 使能调试域和系统域电源
SWD_DP_Write(DP_CTRL_STAT, (1 << 28) | (1 << 30)); // CDBGPWRUPREQ | CSYSPWRUPREQ
while ((SWD_DP_Read(DP_CTRL_STAT) & 0xA0000000) != 0xA0000000); // 等待 ACK

// 4. 选择 AHB-AP
SWD_DP_Write(DP_SELECT, 0x00000000);             // APSEL=0, APBANKSEL=0

// 5. 配置 CSW
SWD_AP_Write(AP_CSW, 0x23000002);                // 32-bit, 自增地址模式

// 6-7. 读写目标内存
SWD_AP_Write(AP_TAR, 0x08000000);                // 设置地址 (STM32 Flash 基址)
uint32_t data = SWD_AP_Read(AP_DRW);             // 读取数据
```

## 传输速率与限制

| 调试器 | 最大 SWCLK | 说明 |
|--------|-----------|------|
| ST-Link V2 | 4 MHz | 常规调试足够 |
| ST-Link V2.1 | 9 MHz | 集成于 Nucleo 板载 |
| ST-Link V3 | 24 MHz | 高速烧录，需短排线 |
| J-Link EDU | 15 MHz | 教育版限制 |
| J-Link Plus/Ultra+ | 50 MHz | 理论最大速率 |
| DAPLink (CMSIS-DAP v1) | 1 MHz | HID 模式，速度受限 |
| DAPLink (CMSIS-DAP v2) | 10 MHz | 批量传输，速度显著提升 |

理论最大值 50 MHz，但实际受 PCB 走线长度、排线质量、目标芯片 SWD 接口的 IO 翻转速度限制，通常稳定工作在 5-10 MHz。使用 20 cm 以上排线时建议降至 1-2 MHz。

## 常见陷阱

1. **SWDIO / SWCLK 未上拉 / 下拉**：SWDIO 未接上拉电阻会导致总线浮空，调试器无法识别目标；SWCLK 未接下拉导致噪声误触发
2. **目标 MCU 进入低功耗模式后 SWD 不可用**：SLEEP、STOP、STANDBY 模式下调试域时钟被关断（除非配置 DBGMCU 寄存器保持调试时钟），需要先唤醒 MCU 再连接
3. **PA13/PA14 被误配置为 GPIO**：代码中将 PA13(SWDIO) 或 PA14(SWCLK) 配置为普通 GPIO 输出后，调试器无法连接。解决办法：拉低 nRESET 的同时发起连接（Connect Under Reset），在复位释放前恢复 SWD 功能；或使用 BOOT0=1 从系统存储器启动
4. **长排线引入反射和串扰**：超过 15 cm 的排线会导致信号完整性下降，表现为偶尔连接成功但频繁断开。应对：降低 SWCLK 频率、使用屏蔽线缆、串接 22-33 Ω 终端电阻
5. **ST-Link 固件版本过旧与目标芯片不兼容**：较新的 STM32 芯片（如 G4、H7 系列）需要 ST-Link 固件升级后才能识别。使用 STM32CubeProgrammer 或 ST-Link Utility 检查并更新固件
6. **JTAG/SWD 接口复用冲突**：部分调试器同时驱动 JTAG 和 SWD，在 OpenOCD 配置中必须明确指定 `transport select swd`，否则默认 JTAG 模式导致连接失败
7. **目标板供电不足或未上电**：ST-Link 的 VAPP 引脚可为目标板提供 3.3V 电源，但最大输出电流仅 100-300 mA。耗电较大的目标板（带显示屏、大功率外设）应独立供电

## 代码示例

### STM32 HAL — 恢复 SWD 引脚为调试功能（在误配为 GPIO 后修复）

```c
// 情况：代码中将 PA13 或 PA14 复用为 GPIO 后无法连接调试器
// 修复方法：启动时加入延迟，给调试器连接窗口

// main.c 开头插入：
void delay_ms_swd_recovery(uint32_t ms) {
    volatile uint32_t delay = ms * 8000;  // 粗粒度延迟
    while (delay--) { __NOP(); }
}

// 在 HAL_Init() 前调用，确保调试器有时间在复位释放后连接
int main(void) {
    delay_ms_swd_recovery(300);  // 等待 300ms，给调试器连接窗口
    HAL_Init();
    // ... 其余初始化
}
```

> **若已锁死**：按住复位键不放 → 调试器发起连接 → 立即执行全片擦除 → 释放复位键。此方法利用复位期间 SWD 引脚保持调试功能的时间窗口。

### OpenOCD 脚本示例

```tcl
# openocd.cfg — 连接 STM32F407 通过 ST-Link/SWD
source [find interface/stlink.cfg]
transport select swd
source [find target/stm32f4x.cfg]

# 降低 SWCLK 频率（适用于长排线场景）
adapter speed 500

# 连接时拉低复位（防止 SWD 引脚已被代码复用）
reset_config srst_only srst_nogate
```

```bash
# 命令行：烧录固件
openocd -f openocd.cfg \
  -c "init" \
  -c "reset init" \
  -c "flash write_image erase build/firmware.hex" \
  -c "reset run" \
  -c "shutdown"

# 命令行：解锁被锁死的 STM32（Read Protection Level 1）
openocd -f openocd.cfg \
  -c "init" \
  -c "reset halt" \
  -c "stm32f4x unlock 0" \
  -c "shutdown"
```

## 调试方法

1. **逻辑分析仪检查波形**：同时抓取 SWCLK 和 SWDIO，观察起始位是否出现、数据是否翻转、是否有持续的 ACK 响应（OK=0b001, WAIT=0b010, FAULT=0b100）
2. **检查目标板上电状态**：用万用表测量 VCC 对 GND 是否稳定在 3.3V，确认 MCU 的 NRST 引脚是否为高电平（未处于复位状态）
3. **降低 SWCLK 频率**：从高频降到最低（100-500 kHz），排除信号完整性问题。OpenOCD 使用 `adapter speed 100` 或 `-c "adapter speed 100"`
4. **ST-Link Utility 或 J-Link Commander 验证基本连接**：使用厂商提供的 GUI/CLI 工具单独测试，判断问题出在硬件链路还是 OpenOCD/pyOCD 配置层面
5. **J-Link Commander 命令示例**：
   ```
   connect          → 选择目标芯片
   device STM32F407VG
   si swd           → 选择 SWD 接口
   speed 1000       → 设置 SWCLK 频率
   mem32 0x08000000 1 → 读取 Flash 基址第一个 word
   ```
6. **Connect Under Reset**：在 OpenOCD 中配置 `reset_config srst_only srst_nogate`，调试器连接时主动拉低 nRESET，释放后立即接管 SWD 接口
