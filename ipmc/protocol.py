from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

from .data import configure_defaults
from .tools import TOOLS

SERVER_INFO = {
    "name": "ipmc-mcp",
    "version": "0.1.0",
}


def make_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def make_error(message_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def list_tools_payload() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": info["description"],
            "inputSchema": info["inputSchema"],
        }
        for name, info in TOOLS.items()
    ]


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

    try:
        result = TOOLS[name]["handler"](arguments)
    except Exception as exc:
        emit(
            make_response(
                message_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "ok": False,
                                    "error": str(exc),
                                },
                                ensure_ascii=True,
                                indent=2,
                            ),
                        }
                    ],
                    "isError": True,
                },
            )
        )
        return

    emit(
        make_response(
            message_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=True, indent=2),
                    }
                ]
            },
        )
    )


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
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
        return {}

    if method == "tools/list":
        return make_response(message_id, {"tools": list_tools_payload()})

    if method == "tools/call":
        if not isinstance(params, dict):
            return make_error(message_id, -32602, "Tool params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in TOOLS:
            return make_error(message_id, -32602, f"Unknown tool '{name}'")
        if not isinstance(arguments, dict):
            return make_error(message_id, -32602, "Tool arguments must be an object")
        try:
            result = TOOLS[name]["handler"](arguments)
        except Exception as exc:
            return make_response(
                message_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2),
                        }
                    ],
                    "isError": True,
                },
            )
        return make_response(
            message_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=True, indent=2),
                    }
                ]
            },
        )

    return make_error(message_id, -32601, f"Method '{method}' not found")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apache Incubator IPMC oversight MCP server")
    parser.add_argument("--podlings-mcp-repo", help="Path to the PodlingsMCP checkout")
    parser.add_argument("--health-mcp-repo", help="Path to the HealthMCP checkout")
    parser.add_argument("--health-source", help="Path to apache-health report Markdown files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_defaults(
        podlings_repo=args.podlings_mcp_repo,
        health_repo=args.health_mcp_repo,
        health_source=args.health_source,
    )

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
            response = handle_message(message)
            if response:
                emit(response)
        except Exception as exc:
            emit(
                make_error(
                    None,
                    -32603,
                    f"Internal error: {exc}",
                    {"traceback": traceback.format_exc()},
                )
            )

    return 0
