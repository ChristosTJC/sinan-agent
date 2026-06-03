# USB DFU 协议与设备固件升级

## 概述

DFU（Device Firmware Upgrade）是 USB-IF 定义的标准设备固件升级协议，属于 USB 设备类规范。无需专用编程器或调试器，仅通过 USB 线缆即可完成固件烧录和升级。

- **USB 设备类代码**：Class = 0xFE (Application Specific), Subclass = 0x01 (Device Firmware Upgrade)
- **传输端点**：仅使用端点 0（Control Transfer），无需额外端点
- **广泛支持**：STM32（系统存储器 Bootloader）、ESP32-S3（ROM Bootloader）、nRF52（DFU Bootloader）、RP2040（RP2 Boot）

## 协议分层

DFU 协议在标准 USB 协议栈之上增加了两层：

```
┌─────────────────────────────────┐
│         DFU 状态机              │  ← 设备固件升级的状态流转
├─────────────────────────────────┤
│    DFU 类特定请求 (bRequest)    │  ← 标准 USB Setup 包中的 bRequest 字段
├─────────────────────────────────┤
│  USB 控制传输 (端点 0)          │  ← 标准 USB Control Transfer，数据在 DATA 阶段传输
├─────────────────────────────────┤
│  USB 总线层 (电气/数据包/握手)   │
└─────────────────────────────────┘
```

## DFU 功能描述符

DFU 设备必须在 USB 描述符链中包含 DFU Functional Descriptor。该描述符紧跟在接口描述符之后：

```
偏移   字段              长度    说明
0x00   bLength            1     描述符长度 (通常 0x09 或 0x07)
0x01   bDescriptorType    1     描述符类型 = 0x21 (DFU Functional)
0x02   bmAttributes       1     属性位掩码
0x03   wDetachTimeOut     2     切换到 DFU 模式的最大等待时间 (ms)
0x05   wTransferSize      2     单次 DFU_DNLOAD / DFU_UPLOAD 最大传输字节数
0x07   bcdDFUVersion      2     DFU 规范版本 (通常 0x0110 = v1.1)
```

### bmAttributes 位定义

| 位 | 名称 | 说明 |
|----|------|------|
| 0-3 | Version | DFU 协议版本号 |
| 3 | WillDetach | 1=设备收到 DFU_DETACH 后自动断开并重新枚举为 DFU 模式 |
| 4 | ManifestationTolerant | 1=设备在 manifest 阶段可以容忍主机延迟 |
| 5 | CanUpload | 1=支持 DFU_UPLOAD（上传当前固件） |
| 6 | CanDnload | 1=支持 DFU_DNLOAD（下载新固件） |
| 7 | Reserved | 保留，必须为 0 |

典型值：`bmAttributes = 0x0F` 表示 WillDetach=1, ManifestationTolerant=1, CanUpload=1, CanDnload=1。

## DFU 类特定请求

所有 DFU 请求通过 USB Setup 包在端点 0 上传输，使用 `bmRequestType = 0x21`（Class, Interface, Host-to-Device）：

| bRequest | 值 | 方向 | 说明 |
|----------|-----|------|------|
| DFU_DETACH | 0x00 | 输出 | 请求设备切换到 DFU 模式并断开 USB |
| DFU_DNLOAD | 0x01 | 输出 | 下载固件数据块到设备 |
| DFU_UPLOAD | 0x02 | 输入 | 从设备上传当前固件数据 |
| DFU_GETSTATUS | 0x03 | 输入 | 查询设备当前状态和传输进度 |
| DFU_CLRSTATUS | 0x04 | 输出 | 清除错误状态（将设备从 dfuERROR 恢复至 dfuIDLE） |
| DFU_GETSTATE | 0x05 | 输入 | 仅获取当前状态（不返回进度信息） |
| DFU_ABORT | 0x06 | 输出 | 中止当前传输，回到 dfuIDLE 状态 |

### DFU_GETSTATUS 返回数据结构

```
字节 0         : bStatus        — 状态码 (0x00=OK, 0x01-0x0B=错误)
字节 1-3       : bwPollTimeout  — 主机在下一次轮询前的等待时间 (ms)，24 位小端
字节 4         : bState         — 当前 DFU 状态
字节 5         : iString        — 错误描述字符串索引 (0=无)
```

## DFU 状态机

设备在 DFU 协议中遵循严格的状态机模型：

