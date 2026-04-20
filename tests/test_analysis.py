from __future__ import annotations

import unittest

from ipmc.analysis import (
    Signal,
    community_pattern,
    confidence_for_record,
    evaluate_record,
    readiness_assessment,
    reporting_reliability_pattern,
    severity_at_least,
    severity_value,
    trend_from_metrics,
)
from ipmc.data import OversightRecord


def make_record(
    *,
    name: str = "Example",
    mentors: list[str] | None = None,
    metrics: dict | None = None,
    twelve_month_metrics: dict | None = None,
    startdate: str | None = "2024-01-01",
    as_of_date: str | None = "2026-04-18",
) -> OversightRecord:
    latest_metrics = {"3m": metrics}
    if twelve_month_metrics is not None:
        latest_metrics["12m"] = twelve_month_metrics
    return OversightRecord(
        podling={
            "name": name,
            "status": "current",
            "mentors": mentors if mentors is not None else ["Mentor One", "Mentor Two"],
            "startdate": startdate,
        },
        report_summary={"latest_metrics": latest_metrics} if metrics is not None else None,
        preferred_window="3m" if metrics is not None else None,
        preferred_metrics=metrics,
        reporting_window="12m" if metrics is not None else None,
        reporting_metrics=twelve_month_metrics or metrics,
        as_of_date=as_of_date,
    )


