"""Tests for board profile loading, validation, and context generation."""

from __future__ import annotations

import json

import pytest

import agent.board_knowledge.validator as validator_mod
from agent.board_knowledge.manager import BoardKnowledgeBase
from agent.board_knowledge.validator import BoardValidator


def _profile(board_id: str = "test_board") -> dict:
    return {
        "schema_version": "1.0.0",
        "board_id": board_id,
        "display_name": "Test Board",
        "mcu": {
            "model": "STM32F103C8T6",
            "arch": "ARM Cortex-M3",
            "clock": "72MHz",
            "flash": "64KB",
            "ram": "20KB",
            "voltage": "2.0V-3.6V",
        },
        "ports": [
            {
                "name": "USART1",
                "type": "serial",
                "pins": {"TX": "PA9", "RX": "PA10"},
                "notes": "debug uart",
            }
        ],
        "peripherals": [
            {
                "name": "LED",
                "kind": "led",
                "pins": {"LED": "PC13"},
                "notes": "active low",
            }
        ],
        "common_pitfalls": ["BOOT0 must be low for normal boot"],
    }


def test_board_knowledge_lists_valid_json_profiles(tmp_path):
    boards_dir = tmp_path / "boards"
    boards_dir.mkdir()
    (boards_dir / "test_board.json").write_text(json.dumps(_profile()), encoding="utf-8")
    (boards_dir / "_ignored.json").write_text(json.dumps(_profile("_ignored")), encoding="utf-8")
    (boards_dir / "broken.json").write_text("{bad json", encoding="utf-8")

    kb = BoardKnowledgeBase(boards_dir)

    assert kb.list_boards() == ["test_board"]


def test_board_knowledge_get_profile_ports_and_peripherals(tmp_path):
    boards_dir = tmp_path / "boards"
    boards_dir.mkdir()
    (boards_dir / "test_board.json").write_text(json.dumps(_profile()), encoding="utf-8")
    kb = BoardKnowledgeBase(boards_dir)

    profile = kb.get_profile("test_board")

    assert profile is not None
    assert profile["display_name"] == "Test Board"
    assert kb.get_ports("test_board")[0]["name"] == "USART1"
    assert kb.get_peripherals("test_board")[0]["name"] == "LED"
    assert kb.get_profile("missing_board") is None


def test_board_knowledge_create_and_update_board(tmp_path):
    boards_dir = tmp_path / "boards"
    boards_dir.mkdir()
    kb = BoardKnowledgeBase(boards_dir)
    profile = _profile("created_board")

    assert kb.create_board("created_board", profile) is True
    assert kb.create_board("created_board", _profile("created_board")) is False
    assert (boards_dir / "created_board.json").is_file()

    assert kb.update_board("created_board", {"display_name": "Updated Board"}) is True
    assert kb.get_profile("created_board")["display_name"] == "Updated Board"
    assert kb.update_board("missing_board", {"display_name": "Nope"}) is False


def test_board_knowledge_build_context_includes_ports_peripherals_and_pitfalls(tmp_path):
    boards_dir = tmp_path / "boards"
    boards_dir.mkdir()
    (boards_dir / "test_board.json").write_text(json.dumps(_profile()), encoding="utf-8")
    kb = BoardKnowledgeBase(boards_dir)

    context = kb.build_context(["test_board"])

    assert "Test Board" in context
    assert "USART1" in context
    assert "LED" in context
    assert "BOOT0 must be low" in context


def test_board_knowledge_invalid_board_id_is_rejected(tmp_path):
    kb = BoardKnowledgeBase(tmp_path)

    with pytest.raises(ValueError, match="board_id"):
        kb.get_profile("../bad")


def test_board_validator_rejects_non_object():
    validator = BoardValidator()

    assert "JSON 对象" in validator.validate(["not", "a", "dict"])[0]


def test_board_validator_reports_missing_required_fields():
    validator = BoardValidator()

    errors = validator.validate({"schema_version": "1.0.0"})

    assert any("board_id" in error for error in errors)
    assert any("mcu" in error for error in errors)


def test_board_validator_validate_or_raise_formats_errors():
    validator = BoardValidator()
    bad = _profile()
    bad["ports"] = [{"name": "BAD", "type": "not-a-valid-type", "pins": {}}]

    with pytest.raises(ValueError, match="板卡配置校验失败"):
        validator.validate_or_raise(bad)


def test_board_validator_warns_when_schema_file_missing(tmp_path, capsys):
    validator = BoardValidator(tmp_path / "missing.schema.json")

    captured = capsys.readouterr()

    assert validator._loaded is False
    assert "Schema 文件不存在" in captured.err


def test_board_validator_reports_invalid_schema_file(tmp_path, capsys):
    schema = tmp_path / "schema.json"
    schema.write_text("{bad json", encoding="utf-8")

    validator = BoardValidator(schema)
    captured = capsys.readouterr()

    assert validator._loaded is False
    assert "无法加载 Schema 文件" in captured.err


def test_board_validator_fallback_checks_nested_required_fields(monkeypatch):
    monkeypatch.setattr(validator_mod, "_HAS_JSONSCHEMA", False)
    validator = BoardValidator()
    bad = {
        "schema_version": "1.0.0",
        "board_id": "fallback_board",
        "display_name": "Fallback",
        "mcu": {"arch": "Cortex-M"},
        "ports": [{"name": "UART"}],
        "peripherals": [{}],
    }

    errors = validator.validate(bad)

    assert any("jsonschema 库未安装" in error for error in errors)
    assert any("mcu. 缺少必填子字段: 'clock'" in error for error in errors)
    assert any("ports[0] 缺少必填字段: 'type'" in error for error in errors)
    assert any("peripherals[0] 缺少必填字段: 'name'" in error for error in errors)


def test_board_validator_fallback_reports_bad_collection_types(monkeypatch):
    monkeypatch.setattr(validator_mod, "_HAS_JSONSCHEMA", False)
    validator = BoardValidator()
    bad = _profile()
    bad["ports"] = "USART1"
    bad["peripherals"] = "LED"

    errors = validator.validate(bad)

    assert any("'ports' 必须是一个数组" in error for error in errors)
    assert any("'peripherals' 必须是一个数组" in error for error in errors)