```
appIDLE ──(DFU_DETACH)──→ appDETACH
appDETACH ──(自动断开)──→ dfuIDLE (重新枚举为 DFU 设备)

dfuIDLE ──(DFU_DNLOAD, 长度>0)──→ dfuDNLOAD-SYNC
dfuIDLE ──(DFU_DNLOAD, 长度=0)──→ dfuMANIFEST-SYNC
dfuIDLE ──(DFU_UPLOAD)──────────→ dfuUPLOAD-IDLE

dfuDNLOAD-SYNC ──(轮询完成)──→ dfuDNBUSY (设备处理数据)
dfuDNBUSY ──(处理完成)───────→ dfuDNLOAD-IDLE
dfuDNLOAD-IDLE ──(DFU_DNLOAD, 长度>0)──→ dfuDNLOAD-SYNC
dfuDNLOAD-IDLE ──(DFU_DNLOAD, 长度=0)──→ dfuMANIFEST-SYNC

dfuMANIFEST-SYNC ──(轮询完成)──→ dfuMANIFEST (校验+写入)
dfuMANIFEST ──(需要复位)───────→ dfuMANIFEST-WAIT-RESET
dfuMANIFEST-WAIT-RESET ──(复位)──→ appIDLE (启动新固件)

任何状态 ──(DFU_ABORT)──→ dfuIDLE
dfuERROR ──(DFU_CLRSTATUS)──→ dfuIDLE
```

### 状态码速查

| 状态 | 值 | 说明 |
|------|-----|------|
| appIDLE | 0 | 正常运行模式 |
| appDETACH | 1 | 等待切换到 DFU 模式 |
| dfuIDLE | 2 | DFU 空闲，等待请求 |
| dfuDNLOAD-SYNC | 3 | 等待下载数据同步 |
| dfuDNBUSY | 4 | 正在处理下载数据 |
| dfuDNLOAD-IDLE | 5 | 下载区块完成，等待下一块 |
| dfuMANIFEST-SYNC | 6 | 等待 Manifest 同步 |
| dfuMANIFEST | 7 | Manifest 阶段 |
| dfuMANIFEST-WAIT-RESET | 8 | 等待主机发起复位 |
| dfuUPLOAD-IDLE | 9 | 上传空闲 |
| dfuERROR | 10 | 错误状态 |

## 固件下载流程

标准 DFU 固件下载的完整交互流程：

1. **发送 DFU_DNLOAD (块 0)**：主机将固件文件头部（通常包含固件大小、版本信息）通过第一个 DFU_DNLOAD 发送。wBlockNum = 0，wLength = 头部大小
2. **设备进入 dfuDNLOAD-SYNC**：设备收到数据后进入该状态，开始处理头部
3. **主机轮询 DFU_GETSTATUS**：主机周期性发送 GETSTATUS，直到 bState 变为 dfuDNLOAD-IDLE（表示设备已准备好接收下一块数据）
4. **继续发送数据块**：重复步骤 1-3，每次递增 wBlockNum，发送后续固件数据块。每块大小不超过 wTransferSize
5. **发送零长度 DFU_DNLOAD**：所有数据传输完毕后，主机发送 wLength=0 的 DFU_DNLOAD，表示传输结束
6. **设备进入 dfuMANIFEST 阶段**：设备进行固件校验（CRC/签名验证）并写入内部 Flash
7. **设备重新枚举或复位**：Manifest 完成后，设备断开 USB 连接并重新枚举（WillDetach=1）或执行软复位，启动新固件

### 时序示意

```
主机                                                     设备(DFU 模式)
 |── DFU_DNLOAD(wBlock=0, 数据)─────────────────────────→|
 |                     ←── ACK (设备进入 dfuDNLOAD-SYNC)──|
 |                                                                    设备处理数据
 |── DFU_GETSTATUS ─────────────────────────────────────→|
 |                     ←── [status=OK, state=dfuDNBUSY]──|
 |── DFU_GETSTATUS ─────────────────────────────────────→|
 |                     ←── [status=OK, state=dfuDNLOAD-IDLE, 轮询时间=1ms]──|
 |── DFU_DNLOAD(wBlock=1, 数据)─────────────────────────→|
 |                     ←── ACK ──────────────────────────|
                              ⋮ (重复直到所有块传输完毕)
 |── DFU_DNLOAD(wBlock=N, wLength=0)────────────────────→|
 |                     ←── ACK ──────────────────────────|
 |── DFU_GETSTATUS ─────────────────────────────────────→|
 |                     ←── [state=dfuMANIFEST-WAIT-RESET]──|
 |── (主机发起 USB 复位或设备自动复位) ───────────────────|
                                                             设备启动新固件
```

