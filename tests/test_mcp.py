import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from scrcrappy import mcp

TOKEN = "s3cret"


def post(server, body, token=TOKEN, origin=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/mcp", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
            return r.status, json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        return e.code, None


@pytest.fixture
def server():
    calls, gate = [], threading.Event()
    gate.set()

    def echo(args):
        calls.append(args)
        gate.wait(5)
        return [{"type": "text", "text": f"hi {args.get('name')}"}]

    def broken(args):
        raise mcp.ToolError("phone says no")

    tools = [mcp.Tool("echo", "Say hi.", {"type": "object", "properties": {"name": {"type": "string"}}}, echo),
             mcp.Tool("broken", "Always fails.", {"type": "object", "properties": {}}, broken)]
    s = mcp.McpServer(TOKEN, lambda: tools, port=0)
    s.start()
    s.calls, s.gate = calls, gate
    yield s
    s.stop()


def call(name, args=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}


def test_rejects_missing_or_wrong_token(server):
    assert post(server, call("echo"), token=None)[0] == 401
    assert post(server, call("echo"), token="nope")[0] == 401
    assert server.calls == []


def test_rejects_foreign_origin(server):
    assert post(server, call("echo"), origin="http://evil.example")[0] == 403
    assert server.calls == []
    assert post(server, call("echo"), origin="http://localhost:3000")[0] == 200


def test_initialize_and_list_tools(server):
    status, r = post(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "t", "version": "0"}}})
    assert status == 200 and r["result"]["protocolVersion"] == "2025-06-18"
    assert r["result"]["serverInfo"]["name"] == "scrcrappy" and "tools" in r["result"]["capabilities"]
    assert post(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
    status, r = post(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in r["result"]["tools"]] == ["echo", "broken"]
    assert r["result"]["tools"][0]["inputSchema"]["properties"]["name"]["type"] == "string"


def test_call_returns_content_and_marks_activity(server):
    before = server.last_request
    server.gate.clear()
    result = {}
    t = threading.Thread(target=lambda: result.update(r=post(server, call("echo", {"name": "bob"}))))
    t.start()
    for _ in range(100):
        if server.busy:
            break
        time.sleep(0.01)
    assert server.busy
    server.gate.set()
    t.join(5)
    status, r = result["r"]
    assert r["result"]["content"] == [{"type": "text", "text": "hi bob"}] and not r["result"].get("isError")
    assert not server.busy and server.last_request > before


def test_tool_error_is_iserror_result(server):
    status, r = post(server, call("broken"))
    assert status == 200 and r["result"]["isError"] is True
    assert r["result"]["content"][0]["text"] == "phone says no"


def test_unknown_method_and_tool(server):
    assert post(server, {"jsonrpc": "2.0", "id": 9, "method": "nope"})[1]["error"]["code"] == -32601
    assert post(server, call("missing"))[1]["error"]["code"] == -32602


def test_get_is_not_allowed(server):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 405


def test_busy_port_raises_oserror():
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    with pytest.raises(OSError):
        mcp.McpServer(TOKEN, lambda: [], port=taken.getsockname()[1]).start()
    taken.close()


def test_non_ascii_authorization_is_401(server):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    c.putrequest("POST", "/mcp")
    c.putheader("Authorization", "Bearer s3crèt".encode("latin-1"))
    c.putheader("Content-Length", "2")
    c.endheaders(b"{}")
    assert c.getresponse().status == 401


def test_401_tells_the_client_it_is_a_bearer_token(server):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}/mcp", b"{}", {"Authorization": "Bearer nope"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401 and e.value.headers["WWW-Authenticate"].startswith("Bearer")
    assert b"Settings" in e.value.read()  # where to get the right command


def test_initialize_answers_a_supported_version(server):
    _, r = post(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert r["result"]["protocolVersion"] in mcp.SUPPORTED
    _, r = post(server, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26"
