#!/usr/bin/env python3
"""Fake MCP server for testing — speaks JSON-RPC over stdio."""
import sys
import json


def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "fake-mcp-server", "version": "1.0"},
        }}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {"name": "hello", "description": "Say hello",
             "inputSchema": {"type": "object", "properties": {
                 "name": {"type": "string", "description": "Name to greet"}}}},
            {"name": "add", "description": "Add two integers",
             "inputSchema": {"type": "object", "properties": {
                 "a": {"type": "integer"}, "b": {"type": "integer"}},
                 "required": ["a", "b"]}},
            {"name": "uppercase", "description": "Convert text to uppercase",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "Input text"}},
                 "required": ["text"]}},
        ]}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        if tool_name == "hello":
            content = f"Hello, {args.get('name', 'World')}!"
        elif tool_name == "add":
            content = str(int(args.get("a", 0)) + int(args.get("b", 0)))
        elif tool_name == "uppercase":
            content = args.get("text", "").upper()
        else:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": content}]}}

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": [
            {"uri": "file:///test/data.txt", "name": "Test Data", "mimeType": "text/plain"},
            {"uri": "file:///test/config.json", "name": "Test Config", "mimeType": "application/json"},
        ]}}

    if method == "resources/read":
        uri = params.get("uri", "")
        return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [
            {"uri": uri, "mimeType": "text/plain", "text": f"Content of {uri}\nLine 2\n"}
        ]}}

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if req.get("method") == "notifications/initialized":
            continue
        resp = handle_request(req)
        if resp:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
