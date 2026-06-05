"""device_bridge device_node 默认参数接入配置测试。"""

from unittest import mock

from agent.tools import get_registry
from agent.tools.device_bridge import DeviceNodeClient


# 非兜底值，用于区分「来自配置」与「恰好等于硬编码 5555/5.0」
_FAKE_CFG = {"default_port": 6000, "timeout_sec": 9.0}


class TestDeviceNodeClientDefaults:
    def test_uses_config_when_args_none(self):
        with mock.patch.object(DeviceNodeClient, "_get_default_config", return_value=_FAKE_CFG):
            client = DeviceNodeClient("192.168.1.10")
        assert client.port == 6000
        assert client.timeout_sec == 9.0

    def test_explicit_args_override_config(self):
        with mock.patch.object(DeviceNodeClient, "_get_default_config", return_value=_FAKE_CFG):
            client = DeviceNodeClient("h", port=7777, timeout_sec=2.0)
        assert client.port == 7777
        assert client.timeout_sec == 2.0


class TestDeviceHandlersDefaultPort:
    def test_device_probe_default_port_from_config(self):
        # device_probe 返回 dict 含 port；未传 port 时应取配置端口（连接失败不影响 port 字段）
        with mock.patch.object(DeviceNodeClient, "_get_default_config", return_value=_FAKE_CFG):
            result = get_registry().call_tool("device_probe", {"host": "127.0.0.1"})
        assert result["port"] == 6000

    def test_device_call_default_port_from_config(self):
        seen = {}
        orig_init = DeviceNodeClient.__init__

        def spy_init(self, host, port=None, timeout_sec=None):
            seen["port"] = port
            orig_init(self, host, port, timeout_sec)

        registry = get_registry()
        # device_call 为 HIGH 危险工具，需先关闭确认门控 handler 才会执行
        registry.set_danger_confirm(False)
        try:
            with mock.patch.object(DeviceNodeClient, "_get_default_config", return_value=_FAKE_CFG), \
                    mock.patch.object(DeviceNodeClient, "__init__", spy_init):
                # 未传 port → handler 取配置端口 6000 传给 DeviceNodeClient
                registry.call_tool("device_call", {"host": "127.0.0.1", "method": "ping"})
        finally:
            registry.set_danger_confirm(True)
        assert seen["port"] == 6000


class TestSchemaDescriptionUpdated:
    def test_port_description_not_stale(self):
        tools = {t["name"]: t for t in get_registry().list_tools()}
        for name in ("device_probe", "device_call"):
            desc = tools[name]["parameters"]["properties"]["port"]["description"]
            assert "tools.device_node.default_port" in desc
