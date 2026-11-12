"""Minimal MCP stdio server loop (JSON-RPC 2.0, newline-delimited), Python standard library only."""
import json
import sys
import traceback

PROTOCOL = "2025-06-18"


def serve(name, version, tools, instructions=""):
    """tools: {tool_name: (description, input_schema, handler(arguments) -> str|dict)}."""
    stdin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin
    out = sys.stdout

    def send(message):
        out.write(json.dumps(message, ensure_ascii=True) + "\n")
        out.flush()

    for raw in stdin:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        method, ident = request.get("method"), request.get("id")
        if ident is None:
            continue  # notifications (for example notifications/initialized) need no reply
        params = request.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": name, "version": version}, "instructions": instructions}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": key, "description": desc, "inputSchema": schema}
                                for key, (desc, schema, _) in tools.items()]}
        elif method == "tools/call":
            tool = tools.get(params.get("name"))
            if tool is None:
                send({"jsonrpc": "2.0", "id": ident,
                      "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}})
                continue
            try:
                value = tool[2](params.get("arguments") or {})
                text = value if isinstance(value, str) else json.dumps(value, indent=2)
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as exc:  # tool errors are reported to the agent, not crashed
                detail = f"{type(exc).__name__}: {exc}"
                print(traceback.format_exc(), file=sys.stderr)
                result = {"content": [{"type": "text", "text": detail}], "isError": True}
        else:
            send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Method not found: {method}"}})
            continue
        send({"jsonrpc": "2.0", "id": ident, "result": result})
