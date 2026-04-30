from __future__ import annotations

import argparse
import json
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from .data import configure_defaults
from .tools import TOOLS

SERVER_INFO = {
    "name": "ipmc-mcp",
    "version": "0.1.0",
}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

NO_RESPONSE: dict[str, Any] = {}
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
SUPPORTED_HTTP_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}


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


class _McpHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True


class McpHttpHandler(BaseHTTPRequestHandler):
    server_version = "IPMCMCPHTTP/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "serverInfo": SERVER_INFO})
            return
        if self.path in {"/", "/mcp"}:
            self._send_empty(HTTPStatus.METHOD_NOT_ALLOWED, allow="POST, OPTIONS")
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in {"/", "/mcp"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
            return
        if not self._accepts_mcp_response():
            self._send_json(
                HTTPStatus.NOT_ACCEPTABLE,
                make_error(
                    None,
                    INVALID_REQUEST,
                    "Invalid Request",
                    _error_data("Accept header must include application/json and text/event-stream"),
                ),
            )
            return
        if not self._valid_protocol_version():
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                make_error(
                    None,
                    INVALID_REQUEST,
                    "Invalid Request",
                    _error_data("Unsupported MCP-Protocol-Version header"),
                ),
            )
            return

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self._send_json(
                HTTPStatus.LENGTH_REQUIRED,
                make_error(None, INVALID_REQUEST, "Invalid Request", _error_data("Content-Length is required")),
            )
            return

        try:
            body = self.rfile.read(int(content_length))
            payload = json.loads(body.decode("utf-8"))
            response = handle_payload(payload)
        except ValueError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                make_error(None, PARSE_ERROR, "Parse error", _error_data(str(exc))),
            )
            return
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                make_error(None, INTERNAL_ERROR, f"Internal error: {exc}", {"traceback": traceback.format_exc()}),
            )
            return

        if response in ({}, []):
            self._send_empty(HTTPStatus.ACCEPTED)
            return
        self._send_json(HTTPStatus.OK, response)

    def do_DELETE(self) -> None:
        if self.path in {"/", "/mcp"}:
            self._send_empty(HTTPStatus.METHOD_NOT_ALLOWED, allow="POST, OPTIONS")
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def _accepts_mcp_response(self) -> bool:
        accept = self.headers.get("Accept")
        if accept is None:
            return True
        accepted_types = {part.split(";", maxsplit=1)[0].strip() for part in accept.split(",")}
        return "*/*" in accepted_types or {"application/json", "text/event-stream"}.issubset(accepted_types)

    def _valid_protocol_version(self) -> bool:
        version = self.headers.get("MCP-Protocol-Version")
        return version is None or version in SUPPORTED_HTTP_PROTOCOL_VERSIONS

    def _send_empty(self, status: HTTPStatus, *, allow: str | None = None) -> None:
        self.send_response(status)
        self._send_common_headers()
        if allow is not None:
            self.send_header("Allow", allow)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type, MCP-Protocol-Version, Mcp-Session-Id")


def run_http(host: str, port: int) -> int:
    server = cast(_McpHttpServer, _McpHttpServer((host, port), McpHttpHandler))
    raw_address, bound_port = server.server_address[:2]
    address = raw_address.decode("utf-8") if isinstance(raw_address, bytes) else raw_address
    print(f"IPMC MCP HTTP server listening on http://{address}:{bound_port}/mcp", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


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
