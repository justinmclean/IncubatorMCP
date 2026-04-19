from __future__ import annotations

import unittest
from unittest import mock

from ipmc import data
from tests.fixtures import make_fixture_sources


class DataTests(unittest.TestCase):
    def test_parse_iso_date_and_months_since(self) -> None:
        self.assertIsNone(data.parse_iso_date(None))
        self.assertIsNone(data.parse_iso_date("bad-date"))
        parsed = data.parse_iso_date("2026-04-18")
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-04-18")
        self.assertIsNone(data.months_since(None))
        self.assertIsNone(data.months_since("2026-04-18", "bad-date"))
        self.assertIsNone(data.months_since("2026-04-18", "2026-01-01"))
        self.assertEqual(data.months_since("2024-01-15", "2026-04-18"), 27)

    def test_preferred_window_helper(self) -> None:
        self.assertEqual(data._preferred_window(None), (None, None))
        self.assertEqual(data._preferred_window({"latest_metrics": {}}), (None, None))
        self.assertEqual(
            data._preferred_window({"latest_metrics": {"6m": {"commits": 10}, "to-date": {"commits": 11}}}),
            ("6m", {"commits": 10}),
        )

    def test_reporting_window_prefers_longer_reporting_evidence(self) -> None:
        self.assertEqual(data._reporting_window(None), (None, None))
        self.assertEqual(
            data._reporting_window(
                {
                    "latest_metrics": {
                        "3m": {"reports_count": 0},
                        "6m": {"reports_count": 1},
                        "12m": {"reports_count": 4},
                    }
                }
            ),
            ("12m", {"reports_count": 4}),
        )

    def test_load_podlings_and_health_summaries(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            podlings, podlings_meta = data.load_podlings(podlings_source)
            summaries, health_meta = data.load_health_summaries(health_source)

        self.assertEqual(len(podlings), 4)
        self.assertEqual(podlings_meta["count"], 4)
        self.assertIn("alpha", summaries)
        self.assertEqual(health_meta["report_count"], 3)

    def test_config_overrides_sibling_repos_and_default_reports_dir(self) -> None:
        module = mock.Mock()
        module.reports_overview.return_value = {"reports_dir": "/tmp/reports", "report_count": 0}
        module.load_reports.return_value = []
        data.configure_defaults(podlings_repo="/tmp/podlings", health_repo="/tmp/health", health_source="/tmp/reports")
        try:
            with mock.patch.object(data, "_ensure_import_path") as ensure_import_path:
                with mock.patch.object(data.importlib, "import_module", return_value=module):
                    summaries, overview = data.load_health_summaries()
        finally:
            data._CONFIGURED_PODLINGS_REPO = None
            data._CONFIGURED_HEALTH_REPO = None
            data._CONFIGURED_HEALTH_SOURCE = None

        ensure_import_path.assert_called_once()
        self.assertEqual(str(ensure_import_path.call_args.args[0]), "/tmp/health/src")
        self.assertEqual(summaries, {})
        self.assertEqual(overview["reports_dir"], "/tmp/reports")

    def test_default_health_source_matches_health_mcp_default(self) -> None:
        self.assertEqual(data.DEFAULT_HEALTH_SOURCE, "reports")

    def test_build_records_filters_current_and_can_include_all(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            current_only = data.build_records(
                podlings_source=podlings_source,
                health_source=health_source,
                as_of_date="2026-04-18",
            )
            all_records = data.build_records(
                podlings_source=podlings_source,
                health_source=health_source,
                as_of_date="2026-04-18",
                include_non_current=True,
            )

        self.assertEqual(len(current_only["records"]), 4)
        self.assertEqual(len(all_records["records"]), 4)
        self.assertEqual(current_only["records"][0].name, "Alpha")
