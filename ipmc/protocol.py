from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

from mcp import types
from mcp.server import Server as McpServer

from .data import configure_defaults
from .tools import TOOLS

SERVER_INFO = {
    "name": "ipmc-mcp",
    "version": "0.1.3",
}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

NO_RESPONSE: dict[str, Any] = {}
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8080


def make_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def make_error(message_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def emit(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)


def tool_response(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Build a standard MCP tool result with structured data when available."""

    if isinstance(payload, str):
        result: dict[str, Any] = {"content": [{"type": "text", "text": payload}]}
    else:
        result = {
            "content": [{"type": "text", "text": _json_text(payload)}],
            "structuredContent": payload,
        }
    if is_error:
        result["isError"] = True
    return result


def list_tools_payload() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": info["description"],
            "inputSchema": info["inputSchema"],
        }
        for name, info in TOOLS.items()
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise ValueError(f"Unknown tool '{name}'")
    try:
        return tool_response(TOOLS[name]["handler"](arguments))
    except Exception as exc:
        return tool_response({"ok": False, "error": str(exc), "tool": name}, is_error=True)


def handle_initialize(message_id: Any, params: dict[str, Any]) -> None:
    protocol_version = params.get("protocolVersion", "2024-11-05")
    emit(
        make_response(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    )


def handle_tools_list(message_id: Any) -> None:
    emit(make_response(message_id, {"tools": list_tools_payload()}))


def handle_tools_call(message_id: Any, params: dict[str, Any]) -> None:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if name not in TOOLS:
        emit(make_error(message_id, -32602, f"Unknown tool '{name}'"))
        return
    if not isinstance(arguments, dict):
        emit(make_error(message_id, -32602, "Tool arguments must be an object"))
        return

    emit(make_response(message_id, call_tool(name, arguments)))


def _error_data(reason: str, **extra: Any) -> dict[str, Any]:
    data = {"reason": reason}
    data.update(extra)
    return data


def _valid_id(message_id: Any) -> bool:
    if message_id is None:
        return True
    if isinstance(message_id, bool):
        return False
    return isinstance(message_id, str | int)


def _request_id(message: Any) -> Any:
    if isinstance(message, dict) and _valid_id(message.get("id")):
        return message.get("id")
    return None


def _invalid_request(message: Any, reason: str, **extra: Any) -> dict[str, Any]:
    return make_error(_request_id(message), INVALID_REQUEST, "Invalid Request", _error_data(reason, **extra))


def _validate_request(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        return _invalid_request(message, "JSON-RPC request must be an object")
    if message.get("jsonrpc") != "2.0":
        return _invalid_request(message, "jsonrpc must be '2.0'", field="jsonrpc")
    if "method" not in message:
        return _invalid_request(message, "method is required", field="method")
    if not isinstance(message["method"], str) or not message["method"]:
        return _invalid_request(message, "method must be a non-empty string", field="method")
    if "id" in message and not _valid_id(message["id"]):
        return _invalid_request(message, "id must be a string, integer, or null", field="id")
    if "params" in message and not isinstance(message["params"], dict):
        return make_error(
            message.get("id"),
            INVALID_PARAMS,
            "Invalid params",
            _error_data("params must be an object", field="params"),
        )
    return {}


def handle_message(message: Any) -> dict[str, Any]:
    validation_error = _validate_request(message)
    if validation_error:
        return validation_error

    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params", {})

    if method == "initialize":
        protocol_version = params.get("protocolVersion", "2024-11-05") if isinstance(params, dict) else "2024-11-05"
        return make_response(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )

    if method == "notifications/initialized":
        return NO_RESPONSE

    if method == "tools/list":
        return make_response(message_id, {"tools": list_tools_payload()})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return make_error(
                message_id,
                INVALID_PARAMS,
                "Invalid params",
                _error_data("Tool name must be a non-empty string", field="name"),
            )
        if name not in TOOLS:
            return make_error(message_id, INVALID_PARAMS, f"Unknown tool '{name}'", _error_data("Unknown tool"))
        if not isinstance(arguments, dict):
            return make_error(
                message_id,
                INVALID_PARAMS,
                "Invalid params",
                _error_data("Tool arguments must be an object", field="arguments"),
            )
        return make_response(message_id, call_tool(name, arguments))

    return make_error(message_id, METHOD_NOT_FOUND, f"Method '{method}' not found")


def handle_payload(payload: Any) -> dict[str, Any] | list[dict[str, Any]]:
    """Handle a JSON-RPC payload, including batch requests."""

    if isinstance(payload, list):
        if not payload:
            return make_error(None, INVALID_REQUEST, "Invalid Request", _error_data("Batch must not be empty"))
        responses = [response for item in payload if (response := handle_message(item))]
        return responses
    return handle_message(payload)


def _configure_from_args(args: argparse.Namespace) -> None:
    configure_defaults(
        podlings_source=args.podlings_source,
        health_source=args.health_source,
        report_source=args.report_source,
        mail_source=args.mail_source,
        mail_api_base=args.mail_api_base,
        release_dist_base=args.release_dist_base,
        release_archive_base=args.release_archive_base,
    )


def _write_stdio_error(code: int, message: str, data: Any = None) -> None:
    emit(make_error(None, code, message, data))


def run_stdio() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
            response = handle_payload(message)
            if response:
                emit(response)
        except json.JSONDecodeError as exc:
            _write_stdio_error(
                PARSE_ERROR,
                "Parse error",
                _error_data(str(exc), line=exc.lineno, column=exc.colno),
            )
        except Exception as exc:
            _write_stdio_error(
                INTERNAL_ERROR,
                f"Internal error: {exc}",
                {"traceback": traceback.format_exc()},
            )

    return 0


def run_http(host: str, port: int) -> int:
    import uvicorn

    uvicorn.run(
        create_streamable_http_app(),
        host=host,
        port=port,
        log_level="info",
    )
    return 0


def create_mcp_server() -> McpServer:
    server: McpServer = McpServer(SERVER_INFO["name"], version=SERVER_INFO["version"])

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=info["description"],
                inputSchema=info["inputSchema"],
            )
            for name, info in TOOLS.items()
        ]

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | types.CallToolResult:
        if name not in TOOLS:
            payload = {"ok": False, "error": f"Unknown tool '{name}'", "tool": name}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=_json_text(payload))],
                structuredContent=payload,
                isError=True,
            )
        try:
            return TOOLS[name]["handler"](arguments or {})
        except Exception as exc:
            payload = {"ok": False, "error": str(exc), "tool": name}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=_json_text(payload))],
                structuredContent=payload,
                isError=True,
            )

    return server


def create_streamable_http_app(*, json_response: bool = False, stateless: bool = False) -> Any:
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    mcp_server = create_mcp_server()
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=json_response,
        stateless=stateless,
    )
    mcp_app = StreamableHTTPASGIApp(session_manager)

    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"ok": True, "serverInfo": SERVER_INFO})

    return Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/mcp", endpoint=mcp_app),
        ],
        lifespan=lambda _app: session_manager.run(),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apache Incubator IPMC oversight MCP server")
    parser.add_argument("--podlings-source", help="Optional URL or local path for podlings.xml")
    parser.add_argument("--health-source", help="Path to apache-health report Markdown files")
    parser.add_argument("--report-source", help="Path to ReportMCP cached ASF Incubator report files")
    parser.add_argument("--mail-source", help="Path to MailMCP cached ASF Incubator general-list message files")
    parser.add_argument("--mail-api-base", help="MailMCP/Pony Mail API base URL for live Incubator general-list search")
    parser.add_argument("--release-dist-base", help="ReleaseMCP dist.apache.org base URL or local release directory")
    parser.add_argument(
        "--release-archive-base",
        help="ReleaseMCP archive.apache.org base URL or local archive directory",
    )
    parser.add_argument("--http", action="store_true", help="Serve JSON-RPC/MCP over HTTP instead of stdio")
    parser.add_argument(
        "--host", default=DEFAULT_HTTP_HOST, help=f"HTTP bind host when --http is set (default: {DEFAULT_HTTP_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP bind port when --http is set (default: {DEFAULT_HTTP_PORT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_from_args(args)
    if args.http:
        return run_http(args.host, args.port)
    return run_stdio()
