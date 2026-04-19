from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.fixtures import make_fixture_sources

ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = ROOT / "server.py"


class McpIntegrationTests(unittest.TestCase):
    def _run_session(self, messages: list[dict], args: list[str] | None = None) -> list[dict]:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), *(args or [])],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            responses = []
            assert proc.stdin is not None
            assert proc.stdout is not None
            assert proc.stderr is not None

            for message in messages:
                proc.stdin.write(json.dumps(message) + "\n")
                proc.stdin.flush()
                responses.append(json.loads(proc.stdout.readline()))

            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()
            return responses
        finally:
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()
            if proc.stderr and not proc.stderr.closed:
                proc.stderr.close()
            if proc.poll() is None:
                proc.kill()

    def test_initialize_and_tool_call(self) -> None:
        with make_fixture_sources() as sources:
            podlings_source, health_source = sources
            responses = self._run_session(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "ipmc_watchlist",
                            "arguments": {
                                "podlings_source": podlings_source,
                                "health_source": health_source,
                                "as_of_date": "2026-04-18",
                            },
                        },
                    },
                ],
                args=["--health-source", health_source],
            )

        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "ipmc-mcp")
        self.assertEqual(responses[1]["result"]["structuredContent"]["items"][0]["podling"], "Charlie")
