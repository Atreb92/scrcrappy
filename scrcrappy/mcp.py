"""A minimal MCP server (Streamable HTTP, JSON responses only) so AI agents can use the running window.

Local only (127.0.0.1), every request needs `Authorization: Bearer <token>`, and requests from web pages
(a non-local Origin) are refused. One tool call runs at a time.
"""
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from typing import Callable

PORT = 7331
LOCAL_ORIGIN = re.compile(r"https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first: answered when a client asks for another


class ToolError(Exception):
    """A tool failed in a way the AI should read (returned as an isError result, not a protocol error)."""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[dict], list[dict]]  # arguments -> MCP content blocks


def _version() -> str:
    try:
        return metadata.version("scrcrappy")
    except metadata.PackageNotFoundError:
        return "dev"


class McpServer:
    def __init__(self, token: str, tools: Callable[[], list[Tool]], port: int = PORT) -> None:
        self.token, self.tools, self.port = token, tools, port
        self.last_request = 0.0  # monotonic time of the last authenticated request
        self.busy = False  # a tool call is running
        self._call_lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        """Serve in a background thread. Raises OSError if the port is taken."""
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # quiet: the terminal belongs to scrcrappy
                pass

            def do_GET(self) -> None:
                self._reply(405, None)  # no server-to-client stream

            def do_DELETE(self) -> None:
                self._reply(405, None)

            def do_POST(self) -> None:
                if self.path.split("?")[0] != "/mcp":
                    return self._reply(404, None)
                if (origin := self.headers.get("Origin")) and not LOCAL_ORIGIN.match(origin):
                    return self._reply(403, None)
                got = self.headers.get("Authorization", "").encode("latin-1")  # http.server decodes as latin-1
                if not hmac.compare_digest(got, f"Bearer {server.token}".encode()):
                    return self._reply(401, _error(None, -32001, "wrong or missing token: copy the setup command "
                                                   "again from scrcrappy's Settings"),
                                       {"WWW-Authenticate": 'Bearer error="invalid_token"'})
                try:
                    msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                except ValueError:
                    return self._reply(400, _error(None, -32700, "parse error"))
                server.last_request = time.monotonic()
                if not isinstance(msg, dict):
                    return self._reply(400, _error(None, -32600, "send one JSON-RPC message per request"))
                if "id" not in msg:  # notification
                    return self._reply(202, None)
                self._reply(200, server.handle(msg))

            def _reply(self, status: int, body: dict | None, headers: dict | None = None) -> None:
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def handle(self, msg: dict) -> dict:
        method, params, id_ = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if not isinstance(params, dict):
            return _error(id_, -32602, "params must be an object")
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _result(id_, {"protocolVersion": asked if asked in SUPPORTED else SUPPORTED[0],
                                 "capabilities": {"tools": {}},
                                 "serverInfo": {"name": "scrcrappy", "version": _version()}})
        if method == "ping":
            return _result(id_, {})
        if method == "tools/list":
            return _result(id_, {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.schema}
                                           for t in self.tools()]})
        if method == "tools/call":
            tool = next((t for t in self.tools() if t.name == params.get("name")), None)
            if not tool:
                return _error(id_, -32602, f"unknown tool: {params.get('name')}")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return _error(id_, -32602, "arguments must be an object")
            with self._call_lock:
                self.busy = True
                try:
                    return _result(id_, {"content": tool.run(args)})
                except ToolError as e:
                    return _result(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
                except Exception as e:  # never drop the connection: the AI gets a readable failure
                    return _result(id_, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                                         "isError": True})
                finally:
                    self.busy = False
        return _error(id_, -32601, f"method not found: {method}")


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
