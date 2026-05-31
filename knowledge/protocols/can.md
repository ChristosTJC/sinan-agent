# CAN 总线协议详解

## 概述

CAN（Controller Area Network）是一种多主、消息广播式的串行通信协议，由博世（Bosch）公司于 1986 年专为汽车电子开发。具有高可靠性和实时性，广泛应用于汽车、工业控制和机器人领域。

## CAN 2.0B 帧格式

### 标准数据帧 (Standard Frame, 11-bit ID)

```
[SOF] [ID 11bit] [RTR] [IDE] [r0] [DLC 4bit] [Data 0-8 bytes] [CRC 15bit] [CRC Del] [ACK] [ACK Del] [EOF 7bit]
```

### 扩展数据帧 (Extended Frame, 29-bit ID)

```
[SOF] [ID 11bit] [SRR] [IDE] [ID 18bit] [RTR] [r1] [r0] [DLC 4bit] [Data 0-8 bytes] [CRC 15bit] [CRC Del] [ACK] [ACK Del] [EOF 7bit]
```

### 帧字段详解

| 字段 | 长度 | 说明 |
|------|------|------|
| SOF (Start of Frame) | 1 bit | 帧起始，显性电平 |
| ID (Identifier) | 11/29 bit | 仲裁域，决定优先级（越小优先级越高） |
| RTR (Remote Transmission Request) | 1 bit | 数据帧=0（显性），远程帧=1（隐性） |
| IDE (ID Extension) | 1 bit | 标准帧=0，扩展帧=1 |
| DLC (Data Length Code) | 4 bit | 数据字节数（0-8） |
| Data | 0-8 bytes | 有效数据载荷（最多 8 字节） |
| CRC | 15 bit | 循环冗余校验 |
| ACK | 2 bit | 应答域（发送方发隐性，接收方回应显性） |
| EOF (End of Frame) | 7 bit | 帧结束标志（7 个隐性位） |

## 总线仲裁机制

CAN 总线采用"线与"逻辑进行非破坏性逐位仲裁：
- **显性电平 (Dominant)**：逻辑 0，差分电压约 2V（CAN_H=3.5V, CAN_L=1.5V）
- **隐性电平 (Recessive)**：逻辑 1，差分电压约 0V（CAN_H=CAN_L=2.5V）
- 总线上任一节点输出显性电平时，总线即为显性
- 仲裁时：先比较 ID，ID 值最小的帧获得总线控制权
- 仲裁失败者自动退出发送，转为接收模式，等待总线空闲后重发
- 仲裁过程不破坏正在发送的数据，无延迟惩罚

**关键推论**：标准帧（11-bit ID）优先级高于扩展帧（29-bit ID），因为 IDE 位在标准帧中为显性。

## 位定时 (Bit Timing)

CAN 位时间由 4 个时间段组成，以时间份额 t_q（Time Quanta）为单位：

```
一个位时间 = Sync_Seg + Prop_Seg + Phase_Seg1 + Phase_Seg2
```

| 段 | 符号 | 典型 t_q 数 | 功能 |
|----|------|------------|------|
| 同步段 | SYNC_SEG | 1 | 同步总线上的各个节点 |
| 传播段 | PROP_SEG | 1-8 | 补偿物理传输延迟 |
| 相位缓冲段 1 | PHASE_SEG1 | 1-8 | 吸收时钟抖动，采样点在此段之后 |
| 相位缓冲段 2 | PHASE_SEG2 | 2-8 | 吸收时钟抖动 |
| 同步跳转宽度 | SJW | 1-4 | 允许的最大相位调整量 |

### 波特率计算

```
波特率 = f_can_clk / (BRP × (1 + TSEG1 + TSEG2))
```

其中：
- `f_can_clk`：CAN 外设输入时钟（通常来自 APB1，STM32F4 为 42 MHz）
- `BRP`：预分频器（Baud Rate Prescaler），1-1024
- `TSEG1 = PROP_SEG + PHASE_SEG1`（以 t_q 计）
- `TSEG2 = PHASE_SEG2`（以 t_q 计）
- 采样点位置 = (1 + TSEG1) / (1 + TSEG1 + TSEG2)

**典型配置（500 kbps, 42 MHz 时钟）**：
- BRP = 7 → t_q = 42 MHz / 7 = 6 MHz, 1 t_q = 166.67 ns
- TSEG1 = 7, TSEG2 = 4
- 波特率 = 42 MHz / (7 × 12) = 500 kbps
- 采样点在 (1+7)/12 = 66.7% 处

## 终端电阻

