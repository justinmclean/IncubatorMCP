from __future__ import annotations

import unittest
from unittest import mock

from ipmc import tools
from ipmc.data import OversightRecord
from tests.fixtures import make_fixture_sources


class ToolTests(unittest.TestCase):
    def test_validation_helpers_reject_bad_values(self) -> None:
        with self.assertRaises(ValueError):
            tools.require_string({"name": ""}, "name")
        with self.assertRaises(ValueError):
            tools.optional_string({"source": 123}, "source")
        with self.assertRaises(ValueError):
            tools.optional_boolean({"flag": "yes"}, "flag")
        with self.assertRaises(ValueError):
            tools.optional_integer({"limit": True}, "limit")
        with self.assertRaises(ValueError):
            tools.optional_list_of_choices({"focus": "risk"}, "focus", tools.FOCUS_AREAS)
        with self.assertRaises(ValueError):
            tools.optional_list_of_choices({"focus": [""]}, "focus", tools.FOCUS_AREAS)
        with self.assertRaises(ValueError):
            tools.optional_list_of_choices({"focus": ["missing"]}, "focus", tools.FOCUS_AREAS)

    def test_ipmc_watchlist_orders_highest_risk_first(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_ipmc_watchlist(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual(payload["items"][0]["podling"], "Charlie")
        self.assertEqual(payload["items"][0]["severity"], "critical")
        self.assertIn("low_mentor_engagement", payload["items"][0]["watch_reasons"])

    def test_ipmc_watchlist_applies_limit_severity_and_reason_filters(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_ipmc_watchlist(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "severity_at_least": "high",
                    "include_reasons": ["release_stall"],
                    "limit": 1,
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual(len(payload["items"]), 1)
        self.assertIn("release_stall", payload["items"][0]["watch_reasons"])

    def test_ipmc_watchlist_handles_no_signals_path(self) -> None:
        record = OversightRecord(
            podling={"name": "Calm", "status": "current", "mentors": ["A", "B"], "startdate": "2026-01-01"},
            report_summary={"latest_metrics": {"3m": {}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 20,
                "unique_committers": 3,
                "releases": 1,
                "dev_unique_posters": 4,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 3,
                "trends": {},
            },
            reporting_window="12m",
            reporting_metrics={
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
            },
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_ipmc_watchlist({})

        self.assertEqual(payload["items"][0]["summary"], "No significant concerns detected.")
        self.assertEqual(payload["items"][0]["recommended_ipmc_action"], "Continue normal oversight.")

    def test_ipmc_watchlist_does_not_mark_new_podling_release_stall(self) -> None:
        record = OversightRecord(
            podling={"name": "Caldera", "status": "current", "mentors": ["A", "B"], "startdate": "2026-01-01"},
            report_summary={"latest_metrics": {"3m": {}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 20,
                "unique_committers": 3,
                "releases": 0,
                "dev_unique_posters": 4,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 3,
                "trends": {},
            },
            reporting_window="12m",
            reporting_metrics={
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
            },
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_ipmc_watchlist({})

        self.assertNotIn("release_stall", payload["items"][0]["watch_reasons"])

    def test_graduation_readiness_marks_delta_ready_or_near_ready(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_graduation_readiness(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "podling": "Delta",
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertIn(payload["assessment"], {"ready", "near_ready"})
        self.assertTrue(payload["strengths"])

    def test_graduation_readiness_can_omit_evidence(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_graduation_readiness(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "podling": "Alpha",
                    "include_evidence": False,
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertNotIn("evidence", payload)

    def test_podling_brief_contains_expected_sections(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_podling_brief(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "podling": "Bravo",
                    "brief_format": "detailed",
                    "focus": ["risk", "mentoring"],
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertIn("Bravo is a current podling", payload["status_summary"])
        self.assertTrue(payload["active_concerns"])
        self.assertTrue(payload["mentor_attention_areas"] or payload["ipmc_attention_areas"])

    def test_podling_brief_without_metrics_or_months(self) -> None:
        record = OversightRecord(
            podling={"name": "Quiet", "status": "current", "mentors": ["A", "B"]},
            report_summary=None,
            preferred_window=None,
            preferred_metrics=None,
            reporting_window=None,
            reporting_metrics=None,
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_podling_brief({"podling": "Quiet"})

        self.assertEqual(payload["key_health_indicators"], [])
        self.assertNotIn("incubating for about", payload["status_summary"])

    def test_mentoring_attention_needed_filters_by_cause(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_mentoring_attention_needed(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "include_causes": ["missing_mentors"],
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual([item["podling"] for item in payload["items"]], ["Charlie"])

    def test_mentoring_attention_needed_applies_urgency_and_skips_non_matches(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_mentoring_attention_needed(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "urgency_at_least": "critical",
                    "include_causes": ["community_stall"],
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual(payload["items"], [])

    def test_mentoring_attention_needed_skips_mature_low_signoff_only(self) -> None:
        record = OversightRecord(
            podling={"name": "Independent", "status": "current", "mentors": ["A", "B"], "startdate": "2023-04-18"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 1}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 1.0,
                "unique_authors": 4,
                "trends": {},
            },
            reporting_window="12m",
            reporting_metrics={
                "reports_count": 1,
                "avg_mentor_signoffs": 1.0,
            },
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_mentoring_attention_needed({"include_causes": ["low_signoffs"]})

        self.assertEqual(payload["items"], [])

    def test_community_health_summary_reports_risk_themes(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_community_health_summary(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "scope": "reporting_podlings",
                    "group_by": "risk_band",
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual(payload["scope"], "reporting_podlings")
        self.assertTrue(payload["risk_themes"])

    def test_community_health_summary_grouping_and_no_examples_paths(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            mentor_load = tools.tool_community_health_summary(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "group_by": "mentor_load",
                    "include_examples": False,
                    "as_of_date": "2026-04-18",
                }
            )
            age_band = tools.tool_community_health_summary(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "group_by": "age_band",
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertIn("mentoring capacity", mentor_load["overall_summary"])
        self.assertIn("Older podlings", age_band["overall_summary"])
        self.assertTrue(all("example_podlings" not in theme for theme in mentor_load["risk_themes"]))

    def test_community_health_summary_handles_no_risk_or_strength_patterns(self) -> None:
        record = OversightRecord(
            podling={"name": "Steady", "status": "current", "mentors": ["A", "B"], "startdate": "2026-01-01"},
            report_summary={"latest_metrics": {"3m": {}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 15,
                "unique_committers": 3,
                "releases": 1,
                "dev_unique_posters": 4,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 3,
                "trends": {},
            },
            reporting_window="12m",
            reporting_metrics={
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
            },
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_community_health_summary({})

        self.assertEqual(payload["strong_patterns"], [])
        self.assertEqual(payload["risk_themes"], [])

    def test_validation_rejects_invalid_choice(self) -> None:
        with self.assertRaises(ValueError):
            tools.tool_podling_brief({"podling": "Alpha", "brief_format": "verbose"})
