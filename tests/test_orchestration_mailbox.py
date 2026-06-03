"""邮箱通信测试."""
import json
import tempfile
from pathlib import Path


class TestMailboxBasic:
    def test_write_and_read(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("test-team", base_dir=Path(tmp))
            mb.write_message("worker1", "执行任务A", sender="team-lead",
                             msg_type="task_assignment", summary="任务分配")
            msgs = mb.read_messages("worker1")
            assert len(msgs) == 1
            assert msgs[0]["from"] == "team-lead"
            assert msgs[0]["text"] == "执行任务A"
            assert msgs[0]["type"] == "task_assignment"

    def test_no_inbox(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("empty", base_dir=Path(tmp))
            msgs = mb.read_messages("nonexistent")
            assert msgs == []

    def test_mark_all_read(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("read-test", base_dir=Path(tmp))
            mb.write_message("agent1", "msg1", sender="x")
            mb.write_message("agent1", "msg2", sender="x")
            assert len(mb.read_messages("agent1", unread_only=True)) == 2
            mb.mark_all_read("agent1")
            assert len(mb.read_messages("agent1", unread_only=True)) == 0
            assert len(mb.read_messages("agent1")) == 2

    def test_unread_filter(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("unread", base_dir=Path(tmp))
            mb.write_message("agent", "one", sender="tl")
            mb.write_message("agent", "two", sender="tl")
            unread = mb.read_messages("agent", unread_only=True)
            assert len(unread) == 2


class TestMailboxNotifications:
    def test_idle_notification(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("notify-team", base_dir=Path(tmp))
            mb.send_idle_notification("worker1", reason="available",
                                      completed_task_id="a123", summary="完成扫描")
            msgs = mb.read_messages("team-lead")
            assert len(msgs) == 1
            assert msgs[0]["type"] == "idle_notification"

    def test_permission_request_and_response(self):
        from agent.orchestration.mailbox import Mailbox
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mb = Mailbox("perm-team", base_dir=Path(tmp))
            mb.send_permission_request("worker1", "req001", "flash_firmware", "需要烧录")
            reqs = mb.read_messages("team-lead")
            assert len(reqs) == 1
            assert reqs[0]["type"] == "permission_request"

            mb.send_permission_response("worker1", "req001", True)
            resps = mb.read_messages("worker1")
            assert len(resps) == 1
            assert resps[0]["type"] == "permission_response"
            payload = json.loads(resps[0]["text"])
            assert payload["approved"] is True