class AnalysisTests(unittest.TestCase):
    def test_severity_helpers(self) -> None:
        self.assertEqual(severity_value("high"), 2)
        self.assertTrue(severity_at_least("high", "medium"))
        self.assertFalse(severity_at_least("low", "medium"))
        self.assertTrue(severity_at_least("low", None))

    def test_trend_from_metrics_paths(self) -> None:
        self.assertEqual(trend_from_metrics(None, ["commits"]), "unknown")
        self.assertEqual(trend_from_metrics({"trends": {}}, ["commits"]), "unknown")
        self.assertEqual(trend_from_metrics({"trends": {"commits": "up"}}, ["commits"]), "improving")
        self.assertEqual(
            trend_from_metrics({"trends": {"commits": "down", "prs_merged": "flat"}}, ["commits", "prs_merged"]),
            "worsening",
        )
        self.assertEqual(
            trend_from_metrics({"trends": {"commits": "flat", "prs_merged": "mixed"}}, ["commits", "prs_merged"]),
            "stable",
        )

    def test_signal_to_dict_includes_optional_value(self) -> None:
        signal = Signal("community_activity", "medium", "Low commits", "apache-health", "Follow up", value=3)
        self.assertEqual(signal.to_dict()["value"], 3)

    def test_evaluate_record_with_no_health_data(self) -> None:
        record = make_record(mentors=[], metrics=None, startdate="2020-01-01")
        result = evaluate_record(record)
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["trend"], "unknown")

    def test_evaluate_record_single_mentor_and_low_activity(self) -> None:
        record = make_record(
            mentors=["Mentor One"],
            metrics={
                "commits": 5,
                "unique_committers": 1,
                "releases": 0,
                "dev_unique_posters": 2,
                "reports_count": 0,
                "avg_mentor_signoffs": 1.0,
                "unique_authors": 2,
                "trends": {"commits": "down"},
            },
        )
        result = evaluate_record(record)
        self.assertEqual(result["severity"], "high")
        self.assertEqual(result["trend"], "worsening")
        self.assertTrue(any(signal.signal == "mentor_coverage" for signal in result["signals"]))

    def test_evaluate_record_skips_release_stall_for_new_podlings(self) -> None:
        record = make_record(
            startdate="2026-01-01",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 0,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 4,
                "trends": {},
            },
        )

        result = evaluate_record(record)

        self.assertFalse(any(signal.signal == "release_maturity" for signal in result["signals"]))

    def test_evaluate_record_flags_release_stall_after_age_threshold(self) -> None:
        metrics = {
            "commits": 30,
            "unique_committers": 4,
            "releases": 0,
            "dev_unique_posters": 6,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
            "unique_authors": 4,
            "trends": {},
        }
        record = make_record(
            startdate="2025-01-01",
            metrics=metrics,
            twelve_month_metrics=metrics,
        )

        result = evaluate_record(record)

        self.assertTrue(any(signal.signal == "release_maturity" for signal in result["signals"]))

    def test_evaluate_record_uses_12m_release_window_for_stall(self) -> None:
        preferred_metrics = {
            "commits": 30,
            "unique_committers": 4,
            "releases": 0,
            "dev_unique_posters": 6,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
            "unique_authors": 4,
            "trends": {},
        }
        twelve_month_metrics = {**preferred_metrics, "releases": 1}
        record = make_record(
            startdate="2025-01-01",
            metrics=preferred_metrics,
            twelve_month_metrics=twelve_month_metrics,
        )

        result = evaluate_record(record)

        self.assertFalse(any(signal.signal == "release_maturity" for signal in result["signals"]))

    def test_evaluate_record_uses_reporting_window_for_missing_reports(self) -> None:
        record = OversightRecord(
            podling={
                "name": "Example",
                "status": "current",
                "mentors": ["Mentor One", "Mentor Two"],
                "startdate": "2025-01-01",
            },
            report_summary={
                "latest_metrics": {
                    "3m": {"commits": 50, "unique_committers": 5, "reports_count": 0},
                    "12m": {"reports_count": 4, "avg_mentor_signoffs": 2.0},
                }
            },
            preferred_window="3m",
            preferred_metrics={"commits": 50, "unique_committers": 5, "reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 4, "avg_mentor_signoffs": 2.0},
            as_of_date="2026-04-18",
        )

        result = evaluate_record(record)

        self.assertFalse(any(signal.signal == "reporting_reliability" for signal in result["signals"]))

    def test_evaluate_record_skips_incubation_duration_before_36_months(self) -> None:
        record = make_record(
            startdate="2023-05-18",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 4,
                "trends": {},
            },
        )

        result = evaluate_record(record)

        self.assertFalse(any(signal.signal == "incubation_duration" for signal in result["signals"]))

    def test_evaluate_record_flags_incubation_duration_at_36_months(self) -> None:
        record = make_record(
            startdate="2023-04-18",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.0,
                "unique_authors": 4,
                "trends": {},
            },
        )

        result = evaluate_record(record)

        self.assertTrue(any(signal.signal == "incubation_duration" for signal in result["signals"]))

    def test_evaluate_record_keeps_signoff_signal_medium_for_younger_podlings(self) -> None:
        record = make_record(
            startdate="2025-01-01",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 1.0,
                "unique_authors": 4,
                "trends": {},
            },
        )

        result = evaluate_record(record)
        signoff_signal = next(signal for signal in result["signals"] if signal.signal == "mentor_engagement")

        self.assertEqual(signoff_signal.severity, "medium")

    def test_evaluate_record_softens_signoff_signal_for_mature_podlings(self) -> None:
        record = make_record(
            startdate="2023-04-18",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 1.0,
                "unique_authors": 4,
                "trends": {},
            },
        )

        result = evaluate_record(record)
        signoff_signal = next(signal for signal in result["signals"] if signal.signal == "mentor_engagement")

        self.assertEqual(signoff_signal.severity, "low")
        self.assertIn("operating more independently", signoff_signal.reason)

    def test_evaluate_record_with_graduation_momentum(self) -> None:
        record = make_record(
            metrics={
                "commits": 30,
                "unique_committers": 5,
                "releases": 1,
                "dev_unique_posters": 6,
                "reports_count": 1,
                "avg_mentor_signoffs": 2.5,
                "unique_authors": 6,
                "trends": {"commits": "up", "new_contributors": "up", "prs_merged": "up", "dev_unique_posters": "up"},
            },
        )
        result = evaluate_record(record)
        self.assertEqual(result["severity"], "low")
        self.assertTrue(any(signal.signal == "graduation_momentum" for signal in result["signals"]))

    def test_confidence_for_record_paths(self) -> None:
        self.assertEqual(confidence_for_record(make_record(metrics=None)), "low")
        self.assertEqual(confidence_for_record(make_record(mentors=[], metrics={"commits": 1})), "medium")
        self.assertEqual(
            confidence_for_record(
                make_record(
                    metrics={
                        "commits": 30,
                        "unique_committers": 5,
                        "reports_count": 1,
                        "avg_mentor_signoffs": 2.0,
                        "dev_unique_posters": 7,
                    }
                )
            ),
            "high",
        )
        self.assertEqual(
            confidence_for_record(make_record(metrics={"commits": 1, "unique_committers": 1})),
            "medium",
        )

    def test_readiness_assessment_paths(self) -> None:
        insufficient = readiness_assessment(make_record(metrics=None))
        self.assertEqual(insufficient["assessment"], "insufficient_data")

        near_ready = readiness_assessment(
            make_record(
                metrics={
                    "commits": 20,
                    "unique_committers": 4,
                    "unique_authors": 5,
                    "releases": 1,
                    "reports_count": 1,
                    "avg_mentor_signoffs": 2.0,
                }
            )
        )
        self.assertIn(near_ready["assessment"], {"near_ready", "ready"})

        at_risk = readiness_assessment(
            make_record(
                mentors=["Mentor One"],
                metrics={
                    "commits": 2,
                    "unique_committers": 1,
                    "unique_authors": 1,
                    "releases": 0,
                    "reports_count": 0,
                    "avg_mentor_signoffs": 0.0,
                },
            ),
            strict_mode=True,
        )
        self.assertEqual(at_risk["assessment"], "at_risk")

        not_yet_ready = readiness_assessment(
            make_record(
                metrics={
                    "commits": 12,
                    "unique_committers": 3,
                    "unique_authors": 3,
                    "releases": 0,
                    "reports_count": 1,
                    "avg_mentor_signoffs": 1.0,
                }
            )
        )
        self.assertEqual(not_yet_ready["assessment"], "not_yet_ready")

    def test_community_pattern_paths(self) -> None:
        self.assertEqual(community_pattern(make_record(metrics=None)), "missing_health_data")
        self.assertEqual(
            community_pattern(
                make_record(
                    metrics={
                        "commits": 2,
                        "unique_committers": 1,
                        "releases": 0,
                        "dev_unique_posters": 1,
                        "reports_count": 0,
                        "avg_mentor_signoffs": 0.0,
                        "unique_authors": 1,
                    }
                )
            ),
            "attention_needed",
        )
        self.assertEqual(
            community_pattern(
                make_record(
                    metrics={
                        "commits": 30,
                        "unique_committers": 5,
                        "releases": 1,
                        "dev_unique_posters": 6,
                        "reports_count": 1,
                        "avg_mentor_signoffs": 2.0,
                        "unique_authors": 6,
                    }
                )
            ),
            "strong_activity",
        )
        self.assertEqual(
            community_pattern(
                make_record(
                    metrics={
                        "commits": 8,
                        "unique_committers": 2,
                        "releases": 1,
                        "dev_unique_posters": 4,
                        "reports_count": 1,
                        "avg_mentor_signoffs": 2.0,
                        "unique_authors": 2,
                    }
                )
            ),
            "weak_activity",
        )
        self.assertEqual(
            community_pattern(
                make_record(
                    metrics={
                        "commits": 15,
                        "unique_committers": 3,
                        "releases": 1,
                        "dev_unique_posters": 5,
                        "reports_count": 1,
                        "avg_mentor_signoffs": 2.0,
                        "unique_authors": 3,
                    }
                )
            ),
            "steady_progress",
        )

    def test_reporting_reliability_pattern_categories(self) -> None:
        consistently_on_time = OversightRecord(
            podling={"name": "Steady", "status": "current", "mentors": ["A"], "startdate": "2024-01-01"},
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
        occasional_late = OversightRecord(
            podling={"name": "Occasional", "status": "current", "mentors": ["A"], "startdate": "2024-01-01"},
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
            podling={"name": "RepeatedLate", "status": "current", "mentors": ["A"], "startdate": "2024-01-01"},
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
        repeated_missing = OversightRecord(
            podling={"name": "Missing", "status": "current", "mentors": ["A"], "startdate": "2024-01-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}, "12m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 0},
            as_of_date="2026-04-18",
        )
        young_no_reports = OversightRecord(
            podling={"name": "New", "status": "current", "mentors": ["A"], "startdate": "2026-02-01"},
            report_summary={"latest_metrics": {"3m": {"reports_count": 0}, "12m": {"reports_count": 0}}},
            preferred_window="3m",
            preferred_metrics={"reports_count": 0},
            reporting_window="12m",
            reporting_metrics={"reports_count": 0},
            as_of_date="2026-04-18",
        )
        no_health_report = OversightRecord(
            podling={"name": "NoHealth", "status": "current", "mentors": ["A"], "startdate": "2016-01-01"},
            report_summary=None,
            preferred_window=None,
            preferred_metrics=None,
            reporting_window=None,
            reporting_metrics=None,
            as_of_date="2026-04-18",
        )

        self.assertEqual(reporting_reliability_pattern(consistently_on_time)["category"], "consistently_on_time")
        self.assertEqual(reporting_reliability_pattern(occasional_late)["category"], "occasional_late")
        self.assertEqual(reporting_reliability_pattern(repeated_late)["category"], "repeated_late")
        self.assertEqual(reporting_reliability_pattern(repeated_missing)["category"], "repeated_missing")
        self.assertEqual(reporting_reliability_pattern(young_no_reports)["category"], "reporting_data_unavailable")
        self.assertEqual(reporting_reliability_pattern(no_health_report)["category"], "reporting_data_unavailable")
