from __future__ import annotations

from agent.config import get_tools_config


def test_tools_config_reads_max_tool_depth_from_settings():
    cfg = get_tools_config({"tools": {"max_tool_depth": 30}})
    assert int(cfg.get("max_tool_depth", 25)) == 30


def test_tools_config_defaults_to_25_when_absent():
    cfg = get_tools_config({"tools": {}})
    assert int(cfg.get("max_tool_depth", 25)) == 25
