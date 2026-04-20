from __future__ import annotations

import json
import unittest
from unittest import mock

from ipmc import protocol
from tests.fixtures import make_fixture_sources


class ProtocolTests(unittest.TestCase):
    def test_make_response_and_make_error_helpers(self) -> None:
        self.assertEqual(protocol.make_response(7, {"ok": True}), {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}})
        self.assertEqual(
            protocol.make_error(8, -1, "bad", {"extra": True}),
            {"jsonrpc": "2.0", "id": 8, "error": {"code": -1, "message": "bad", "data": {"extra": True}}},
        )

    def test_list_tools_payload_contains_expected_tools(self) -> None:
        tool_names = [tool["name"] for tool in protocol.list_tools_payload()]

        self.assertEqual(
            tool_names,
            [
                "recent_changes",
                "significant_changes",
                "reporting_gaps",
                "reporting_reliability",
                "release_visibility",
                "reporting_cohort",
                "stalled_podlings",
                "ipmc_watchlist",
                "graduation_readiness",
                "podling_brief",
                "mentoring_attention_needed",
                "community_health_summary",
            ],
        )

    def test_handle_message_initialize(self) -> None:
        response = protocol.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )

        self.assertEqual(response["result"]["serverInfo"]["name"], "ipmc-mcp")

    def test_emit_and_wrapper_handlers(self) -> None:
        stdout = mock.Mock()
        with mock.patch.object(protocol.sys, "stdout", stdout):
            protocol.emit({"ok": True})
            protocol.handle_initialize(1, {"protocolVersion": "2024-11-05"})
            protocol.handle_tools_list(2)

        self.assertTrue(stdout.write.called)
        self.assertTrue(stdout.flush.called)

    def test_handle_tools_call_wrapper_error_paths(self) -> None:
        stdout = mock.Mock()
        with mock.patch.object(protocol.sys, "stdout", stdout):
            protocol.handle_tools_call(1, {"name": "missing", "arguments": {}})
            protocol.handle_tools_call(2, {"name": "podling_brief", "arguments": []})

        writes = [json.loads(call.args[0]) for call in stdout.write.call_args_list]
        self.assertEqual(writes[0]["error"]["code"], -32602)
        self.assertEqual(writes[1]["error"]["code"], -32602)

    def test_tool_response_includes_structured_content_for_json_payloads(self) -> None:
        response = protocol.tool_response({"ok": True})

        self.assertEqual(response["structuredContent"], {"ok": True})
        self.assertEqual(json.loads(response["content"][0]["text"]), {"ok": True})

    def test_parse_args_accepts_startup_sources(self) -> None:
        args = protocol.parse_args(
            [
                "--podlings-source",
                "/tmp/podlings.xml",
                "--health-source",
                "/tmp/reports",
                "--report-source",
                "/tmp/report-cache",
            ]
        )

        self.assertEqual(args.podlings_source, "/tmp/podlings.xml")
        self.assertEqual(args.health_source, "/tmp/reports")
        self.assertEqual(args.report_source, "/tmp/report-cache")

    def test_call_tool_success(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            result = protocol.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "podling_brief",
                        "arguments": {
                            "podling": "Alpha",
                            "podlings_source": podlings_source,
                            "health_source": health_source,
                            "as_of_date": "2026-04-18",
                        },
                    },
                }
            )

        self.assertIn("result", result)
        self.assertEqual(result["result"]["structuredContent"]["podling"], "Alpha")

    def test_handle_message_paths(self) -> None:
        self.assertEqual(
            protocol.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            {},
        )
        self.assertEqual(
            protocol.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})["result"][
                "tools"
            ][0]["name"],
            "recent_changes",
        )
        error = protocol.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": []})
        self.assertEqual(error["error"]["code"], -32602)
        unknown = protocol.handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "missing", "arguments": {}}}
        )
        self.assertEqual(unknown["error"]["code"], -32602)
        bad_method = protocol.handle_message({"jsonrpc": "2.0", "id": 5, "method": "unknown/method", "params": {}})
        self.assertEqual(bad_method["error"]["code"], -32601)

    def test_handle_message_rejects_malformed_requests(self) -> None:
        cases = [
            ([], -32600, "JSON-RPC request must be an object"),
            ({"id": 1, "method": "tools/list", "params": {}}, -32600, "jsonrpc must be '2.0'"),
            ({"jsonrpc": "2.0", "id": 1, "params": {}}, -32600, "method is required"),
            ({"jsonrpc": "2.0", "id": 1, "method": "", "params": {}}, -32600, "method must be a non-empty string"),
            ({"jsonrpc": "2.0", "id": True, "method": "tools/list", "params": {}}, -32600, "id must be"),
            ({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}, -32602, "params must be an object"),
        ]

        for payload, expected_code, expected_reason in cases:
            with self.subTest(payload=payload):
                response = protocol.handle_message(payload)
                self.assertEqual(response["error"]["code"], expected_code)
                self.assertIn(expected_reason, response["error"]["data"]["reason"])

    def test_tools_call_requires_name(self) -> None:
        response = protocol.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}}
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["data"]["field"], "name")

    def test_handle_payload_supports_batches(self) -> None:
        response = protocol.handle_payload(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "unknown/method", "params": {}},
                "not a request",
            ]
        )

        self.assertIsInstance(response, list)
        assert isinstance(response, list)
        self.assertEqual(len(response), 3)
        self.assertIn("tools", response[0]["result"])
        self.assertEqual(response[1]["id"], 2)
        self.assertEqual(response[1]["error"]["code"], -32601)
        self.assertEqual(response[2]["id"], None)
        self.assertEqual(response[2]["error"]["code"], -32600)

    def test_handle_payload_empty_batch_is_invalid(self) -> None:
        response = protocol.handle_payload([])

        assert isinstance(response, dict)
        self.assertEqual(response["error"]["code"], -32600)
        self.assertEqual(response["id"], None)

    def test_handle_payload_notification_only_batch_has_no_response(self) -> None:
        response = protocol.handle_payload([{"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}])

        self.assertEqual(response, [])

    def test_call_tool_invalid_arguments_returns_jsonrpc_error(self) -> None:
        response = protocol.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "podling_brief", "arguments": []},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)

    def test_handle_message_tool_handler_error_payload(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            response = protocol.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "podling_brief",
                        "arguments": {
                            "podling": "Missing",
                            "podlings_source": podlings_source,
                            "health_source": health_source,
                        },
                    },
                }
            )

        self.assertTrue(response["result"]["isError"])
        payload = response["result"]["structuredContent"]
        self.assertFalse(payload["ok"])

    def test_main_handles_parse_error_and_internal_error(self) -> None:
        stdin = mock.Mock()
        stdin.__iter__ = mock.Mock(
            return_value=iter(
                [
                    "\n",
                    '{"broken"\n',
                    '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n',
                    "[]\n",
                ]
            )
        )
        stdout = mock.Mock()
        writes: list[str] = []
        stdout.write.side_effect = writes.append

        with mock.patch.object(protocol.sys, "stdin", stdin):
            with mock.patch.object(protocol.sys, "stdout", stdout):
                exit_code = protocol.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(writes), 3)
        self.assertEqual(json.loads(writes[0])["error"]["code"], -32700)
        self.assertIn("tools", json.loads(writes[1])["result"])
        self.assertEqual(json.loads(writes[2])["error"]["code"], -32600)

    def test_main_configures_startup_sources(self) -> None:
        stdin = mock.Mock()
        stdin.__iter__ = mock.Mock(return_value=iter([]))

        with mock.patch.object(protocol.sys, "stdin", stdin):
            with mock.patch.object(protocol, "configure_defaults") as configure_defaults:
                exit_code = protocol.main(
                    [
                        "--podlings-source",
                        "/tmp/podlings.xml",
                        "--health-source",
                        "/tmp/reports",
                        "--report-source",
                        "/tmp/report-cache",
                    ]
                )

        self.assertEqual(exit_code, 0)
        configure_defaults.assert_called_once_with(
            podlings_source="/tmp/podlings.xml",
            health_source="/tmp/reports",
            report_source="/tmp/report-cache",
        )
