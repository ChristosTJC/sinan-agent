"""编排任务工具测试 — task_create/list/get/update/stop/output."""

import time


class TestTaskCreate:
    def test_create_local_agent(self):
        from agent.tools import get_registry
        r = get_registry()
        result = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "测试 worker",
            "owner": "driver", "allowed_tools": ["read_file", "grep"],
        })
        assert result.get("success"), result
        assert result["task_id"].startswith("a")

    def test_create_hardware_op(self):
        from agent.tools import get_registry
        r = get_registry()
        result = r.call_tool("task_create", {
            "agent_type": "hardware_op", "description": "编译固件",
        })
        assert result.get("success"), result
        assert result["task_id"].startswith("h")

    def test_rejects_invalid_type(self):
        from agent.tools import get_registry
        r = get_registry()
        result = r.call_tool("task_create", {
            "agent_type": "invalid_type", "description": "bad",
        })
        assert result.get("success") is False


class TestTaskListGet:
    def test_list_and_get(self):
        from agent.tools import get_registry
        r = get_registry()
        result = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "测试列表",
            "owner": "debugger",
        })
        tid = result["task_id"]

        tasks = r.call_tool("task_list", {})
        assert tasks["count"] >= 1

        detail = r.call_tool("task_get", {"task_id": tid})
        assert detail["success"]
        assert detail["owner"] == "debugger"

    def test_get_nonexistent(self):
        from agent.tools import get_registry
        r = get_registry()
        result = r.call_tool("task_get", {"task_id": "x00000000"})
        assert result.get("success") is False


class TestTaskUpdate:
    def test_valid_transition_pending_to_in_progress(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "状态转换测试",
        })
        tid = create["task_id"]

        result = r.call_tool("task_update", {"task_id": tid, "status": "in_progress"})
        assert result.get("success"), result
        assert result["status"] == "in_progress"

    def test_invalid_transition_rejected(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "非法转换测试",
        })
        tid = create["task_id"]

        result = r.call_tool("task_update", {"task_id": tid, "status": "completed"})
        assert result.get("success") is False
        assert "非法" in result.get("error", "")


class TestTaskStop:
    def test_stop_pending_task(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "停止测试",
        })
        tid = create["task_id"]

        result = r.call_tool("task_stop", {"task_id": tid})
        assert result.get("success"), result
        assert result["status"] == "killed"

    def test_stop_hardware_in_progress_graceful_only(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "hardware_op", "description": "烧录任务",
        })
        tid = create["task_id"]
        r.call_tool("task_update", {"task_id": tid, "status": "in_progress"})

        result = r.call_tool("task_stop", {"task_id": tid})
        assert result.get("success") is False
        assert result.get("hint") == "graceful_only"

    def test_stop_hardware_with_force(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "hardware_op", "description": "烧录任务",
        })
        tid = create["task_id"]
        r.call_tool("task_update", {"task_id": tid, "status": "in_progress"})

        result = r.call_tool("task_stop", {"task_id": tid, "force": True})
        assert result.get("success"), result


class TestTaskOutput:
    def test_task_output_empty(self):
        from agent.tools import get_registry
        r = get_registry()
        create = r.call_tool("task_create", {
            "agent_type": "local_agent", "description": "输出测试",
        })
        tid = create["task_id"]
        result = r.call_tool("task_output", {"task_id": tid})
        assert result.get("success"), result
