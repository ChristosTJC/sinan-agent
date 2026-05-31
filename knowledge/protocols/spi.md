# SPI 总线协议详解

## 概述

SPI（Serial Peripheral Interface）是一种高速、全双工的同步串行通信协议，由摩托罗拉公司开发。采用主从架构，支持一对多通信。

## 信号线定义

### 4 线制（标准模式）
| 信号 | 全称 | 方向 | 说明 |
|------|------|------|------|
| SCLK | Serial Clock | 主→从 | 时钟信号，由主设备产生 |
| MOSI | Master Out Slave In | 主→从 | 主设备数据输出，从设备数据输入 |
| MISO | Master In Slave Out | 从→主 | 从设备数据输出，主设备数据输入 |
| CS/SS | Chip Select / Slave Select | 主→从 | 片选信号，低电平有效 |

### 3 线制（半双工模式）
仅有 SCLK、CS 和一根双向数据线（有时标记为 SISO 或 SDIO）。适用于引脚资源紧张的场景，但只能半双工通信。

## 时钟模式 (CPOL / CPHA)

SPI 有 4 种工作模式，由 CPOL 和 CPHA 两个参数决定：

| 模式 | CPOL | CPHA | 空闲时钟电平 | 数据采样沿 |
|------|------|------|-------------|-----------|
| Mode 0 | 0 | 0 | 低电平 | 第 1 个边沿（上升沿） |
| Mode 1 | 0 | 1 | 低电平 | 第 2 个边沿（下降沿） |
| Mode 2 | 1 | 0 | 高电平 | 第 1 个边沿（下降沿） |
| Mode 3 | 1 | 1 | 高电平 | 第 2 个边沿（上升沿） |

- **CPOL (Clock Polarity)**：决定时钟空闲时的电平状态
- **CPHA (Clock Phase)**：决定数据在第几个时钟边沿被采样
- Mode 0 最为常见，但具体需要查阅从设备数据手册

## 数据传输特性

- **MSB/LSB 优先**：大多数设备 MSB 优先，但部分传感器可能 LSB 优先
- **全双工**：每个时钟周期同时发送和接收一位数据，效率高
- **数据帧大小**：通常 8 位，也可配置为 16 位（STM32 支持 4-16 位）
- **无固定帧格式**：没有起始位、停止位和应答机制，完全由时钟和片选控制

## 时钟速度

SPI 时钟频率取决于主设备和从设备的能力，常见速率：
- 标准：1-10 MHz
- 高速：20-50 MHz
- 超高速：60 MHz 以上

STM32F4 的 SPI 最高时钟为 APB2/2 = 42 MHz（SPI1）或 APB1/2 = 21 MHz（SPI2/3）。

## 菊花链 (Daisy-Chaining)

多个 SPI 从设备共享相同的 SCLK、MOSI、MISO 和 CS 信号线，但数据从一个设备串行传递到下一个设备。所有设备共享片选，数据依次移位经过整个链条。

优点：仅需一个片选信号
缺点：延迟随设备数量线性增长；任一设备故障影响整条链

## 片选 (CS) 管理

- **硬件 CS (NSS)**：由 SPI 外设自动控制，速度快但固定引脚
- **软件 CS**：通过 GPIO 手动拉低/拉高，灵活但稍慢
- 每次传输前拉低 CS，传输结束后拉高 CS
- 从设备通过 CS 的上升沿识别帧结束

## 常见陷阱

1. **时钟模式不匹配**：最常见的通信失败原因，不同设备对 CPOL/CPHA 要求不同
2. **时钟极性与采样沿混淆**：CPOL=0/CPHA=0 (Mode 0) 与 CPOL=0/CPHA=1 (Mode 1) 的区别需仔细确认
3. **片选信号毛刺**：软件 CS 切换时，如果 CS 和时钟/数据不同步，从设备可能误判帧边界
4. **电平不匹配**：3.3V 主设备驱动 5V 从设备时 MISO 可能超过主设备耐压
5. **时钟速度超限**：从设备有最大 SPI 时钟频率限制，超过会导致数据错误
6. **MISO 浮空**：未被选中的从设备 MISO 应处于高阻态，否则会与选中设备冲突
7. **布线长度**：高速 SPI 走线应尽量短，必要时串联 22-33Ω 终端电阻抑制反射

## 调试方法

1. **逻辑分析仪**：同时抓取 SCLK、MOSI、MISO、CS 四路信号，逐一对比波形与数据手册
2. **降低时钟**：先用最低速度（如 100 kHz）验证基本通信，再逐步提升
3. **读取已知寄存器**：如 WHO_AM_I 或设备 ID 寄存器，确认读操作正确
4. **回环测试**：将 MOSI 与 MISO 短接，发送数据验证接收一致

## 代码示例 (STM32 HAL)

```c
// 配置 SPI1: Mode 0, MSB first, 8-bit, 10 MHz
// CubeMX 生成后直接使用以下 API：

// 全双工收发
uint8_t tx_buf[2] = {0x80, 0x00};  // 读寄存器 0x00
uint8_t rx_buf[2] = {0};

HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_RESET);  // 拉低 CS
HAL_SPI_TransmitReceive(&hspi1, tx_buf, rx_buf, 2, 100);
HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_SET);    // 拉高 CS

// 仅发送
uint8_t cmd = 0x8F;  // 写命令
HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_RESET);
HAL_SPI_Transmit(&hspi1, &cmd, 1, 100);
HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_SET);
```
