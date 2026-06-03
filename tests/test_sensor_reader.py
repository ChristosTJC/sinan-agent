"""Tests for sensor data format detection, parsing, collection, and export."""

from __future__ import annotations

import csv

from agent.tools.sensor_reader import SensorReader, auto_detect_format, parse_line


class FakeMonitor:
    def __init__(self, lines):
        self.lines = list(lines)
        self.is_open = True
        self.closed = False

    def read_line(self):
        if not self.lines:
            return None
        return self.lines.pop(0)

    def close(self):
        self.closed = True
        self.is_open = False


def test_auto_detect_format_for_supported_lines():
    assert auto_detect_format("$TEMP,25.3,HUM,62.1*3F") == "nmea"
    assert auto_detect_format('{"temp": 25.3}') == "json"
    assert auto_detect_format("temp=25.3 humidity=62") == "kv"
    assert auto_detect_format("25.3,62.1,ok") == "csv"
    assert auto_detect_format("") == "unknown"


def test_module_parse_line_returns_structured_values():
    assert parse_line('{"temp": 25.3}') == {"temp": 25.3}
    assert parse_line("1,2.5,label") == {"format": "csv", "fields": [1, 2.5, "label"]}
    assert parse_line("temp=25.3 humidity=62") == {"temp": 25.3, "humidity": 62}
    assert parse_line("$TEMP,25.3,HUM,62.1")["format"] == "nmea"
    assert parse_line("") is None


def test_sensor_reader_parse_line_supports_all_text_formats():
    reader = SensorReader("/dev/fake")

    assert reader.parse_line('{"temp": 25.3}') == {"temp": 25.3}
    assert reader.parse_line("temp=25.3 humidity=62") == {
        "_format": "kv",
        "temp": 25.3,
        "humidity": 62,
    }
    assert reader.parse_line("25.3,62,label") == {
        "_format": "csv",
        "field_0": 25.3,
        "field_1": 62,
        "field_2": "label",
    }
    nmea = reader.parse_line("$TEMP,T,25.3,H,62")
    assert nmea["_format"] == "nmea"
    assert nmea["T"] == 25.3
    assert nmea["H"] == 62


def test_sensor_reader_read_sample_adds_timestamp(monkeypatch):
    reader = SensorReader("/dev/fake")
    reader._monitor = FakeMonitor(["temp=25.3"])
    monkeypatch.setattr("agent.tools.sensor_reader.time.time", lambda: 123.456)

    sample = reader.read_sample()

    assert sample == {"_format": "kv", "temp": 25.3, "_timestamp": 123.456}


def test_sensor_reader_collect_samples_stops_when_no_data(monkeypatch):
    reader = SensorReader("/dev/fake")
    reader._monitor = FakeMonitor(["temp=25.3", None, "humidity=62"])
    monkeypatch.setattr("agent.tools.sensor_reader.time.sleep", lambda _seconds: None)

    samples = reader.collect_samples(3, interval_sec=0.01)

    assert [sample for sample in samples if "temp" in sample or "humidity" in sample] == [
        {"_format": "kv", "temp": 25.3, "_timestamp": samples[0]["_timestamp"]},
        {"_format": "kv", "humidity": 62, "_timestamp": samples[1]["_timestamp"]},
    ]


def test_sensor_reader_export_csv_and_summary(tmp_path):
    samples = [
        {"_timestamp": 1.0, "temp": 20.0, "humidity": 50},
        {"_timestamp": 2.0, "temp": 22.0, "humidity": 54, "label": "ok"},
    ]
    output = tmp_path / "out" / "samples.csv"

    assert SensorReader.export_csv(samples, str(output)) is True
    with output.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["temp"] == "20.0"
    assert rows[1]["humidity"] == "54"

    summary = SensorReader.summary(samples)
    assert summary["temp"] == {"min": 20.0, "max": 22.0, "mean": 21.0, "std": 1.0, "count": 2}
    assert summary["humidity"]["mean"] == 52.0


def test_sensor_reader_export_csv_rejects_empty_samples(tmp_path):
    assert SensorReader.export_csv([], str(tmp_path / "empty.csv")) is False
    assert SensorReader.summary([]) == {}
