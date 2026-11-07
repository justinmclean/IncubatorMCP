from __future__ import annotations

import unittest

from ipmc.analysis import (
    Signal,
    community_pattern,
    confidence_for_record,
    cross_source_mismatches,
    evaluate_record,
    readiness_assessment,
    reconcile_trajectory_and_readiness,
    report_narrative_signals,
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
    incubator_reports: list[dict] | None = None,
    incubator_general_mail: list[dict] | None = None,
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
        incubator_reports=incubator_reports or [],
        incubator_general_mail=incubator_general_mail or [],
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

    def test_report_narrative_signals_detect_recurring_issues_and_release_mismatch(self) -> None:
        repeated_body = (
            "The podling continues community building, release preparation, and mentor follow-up. "
            "The podling continues community building, release preparation, and mentor follow-up. "
            "The podling continues community building, release preparation, and mentor follow-up. "
            "The podling continues community building, release preparation, and mentor follow-up. "
            "The podling continues community building, release preparation, and mentor follow-up."
        )
        record = make_record(
            startdate="2024-01-01",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "unique_authors": 5,
                "releases": 0,
                "trends": {},
            },
            twelve_month_metrics={
                "commits": 90,
                "unique_committers": 5,
                "unique_authors": 6,
                "releases": 0,
                "median_gap_days": 220.0,
                "trends": {},
            },
        )
        record.incubator_reports = [
            {
                "report_id": "2026-01",
                "report_period": "2026-01",
                "body": repeated_body,
                "issues": ["Need more community review", "Release pending"],
                "observed_mentor_signoff_count": 2,
                "last_release": "0.9.0",
            },
            {
                "report_id": "2026-04",
                "report_period": "2026-04",
                "body": repeated_body + " ",
                "issues": ["Need more community review", "Mentor follow-up needed"],
                "observed_mentor_signoff_count": 1,
                "last_release": "0.9.0",
            },
        ]

        signals = report_narrative_signals(record)
        signal_names = {signal["signal"] for signal in signals}

        self.assertEqual(
            signal_names,
            {
                "latest_reported_issues",
                "recurring_reported_issue",
                "possible_report_copy_forward",
                "low_observed_mentor_signoff",
                "report_release_visibility_mismatch",
            },
        )
        repeated = next(signal for signal in signals if signal["signal"] == "recurring_reported_issue")
        self.assertEqual(repeated["current_value"][0]["issue"], "Need more community review")
        copy_forward = next(signal for signal in signals if signal["signal"] == "possible_report_copy_forward")
        self.assertEqual(copy_forward["current_value"]["previous_report_period"], "2026-01")

    def test_report_narrative_signals_skip_copy_forward_for_short_bodies(self) -> None:
        record = make_record(
            metrics={
                "commits": 12,
                "unique_committers": 3,
                "unique_authors": 3,
                "releases": 0,
                "trends": {},
            }
        )
        record.incubator_reports = [
            {
                "report_id": "2026-01",
                "report_period": "2026-01",
                "body": "No change.",
                "issues": ["Need more community review"],
            },
            {
                "report_id": "2026-04",
                "report_period": "2026-04",
                "body": "No change.",
                "issues": ["Need more community review"],
            },
        ]

        signals = report_narrative_signals(record)

        self.assertNotIn("possible_report_copy_forward", {signal["signal"] for signal in signals})

    def test_cross_source_mismatches_detect_quiet_report_and_signoff_drop(self) -> None:
        record = make_record(
            startdate="2024-01-01",
            metrics={
                "commits": 30,
                "unique_committers": 4,
                "unique_authors": 5,
                "releases": 0,
                "trends": {},
            },
            twelve_month_metrics={
                "commits": 90,
                "unique_committers": 5,
                "unique_authors": 6,
                "releases": 0,
                "median_gap_days": 220.0,
                "trends": {},
            },
        )
        record.reporting_metrics = {"reports_count": 1, "avg_mentor_signoffs": 2.5}
        record.incubator_reports = [
            {
                "report_id": "2026-04",
                "report_period": "2026-04",
                "issues": [],
                "observed_mentor_signoff_count": 1,
                "last_release": "0.9.0",
            }
        ]

        mismatches = cross_source_mismatches(record)
        mismatch_names = {mismatch["signal"] for mismatch in mismatches}

        self.assertEqual(
            mismatch_names,
            {
                "report_release_visibility_mismatch",
                "quiet_report_high_risk_mismatch",
                "latest_signoff_drop_vs_average",
            },
        )

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
        full_metrics = {
            "commits": 30,
            "unique_committers": 5,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
            "dev_unique_posters": 7,
        }
        report = {"report_period": "2026-02", "body": "Report"}
        mail = {"subject": "[RESULT][VOTE] Release Example 1.0.0"}
        self.assertEqual(confidence_for_record(make_record(metrics=None)), "low")
        self.assertEqual(confidence_for_record(make_record(mentors=[], metrics={"commits": 1})), "medium")
        self.assertEqual(
            confidence_for_record(
                make_record(metrics=full_metrics, incubator_reports=[report], incubator_general_mail=[mail])
            ),
            "high",
        )
        self.assertEqual(
            confidence_for_record(make_record(metrics={"commits": 1, "unique_committers": 1})),
            "medium",
        )

    def test_confidence_is_capped_without_source_coverage(self) -> None:
        full_metrics = {
            "commits": 30,
            "unique_committers": 5,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
            "dev_unique_posters": 7,
        }
        report = {"report_period": "2026-02", "body": "Report"}
        mail = {"subject": "[RESULT][VOTE] Release Example 1.0.0"}
        # Full metrics alone used to read "high"; without either cached source it is "medium".
        self.assertEqual(confidence_for_record(make_record(metrics=full_metrics)), "medium")
        self.assertEqual(
            confidence_for_record(make_record(metrics=full_metrics, incubator_reports=[report])),
            "medium",
        )
        self.assertEqual(
            confidence_for_record(make_record(metrics=full_metrics, incubator_general_mail=[mail])),
            "medium",
        )
        # The cap never raises a lower level.
        self.assertEqual(
            confidence_for_record(
                make_record(
                    metrics={"commits": 1, "unique_committers": 1},
                    incubator_reports=[report],
                    incubator_general_mail=[mail],
                )
            ),
            "medium",
        )
        self.assertEqual(
            confidence_for_record(
                make_record(metrics={"commits": 1}, incubator_reports=[report], incubator_general_mail=[mail])
            ),
            "low",
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

    def _ready_metrics(self) -> dict:
        return {
            "commits": 60,
            "unique_committers": 6,
            "unique_authors": 8,
            "releases": 2,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
            "dev_unique_posters": 9,
        }

    def test_readiness_uses_ipmc_release_result_from_mail(self) -> None:
        metrics = self._ready_metrics() | {"releases": 0}
        mail = [{"subject": "[RESULT][VOTE] Release Apache Example 1.2.0", "date": "2026-02-01 10:00:00 UTC"}]
        result = readiness_assessment(
            make_record(metrics=metrics, twelve_month_metrics=metrics, incubator_general_mail=mail)
        )
        self.assertEqual(result["dimension_scores"]["release_maturity"], "strong")
        self.assertEqual(result["mail_signals"]["latest_ipmc_release_result"], "2026-02-01")
        self.assertIn("2026-02-01", result["summary"])

    def test_readiness_downgrades_release_maturity_without_result_or_after_cancel(self) -> None:
        metrics = self._ready_metrics()
        no_result = readiness_assessment(
            make_record(
                metrics=metrics,
                twelve_month_metrics=metrics,
                incubator_general_mail=[{"subject": "[DISCUSS] Example roadmap", "date": "2026-03-01 00:00:00 UTC"}],
            )
        )
        self.assertEqual(no_result["dimension_scores"]["release_maturity"], "mixed")
        self.assertIn(
            "No IPMC release vote result found on general@ in the last 12 months.", no_result["missing_evidence"]
        )

        cancelled = readiness_assessment(
            make_record(
                metrics=metrics,
                twelve_month_metrics=metrics,
                incubator_general_mail=[
                    {"subject": "[RESULT][VOTE] Release Apache Example 1.0.0", "date": "2025-11-01 00:00:00 UTC"},
                    {"subject": "[CANCEL][VOTE] Release Apache Example 1.1.0 RC2", "date": "2026-03-10 00:00:00 UTC"},
                    {
                        "subject": "Re: [CANCEL][VOTE] Release Apache Example 1.1.0 RC2",
                        "date": "2026-03-11 00:00:00 UTC",
                    },
                ],
            )
        )
        self.assertTrue(cancelled["mail_signals"]["cancelled_after_last_result"])
        self.assertEqual(cancelled["mail_signals"]["thread_count"], 2)
        self.assertEqual(cancelled["dimension_scores"]["release_maturity"], "mixed")
        self.assertTrue(any("cancelled" in blocker for blocker in cancelled["blockers"]))

    def test_readiness_treats_a_later_open_vote_round_as_in_progress(self) -> None:
        metrics = self._ready_metrics()
        mail = [
            {"subject": "[RESULT][VOTE] Release Apache Example 1.0.0", "date": "2025-11-01 00:00:00 UTC"},
            {"subject": "[VOTE]Release Apache Example 1.1.0(Round1)", "date": "2026-03-05 00:00:00 UTC"},
            {"subject": "[CANCEL][VOTE]Release Apache Example 1.1.0(Round1)", "date": "2026-03-10 00:00:00 UTC"},
            {"subject": "[VOTE]Release Apache Example 1.1.0(Round2)", "date": "2026-04-10 00:00:00 UTC"},
            {"subject": "Re: [VOTE]Release Apache Example 1.1.0(Round2)", "date": "2026-04-14 00:00:00 UTC"},
            {"subject": "[VOTE] Release Apache Example 0.9.0", "date": "2026-01-02 00:00:00 UTC"},
        ]
        result = readiness_assessment(
            make_record(metrics=metrics, twelve_month_metrics=metrics, incubator_general_mail=mail)
        )
        signals = result["mail_signals"]
        self.assertEqual(signals["open_release_votes"], ["[vote]release apache example 1.1.0(round2)"])
        self.assertFalse(signals["cancelled_after_last_result"])
        self.assertFalse(any("cancelled" in blocker for blocker in result["blockers"]))
        self.assertTrue(any("release vote is open" in item for item in result["missing_evidence"]))
        self.assertIn(
            "Follow the open release vote on general@ through to a [RESULT].", result["recommended_next_steps"]
        )

    def test_readiness_next_steps_match_a_weak_release_verdict(self) -> None:
        # Health counts a release, but general@ shows no result in 12 months and a later cancelled vote.
        metrics = self._ready_metrics() | {"releases": 1}
        mail = [{"subject": "[CANCEL][VOTE] Release Apache Example 2.0.0", "date": "2026-02-10 00:00:00 UTC"}]
        result = readiness_assessment(
            make_record(metrics=metrics, twelve_month_metrics=metrics, incubator_general_mail=mail)
        )
        self.assertEqual(result["dimension_scores"]["release_maturity"], "weak")
        self.assertEqual(result["assessment"], "not_yet_ready")
        self.assertNotIn("Other dimensions are strong", result["summary"])
        steps = result["recommended_next_steps"]
        self.assertIn("Encourage a visible, policy-compliant release cadence.", steps)
        self.assertTrue(any("cancelled release vote" in step for step in steps))
        self.assertFalse(any("momentum" in step for step in steps))
        self.assertIn("A visible recent release cadence.", result["missing_evidence"])

    def test_readiness_retirement_thread_caps_the_verdict(self) -> None:
        metrics = self._ready_metrics()
        mail = [
            {"subject": "[RESULT][VOTE] Release Apache Example 1.0.0", "date": "2026-01-10 00:00:00 UTC"},
            {"subject": "[DISCUSS] Retiring Apache Example?", "date": "2026-03-20 00:00:00 UTC"},
        ]
        result = readiness_assessment(
            make_record(metrics=metrics, twelve_month_metrics=metrics, incubator_general_mail=mail)
        )
        self.assertEqual(result["dimension_scores"]["governance_health"], "weak")
        self.assertEqual(result["assessment"], "not_yet_ready")
        self.assertEqual(result["mail_signals"]["retirement_threads_12m"], ["[discuss] retiring apache example?"])

    def test_stale_sources_are_flagged_and_hold_ready_at_near_ready(self) -> None:
        metrics = self._ready_metrics()
        mail = [{"subject": "[RESULT][VOTE] Release Apache Example 1.0.0", "date": "2026-03-01 00:00:00 UTC"}]
        fresh = make_record(metrics=metrics, twelve_month_metrics=metrics, incubator_general_mail=mail)
        fresh.report_summary["generated_on"] = "2026-04-10"  # type: ignore[index]
        fresh_result = readiness_assessment(fresh)
        self.assertEqual(fresh_result["source_freshness"]["health_report_age_days"], 8)
        self.assertEqual(fresh_result["source_freshness"]["general_mail_age_days"], 0)
        self.assertEqual(fresh_result["source_freshness"]["stale_sources"], [])
        self.assertEqual(fresh_result["assessment"], "ready")

        stale = make_record(
            metrics=metrics,
            twelve_month_metrics=metrics,
            incubator_reports=[{"report_period": "2026-02"}],
            incubator_general_mail=[mail[0] | {"cached_at": "2026-03-02T00:00:00Z"}],
        )
        stale.report_summary["generated_on"] = "2026-02-01"  # type: ignore[index]
        stale_result = readiness_assessment(stale)
        self.assertEqual(stale_result["source_freshness"]["stale_sources"], ["health_report", "general_mail"])
        self.assertEqual(stale_result["source_freshness"]["general_mail_age_days"], 47)
        self.assertEqual(stale_result["assessment"], "near_ready")
        self.assertEqual(sum("76 days old" in item for item in stale_result["missing_evidence"]), 1)
        self.assertEqual(confidence_for_record(stale), "medium")

    def test_readiness_assessment_requires_release_in_12m_window(self) -> None:
        active = {
            "commits": 300,
            "unique_committers": 40,
            "unique_authors": 40,
            "releases": 0,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.0,
        }
        no_release = readiness_assessment(make_record(metrics=active, twelve_month_metrics=active))
        self.assertEqual(no_release["dimension_scores"]["release_maturity"], "weak")
        self.assertEqual(no_release["assessment"], "not_yet_ready")
        self.assertIn("no IPMC-approved release", no_release["summary"])

        released_earlier_in_year = readiness_assessment(
            make_record(metrics=active, twelve_month_metrics={**active, "releases": 1})
        )
        self.assertEqual(released_earlier_in_year["dimension_scores"]["release_maturity"], "strong")
        self.assertEqual(released_earlier_in_year["assessment"], "ready")

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


class ReconcileTrajectoryAndReadinessTests(unittest.TestCase):
    def test_strong_levels_with_worsening_trend_is_explained(self) -> None:
        note = reconcile_trajectory_and_readiness("worsening", "ready")
        assert note is not None
        self.assertIn("strong but softening", note)

    def test_near_ready_with_worsening_trend_is_explained(self) -> None:
        self.assertIsNotNone(reconcile_trajectory_and_readiness("worsening", "near_ready"))

    def test_weak_levels_with_improving_trend_is_explained(self) -> None:
        note = reconcile_trajectory_and_readiness("improving", "at_risk")
        assert note is not None
        self.assertIn("improving from a low base", note)

    def test_agreeing_signals_return_no_note(self) -> None:
        self.assertIsNone(reconcile_trajectory_and_readiness("improving", "ready"))
        self.assertIsNone(reconcile_trajectory_and_readiness("worsening", "at_risk"))

    def test_unknown_trend_returns_no_note(self) -> None:
        self.assertIsNone(reconcile_trajectory_and_readiness("unknown", "ready"))
        self.assertIsNone(reconcile_trajectory_and_readiness("stable", "at_risk"))


STRONG_METRICS = {
    "commits": 40,
    "unique_committers": 6,
    "unique_authors": 8,
    "releases": 1,
    "reports_count": 3,
    "avg_mentor_signoffs": 2.5,
}


def strong_record(*, generated_on: str, last_release: str | None, as_of_date: str = "2026-11-07") -> OversightRecord:
    record = make_record(metrics=STRONG_METRICS, twelve_month_metrics=STRONG_METRICS, as_of_date=as_of_date)
    assert record.report_summary is not None
    record.report_summary["generated_on"] = generated_on
    if last_release is not None:
        record.incubator_reports = [{"report_period": "2026-08", "last_release": last_release}]
    return record


class ReadinessStatusAndReleaseAgeTests(unittest.TestCase):
    def test_graduated_podling_is_not_applicable(self) -> None:
        record = strong_record(generated_on="2026-11-01", last_release="2026-08-01")
        record.podling.update({"status": "graduated", "enddate": "2026-09-16"})

        result = readiness_assessment(record)

        self.assertEqual(result["assessment"], "not_applicable")
        self.assertIn("2026-09-16", result["summary"])

    def test_graduated_podling_is_scored_as_of_a_date_before_it_ended(self) -> None:
        record = strong_record(generated_on="2026-06-01", last_release="2026-03-02", as_of_date="2026-06-01")
        record.podling.update({"status": "graduated", "enddate": "2026-07-16"})

        self.assertEqual(readiness_assessment(record)["assessment"], "ready")

    def test_stale_health_window_does_not_credit_an_old_stated_release(self) -> None:
        # Health data from 2026-09-06 counts a 2025-09-11 release in its 12m
        # window, but by 2026-11-07 that release is more than a year old.
        record = strong_record(generated_on="2026-09-06", last_release="2025-09-11, released 0.8.1")

        result = readiness_assessment(record)

        self.assertEqual(result["dimension_scores"]["release_maturity"], "weak")
        self.assertNotEqual(result["assessment"], "ready")
        self.assertTrue(any("62 days old" in item for item in result["missing_evidence"]))

    def test_fresh_health_window_credits_a_release_newer_than_the_report(self) -> None:
        record = strong_record(generated_on="2026-11-01", last_release="2025-09-11")

        self.assertEqual(readiness_assessment(record)["dimension_scores"]["release_maturity"], "strong")

    def test_recent_stated_release_is_strong_even_with_stale_health_data(self) -> None:
        record = strong_record(generated_on="2026-09-06", last_release="2026-08-25")

        self.assertEqual(readiness_assessment(record)["dimension_scores"]["release_maturity"], "strong")


def election_record(answer: str) -> OversightRecord:
    record = strong_record(generated_on="2026-11-01", last_release="2026-08-25")
    record.incubator_reports = [
        {
            "report_id": "board-minutes-2026-08-19",
            "report_period": "2026-08",
            "last_release": "2026-08-25",
            "body": "### When were the last committers or PPMC members elected?\n\n"
            f"{answer}\n\n### Have your mentors been helpful and responsive?\n\nYes.\n",
        }
    ]
    return record


class CommunityElectionTests(unittest.TestCase):
    def test_no_election_since_start_lowers_community_independence(self) -> None:
        for answer in ("At founding", "N/A", "2024-01-01, when the podling was accepted"):
            with self.subTest(answer=answer):
                result = readiness_assessment(election_record(answer))
                self.assertEqual(result["dimension_scores"]["community_independence"], "mixed")

    def test_recent_election_keeps_community_independence(self) -> None:
        for answer in ("2026-07-24", "March 24, 2026 - three new committers", "Rose Duan, 19th Jan 2026"):
            with self.subTest(answer=answer):
                result = readiness_assessment(election_record(answer))
                self.assertEqual(result["dimension_scores"]["community_independence"], "strong")

    def test_old_election_lowers_community_independence(self) -> None:
        result = readiness_assessment(election_record("2025-02-01"))
        self.assertEqual(result["dimension_scores"]["community_independence"], "mixed")

    def test_undated_election_is_not_counted_as_none(self) -> None:
        answer = "None so far. The vote to add Foo as a committer and PPMC member has passed."
        result = readiness_assessment(election_record(answer))
        self.assertEqual(result["dimension_scores"]["community_independence"], "strong")


class MailSignalSubjectTests(unittest.TestCase):
    def signals(self, *subjects: str) -> dict:
        from ipmc.analysis import mail_signals

        record = make_record(
            metrics=STRONG_METRICS,
            as_of_date="2026-11-07",
            incubator_general_mail=[
                {"subject": subject, "date": f"2026-10-{index + 1:02d} 00:00:00 UTC"}
                for index, subject in enumerate(subjects)
            ],
        )
        return mail_signals(record)

    def test_acceptance_vote_result_is_not_a_release(self) -> None:
        signals = self.signals("[RESULT][VOTE] Accept Foo into the Apache Incubator")
        self.assertIsNone(signals["latest_ipmc_release_result"])

    def test_cancel_without_vote_in_subject_is_found(self) -> None:
        signals = self.signals(
            "[VOTE] Release Apache Foo (Incubating) 2.1.0-incubating RC2",
            "[CANCEL] Apache Foo (Incubating) 2.1.0-incubating RC2",
        )
        self.assertIsNotNone(signals["latest_cancelled_vote"])
        self.assertEqual(signals["open_release_votes"], [])

    def test_result_with_outcome_word_closes_its_vote(self) -> None:
        signals = self.signals(
            "[VOTE] Release Foo (Incubating) 0.7.4",
            "[RESULT] [VOTE] Release Apache Foo (Incubating) 0.7.4 PASSED",
        )
        self.assertEqual(signals["open_release_votes"], [])
        self.assertIsNotNone(signals["latest_ipmc_release_result"])

    def test_status_thread_is_reported(self) -> None:
        signals = self.signals("Discuss the status of Apache Foo")
        self.assertEqual(signals["status_threads_12m"], ["discuss the status of apache foo"])
