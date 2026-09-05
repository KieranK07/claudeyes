"""A minimal stdio MCP server. No dependencies, on purpose.

`pip install mcp` is one more thing to go wrong on a machine where this is
supposed to be running all day, and the protocol surface we need is small.

Hard rule for stdio transport: stdout carries JSON-RPC and NOTHING else. Every
diagnostic goes to stderr. One stray print() corrupts the stream and the server
dies with an unhelpful parse error.
"""
from __future__ import annotations

import json
import sys
import threading
from typing import Any, Callable

PROTOCOL_VERSION = "2024-11-05"


class Server:
    def __init__(self, name: str, version: str = "0.1.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._write_lock = threading.Lock()

    def tool(self, name: str, description: str, schema: dict):
        def deco(fn: Callable[[dict], Any]):
            self._tools[name] = {
                "name": name,
                "description": description,
                "inputSchema": schema,
            }
            self._handlers[name] = fn
            return fn
        return deco

    # -- transport -------------------------------------------------------

    def _send(self, obj: dict) -> None:
        with self._write_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    def log(self, *a) -> None:
        print(*a, file=sys.stderr, flush=True)

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Notifications have no id and expect no reply.
            if "id" not in msg:
                continue
            try:
                result = self._dispatch(msg)
            except Exception as e:  # never die on one bad call
                self._send({"jsonrpc": "2.0", "id": msg.get("id"),
                            "error": {"code": -32603, "message": str(e)}})
                continue
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _dispatch(self, msg: dict) -> dict:
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            }
        if method == "tools/list":
            return {"tools": list(self._tools.values())}
        if method == "tools/call":
            tname = params.get("name", "")
            args = params.get("arguments") or {}
            fn = self._handlers.get(tname)
            if fn is None:
                return {"isError": True,
                        "content": [{"type": "text", "text": f"no such tool: {tname}"}]}
            out = fn(args)
            if not isinstance(out, str):
                out = json.dumps(out, indent=2, default=str)
            return {"content": [{"type": "text", "text": out}]}
        if method in ("ping", "notifications/initialized"):
            return {}
        raise ValueError(f"unsupported method: {method}")
