"""测试活的 ToolRegistry 入口兼容性。"""


class TestLegacyToolRegistryCompatibility:
    """测试旧版 ToolRegistry 入口兼容性。"""

    def test_imports_legacy_registry_helpers(self):
        from agent.tools import (
            ToolRegistry,
            _extract_description,
            _parse_params_from_docstring,
            get_registry,
        )

        assert ToolRegistry is not None
        assert get_registry is not None
        assert _extract_description is not None
        assert _parse_params_from_docstring is not None

    def test_register_accepts_phase2c_func_keyword(self):
        from agent.tools import ToolRegistry

        registry = ToolRegistry()
        registry.register(
            name="phase2c_tool",
            func=lambda arguments: {"value": arguments["value"]},
            description="Phase 2C 兼容工具",
            parameters={"value": {"type": "string", "required": True}},
        )

        assert registry.call_tool("phase2c_tool", {"value": "ok"}) == {
            "value": "ok",
            "success": True,
        }

    def test_new_phase2c_tool_registration_functions_are_importable(self):
        from agent.tools.pyocd_flasher import register_pyocd_tool

        assert register_pyocd_tool is not None
