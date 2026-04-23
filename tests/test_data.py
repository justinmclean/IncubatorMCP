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
        self.assertEqual(data._select_window({"latest_metrics": {}}, ("3m",)), (None, None))
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
        self.assertEqual(health_meta["source"], health_meta["reports_dir"])

    def test_load_health_summaries_reads_current_trend_sections(self) -> None:
        report = mock.Mock()
        report.podling = "Trendful"
        report.raw_text = """# Trendful
## Trends (short vs medium)

- **Releases (from list votes/results):** 1 (—)
- **Unique committers:** 8 (↗↗)
- **Commits:** 12 (↘)

## Window Details
### 3m
"""
        module = mock.Mock()
        module.reports_overview.return_value = {"reports_dir": "/tmp/reports", "report_count": 1}
        module.load_reports.return_value = [report]
        module.summarize_report.return_value = {
            "podling": "Trendful",
            "latest_metrics": {"3m": {"commits": 12, "unique_committers": 8, "releases": 1, "trends": {}}},
        }

        with mock.patch.object(data, "health_parser", module):
            summaries, _ = data.load_health_summaries("/tmp/reports")

        self.assertEqual(
            summaries["trendful"]["latest_metrics"]["3m"]["trends"],
            {"unique_committers": "up", "commits": "down"},
        )

    def test_config_overrides_default_reports_dir(self) -> None:
        module = mock.Mock()
        module.reports_overview.return_value = {"reports_dir": "/tmp/reports", "report_count": 0}
        module.load_reports.return_value = []
        data.configure_defaults(health_source="/tmp/reports")
        try:
            with mock.patch.object(data, "health_parser", module):
                summaries, overview = data.load_health_summaries()
        finally:
            data._CONFIGURED_HEALTH_SOURCE = None

        self.assertEqual(summaries, {})
        self.assertEqual(overview["reports_dir"], "/tmp/reports")
        self.assertEqual(overview["source"], "/tmp/reports")

    def test_environment_overrides_source_defaults(self) -> None:
        podlings_module = mock.Mock()
        podlings_module.DEFAULT_SOURCE = "https://example.invalid/default-podlings.xml"
        podlings_module.parse_podlings.return_value = ([], {"source": "/tmp/podlings.xml", "count": 0})
        health_module = mock.Mock()
        health_module.reports_overview.return_value = {"reports_dir": "/tmp/reports", "report_count": 0}
        health_module.load_reports.return_value = []

        with mock.patch.dict(
            data.os.environ,
            {
                data.PODLINGS_SOURCE_ENV: "/tmp/podlings.xml",
                data.HEALTH_SOURCE_ENV: "/tmp/reports",
            },
        ):
            with mock.patch.object(data, "podlings_data", podlings_module):
                podlings, podlings_meta = data.load_podlings()
            with mock.patch.object(data, "health_parser", health_module):
                summaries, health_meta = data.load_health_summaries()

        self.assertEqual(podlings, [])
        self.assertEqual(summaries, {})
        podlings_module.parse_podlings.assert_called_once_with("/tmp/podlings.xml")
        health_module.reports_overview.assert_called_once_with("/tmp/reports")
        health_module.load_reports.assert_called_once_with("/tmp/reports")
        self.assertEqual(podlings_meta["source"], "/tmp/podlings.xml")
        self.assertEqual(health_meta["source"], "/tmp/reports")

    def test_explicit_source_overrides_environment_defaults(self) -> None:
        module = mock.Mock()
        module.reports_overview.return_value = {"reports_dir": "/tmp/explicit", "report_count": 0}
        module.load_reports.return_value = []

        with mock.patch.dict(data.os.environ, {data.HEALTH_SOURCE_ENV: "/tmp/env"}):
            with mock.patch.object(data, "health_parser", module):
                summaries, overview = data.load_health_summaries("/tmp/explicit")

        self.assertEqual(summaries, {})
        module.reports_overview.assert_called_once_with("/tmp/explicit")
        self.assertEqual(overview["source"], "/tmp/explicit")

    def test_load_incubator_reports_uses_report_mcp_parser(self) -> None:
        signoff = mock.Mock()
        signoff.mentor = "Mentor One"
        signoff.checked = True
        item = mock.Mock()
        item.podling = "Alpha"
        item.to_dict.return_value = {
            "podling": "Alpha",
            "issues": ["Grow community."],
            "observed_mentor_signoff_count": 1,
        }
        report = mock.Mock()
        report.report_id = "report202604"
        report.report_period = "2026-04"
        report.title = "Incubator Report April 2026"
        report.path = "/tmp/reports/report202604.txt"
        report.source_url = None
        report.cached_at = None
        report.podling_reports = [item]
        module = mock.Mock()
        module.load_reports.return_value = [report]
        module.reports_overview.return_value = {
            "reports_dir": "/tmp/reports",
            "report_count": 1,
            "podling_count": 1,
        }

        with mock.patch.object(data.Path, "exists", return_value=True):
            with mock.patch.object(data, "incubator_report_parser", module):
                reports, meta = data.load_incubator_reports("/tmp/reports")

        self.assertEqual(meta["source"], "/tmp/reports")
        self.assertTrue(meta["available"])
        self.assertEqual(reports["alpha"][0]["report_id"], "report202604")
        self.assertEqual(reports["alpha"][0]["issues"], ["Grow community."])
        item.to_dict.assert_called_once_with(include_body=False)

    def test_environment_overrides_report_source_default(self) -> None:
        module = mock.Mock()
        module.load_reports.return_value = []
        module.reports_overview.return_value = {"reports_dir": "/tmp/report-cache", "report_count": 0}

        with mock.patch.dict(data.os.environ, {data.REPORT_SOURCE_ENV: "/tmp/report-cache"}):
            with mock.patch.object(data.Path, "exists", return_value=True):
                with mock.patch.object(data, "incubator_report_parser", module):
                    _, meta = data.load_incubator_reports()

        module.load_reports.assert_called_once_with("/tmp/report-cache")
        self.assertEqual(meta["source"], "/tmp/report-cache")

    def test_load_incubator_general_mail_uses_mail_mcp_cache(self) -> None:
        module = mock.Mock()
        module.load_cached_mail.return_value = {
            "cache_dir": "/tmp/mail-cache",
            "count": 2,
            "returned": 2,
            "emails": [
                {
                    "id": "alpha-message",
                    "subject": "[DISCUSS] Alpha graduation",
                    "from": "Mentor <mentor@apache.org>",
                    "date": "2026-04-20 00:00:00 UTC",
                },
                {
                    "id": "other-message",
                    "subject": "Incubator housekeeping",
                    "from": "Mentor <mentor@apache.org>",
                    "date": "2026-04-19 00:00:00 UTC",
                },
            ],
        }

        with mock.patch.object(data.Path, "exists", return_value=True):
            with mock.patch.object(data, "incubator_mail_client", module):
                mail, meta = data.load_incubator_general_mail(
                    "/tmp/mail-cache",
                    [{"name": "Alpha"}, {"name": "Bravo"}],
                )

        module.load_cached_mail.assert_called_once_with(cache_dir="/tmp/mail-cache")
        self.assertEqual(meta["source"], "/tmp/mail-cache")
        self.assertTrue(meta["available"])
        self.assertEqual(meta["message_count"], 2)
        self.assertEqual(meta["podling_count"], 1)
        self.assertEqual(mail["alpha"][0]["id"], "alpha-message")
        self.assertNotIn("bravo", mail)

    def test_environment_overrides_mail_source_default(self) -> None:
        module = mock.Mock()
        module.load_cached_mail.return_value = {"cache_dir": "/tmp/mail-cache", "count": 0, "emails": []}

        with mock.patch.dict(data.os.environ, {data.MAIL_SOURCE_ENV: "/tmp/mail-cache"}):
            with mock.patch.object(data.Path, "exists", return_value=True):
                with mock.patch.object(data, "incubator_mail_client", module):
                    _, meta = data.load_incubator_general_mail()

        module.load_cached_mail.assert_called_once_with(cache_dir="/tmp/mail-cache")
        self.assertEqual(meta["source"], "/tmp/mail-cache")

    def test_load_incubator_general_mail_falls_back_to_live_search_without_default_cache(self) -> None:
        module = mock.Mock()
        module.fetch_mail_stats.side_effect = [
            {
                "emails": [
                    {
                        "id": "alpha-message",
                        "subject": "[DISCUSS] Alpha graduation",
                        "from": "Mentor <mentor@apache.org>",
                        "date": "2026-04-20 00:00:00 UTC",
                    }
                ]
            },
            {"emails": []},
        ]

        with mock.patch.object(data.Path, "exists", return_value=False):
            with mock.patch.object(data, "incubator_mail_client", module):
                mail, meta = data.load_incubator_general_mail(
                    podlings=[{"name": "Alpha"}, {"name": "Bravo"}],
                    mail_api_base="https://example.test/api",
                )

        self.assertEqual(module.fetch_mail_stats.call_count, 2)
        module.fetch_mail_stats.assert_any_call(
            api_base="https://example.test/api",
            timespan=data.DEFAULT_MAIL_SEARCH_TIMESPAN,
            query="Alpha",
            limit=data.DEFAULT_MAIL_QUERY_LIMIT,
        )
        self.assertEqual(meta["mode"], "live")
        self.assertEqual(meta["source"], "https://example.test/api")
        self.assertTrue(meta["available"])
        self.assertEqual(meta["message_count"], 1)
        self.assertEqual(mail["alpha"][0]["id"], "alpha-message")
        self.assertNotIn("bravo", mail)

    def test_load_incubator_general_mail_reports_live_fallback_failure(self) -> None:
        module = mock.Mock()
        module.fetch_mail_stats.side_effect = RuntimeError("network unavailable")

        with mock.patch.object(data.Path, "exists", return_value=False):
            with mock.patch.object(data, "incubator_mail_client", module):
                mail, meta = data.load_incubator_general_mail(podlings=[{"name": "Alpha"}])

        self.assertEqual(mail, {})
        self.assertFalse(meta["available"])
        self.assertIn("live MailMCP search failed", meta["reason"])

    def test_load_podling_release_vote_history_uses_mail_mcp(self) -> None:
        module = mock.Mock()
        module.podling_release_vote_history.return_value = {
            "podling": "Alpha",
            "timespan": "lte=6M",
            "vote_count": 1,
            "result_count": 1,
            "votes": [{"thread_id": "vote-thread"}],
            "results": [{"thread_id": "result-thread"}],
        }

        with mock.patch.object(data, "incubator_mail_client", module):
            history = data.load_podling_release_vote_history(
                "Alpha",
                mail_api_base="https://example.test/api",
                timespan="lte=6M",
                limit=5,
            )

        module.podling_release_vote_history.assert_called_once_with(
            podling="Alpha",
            api_base="https://example.test/api",
            timespan="lte=6M",
            limit=5,
        )
        self.assertTrue(history["available"])
        self.assertEqual(history["api_base"], "https://example.test/api")
        self.assertEqual(history["vote_count"], 1)

    def test_load_podling_release_vote_history_handles_old_mail_mcp(self) -> None:
        module = mock.Mock(spec=[])

        with mock.patch.object(data, "incubator_mail_client", module):
            history = data.load_podling_release_vote_history("Alpha")

        self.assertFalse(history["available"])
        self.assertEqual(history["vote_count"], 0)
        self.assertIn("podling_release_vote_history", history["reason"])

    def test_load_podling_release_artifacts_uses_release_mcp(self) -> None:
        module = mock.Mock()
        module.release_overview.return_value = {
            "podling": "Alpha",
            "podling_slug": "alpha",
            "release_count": 1,
            "source_artifact_count": 1,
            "signature_count": 1,
            "checksum_count": 1,
            "releases": [{"version": "1.0.0"}],
            "cadence": {"last_release_date": "2026-04-01"},
        }

        with mock.patch.object(data, "incubator_releases", module):
            evidence = data.load_podling_release_artifacts(
                "Alpha",
                release_dist_base="/tmp/dist",
                release_archive_base="/tmp/archive",
                max_depth=0,
            )

        module.release_overview.assert_called_once_with(
            "Alpha",
            dist_base="/tmp/dist",
            archive_base="/tmp/archive",
            max_depth=0,
        )
        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["source"], "apache-incubator-releases")
        self.assertEqual(evidence["release_count"], 1)

    def test_load_podling_release_artifacts_defaults_to_one_level_scan(self) -> None:
        module = mock.Mock()
        module.release_overview.return_value = {
            "podling": "Alpha",
            "releases": [],
        }

        with mock.patch.object(data, "incubator_releases", module):
            data.load_podling_release_artifacts("Alpha")

        self.assertEqual(module.release_overview.call_args.kwargs["max_depth"], 1)

    def test_load_podling_release_artifacts_handles_missing_release_mcp(self) -> None:
        with mock.patch.object(data, "incubator_releases", None):
            evidence = data.load_podling_release_artifacts("Alpha")

        self.assertFalse(evidence["available"])
        self.assertEqual(evidence["release_count"], 0)
        self.assertIn("not importable in the IPMC server environment", evidence["reason"])
        self.assertIn("PYTHONPATH", evidence["reason"])

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
        self.assertIn("report_source", current_only)
        self.assertIn("mail_source", current_only)

    def test_build_records_skips_general_mail_by_default(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            with mock.patch.object(data, "load_incubator_general_mail") as load_mail:
                records = data.build_records(
                    podlings_source=podlings_source,
                    health_source=health_source,
                    as_of_date="2026-04-18",
                )

        load_mail.assert_not_called()
        self.assertFalse(records["mail_source"]["available"])
        self.assertEqual(records["mail_source"]["source"], "not_loaded")