## 各平台 DFU 进入方式

| 平台 | 进入方法 | VID:PID (DFU 模式) | 烧录工具 |
|------|---------|-------------------|---------|
| STM32 (系统 Bootloader) | BOOT0=1 上电或软件跳转 | 0483:df11 | STM32CubeProgrammer, stm32flash, dfu-util |
| STM32 (USB DFU Bootloader 自定义) | 应用程序中调用跳转函数 | 用户自定义 | dfu-util |
| ESP32-S3 | GPIO0=0 上电或软件复位进入 ROM Bootloader | 303a:0002 (USB-Serial-JTAG) | esptool, dfu-util |
| nRF52840 | 按住 IF BOOT (P1.02) 上电或 `nrf_power_gpregret_set()` 后复位 | 1915:521F | nrfutil, adafruit-nrfutil |
| RP2040 | 上电时 BOOTSEL=0 | 2E8A:0003 (RP2 Boot, 大容量存储 + UF2) | 拖拽 .uf2 文件到虚拟磁盘 |
| AT32 (Artery) | BOOT0=1 上电 | 2E3C:df11 | Artery ISP Programmer, dfu-util |

> **注意**：STM32 系统存储器 DFU Bootloader 仅支持 USART1 和 USB 二选一，由 BOOT1 引脚决定选择何种接口。BOOT1=0 选择 USB DFU，BOOT1=1 选择 USART1。

## 常见陷阱

1. **Manifest 阶段 Flash 写入失败导致变砖**：固件校验通过但 Flash 物理写入失败（供电不稳、Flash 损坏）。此时设备可能无法正常启动，需要用 SWD/JTAG 强制恢复
2. **DFU_DETACH 的 wDetachTimeOut 太短**：描述符中设置的超时时间过短，主机来不及在超时前发起 DFU 模式下的后续请求，表现为设备断开后再也无法识别
3. **USB 供电不足**：目标板在 Flash 写入期间耗电骤增，若仅靠 USB VBUS 供电（500 mA 上限），可能导致供电电压跌落、MCU 复位，写入中断后固件损坏（变砖）
4. **DFU 文件后缀 (DFU Suffix) 不匹配**：.dfu 文件末尾的 DFU suffix 包含 bcdDFU 版本号和 bcdDevice 设备版本号。dfu-util 默认校验这些字段，不匹配时拒绝烧录。使用 `dfu-util --force` 可跳过校验
5. **dfu-util 的 --alt 参数错误**：DFU 设备可能有多个 Alternate Settings。alt=0 通常代表内部 Flash，但具体映射需查阅设备文档（`dfu-util --list` 可列出所有 setting）
6. **操作系统驱动冲突**：Windows 上 STM DFU 设备可能被识别为 "STM Device in DFU Mode" 但缺少驱动。需安装 STM32CubeProgrammer 附带的 DFU 驱动或使用 Zadig 安装 WinUSB 驱动
7. **STM32 BOOT1 引脚配置错误**：部分 STM32 型号（如 F103、F2）需要正确配置 BOOT1 引脚选择 USB 接口，否则 Bootloader 进入 USART 模式而非 DFU 模式

## 调试方法

1. **lsusb 检查 DFU 设备识别**：
   ```bash
   lsusb | grep -i dfu
   # 输出示例: Bus 001 Device 015: ID 0483:df11 STMicroelectronics STM Device in DFU Mode
   ```
2. **dfu-util --list 列出设备详情**：
   ```bash
   dfu-util --list
   # 显示 DFU 设备、VID:PID、wTransferSize、各 Alternate Setting 的映射目标
   ```
3. **dmesg 查看 USB 枚举日志**：
   ```bash
   dmesg -w | grep -i usb
   # 观察设备插入时的枚举过程、描述符解析是否成功
   ```
4. **Wireshark USB 抓包**：在 Linux 上加载 `usbmon` 模块（`modprobe usbmon`），用 Wireshark 抓取 Setup 包和 Data 包，逐一检查 DFU 类请求的 bRequest、wValue、wLength 是否符合预期
5. **缩短 wTransferSize 排查数据块大小问题**：在 dfu-util 命令中添加 `--transfer-size 64`，逐步缩小单次传输量，排查大块数据传输引起的超时或缓冲区溢出

