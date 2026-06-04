from __future__ import annotations

from agent.core.approval import AutoApprove, DenyDangerous, InteractiveApproval
from agent.tools import DangerLevel


def test_auto_approve_always_true():
    policy = AutoApprove()
    assert policy.approve("flash_firmware", {}, DangerLevel.HIGH) is True


def test_deny_dangerous_allows_safe_and_low_only():
    policy = DenyDangerous()
    assert policy.approve("scan_usb", {}, DangerLevel.SAFE) is True
    assert policy.approve("read_sensor", {}, DangerLevel.LOW) is True
    assert policy.approve("flash_firmware", {}, DangerLevel.MEDIUM) is False
    assert policy.approve("serial_write", {}, DangerLevel.HIGH) is False


def test_interactive_approval_reads_yes_no():
    yes = InteractiveApproval(input_fn=lambda _prompt: "y", out=lambda _m: None)
    no = InteractiveApproval(input_fn=lambda _prompt: "", out=lambda _m: None)
    assert yes.approve("flash_firmware", {"port": "x"}, DangerLevel.HIGH) is True
    assert no.approve("flash_firmware", {"port": "x"}, DangerLevel.HIGH) is False
