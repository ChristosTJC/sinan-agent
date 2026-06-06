"""CLI command contract tests."""

from __future__ import annotations

from agent import cli
from agent.llm.client import LLMResponse, ToolCall


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.confirm_callback = None
        self.danger_confirm = None

    def set_confirm_callback(self, callback):
        self.confirm_callback = callback

    def set_danger_confirm(self, enabled: bool):
        self.danger_confirm = enabled

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        return {"success": True, "output": ""}

    def list_tools(self) -> list[dict]:
        return [
            {"name": "scan_serial", "description": "扫描串口端口", "parameters": {"type": "object", "properties": {}}},
            {"name": "build_firmware", "description": "编译固件", "parameters": {"type": "object", "properties": {}}},
        ]

    def get_danger_level(self, _name: str):
        from agent.tools import DangerLevel

        return DangerLevel.SAFE

    def is_dangerous(self, _name: str) -> bool:
        return False


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.model = "fake"

    def chat(self, _messages: list[dict], tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="a", name="scan_serial", arguments={})],
                model="fake",
            )
        return LLMResponse(content="已完成串口扫描", model="fake")


def test_readme_build_command_is_accepted_and_calls_build_tool(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)

    rc = cli.main(["build", "--platform", "nordic", "--chip", "nRF52840", "--force"])

    assert rc == 0
    assert registry.calls == [
        (
            "build_firmware",
            {
                "project_path": ".",
                "target": None,
                "env": None,
                "platform": "nordic",
                "chip": "nRF52840",
            },
        )
    ]
    assert registry.danger_confirm is False


def test_readme_flash_command_is_accepted_and_calls_pyocd_tool(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)

    rc = cli.main(
        [
            "flash",
            "--chip",
            "nRF52840",
            "--firmware",
            "build/zephyr/zephyr.hex",
            "--force",
        ]
    )

    assert rc == 0
    assert registry.calls == [
        (
            "pyocd_flash",
            {
                "firmware_path": "build/zephyr/zephyr.hex",
                "chip_model": "nRF52840",
            },
        )
    ]
    assert registry.danger_confirm is False


def test_flash_command_passes_platform_and_chip_to_flash_tool(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)

    rc = cli.main([
        "flash",
        "--project-path",
        "/tmp/fw",
        "--port",
        "/dev/ttyUSB0",
        "--platform",
        "esp32",
        "--chip",
        "ESP32-S3",
        "--force",
    ])

    assert rc == 0
    assert registry.calls == [
        (
            "flash_firmware",
            {
                "project_path": "/tmp/fw",
                "port": "/dev/ttyUSB0",
                "method": "auto",
                "platform": "esp32",
                "chip": "ESP32-S3",
            },
        )
    ]


def test_demo_command_runs_without_hardware(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path / "home"))

    rc = cli.main(["demo"])

    captured = capsys.readouterr()
    out = captured.out
    assert rc == 0
    assert "司南 demo" in out
    assert "knowledge" in out
    assert "未检测到" not in out
    assert "未检测到" not in captured.err
    assert (tmp_path / "home" / "memories").is_dir()


def test_doctor_command_reports_core_environment(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path / "home"))

    rc = cli.main(["doctor"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "司南 doctor" in out
    assert "Python" in out
    assert "SINAN_HOME" in out


def test_report_command_writes_redacted_markdown(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SINAN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    output = tmp_path / "sinan-report.md"

    rc = cli.main(["report", "--output", str(output)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "诊断报告已写入" in out
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert "[REDACTED]" in text


def test_run_command_shows_visible_agent_loop(monkeypatch, tmp_path, capsys):
    registry = FakeRegistry()
    monkeypatch.setenv("SINAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)
    output_dir = tmp_path / "run-artifacts"

    rc = cli.main(["run", "扫描串口设备", "--output-dir", str(output_dir)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "[1/6] 理解目标" in out
    assert "[4/6] 执行工具" in out
    assert "scan_serial" in out
    assert (output_dir / "task.json").exists()
    assert (output_dir / "plan.md").exists()
    assert (output_dir / "trace.jsonl").exists()
    assert (output_dir / "report.md").exists()


def test_run_command_can_use_llm_client(monkeypatch, tmp_path):
    # 决策 X：传 --llm 即走 AgentSession（真 agent loop），由 LLM 自主驱动工具调用
    registry = FakeRegistry()
    llm = FakeLLM()
    monkeypatch.setenv("SINAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)
    monkeypatch.setattr("agent.llm.client.create_client", lambda provider=None, model=None: llm)

    rc = cli.main(["run", "执行 LLM 指定动作", "--llm", "--output-dir", str(tmp_path / "run-llm")])

    assert rc == 0
    assert registry.calls == [("scan_serial", {})]
    assert llm.calls >= 1
    assert (tmp_path / "run-llm" / "event.jsonl").exists()


def test_diagnose_log_command_reads_file_and_prints_json(tmp_path, capsys):
    log_file = tmp_path / "esp32.log"
    log_file.write_text("Guru Meditation Error: Core  0 panic'ed (StoreProhibited).\n", encoding="utf-8")

    rc = cli.main(["diagnose-log", "--file", str(log_file)])

    out = capsys.readouterr().out
    assert rc == 0
    assert '"platform": "esp32"' in out
    assert "StoreProhibited" in out


def test_diagnose_log_command_accepts_inline_log(capsys):
    rc = cli.main(["diagnose-log", "--platform", "stm32", "HardFault_Handler entered"])

    out = capsys.readouterr().out
    assert rc == 0
    assert '"platform": "stm32"' in out
    assert "HardFault" in out


def test_golden_path_registered_with_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["golden-path"])
    assert args.command == "golden-path"
    assert args.project_path == "."
    assert args.baudrate == 115200
    assert args.execute is False
    assert args.yes is False


def test_golden_path_default_is_dry_run_and_never_calls_build_or_flash(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)

    rc = cli.main(["golden-path"])

    called = [name for name, _ in registry.calls]
    assert "build_firmware" not in called
    assert "flash_firmware" not in called
    assert rc in (0, 1)  # 无硬件机器上 dry 预检通常 fail→1，不视为错误


def test_golden_path_yes_without_execute_stays_dry_and_keeps_safety_gate(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)

    cli.main(["golden-path", "--yes"])

    # 未配置危险确认（保持初始 None），且未触发 build/flash —— 钉死 "--yes 无 --execute 无意义"
    assert registry.danger_confirm is None
    assert registry.confirm_callback is None
    called = [name for name, _ in registry.calls]
    assert "build_firmware" not in called
    assert "flash_firmware" not in called


def test_golden_path_dry_returns_zero_on_success(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)
    monkeypatch.setattr(
        "agent.workflows.HardwareGoldenPath.run_dry",
        lambda self, project_path: {
            "success": True, "board_detected": True, "board_type": "nRF52840",
            "ports": ["/dev/ttyUSB0"], "build_tools_available": True, "error": None,
        },
    )

    rc = cli.main(["golden-path"])

    assert rc == 0


def test_golden_path_dry_returns_one_on_failure(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("agent.tools.get_registry", lambda: registry)
    monkeypatch.setattr(
        "agent.workflows.HardwareGoldenPath.run_dry",
        lambda self, project_path: {
            "success": False, "board_detected": False, "ports": [],
            "build_tools_available": False, "error": "未检测到任何串口设备",
        },
    )

    rc = cli.main(["golden-path"])

    assert rc == 1
