"""Public ASGI API for Coze/OpenAPI plugin deployment."""

from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import unquote

from agent.board_knowledge.manager import BoardKnowledgeBase
from agent.tools import get_registry


JsonDict = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _package_version() -> str:
    try:
        return version("sinan-embedded-agent")
    except PackageNotFoundError:
        return "0.1.0"


def _default_knowledge_base() -> Any | None:
    kb_dir = _repo_root() / "knowledge"
    if not kb_dir.is_dir():
        return None
    try:
        from agent.config import get_sinan_home
        from agent.memory.knowledge_base import KnowledgeBase

        return KnowledgeBase(kb_dir=kb_dir, user_kb_dir=get_sinan_home() / "knowledge")
    except Exception:
        return None


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _json_body(raw: bytes) -> JsonDict:
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _pick(data: JsonDict, names: list[str]) -> JsonDict:
    return {name: data[name] for name in names if name in data and data[name] is not None}


class SinanASGIApp:
    """Small ASGI adapter around Sinan's existing tool and knowledge backends."""

    def __init__(
        self,
        *,
        registry: Any | None = None,
        knowledge_base: Any | None = None,
        board_kb: BoardKnowledgeBase | None = None,
        api_key: str | None = None,
    ) -> None:
        self.registry = registry if registry is not None else get_registry()
        if hasattr(self.registry, "set_danger_confirm"):
            self.registry.set_danger_confirm(False)
        self.knowledge_base = knowledge_base if knowledge_base is not None else _default_knowledge_base()
        self.board_kb = board_kb if board_kb is not None else BoardKnowledgeBase()
        self.api_key = api_key if api_key is not None else os.environ.get("SINAN_API_KEY", "")

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._send_json(send, 500, {"error": "unsupported_scope"})
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", "/"))
        request_headers = _headers(scope)

        if not self.api_key:
            await self._send_json(send, 503, {"error": "SINAN_API_KEY is not configured"})
            return
        if request_headers.get("x-api-key") != self.api_key:
            await self._send_json(send, 401, {"error": "unauthorized"})
            return

        try:
            body = _json_body(await _read_body(receive)) if method in {"POST", "PUT", "PATCH"} else {}
            status, payload = self._dispatch(method, path, body)
        except json.JSONDecodeError:
            status, payload = 400, {"error": "invalid_json"}
        except ValueError as exc:
            status, payload = 400, {"error": str(exc)}
        except Exception as exc:
            status, payload = 500, {"error": f"internal_error: {exc}"}

        await self._send_json(send, status, payload)

    def _dispatch(self, method: str, path: str, body: JsonDict) -> tuple[int, JsonDict]:
        if method == "GET" and path == "/health":
            return 200, self._health()
        if method == "POST" and path == "/scan_serial":
            return 200, self._scan_serial(body)
        if method == "POST" and path == "/serial_monitor":
            return 200, self._tool("serial_monitor", body, ["port", "baudrate", "duration_sec", "max_bytes"])
        if method == "POST" and path == "/sensor_read":
            return 200, self._tool("read_sensor", body, ["port", "baudrate", "count", "interval_sec", "export_csv"])
        if method == "POST" and path == "/build_firmware":
            return 200, self._tool(
                "build_firmware",
                body,
                ["project_path", "target", "env", "platform", "chip", "force"],
            )
        if method == "POST" and path == "/flash_firmware":
            return 200, self._tool(
                "flash_firmware",
                body,
                ["project_path", "port", "method", "platform", "chip"],
            )
        if method == "POST" and path == "/knowledge_search":
            return 200, self._knowledge_search(body)
        if method == "GET" and path == "/board_list":
            return 200, {"boards": self.board_kb.list_boards()}
        if method == "GET" and path.startswith("/board_profile/"):
            board_id = unquote(path.removeprefix("/board_profile/"))
            return self._board_profile(board_id)
        if method == "POST" and path == "/device_bridge":
            return 200, self._tool("device_call", body, ["host", "port", "method", "params"])
        return 404, {"error": "not_found"}

    def _health(self) -> JsonDict:
        tools = []
        for tool in self.registry.list_tools():
            name = tool.get("name") if isinstance(tool, dict) else None
            if name:
                tools.append(name)
        return {"status": "ok", "version": _package_version(), "tools_available": tools}

    def _scan_serial(self, body: JsonDict) -> JsonDict:
        result = self.registry.call_tool("scan_serial", {})
        if body.get("include_usb", True):
            result["usb_devices"] = self.registry.call_tool("scan_usb", {}).get("result", [])
        return result

    def _tool(self, name: str, body: JsonDict, allowed_fields: list[str]) -> JsonDict:
        return self.registry.call_tool(name, _pick(body, allowed_fields))

    def _knowledge_search(self, body: JsonDict) -> JsonDict:
        query = str(body.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        limit = int(body.get("limit", 5))
        doc_type = body.get("doc_type")

        if self.knowledge_base is None or not hasattr(self.knowledge_base, "search"):
            return {"results": [], "total": 0}

        results = list(self.knowledge_base.search(query, limit=limit, source="all"))
        if doc_type:
            results = [r for r in results if r.get("doc_type") == doc_type]
        return {"results": results[:limit], "total": len(results)}

    def _board_profile(self, board_id: str) -> tuple[int, JsonDict]:
        if not board_id:
            return 400, {"error": "board_id is required"}
        profile = self.board_kb.get_profile(board_id)
        if profile is None:
            return 404, {"error": "board_not_found", "board_id": board_id}
        return 200, {"board_id": board_id, "profile": profile}

    @staticmethod
    async def _send_json(send: Send, status: int, payload: JsonDict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})


app = SinanASGIApp()

