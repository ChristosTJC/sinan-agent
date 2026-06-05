# 司南嵌入式智能体

司南 (Sinán) 是面向嵌入式开发者的智能体工作台，提供知识库检索、板卡资料管理、串口/USB 工具、固件构建、固件烧录和多轮调试记忆。

当前状态：Alpha。已完成 no-hardware smoke、dry-run 端到端验证、硬件黄金路径模拟和 585 个单元/集成测试，覆盖率达 63%。真实板卡 HIL 闭环验证待社区贡献或后续硬件环境补齐——欢迎插上板卡跑 `sinan run` 反馈结果。定位：**ready for hardware validation**。

## 快速开始

### 1. 安装

从源码安装开发版：

```bash
git clone <仓库地址>
cd sinan-embedded-agent
python -m pip install ".[dev]"
```

安装后确认 CLI 可用：

```bash
sinan --help
sinan demo
sinan doctor
```

`sinan demo` 是无硬件 smoke test：验证包数据、知识库、板卡资料、技能和工具注册是否可用。
`sinan doctor` 会检查 Python、`SINAN_HOME`、当前项目构建系统和常见外部工具。默认不扫描硬件；需要只读 USB/串口扫描时显式加：

```bash
sinan doctor --scan-hardware
```

遇到问题时生成脱敏诊断报告：

```bash
sinan report --output sinan-report.md
```

把一个目标交给可见的 6 阶段 Agent loop：

```bash
sinan run "扫描串口设备"
sinan run "编译固件"
```

`sinan run` 会展示理解、检索、规划、执行、验证和沉淀六个阶段。默认只自动执行安全工具；`build_firmware`、`flash_firmware` 等 `MEDIUM`/`HIGH` 工具会被标记为“需要确认”并阻断。你明确接受风险时再使用：

```bash
sinan run "编译固件" --yes
```

顺序链路会在第一个失败步骤后停止后续工具调用。例如 `build → flash` 中编译失败或未确认时，不会继续烧录。

默认 `sinan run` 使用规则式 fallback planner，不联网。需要让 LLM 生成计划时显式开启：

```bash
sinan run "帮我找出板子上的串口并监听输出" --llm
sinan run "分析 ESP32 blink 工程为什么编译失败" --llm --provider openai --model <model>
```

每次运行会写入 trace 产物：

```text
~/.sinan/runs/<run-id>/
  task.json
  plan.md
  trace.jsonl
  report.md
```

如果你只想本地运行测试：

```bash
python -m pytest -q
python -m ruff check .
```

### 2. 查询知识库和板卡资料

```bash
sinan knowledge categories
sinan knowledge search stm32
sinan board list
sinan board show example_stm32f407
```

### 3. 编译固件

在你的固件项目根目录运行：

```bash
sinan build --platform nordic --chip nRF52840
```

司南会自动检测项目构建系统。当前支持 PlatformIO、CMake、Make、Arduino CLI。Nordic CMake 项目会补充 `BOARD`/`CHIP` 参数。

也可以指定项目路径：

```bash
sinan build --project-path /path/to/firmware --platform nordic --chip nRF52840
```

### 4. 烧录固件

使用 pyOCD 按芯片型号烧录已有固件：

```bash
sinan flash --chip nRF52840 --firmware build/zephyr/zephyr.hex
```

使用项目自动检测的烧录方法，并显式指定端口：

```bash
sinan flash --project-path /path/to/firmware --port /dev/ttyACM0 --method auto
```

`flash` 属于高危操作，默认会要求交互确认。自动化环境可显式加 `--force` 跳过确认。

## 平台和依赖矩阵

