"""Tests for SerialMonitor using fake pyserial objects."""

from __future__ import annotations

import sys
import types

import pytest

from agent.tools import serial_monitor
from agent.tools.serial_monitor import SerialMonitor, auto_detect_baud


class FakeSerialException(Exception):
    pass


class FakeSerial:
    instances = []

    def __init__(self, port, baudrate, timeout):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self.in_waiting = 0
        self.lines = []
        self.read_chunks = []
        self.writes = []
        self.closed = False
        FakeSerial.instances.append(self)

    def readline(self):
        if not self.lines:
            return b""
        return self.lines.pop(0)

    def read(self, _size):
        if not self.read_chunks:
            return b""
        return self.read_chunks.pop(0)

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        return None

    def close(self):
        self.closed = True
        self.is_open = False

    def reset_input_buffer(self):
        return None


@pytest.fixture
def fake_serial_module(monkeypatch):
    FakeSerial.instances = []
    module = types.SimpleNamespace(Serial=FakeSerial, SerialException=FakeSerialException)
    monkeypatch.setitem(sys.modules, "serial", module)
    return module


def test_serial_monitor_open_read_write_and_close(fake_serial_module):
    monitor = SerialMonitor("/dev/fake", baudrate=9600, max_bytes=5)

    assert monitor.open() is True
    serial = FakeSerial.instances[-1]
    serial.lines = [b"hello\r\n"]
    serial.in_waiting = 20
    serial.read_chunks = [b"abcdef"]

    assert monitor.read_line() == "hello"
    assert monitor.read_all() == "abcdef"
    assert monitor.write(b"AT\r\n") == 4
    assert monitor.write_command("PING") == 5

    monitor.close()
    assert serial.closed is True
    assert monitor.serial is None


def test_serial_monitor_open_handles_serial_exception(monkeypatch, fake_serial_module):
    def raise_serial(**_kwargs):
        raise FakeSerialException("busy")

    fake_serial_module.Serial = raise_serial
    monitor = SerialMonitor("/dev/busy")

    assert monitor.open() is False
    assert monitor.serial is None


def test_serial_monitor_methods_return_empty_when_closed():
    monitor = SerialMonitor("/dev/fake")

    assert monitor.read_line() is None
    assert monitor.read_all() == ""
    assert monitor.monitor(0.01) == []
    assert monitor.write(b"data") == 0


def test_serial_monitor_monitor_collects_lines_and_handles_callback(monkeypatch, fake_serial_module):
    monitor = SerialMonitor("/dev/fake", max_bytes=100, max_duration_sec=1)
    assert monitor.open() is True
    serial = FakeSerial.instances[-1]
    serial.lines = [b"line1\n", b"line2\n", b""]
    times = iter([0.0, 0.1, 0.2, 1.2, 1.3])
    monkeypatch.setattr(serial_monitor.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(serial_monitor.time, "sleep", lambda _seconds: None)
    seen = []

    lines = monitor.monitor(5.0, callback=lambda line: seen.append(line))

    assert lines == ["line1", "line2"]
    assert seen == ["line1", "line2"]


def test_auto_detect_baud_returns_first_ok_response(monkeypatch, fake_serial_module):
    class BaudSerial(FakeSerial):
        def read(self, _size):
            return b"OK\r\n" if self.baudrate == 9600 else b""

    fake_serial_module.Serial = BaudSerial
    monkeypatch.setattr(serial_monitor, "_AUTO_BAUD_CANDIDATES", [115200, 9600])
    ticks = iter([0.0, 0.1, 0.0, 0.1, 1.2])
    monkeypatch.setattr(serial_monitor.time, "monotonic", lambda: next(ticks))

    assert auto_detect_baud("/dev/fake") == 9600


def test_auto_detect_baud_returns_none_when_serial_unavailable(monkeypatch):
    monkeypatch.delitem(sys.modules, "serial", raising=False)

    class BlockSerialImport:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "serial":
                raise ImportError("blocked")
            return None

    blocker = BlockSerialImport()
    sys.meta_path.insert(0, blocker)
    try:
        assert auto_detect_baud("/dev/fake") is None
    finally:
        sys.meta_path.remove(blocker)