## 代码示例

### dfu-util 命令行操作

```bash
# 列出所有 DFU 设备及其 Alternate Settings
dfu-util --list

# 读取当前固件到文件 (备份)
dfu-util --alt 0 --upload firmware_backup.bin

# 烧录固件 (STM32, Alternate Setting 0 = 内部 Flash)
dfu-util --alt 0 --download build/firmware.bin

# 烧录 .dfu 格式文件并跳过 bcdDevice 校验
dfu-util --alt 0 --force --download firmware.dfu

# 全片擦除 (发送 0 字节数据触发 mass erase)
dfu-util --alt 0 --download '' --force

# 烧录后自动复位 (--detach 通知设备复位并重新枚举)
dfu-util --alt 0 --download firmware.bin --detach

# 指定 VID:PID 避免选择错误设备
dfu-util --device 0483:df11 --alt 0 --download firmware.bin
```

### STM32CubeProgrammer CLI DFU 命令

```bash
# 通过 DFU 烧录 HEX 文件
STM32_Programmer_CLI -c port=usb1 -w build/firmware.hex -v -rst

# 读取当前固件
STM32_Programmer_CLI -c port=usb1 -r flash_backup.bin 0x08000000 0x100000

# 全片擦除
STM32_Programmer_CLI -c port=usb1 -e all

# 解除读保护 (RDP Level 1 → Level 0, 会触发全片擦除)
STM32_Programmer_CLI -c port=usb1 -rdu
```

### STM32 HAL 软件跳转至 DFU Bootloader

```c
// 应用程序中主动跳转至 STM32 系统存储器 Bootloader (USB DFU 模式)
// 适用于需要固件升级时由应用程序触发的场景

void jump_to_dfu_bootloader(void) {
    typedef void (*pFunction)(void);
    pFunction bootloader_entry;

    // 1. 关闭所有外设和中断
    HAL_RCC_DeInit();
    HAL_DeInit();
    __disable_irq();

    // 2. 恢复 RCC 到复位状态
    RCC->CR |= RCC_CR_HSION;
    RCC->CFGR = 0x00000000;
    while ((RCC->CR & RCC_CR_HSIRDY) == 0);

    // 3. 禁用 SysTick 并清除其中断
    SysTick->CTRL = 0;
    SysTick->LOAD = 0;
    SysTick->VAL = 0;
    SCB->ICSR |= SCB_ICSR_PENDSTCLR_Msk;

    // 4. 清除所有中断使能和挂起标志
    for (uint8_t i = 0; i < 8; i++) {
        NVIC->ICER[i] = 0xFFFFFFFF;
        NVIC->ICPR[i] = 0xFFFFFFFF;
    }

    // 5. 重新使能中断（Bootloader 需要）
    __enable_irq();

    // 6. 重映射到系统存储器 (0x1FFF0000 for STM32F4, 不同系列地址不同)
    SYSCFG->MEMRMP = 0x01;  // 系统存储器映射到 0x00000000
    __DSB();
    __ISB();

    // 7. 设置主堆栈指针并跳转
    uint32_t bootloader_addr = 0x1FFF0000;  // STM32F4 系统存储器基址
    __set_MSP(*(volatile uint32_t *)bootloader_addr);
    bootloader_entry = (pFunction)(*(volatile uint32_t *)(bootloader_addr + 4));
    bootloader_entry();

    // 永远不会到达这里
    while (1);
}

// 调用示例: 检测到某个 GPIO 按下或串口升级命令后
void check_firmware_update_request(void) {
    if (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_0) == GPIO_PIN_SET) {
        // 可选: 在备份寄存器中写入标记，通知 Bootloader 进入 DFU 模式
        // RTC_BKP_DR0 或 TAMP_BKP0R 可用作标记
        jump_to_dfu_bootloader();
    }
}
```

> **STM32 系列系统存储器基址速查**：
> - STM32F0: 0x1FFFEC00
> - STM32F1 (XL-Density): 0x1FFFF000
> - STM32F2/F4: 0x1FFF0000
> - STM32F7/H7: 0x1FF00000
> - STM32G0: 0x1FFF0000
> - STM32G4: 0x1FFF0000
> - STM32L0: 0x1FF00000
> - STM32L4: 0x1FFF0000
