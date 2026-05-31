# 司南嵌入式智能体

司南是面向嵌入式开发的智能体工具集，提供知识库检索、工具调用、任务规划和多平台固件工作流支持。

## 支持的平台

### STM32 系列
- **厂商**: STMicroelectronics
- **架构**: ARM Cortex-M
- **构建系统**: Make, CMake
- **烧录工具**: OpenOCD, ST-Link

### Nordic nRF 系列
- **厂商**: Nordic Semiconductor
- **架构**: ARM Cortex-M
- **支持芯片**:
  - nRF52 系列: nRF52810, nRF52832, nRF52833, nRF52840
  - nRF53 系列: nRF5340（双核）
- **构建系统**: CMake（nRF Connect SDK）
- **烧录工具**: pyOCD, nrfjprog, OpenOCD

## 快速开始 - Nordic nRF52840

### 1. 安装依赖

```bash
pip install pyocd
```

nRF Connect SDK 为可选依赖，用于完整 Nordic 开发体验。

### 2. 构建固件

```bash
sinan build --platform nordic --chip nRF52840
```

或手动使用 CMake:

```bash
cmake -B build -S . -DBOARD=nrf52840dk_nrf52840
cmake --build build
```

### 3. 烧录固件

```bash
sinan flash --chip nRF52840 --firmware build/zephyr/zephyr.hex
```

或手动使用 pyOCD:

```bash
pyocd flash -t nrf52840 build/zephyr/zephyr.hex
```

## 平台扩展

司南采用插件式平台架构，支持添加新平台：

1. 在 `agent/platforms/` 创建新平台模块
2. 实现 `ChipFamily` 和变体检测
3. 注册到全局 `PlatformRegistry`
4. 添加知识库文档到 `board_knowledge/`
