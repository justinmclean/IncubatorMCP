from __future__ import annotations

import unittest
from unittest import mock

from ipmc import tools
from ipmc.data import OversightRecord
from tests.fixtures import make_fixture_sources


def assert_explainability(testcase: unittest.TestCase, payload: dict) -> None:
    testcase.assertIn("source_data_used", payload)
    testcase.assertIn("reasoning", payload)
    testcase.assertIn("confidence", payload)
    testcase.assertIn("missing", payload)
    testcase.assertTrue(payload["source_data_used"])
    testcase.assertTrue(payload["reasoning"])
    testcase.assertTrue(payload["confidence"])
    testcase.assertTrue(payload["missing"])


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
        assert_explainability(self, payload["items"][0]["explainability"])
        assert_explainability(self, payload["items"][0]["supporting_signals"][0]["explainability"])

    def test_ipmc_watchlist_applies_limit_severity_and_reason_filters(self) -> None:
        with make_fixture_sources() as (podlings_source, health_source):
            payload = tools.tool_ipmc_watchlist(
                {
                    "podlings_source": podlings_source,
                    "health_source": health_source,
                    "severity_at_least": "high",
                    "include_reasons": ["missing_reports"],
                    "limit": 1,
                    "as_of_date": "2026-04-18",
                }
            )

        self.assertEqual(len(payload["items"]), 1)
        self.assertIn("missing_reports", payload["items"][0]["watch_reasons"])

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
        assert_explainability(self, payload["explainability"])
        assert_explainability(self, payload["evidence"][0]["explainability"])

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
        assert_explainability(self, payload["explainability"])

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
        assert_explainability(self, payload["items"][0]["explainability"])

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
        assert_explainability(self, payload["explainability"])
        assert_explainability(self, payload["risk_themes"][0]["explainability"])

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

    def test_recent_changes_returns_only_delta_events(self) -> None:
        record = OversightRecord(
            podling={"name": "Motion", "status": "current", "mentors": ["A", "B"], "startdate": "2025-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 42,
                "unique_committers": 4,
                "releases": 1,
                "trends": {
                    "commits": "up",
                    "unique_committers": "flat",
                    "releases": "down",
                },
            },
            reporting_window="12m",
            reporting_metrics={
                "reports_count": 0,
                "avg_mentor_signoffs": 1.0,
                "trends": {"reports_count": "down", "avg_mentor_signoffs": "flat"},
            },
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_recent_changes({})

        changes = payload["items"][0]["changes"]
        self.assertEqual(
            [change["change"] for change in changes],
            ["commits_spike", "reports_newly_missing", "releases_decreased"],
        )
        self.assertNotIn("unique_committers", [change["field"] for change in changes])
        assert_explainability(self, payload["items"][0]["explainability"])

    def test_significant_changes_returns_release_crossing_and_activity_shifts(self) -> None:
        record = OversightRecord(
            podling={"name": "Signal", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"commits": 3, "unique_committers": 5, "dev_unique_posters": 2, "releases": 0},
                    "12m": {"commits": 30, "unique_committers": 8, "dev_unique_posters": 20, "releases": 0},
                }
            },
            preferred_window="3m",
            preferred_metrics={"commits": 3, "unique_committers": 5, "dev_unique_posters": 2, "releases": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_significant_changes({})

        changes = payload["items"][0]["changes"]
        self.assertEqual(payload["generated_for"], "significant_changes")
        self.assertEqual(
            [change["change"] for change in changes],
            [
                "crossed_12m_without_release",
                "commits_down_committers_up",
                "dev_unique_posters_activity_shift_down",
            ],
        )
        self.assertEqual(changes[1]["evidence"]["commits"]["annualized_3m"], 12)
        self.assertEqual(changes[1]["evidence"]["commits"]["threshold_ratio"], 2.0)
        assert_explainability(self, payload["items"][0]["explainability"])

    def test_significant_changes_signal_filter(self) -> None:
        record = OversightRecord(
            podling={"name": "Filter", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {"commits": 3}, "12m": {"commits": 30, "releases": 0}}},
            preferred_window="3m",
            preferred_metrics={"commits": 3, "releases": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_significant_changes({"include_signals": ["meaningful_activity_shift"]})

        self.assertEqual([change["signal"] for change in payload["items"][0]["changes"]], ["meaningful_activity_shift"])

    def test_reporting_gaps_are_compliance_only(self) -> None:
        record = OversightRecord(
            podling={"name": "Reporter", "status": "current", "mentors": ["A", "B"], "startdate": "2025-01-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}, "12m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 0,
                "unique_committers": 0,
                "dev_unique_posters": 0,
                "releases": 0,
                "trends": {"commits": "down"},
            },
            reporting_window="12m",
            reporting_metrics={"reports_count": 0, "trends": {"reports_count": "down"}},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_reporting_gaps({})

        gaps = [gap["gap"] for gap in payload["items"][0]["gaps"]]
        self.assertIn("missing_recent_reports", gaps)
        self.assertIn("newly_missing_reports", gaps)
        self.assertNotIn("low_activity", gaps)
        assert_explainability(self, payload["items"][0]["explainability"])

    def test_reporting_gaps_allows_zero_reports_in_three_month_window(self) -> None:
        record = OversightRecord(
            podling={"name": "Quarterly", "status": "current", "mentors": ["A", "B"], "startdate": "2025-01-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={"commits": 12, "unique_committers": 3, "dev_unique_posters": 5, "releases": 1},
            reporting_window="3m",
            reporting_metrics={"reports_count": 0, "trends": {"reports_count": "down"}},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_reporting_gaps({})

        self.assertEqual(payload["items"], [])

    def test_reporting_gaps_does_not_treat_rolling_windows_as_inconsistent(self) -> None:
        record = OversightRecord(
            podling={"name": "Rolling", "status": "current", "mentors": ["A", "B"], "startdate": "2025-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"reports_count": 0},
                    "6m": {"reports_count": 1},
                    "12m": {"reports_count": 2},
                }
            },
            preferred_window="3m",
            preferred_metrics={"commits": 30, "unique_committers": 4, "dev_unique_posters": 8, "releases": 1},
            reporting_window="12m",
            reporting_metrics={"reports_count": 2, "trends": {"reports_count": "flat"}},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_reporting_gaps({})

        self.assertEqual(payload["items"], [])

    def test_reporting_reliability_groups_over_time_patterns(self) -> None:
        steady = OversightRecord(
            podling={"name": "Steady", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"reports_count": 1},
                    "6m": {"reports_count": 2},
                    "12m": {"reports_count": 4},
                }
            },
            preferred_window="3m",
            preferred_metrics={"reports_count": 1},
            reporting_window="12m",
            reporting_metrics={"reports_count": 4, "trends": {"reports_count": "flat"}},
            as_of_date="2026-04-18",
        )
        occasional = OversightRecord(
            podling={"name": "Occasional", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"reports_count": 0},
                    "6m": {"reports_count": 1},
                    "12m": {"reports_count": 3},
                }
            },
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 3},
            as_of_date="2026-04-18",
        )
        repeated_late = OversightRecord(
            podling={"name": "RepeatedLate", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"reports_count": 0},
                    "6m": {"reports_count": 0},
                    "12m": {"reports_count": 1},
                }
            },
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "trends": {"reports_count": "down"}},
            as_of_date="2026-04-18",
        )
        missing = OversightRecord(
            podling={"name": "Missing", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}, "12m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 0},
            as_of_date="2026-04-18",
        )
        young = OversightRecord(
            podling={"name": "Young", "status": "current", "mentors": ["A", "B"], "startdate": "2026-02-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}, "12m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 0},
            as_of_date="2026-04-18",
        )
        no_health = OversightRecord(
            podling={"name": "NoHealth", "status": "current", "mentors": ["A", "B"], "startdate": "2016-01-01"},
            report_summary=None,
            preferred_window=None,
            preferred_metrics=None,
            reporting_window=None,
            reporting_metrics=None,
            as_of_date="2026-04-18",
        )
        data = {
            "records": [steady, occasional, repeated_late, missing, young, no_health],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_reporting_reliability({})

        self.assertEqual(payload["generated_for"], "reporting_reliability")
        self.assertEqual(payload["buckets"]["consistently_on_time"][0]["podling"], "Steady")
        self.assertEqual(payload["buckets"]["occasional_late"][0]["podling"], "Occasional")
        self.assertEqual(payload["buckets"]["repeated_late"][0]["podling"], "RepeatedLate")
        self.assertEqual(payload["buckets"]["repeated_missing"][0]["podling"], "Missing")
        self.assertEqual(
            [item["podling"] for item in payload["buckets"]["reporting_data_unavailable"]],
            ["NoHealth", "Young"],
        )
        assert_explainability(self, payload["buckets"]["repeated_missing"][0]["explainability"])
        assert_explainability(self, payload["explainability"])

    def test_release_visibility_uses_governance_lens(self) -> None:
        record = OversightRecord(
            podling={"name": "Shipping", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={
                "latest_metrics": {
                    "3m": {"commits": 30, "unique_committers": 4, "unique_authors": 5, "releases": 0},
                    "12m": {"releases": 0, "median_gap_days": 220.0},
                }
            },
            preferred_window="3m",
            preferred_metrics={"commits": 30, "unique_committers": 4, "unique_authors": 5, "releases": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_release_visibility({})

        signals = [signal["signal"] for signal in payload["items"][0]["signals"]]
        self.assertIn("no_releases_12m", signals)
        self.assertIn("long_release_gap", signals)
        self.assertIn("high_activity_no_releases", signals)
        self.assertIn("contributors_no_releases", signals)
        assert_explainability(self, payload["items"][0]["explainability"])

    def test_release_vote_evidence_combines_mail_history_with_visibility(self) -> None:
        record = OversightRecord(
            podling={"name": "Shipping", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {"releases": 0}, "12m": {"releases": 0}}},
            preferred_window="3m",
            preferred_metrics={"commits": 30, "unique_committers": 4, "unique_authors": 5, "releases": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
            incubator_general_mail=[{"id": "cached-message"}],
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
            "report_source": {"source": "reports", "available": True},
            "mail_source": {"source": "mail", "available": True},
        }
        history = {
            "source": "apache-incubator-mail",
            "api_base": "https://example.test/api",
            "timespan": "lte=6M",
            "available": True,
            "vote_count": 1,
            "result_count": 1,
            "votes": [{"thread_id": "vote-thread"}],
            "results": [{"thread_id": "result-thread"}],
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            with mock.patch.object(tools, "load_podling_release_vote_history", return_value=history) as load_history:
                payload = tools.tool_release_vote_evidence(
                    {
                        "podling": "Shipping",
                        "mail_api_base": "https://example.test/api",
                        "mail_timespan": "lte=6M",
                        "limit": 5,
                    }
                )

        load_history.assert_called_once_with(
            "Shipping",
            mail_api_base="https://example.test/api",
            timespan="lte=6M",
            limit=5,
        )
        self.assertEqual(payload["generated_for"], "release_vote_evidence")
        self.assertEqual(payload["observed"]["vote_count"], 1)
        self.assertEqual(payload["observed"]["result_count"], 1)
        self.assertEqual(payload["observed"]["cached_general_mail_matches"], 1)
        self.assertTrue(payload["release_visibility_signals"])
        assert_explainability(self, payload["explainability"])

    def test_reporting_cohort_groups_current_reporting_podlings_without_ranking(self) -> None:
        reporting_issue = OversightRecord(
            podling={"name": "B-Report", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 1}}},
            preferred_window="3m",
            preferred_metrics={"commits": 12, "unique_committers": 3, "releases": 1},
            reporting_window="12m",
            reporting_metrics={"reports_count": 0, "trends": {"reports_count": "down"}},
            as_of_date="2026-04-18",
        )
        release_issue = OversightRecord(
            podling={"name": "A-Release", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 0}}},
            preferred_window="3m",
            preferred_metrics={"commits": 10, "unique_committers": 2, "unique_authors": 2, "releases": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        changed = OversightRecord(
            podling={"name": "C-Changed", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {"commits": 20}, "12m": {"commits": 20, "releases": 1}}},
            preferred_window="3m",
            preferred_metrics={"commits": 20, "unique_committers": 4, "releases": 1, "trends": {"commits": "up"}},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        quiet = OversightRecord(
            podling={"name": "D-Quiet", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 1}}},
            preferred_window="3m",
            preferred_metrics={"commits": 15, "unique_committers": 3, "releases": 1},
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        not_in_reporting_cohort = OversightRecord(
            podling={"name": "E-MissingHealth", "status": "current", "mentors": ["A"], "startdate": "2024-01-01"},
            report_summary=None,
            preferred_window=None,
            preferred_metrics=None,
            reporting_window=None,
            reporting_metrics=None,
            as_of_date="2026-04-18",
        )
        data = {
            "records": [quiet, changed, release_issue, reporting_issue, not_in_reporting_cohort],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_reporting_cohort({})

        self.assertEqual(payload["generated_for"], "reporting_cohort")
        self.assertEqual(payload["counts"]["reporting_issues"], 1)
        self.assertEqual(payload["counts"]["release_visibility_issues"], 1)
        self.assertEqual(payload["counts"]["recent_significant_changes"], 2)
        self.assertEqual(payload["counts"]["no_obvious_concerns"], 2)
        self.assertEqual(payload["buckets"]["reporting_issues"][0]["podling"], "B-Report")
        self.assertEqual(payload["buckets"]["release_visibility_issues"][0]["podling"], "A-Release")
        self.assertEqual(
            [item["podling"] for item in payload["buckets"]["recent_significant_changes"]],
            ["A-Release", "B-Report"],
        )
        self.assertEqual(
            [item["podling"] for item in payload["buckets"]["no_obvious_concerns"]],
            ["C-Changed", "D-Quiet"],
        )
        self.assertNotIn("E-MissingHealth", str(payload["buckets"]))
        assert_explainability(self, payload["explainability"])

    def test_stalled_podlings_require_all_stall_conditions(self) -> None:
        stalled = OversightRecord(
            podling={"name": "Stalled", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 0}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 5,
                "unique_committers": 1,
                "dev_messages": 2,
                "dev_unique_posters": 2,
                "releases": 0,
            },
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        moving = OversightRecord(
            podling={"name": "Moving", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 0}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 5,
                "unique_committers": 3,
                "dev_messages": 50,
                "dev_unique_posters": 5,
                "releases": 0,
            },
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [moving, stalled],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_stalled_podlings({})

        self.assertEqual([item["podling"] for item in payload["items"]], ["Stalled"])
        self.assertEqual(
            payload["items"][0]["definition_matched"],
            ["low_commits", "low_committers", "low_discussion", "no_releases"],
        )
        assert_explainability(self, payload["items"][0]["explainability"])

    def test_stalled_podlings_can_have_discussion_without_delivery(self) -> None:
        record = OversightRecord(
            podling={"name": "Talkative", "status": "current", "mentors": ["A", "B"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {}, "12m": {"releases": 0}}},
            preferred_window="3m",
            preferred_metrics={
                "commits": 0,
                "unique_committers": 0,
                "dev_messages": 92,
                "dev_unique_posters": 7,
                "releases": 0,
            },
            reporting_window="12m",
            reporting_metrics={"reports_count": 1, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )
        data = {
            "records": [record],
            "podlings_source": {"source": "podlings.xml"},
            "health_source": {"reports_dir": "reports"},
        }
        with mock.patch.object(tools, "build_records", return_value=data):
            payload = tools.tool_stalled_podlings({})

        self.assertEqual(payload["items"][0]["podling"], "Talkative")
        self.assertIn("discussion_without_delivery", payload["items"][0]["definition_matched"])

    def test_validation_rejects_invalid_choice(self) -> None:
        with self.assertRaises(ValueError):
            tools.tool_podling_brief({"podling": "Alpha", "brief_format": "verbose"})
