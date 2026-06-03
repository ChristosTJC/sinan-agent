"""共享测试夹具、辅助类和 fixture 工厂。

提供跨测试文件的 Fake 依赖、模拟 subprocess 返回值和临时固件项目夹具，
避免在每个测试文件中重复定义。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import pytest

from agent.llm.client import LLMResponse
from agent.tools import DangerLevel


# ── 模拟工具类 ──────────────────────────────────────────────────────────────


class Completed:
    """模拟 subprocess.CompletedProcess，用于替代 _run_command / subprocess.run。

    在所有 platform-aware 构建/烧录测试中统一使用，避免每个文件各定义一个。
    """

    def __init__(self, returncode: int = 0, stdout: str = "ok", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRegistry:
    """模拟 ToolRegistry，记录工具调用并返回预设结果。

    同时暴露 set_confirm_callback / set_danger_confirm 以支持 CLI 测试。
    """

    def __init__(
        self,
        danger_levels: dict[str, DangerLevel] | None = None,
        responses: dict[str, dict] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.confirm_callback = None
        self.danger_confirm: Optional[bool] = None
        self.danger_levels: dict[str, DangerLevel] = danger_levels or {}
        self.responses: dict[str, dict] = responses or {}

    def set_confirm_callback(self, callback) -> None:
        self.confirm_callback = callback

    def set_danger_confirm(self, enabled: bool) -> None:
        self.danger_confirm = enabled

    def list_tools(self) -> list[dict]:
        return [
            {"name": "scan_usb", "description": "扫描 USB 设备", "parameters": {"type": "object", "properties": {}}},
            {"name": "scan_serial", "description": "扫描串口端口", "parameters": {"type": "object", "properties": {}}},
            {"name": "build_firmware", "description": "编译固件", "parameters": {"type": "object", "properties": {}}},
            {"name": "flash_firmware", "description": "烧录固件", "parameters": {"type": "object", "properties": {}}},
            {"name": "esp32_diagnose_log", "description": "分析 ESP32 日志", "parameters": {"type": "object", "properties": {}}},
            {"name": "stm32_diagnose_log", "description": "分析 STM32 日志", "parameters": {"type": "object", "properties": {}}},
            {"name": "nordic_diagnose_log", "description": "分析 Nordic 日志", "parameters": {"type": "object", "properties": {}}},
            {"name": "diagnose_log", "description": "自动分析日志", "parameters": {"type": "object", "properties": {}}},
        ]

    def get_danger_level(self, name: str) -> DangerLevel:
        return self.danger_levels.get(name, DangerLevel.SAFE)

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        args = arguments or {}
        self.calls.append((name, args))
        if name in self.responses:
            return self.responses[name]
        if name == "scan_serial":
            return {"success": True, "result": [{"port": "/dev/ttyUSB0"}]}
        if name == "scan_usb":
            return {"success": True, "result": [{"vid": "1234", "pid": "abcd"}]}
        if name == "build_firmware":
            return {"success": True, "output": "build ok"}
        if name == "flash_firmware":
            return {"success": True, "output": "flash ok"}
        if name.endswith("_diagnose_log") or name == "diagnose_log":
            return {"success": True, "summary": "diagnosed"}
        return {"success": False, "error": f"unexpected tool: {name}"}


class FakeLLM:
    """模拟 LLMClient，返回预设的计划和验证内容。"""

    def __init__(
        self,
        content: str = '[{"step_id":1,"action":"scan","tool":"scan_serial","args":{},"expected_outcome":"ok"}]',
        verify_content: str = '{"passed": true, "reason": "ok"}',
    ) -> None:
        self.contents = [content, verify_content]
        self.messages: list[list[dict]] = []

    def chat(self, messages: list[dict]) -> LLMResponse:
        self.messages.append(messages)
        content = self.contents.pop(0) if self.contents else '{"passed": true, "reason": "ok"}'
        return LLMResponse(content=content, model="fake")


class NullMemory:
    """空记忆后端——不存储、不查询。"""

    def build_context(self) -> str:
        return ""

    def add_fact(self, _fact: str) -> bool:
        return True

    def flush_to_disk(self, _path) -> None:
        return None


class NullSessionDB:
    """空会话数据库——不持久化消息。"""

    def create_session(self, project: str = "test", model: str = "unknown") -> str:
        return f"{project}-{model}"

    def detect_project(self) -> str:
        return "test"

    def search(self, _query: str, limit: int = 3) -> list:
        return []

    def add_message(self, *_args, **_kwargs) -> None:
        return None


class NullKnowledge:
    """空知识库——不检索，返回空上下文。"""

    def build_context(self, query: str, max_chars: int = 2000) -> str:
        return f"context for {query}"[:max_chars]


# ── Fixture 工厂 ─────────────────────────────────────────────────────────────


@pytest.fixture
def stm32_cmake_project(tmp_path: Path) -> Path:
    """创建模拟的 STM32F4 CMake 项目，含最小 CMakeLists.txt 和 main.c。"""
    project_dir = tmp_path / "stm32_app"
    project_dir.mkdir()

    (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(stm32_blinky C ASM)

set(CMAKE_SYSTEM_PROCESSOR cortex-m4)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)

add_executable(app src/main.c)
""")

    src = project_dir / "src"
    src.mkdir()
    (src / "main.c").write_text("""
#include "stm32f4xx_hal.h"

int main(void) {
    HAL_Init();
    while (1) {}
}
""")

    return project_dir


@pytest.fixture
def esp32_idf_project(tmp_path: Path) -> Path:
    """创建模拟的 ESP32-S3 ESP-IDF 项目，含 CMakeLists.txt + sdkconfig。"""
    project_dir = tmp_path / "esp32_app"
    project_dir.mkdir()

    (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_blinky)
""")

    (project_dir / "sdkconfig").write_text("""
CONFIG_IDF_TARGET="esp32s3"
CONFIG_FREERTOS_UNICORE=n
""")

    main_dir = project_dir / "main"
    main_dir.mkdir()
    (main_dir / "main.c").write_text("""
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
    while (1) { vTaskDelay(1000 / portTICK_PERIOD_MS); }
}
""")

    return project_dir


@pytest.fixture
def nordic_zephyr_project(tmp_path: Path) -> Path:
    """创建模拟的 nRF52840 Zephyr/CMake 项目。"""
    project_dir = tmp_path / "nrf_app"
    project_dir.mkdir()

    (project_dir / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(nrf52840_blinky C ASM)

set(BOARD nrf52840dk_nrf52840)
set(BOARD_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

target_sources(app PRIVATE src/main.c)
""")

    src = project_dir / "src"
    src.mkdir()
    (src / "main.c").write_text("""
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>

void main(void) {
    printk("nRF52840 Blinky\\n");
    while (1) { k_sleep(K_MSEC(1000)); }
}
""")

    return project_dir
