"""Visible agent run-loop tests."""

from __future__ import annotations

import json

from agent.tools import DangerLevel


class FakeRegistry:
    def __init__(
        self,
        danger_levels: dict[str, DangerLevel] | None = None,
        responses: dict[str, dict] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.danger_levels = danger_levels or {}
        self.responses = responses or {}

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


class NullMemory:
    def build_context(self) -> str:
        return ""

    def add_fact(self, _fact: str) -> bool:
        return True

    def flush_to_disk(self, _path) -> None:
        return None


class NullSessionDB:
    def create_session(self, project: str = "test", model: str = "unknown") -> str:
        return f"{project}-{model}"

    def detect_project(self) -> str:
        return "test"

    def search(self, _query: str, limit: int = 3) -> list:
        return []

    def add_message(self, *_args, **_kwargs) -> None:
        return None


class NullKnowledge:
    def build_context(self, query: str, max_chars: int = 2000) -> str:
        return f"context for {query}"[:max_chars]


def _controller(tmp_path, registry: FakeRegistry, **kwargs):
    from agent.run_loop import SinanRunController

    return SinanRunController(
        sinan_home=tmp_path / "home",
        project_path=tmp_path,
        registry=registry,
        memory_store=NullMemory(),
        session_db=NullSessionDB(),
        knowledge_base=NullKnowledge(),
        **kwargs,
    )


def test_run_loop_executes_safe_tool_and_writes_artifacts(tmp_path):
    registry = FakeRegistry()
    events: list[dict] = []
    controller = _controller(tmp_path, registry, event_callback=events.append)

    result = controller.run("扫描串口设备")

    assert result["success"] is True
    assert result["run_id"]
    assert ("scan_serial", {}) in registry.calls
    assert [e["phase"] for e in events if e["event"] == "phase_start"] == [
        "understand",
        "retrieve",
        "plan",
        "execute",
        "verify",
        "consolidate",
    ]

    run_dir = tmp_path / "home" / "runs" / result["run_id"]
    assert (run_dir / "task.json").exists()
    assert (run_dir / "plan.md").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.md").exists()

    task = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
    assert task["goal"] == "扫描串口设备"
    assert task["success"] is True
    trace = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "scan_serial" in trace
    event_types = [
        json.loads(line)["type"]
        for line in (run_dir / "event.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "step_start" in event_types
    assert "step_done" in event_types


def test_run_loop_blocks_dangerous_tool_without_yes(tmp_path):
    registry = FakeRegistry({"build_firmware": DangerLevel.MEDIUM})
    controller = _controller(tmp_path, registry)

    result = controller.run("编译固件")

    assert result["success"] is False
    assert registry.calls == []
    execute_steps = result["phases"]["execute"]["steps"]
    assert execute_steps[0]["status"] == "blocked_confirmation"
    assert execute_steps[0]["tool"] == "build_firmware"

    report = (tmp_path / "home" / "runs" / result["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "需要确认" in report
    assert "build_firmware" in report

    event_path = tmp_path / "home" / "runs" / result["run_id"] / "event.jsonl"
    event_types = [json.loads(line)["type"] for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert "step_blocked" in event_types


def test_run_loop_stops_after_first_failed_step(tmp_path):
    # fallback pipeline（无 LLM）顺序链路：首步执行失败后停止后续步骤
    registry = FakeRegistry(responses={"build_firmware": {"success": False, "error": "build failed"}})
    controller = _controller(tmp_path, registry)

    result = controller.run("编译并烧录固件")

    assert result["success"] is False
    assert registry.calls == [("build_firmware", {"project_path": "."})]
    steps = result["phases"]["execute"]["steps"]
    assert steps[0]["status"] == "failed"
    assert steps[1]["status"] == "skipped_previous_failure"
    assert steps[1]["tool"] == "flash_firmware"

    event_path = tmp_path / "home" / "runs" / result["run_id"] / "event.jsonl"
    event_types = [json.loads(line)["type"] for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert "step_skipped" in event_types


def test_fallback_plan_maps_build_and_flash_to_dangerous_tools(tmp_path):
    registry = FakeRegistry({
        "build_firmware": DangerLevel.MEDIUM,
        "flash_firmware": DangerLevel.HIGH,
    })
    controller = _controller(tmp_path, registry)

    result = controller.run("编译并烧录固件")

    assert registry.calls == []
    plan_tools = [step["tool"] for step in result["phases"]["plan"]]
    assert plan_tools == ["build_firmware", "flash_firmware"]
    steps = result["phases"]["execute"]["steps"]
    assert steps[0]["status"] == "blocked_confirmation"
    assert steps[1]["status"] == "skipped_previous_failure"
    assert steps[1]["tool"] == "flash_firmware"


def test_fallback_plan_maps_esp32_panic_log_to_diagnostic_tool(tmp_path):
    registry = FakeRegistry()
    controller = _controller(tmp_path, registry)
    goal = "分析 ESP32 panic 日志: Guru Meditation Error: Core  1 panic'ed (LoadProhibited)."

    result = controller.run(goal)

    assert result["success"] is True
    assert registry.calls == [("esp32_diagnose_log", {"log": goal})]
    assert result["phases"]["plan"][0]["tool"] == "esp32_diagnose_log"


def test_fallback_plan_maps_unknown_platform_log_to_generic_diagnostic_tool(tmp_path):
    registry = FakeRegistry()
    controller = _controller(tmp_path, registry)
    goal = "分析日志: HardFault_Handler entered HFSR=0x40000000"

    result = controller.run(goal)

    assert result["success"] is True
    assert registry.calls == [("diagnose_log", {"log": goal})]
    assert result["phases"]["plan"][0]["tool"] == "diagnose_log"
