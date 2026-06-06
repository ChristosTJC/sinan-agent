from __future__ import annotations

import asyncio
import json


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self) -> list[dict]:
        return [
            {"name": "scan_serial"},
            {"name": "build_firmware"},
            {"name": "flash_firmware"},
            {"name": "read_sensor"},
            {"name": "device_call"},
        ]

    def set_danger_confirm(self, _enabled: bool) -> None:
        return None

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        args = arguments or {}
        self.calls.append((name, args))
        return {"success": True, "tool": name, "arguments": args}


class FakeKnowledgeBase:
    def search(self, query: str, limit: int = 10, source: str = "all") -> list[dict]:
        return [
            {
                "title": f"doc:{query}",
                "content": "matched",
                "doc_type": "mcu",
                "score": 1.0,
                "source": source,
            }
        ][:limit]


class FakeBoardKnowledgeBase:
    def list_boards(self) -> list[str]:
        return ["example_esp32s3"]

    def get_profile(self, board_id: str) -> dict | None:
        if board_id == "example_esp32s3":
            return {"board_id": board_id, "mcu": {"family": "esp32"}}
        return None


async def _asgi_request(app, method: str, path: str, body: dict | None = None, headers: dict | None = None):
    raw_body = json.dumps(body or {}).encode("utf-8") if body is not None else b""
    sent: list[dict] = []
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": raw_body, "more_body": False}

    async def send(message: dict):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in (headers or {}).items()
        ],
    }
    await app(scope, receive, send)

    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    chunks = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    payload = json.loads(b"".join(chunks).decode("utf-8") or "{}")
    return status, payload


def _make_app():
    from agent.api import SinanASGIApp

    return SinanASGIApp(
        registry=FakeRegistry(),
        knowledge_base=FakeKnowledgeBase(),
        board_kb=FakeBoardKnowledgeBase(),
        api_key="secret",
    )


def test_api_rejects_missing_api_key():
    app = _make_app()

    status, payload = asyncio.run(_asgi_request(app, "GET", "/health"))

    assert status == 401
    assert payload["error"] == "unauthorized"


def test_health_returns_available_tools_with_api_key():
    app = _make_app()

    status, payload = asyncio.run(_asgi_request(app, "GET", "/health", headers={"X-API-Key": "secret"}))

    assert status == 200
    assert payload["status"] == "ok"
    assert "flash_firmware" in payload["tools_available"]


def test_flash_firmware_endpoint_uses_project_path_and_port_contract():
    app = _make_app()

    status, payload = asyncio.run(
        _asgi_request(
            app,
            "POST",
            "/flash_firmware",
            body={
                "project_path": "/tmp/fw",
                "port": "/dev/ttyUSB0",
                "method": "esptool",
                "platform": "esp32",
                "chip": "ESP32-S3",
            },
            headers={"X-API-Key": "secret"},
        )
    )

    assert status == 200
    assert payload["tool"] == "flash_firmware"
    assert payload["arguments"] == {
        "project_path": "/tmp/fw",
        "port": "/dev/ttyUSB0",
        "method": "esptool",
        "platform": "esp32",
        "chip": "ESP32-S3",
    }


def test_sensor_read_endpoint_uses_read_sensor_contract():
    app = _make_app()

    status, payload = asyncio.run(
        _asgi_request(
            app,
            "POST",
            "/sensor_read",
            body={"port": "/dev/ttyACM0", "baudrate": 9600, "count": 3, "interval_sec": 0.2},
            headers={"X-API-Key": "secret"},
        )
    )

    assert status == 200
    assert payload["tool"] == "read_sensor"
    assert payload["arguments"] == {
        "port": "/dev/ttyACM0",
        "baudrate": 9600,
        "count": 3,
        "interval_sec": 0.2,
    }


def test_knowledge_and_board_endpoints_are_served_by_local_backends():
    app = _make_app()

    knowledge_status, knowledge_payload = asyncio.run(
        _asgi_request(
            app,
            "POST",
            "/knowledge_search",
            body={"query": "ESP32-S3", "limit": 1},
            headers={"X-API-Key": "secret"},
        )
    )
    board_status, board_payload = asyncio.run(
        _asgi_request(app, "GET", "/board_profile/example_esp32s3", headers={"X-API-Key": "secret"})
    )

    assert knowledge_status == 200
    assert knowledge_payload["total"] == 1
    assert knowledge_payload["results"][0]["title"] == "doc:ESP32-S3"
    assert board_status == 200
    assert board_payload["profile"]["mcu"]["family"] == "esp32"


def test_coze_openapi_matches_api_contract():
    spec = json.loads(open("coze-plugin-openapi.json", encoding="utf-8").read())

    flash_schema = spec["paths"]["/flash_firmware"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    sensor_schema = spec["paths"]["/sensor_read"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    device_schema = spec["paths"]["/device_bridge"]["post"]["requestBody"]["content"]["application/json"]["schema"]

    assert flash_schema["required"] == ["project_path", "port"]
    assert "firmware" not in flash_schema["properties"]
    assert {"platformio", "stm32cubeprog", "jlink", "arduino", "nrfjprog", "west"}.issubset(
        set(flash_schema["properties"]["method"]["enum"])
    )
    assert "count" in sensor_schema["properties"]
    assert "interval_sec" in sensor_schema["properties"]
    assert "duration_sec" not in sensor_schema["properties"]
    assert device_schema["required"] == ["host", "method"]