CAN_H 和 CAN_L 之间必须在总线两端各接一个 120Ω 终端电阻：
- 作用：抑制信号反射，确保阻抗匹配
- 仅两个端点（物理最远端）需要，中间节点不加
- 总电阻 = 120Ω ∥ 120Ω = 60Ω（从任意节点测量 CAN_H 对 CAN_L 的电阻）

**典型接线**：
```
Node 1 ─┬─ 120Ω ─┬─ Node 2 ─── Node 3 ─┬─ 120Ω ─┬─ Node N
        │        │                      │        │
       CAN_H   CAN_L                  CAN_H   CAN_L
```

## 错误处理

CAN 协议设有完善的错误检测与处理机制：

| 错误类型 | 检测机制 | 说明 |
|---------|---------|------|
| 位错误 | 发送方监控 | 发送位与总线实际电平不一致 |
| 填充错误 | 接收方检测 | 5 个连续相同位后应有相反填充位 |
| CRC 错误 | 接收方检测 | 计算 CRC 与接收 CRC 不一致 |
| 格式错误 | 接收方检测 | 固定格式位（CRC Delimiter, ACK Delimiter, EOF）出现错误 |
| 应答错误 | 发送方检测 | ACK Slot 期间未检测到显性位 |

节点根据错误计数器管理状态：Error Active → Error Passive → Bus Off。

## CAN-FD 简介

CAN-FD（CAN with Flexible Data-rate）是对 CAN 2.0 的升级：
- 数据段速率可切换至更高（最高 8 Mbps vs CAN 2.0 的 1 Mbps）
- 数据场扩展至最大 64 字节（vs CAN 2.0 的 8 字节）
- 兼容 CAN 2.0 节点（共存于同一网络）
- STM32G4/H7 系列支持 CAN-FD

## 常见陷阱

1. **遗漏终端电阻**：总线未接 120Ω 终端电阻或仅接一个，导致信号反射、波形畸变、通信异常
2. **位定时配置错误**：采样点位置不合理（<60% 或 >90%），低频时通信正常、高频时出错
3. **终端电阻位置错误**：每个节点都接 120Ω 导致总线电阻过小，驱动能力不足
4. **ID 冲突**：两个节点发送相同 ID 的报文，仲裁机制可能掩盖问题（谁最先发送谁获胜）
5. **总线进入 Bus-Off 状态**：频繁发送错误导致 TEC > 255，节点自动脱离总线，需手动恢复
6. **CAN 收发器供电**：SN65HVD230 等 3.3V 收发器需要稳定的 3.3V 电源，5V 收发器不可直连 3.3V MCU
7. **共模电压范围超限**：不同节点的地电位差过大，超出收发器共模范围（通常 -7V~+12V）

## 调试方法

1. **CAN 分析仪 (USB-CAN)**：最有效的调试工具，可抓取、发送、过滤报文
2. **示波器**：检查 CAN_H/CAN_L 差分波形，验证终端电阻是否存在
3. **中断/状态寄存器**：STM32 CAN 外设提供丰富的错误状态寄存器（ESR/TSR/RF1R），逐一排查
4. **回环模式 (Loopback)**：先将 CAN 设为回环模式，验证发送逻辑正确，再切换到正常模式排查物理层

## 代码示例 (STM32 HAL)

```c
// 配置 CAN 滤波器（接收所有报文）
CAN_FilterTypeDef filter = {0};
filter.FilterBank = 0;
filter.FilterMode = CAN_FILTERMODE_IDMASK;
filter.FilterScale = CAN_FILTERSCALE_32BIT;
filter.FilterIdHigh = 0x0000;
filter.FilterIdLow = 0x0000;
filter.FilterMaskIdHigh = 0x0000;
filter.FilterMaskIdLow = 0x0000;
filter.FilterFIFOAssignment = CAN_RX_FIFO0;
filter.FilterActivation = ENABLE;
HAL_CAN_ConfigFilter(&hcan1, &filter);

// 启动 CAN
HAL_CAN_Start(&hcan1);

// 发送报文
CAN_TxHeaderTypeDef tx_header = {0};
uint8_t tx_data[8] = {0x01, 0x02, 0x03, 0x04};
uint32_t tx_mailbox;

tx_header.StdId = 0x200;           // 标准 ID
tx_header.ExtId = 0;
tx_header.IDE = CAN_ID_STD;        // 标准帧
tx_header.RTR = CAN_RTR_DATA;      // 数据帧
tx_header.DLC = 4;                 // 数据长度
tx_header.TransmitGlobalTime = DISABLE;

HAL_CAN_AddTxMessage(&hcan1, &tx_header, tx_data, &tx_mailbox);

// 中断接收（在 HAL_CAN_RxFifo0MsgPendingCallback 中处理）
HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING);
```