| 场景 | 司南命令 | 必装依赖 | 可选/外部工具 | 说明 |
|---|---|---|---|---|
| 无硬件 smoke/环境诊断 | `sinan demo` / `sinan doctor` / `sinan report` | Python 3.10+，项目依赖 | 无 | 适合首次安装、CI 和 issue 诊断 |
| 可见 Agent loop | `sinan run "目标"` | Python 3.10+，项目依赖 | 目标涉及的外部工具 | 默认只执行安全工具，并写入 run trace |
| 通用 CLI、知识库、板卡管理 | `sinan knowledge` / `sinan board` | Python 3.10+，项目依赖 | 无 | 适合离线查资料和管理板卡配置 |
| 串口扫描/监听 | `sinan tools` 后由智能体调用 `scan_serial` / `serial_monitor` | `pyserial` | 串口权限，如 Linux `dialout` 组 | 串口监听有时间和字节上限 |
| PlatformIO 项目构建/上传 | `sinan build` / `sinan flash --method platformio` | 司南核心依赖 | `platformio` | 通过 `platformio.ini` 自动检测 |
| CMake/Make 项目构建 | `sinan build` | 司南核心依赖 | `cmake`、`make`、交叉编译器 | 适合 STM32、Nordic、裸机工程 |
| Nordic nRF52/nRF53 烧录 | `sinan flash --chip ... --firmware ...` | 司南核心依赖 | `pyocd`，可选 `nrfjprog` / OpenOCD | README 示例默认走 pyOCD |
| STM32 烧录 | `sinan flash --method stm32cubeprog/openocd` | 司南核心依赖 | STM32CubeProgrammer 或 OpenOCD | 具体 probe 和板卡配置需由项目提供 |
| ESP32/ESP8266 烧录 | `sinan flash --method esptool` | 司南核心依赖 | `esptool` | 固件文件从项目构建目录自动查找 |
| Arduino 草图 | `sinan build` / `sinan flash --method arduino` | 司南核心依赖 | `arduino-cli` | 可用 `ARDUINO_FQBN` 指定板型 |

常用额外安装：

```bash
python -m pip install pyocd
python -m pip install esptool
python -m pip install platformio
```

## 安全机制

司南把工具分为安全等级：

| 等级 | 示例 | 默认行为 |
|---|---|---|
| `SAFE` | 文件读取、知识库查询、USB/串口扫描 | 直接执行 |
| `LOW` | 可逆或低风险操作 | 直接执行 |
| `MEDIUM` | 固件编译、文件写入、文件编辑 | 需要确认 |
| `HIGH` | 固件烧录、串口写入、远程设备调用 | 需要确认 |

危险工具确认机制在 `ToolRegistry.call_tool()` 层统一执行，因此 CLI、REPL、工作流和智能体编排路径都会被拦截。没有确认回调时，`MEDIUM` 和 `HIGH` 工具会被拒绝执行。

跳过确认：

```bash
sinan build --platform nordic --chip nRF52840 --force
sinan flash --chip nRF52840 --firmware build/zephyr/zephyr.hex --force
```

只有在 CI、脚本化测试或你完全确认目标设备和固件路径时才使用 `--force`。

审计日志默认写入：

```text
~/.sinan/audit/audit-YYYYMMDD.jsonl
```

可通过 `SINAN_HOME` 改变运行时数据目录：

```bash
SINAN_HOME=/tmp/sinan-test sinan tools
```

诊断报告会对常见 token、API key、password、secret 等字段做脱敏；但提交 issue 前仍建议人工快速扫一眼报告内容。

## 项目结构

```text
agent/             核心 CLI、REPL、工具、记忆、平台抽象
knowledge/         内置 MCU、协议、传感器、错误码知识库
board_knowledge/   板卡配置、schema、模板和平台资料
skills/            面向嵌入式调试流程的可复用技能
tests/             单元测试和集成路径测试
.github/workflows/ CI：lint、pytest、wheel artifact
```

## 开发

```bash
python -m pip install ".[dev]"
python -m ruff check .
python -m pytest -q
python -m pip wheel --no-deps . -w dist
```

CI 会在 Ubuntu 22.04 上执行 lint、测试和 wheel 构建，并上传 `dist/*.whl` 作为 artifact。

## 平台扩展

司南采用插件式平台架构，支持添加新平台：

1. 在 `agent/platforms/` 创建新平台模块。
2. 实现芯片家族、变体检测、构建参数和烧录目标映射。
3. 注册到全局 `PlatformRegistry`。
4. 添加知识库文档到 `board_knowledge/`。
5. 为平台检测、命令生成和失败路径补测试。
