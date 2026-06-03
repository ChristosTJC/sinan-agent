"""
tools/__init__.py 单元测试。

覆盖:
- _extract_description: docstring 描述提取
- _parse_params_from_docstring: Google 风格参数解析
- ToolRegistry: 注册、注销、调用、schema 生成
"""

import pytest

from agent.tools import ToolRegistry, _extract_description, _parse_params_from_docstring


# ---------------------------------------------------------------------------
# _extract_description
# ---------------------------------------------------------------------------


class TestExtractDescription:
    def test_single_line(self):
        def fn():
            """这是描述。"""

        assert _extract_description(fn) == "这是描述。"

    def test_multi_line(self):
        def fn():
            """第一行描述。

            详细说明。
            """

        assert _extract_description(fn) == "第一行描述。"

    def test_no_docstring(self):
        def fn():
            pass

        assert _extract_description(fn) == ""


# ---------------------------------------------------------------------------
# _parse_params_from_docstring
# ---------------------------------------------------------------------------


class TestParseParams:
    def test_google_style(self):
        def fn():
            """工具描述。

            Args:
                port (str): 串口路径 [required]
                baudrate (int): 波特率
                duration_sec (float): 时长秒数
            """

        params = _parse_params_from_docstring(fn)
        assert "port" in params
        assert params["port"]["type"] == "string"
        assert params["port"]["required"] is True
        assert params["baudrate"]["type"] == "integer"
        assert params["baudrate"]["required"] is False
        assert params["duration_sec"]["type"] == "number"

    def test_no_args_section(self):
        def fn():
            """简单描述，无 Args。"""

        assert _parse_params_from_docstring(fn) == {}

    def test_no_docstring(self):
        def fn():
            pass

        assert _parse_params_from_docstring(fn) == {}

    def test_bool_type(self):
        def fn():
            """描述。

            Args:
                flag (bool): 开关 [required]
            """

        params = _parse_params_from_docstring(fn)
        assert params["flag"]["type"] == "boolean"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_register_and_list(self):
        reg = ToolRegistry()

        def my_tool(arguments: dict) -> dict:
            """我的工具。"""
            return {"success": True}

        reg.register("my_tool", my_tool, description="我的工具", parameters={})
        tools = reg.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "my_tool"
        assert tools[0]["description"] == "我的工具"

    def test_register_with_auto_description(self):
        reg = ToolRegistry()

        def my_tool(arguments: dict) -> dict:
            """自动提取的描述。"""
            return {"success": True}

        reg.register("my_tool", my_tool)
        tools = reg.list_tools()
        assert tools[0]["description"] == "自动提取的描述。"

    def test_duplicate_register_raises(self):
        reg = ToolRegistry()

        def fn(arguments):
            return {}

        reg.register("t", fn)
        with pytest.raises(ValueError, match="已经注册"):
            reg.register("t", fn)

    def test_unregister(self):
        reg = ToolRegistry()

        def fn(arguments):
            return {}

        reg.register("t", fn)
        reg.unregister("t")
        # 直接检查内部状态，避免 list_tools() 触发 discover()
        assert "t" not in reg._tools
        assert "t" not in reg._meta

    def test_call_tool_success(self):
        reg = ToolRegistry()

        def add_tool(arguments: dict) -> dict:
            return {"success": True, "result": arguments.get("a", 0) + arguments.get("b", 0)}

        reg.register("add", add_tool, description="加法")
        result = reg.call_tool("add", {"a": 3, "b": 4})
        assert result["success"] is True
        assert result["result"] == 7

    def test_call_nonexistent_tool(self):
        reg = ToolRegistry()
        result = reg.call_tool("nonexistent")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_call_tool_exception_caught(self):
        reg = ToolRegistry()

        def bad_tool(arguments: dict) -> dict:
            raise RuntimeError("boom")

        reg.register("bad", bad_tool, description="会崩溃的工具")
        result = reg.call_tool("bad")
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_discovered_scan_tools_accept_registry_arguments(self, monkeypatch):
        from agent.tools import serial_scanner

        monkeypatch.setattr(serial_scanner, "scan_usb_devices", lambda: [{"vid": "1234", "pid": "abcd"}])
        monkeypatch.setattr(serial_scanner, "scan_serial_ports", lambda: [{"port": "/dev/ttyUSB0"}])

        reg = ToolRegistry()
        reg.discover()

        usb = reg.call_tool("scan_usb", {})
        serial = reg.call_tool("scan_serial", {})

        assert usb["success"] is True
        assert usb["result"] == [{"vid": "1234", "pid": "abcd"}]
        assert serial["success"] is True
        assert serial["result"] == [{"port": "/dev/ttyUSB0"}]

    def test_serial_monitor_can_return_diagnostic_when_requested(self, monkeypatch):
        from agent.tools import serial_monitor

        class FakeMonitor:
            def __init__(self, port: str, baudrate: int):
                self.port = port
                self.baudrate = baudrate

            def open(self):
                return True

            def monitor(self, duration_sec: float):
                return ["Guru Meditation Error: Core  0 panic'ed (StoreProhibited)."]

            def close(self):
                return None

        monkeypatch.setattr(serial_monitor, "SerialMonitor", FakeMonitor)

        reg = ToolRegistry()
        reg.discover()

        result = reg.call_tool("serial_monitor", {
            "port": "/dev/ttyUSB0",
            "diagnose": True,
            "platform": "esp32",
        })

        assert result["success"] is True
        assert result["diagnostic"]["platform"] == "esp32"
        assert result["diagnostic"]["diagnostic"]["panic"]["reason"] == "StoreProhibited"

    def test_schema_includes_required(self):
        reg = ToolRegistry()

        def fn(arguments):
            return {}

        params = {
            "port": {"type": "string", "description": "路径", "required": True},
            "baud": {"type": "integer", "description": "波特率", "required": False},
        }
        reg.register("t", fn, description="test", parameters=params)
        schema = reg.list_tools()[0]["parameters"]
        assert "port" in schema["required"]
        assert "baud" not in schema["required"]

    def test_discover_registers_nrfjprog_flash_tool(self):
        from agent.tools import DangerLevel

        reg = ToolRegistry()
        reg.discover()

        tool_names = {tool["name"] for tool in reg.list_tools()}

        assert "nrfjprog_flash" in tool_names
        assert reg.get_danger_level("nrfjprog_flash") == DangerLevel.HIGH

    def test_discover_registers_esp32_diagnose_log_tool(self):
        from agent.tools import DangerLevel

        reg = ToolRegistry()
        reg.discover()

        tool_names = {tool["name"] for tool in reg.list_tools()}

        assert "esp32_diagnose_log" in tool_names
        assert reg.get_danger_level("esp32_diagnose_log") == DangerLevel.SAFE

    def test_discover_registers_stm32_diagnose_log_tool(self):
        from agent.tools import DangerLevel

        reg = ToolRegistry()
        reg.discover()

        tool_names = {tool["name"] for tool in reg.list_tools()}

        assert "stm32_diagnose_log" in tool_names
        assert reg.get_danger_level("stm32_diagnose_log") == DangerLevel.SAFE

    def test_discover_registers_nordic_diagnose_log_tool(self):
        from agent.tools import DangerLevel

        reg = ToolRegistry()
        reg.discover()

        tool_names = {tool["name"] for tool in reg.list_tools()}

        assert "nordic_diagnose_log" in tool_names
        assert reg.get_danger_level("nordic_diagnose_log") == DangerLevel.SAFE

    def test_discover_registers_generic_diagnose_log_tool(self):
        from agent.tools import DangerLevel

        reg = ToolRegistry()
        reg.discover()

        tool_names = {tool["name"] for tool in reg.list_tools()}

        assert "diagnose_log" in tool_names
        assert reg.get_danger_level("diagnose_log") == DangerLevel.SAFE
