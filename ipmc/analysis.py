"""Opinionated scoring and summary helpers for IPMC oversight views."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .data import OversightRecord

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RELEASE_STALL_MIN_MONTHS = 6
RELEASE_STALL_WINDOW = "12m"
INCUBATION_DURATION_MIN_MONTHS = 36
LONG_RELEASE_GAP_MONTHS = 6
LONG_RELEASE_GAP_DAYS = LONG_RELEASE_GAP_MONTHS * 30
HIGH_ACTIVITY_COMMITS = 25
CONTRIBUTOR_BREADTH_MIN = 3
STALLED_COMMITS_MAX = 10
STALLED_COMMITTERS_MAX = 2
STALLED_DISCUSSION_MESSAGES_MAX = 10
SIGNIFICANT_ACTIVITY_SHIFT_RATIO = 2.0
SIGNIFICANT_ACTIVITY_FIELDS = {
    "commits": "commit activity",
    "unique_committers": "active committer breadth",
    "dev_unique_posters": "dev-list participation",
}
REPORT_ISSUE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
REPORT_BODY_WHITESPACE_RE = re.compile(r"\s+")
REPORT_COPY_FORWARD_MIN_CHARS = 300
REPORT_COPY_FORWARD_SIMILARITY = 0.75


def severity_value(value: str) -> int:
    return SEVERITY_ORDER[value]


def severity_at_least(value: str, minimum: str | None) -> bool:
    if minimum is None:
        return True
    return severity_value(value) >= severity_value(minimum)


def trend_from_metrics(metrics: dict[str, Any] | None, fields: list[str]) -> str:
    if not metrics:
        return "unknown"
    trends = metrics.get("trends") or {}
    values = [trends.get(field) for field in fields if trends.get(field) in {"up", "down", "flat", "mixed"}]
    if not values:
        return "unknown"
    if all(value == "up" for value in values):
        return "improving"
    if all(value == "down" for value in values):
        return "worsening"
    if "down" in values:
        return "worsening"
    return "stable"


@dataclass
class Signal:
    signal: str
    severity: str
    reason: str
    source: str
    recommended_action: str
    value: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "signal": self.signal,
            "severity": self.severity,
            "reason": self.reason,
            "source": self.source,
            "recommended_action": self.recommended_action,
        }
        if self.value is not None:
            data["value"] = self.value
        return data


def _metric(metrics: dict[str, Any] | None, key: str) -> Any:
    if not metrics:
        return None
    return metrics.get(key)


def _trend(metrics: dict[str, Any] | None, key: str) -> str | None:
    if not metrics:
        return None
    value = (metrics.get("trends") or {}).get(key)
    return value if value in {"up", "down", "mixed"} else None


def _window_metrics(record: OversightRecord, window: str) -> dict[str, Any] | None:
    return ((record.report_summary or {}).get("latest_metrics") or {}).get(window)


def release_stall_age_eligible(months_in_incubation: int | None) -> bool:
    return months_in_incubation is None or months_in_incubation >= RELEASE_STALL_MIN_MONTHS


def release_stall_releases(record: OversightRecord) -> Any:
    return _metric(_window_metrics(record, RELEASE_STALL_WINDOW), "releases")


def mature_podling_oversight(months_in_incubation: int | None) -> bool:
    return months_in_incubation is not None and months_in_incubation >= INCUBATION_DURATION_MIN_MONTHS


def evaluate_record(record: OversightRecord) -> dict[str, Any]:
    metrics = record.preferred_metrics
    reporting_metrics = record.reporting_metrics
    signals: list[Signal] = []

    mentor_count = record.mentor_count
    months = record.months_in_incubation
    commits = _metric(metrics, "commits")
    unique_committers = _metric(metrics, "unique_committers")
    releases = _metric(metrics, "releases")
    stall_window_releases = release_stall_releases(record)
    dev_posters = _metric(metrics, "dev_unique_posters")
    reports_count = _metric(reporting_metrics, "reports_count")
    signoffs = _metric(reporting_metrics, "avg_mentor_signoffs")
    unique_authors = _metric(metrics, "unique_authors")
    if mentor_count == 0:
        signals.append(
            Signal(
                signal="mentor_coverage",
                severity="critical",
                reason="No mentors are listed for this podling.",
                source="podlings",
                recommended_action="Confirm active mentor assignment and escalate for mentor coverage.",
                value=mentor_count,
            )
        )
    elif mentor_count == 1:
        signals.append(
            Signal(
                signal="mentor_coverage",
                severity="high",
                reason="Only one mentor is listed, which creates coverage risk.",
                source="podlings",
                recommended_action="Add or confirm additional mentor coverage.",
                value=mentor_count,
            )
        )

    if metrics is None:
        signals.append(
            Signal(
                signal="health_reporting",
                severity="high",
                reason="No apache-health report was found for this podling.",
                source="apache-health",
                recommended_action="Check whether reporting is missing or health inputs are incomplete.",
            )
        )
    else:
        if not reports_count:
            signals.append(
                Signal(
                    signal="reporting_reliability",
                    severity="high",
                    reason="No incubator reports were seen in the reporting health window.",
                    source="apache-health",
                    recommended_action="Confirm reporting timeliness and follow up on missed reports.",
                    value=reports_count,
                )
            )
        if signoffs is not None and signoffs < 2.0:
            mature_oversight = mature_podling_oversight(months)
            signals.append(
                Signal(
                    signal="mentor_engagement",
                    severity="low" if mature_oversight else "medium",
                    reason=(
                        "Average mentor sign-offs are lower than expected, but this long-running podling may be "
                        "operating more independently or with lower activity."
                        if mature_oversight
                        else "Average mentor sign-offs are lower than expected for steady oversight."
                    ),
                    source="apache-health",
                    recommended_action=(
                        "Confirm whether reduced mentor sign-off reflects intentional independence or a real "
                        "oversight gap."
                        if mature_oversight
                        else "Check whether mentors are consistently reviewing and signing reports."
                    ),
                    value=signoffs,
                )
            )
        if commits is not None and commits <= 10:
            signals.append(
                Signal(
                    signal="community_activity",
                    severity="high" if commits <= 5 else "medium",
                    reason="Commit activity is low in the preferred reporting window.",
                    source="apache-health",
                    recommended_action="Check whether development has stalled or moved elsewhere.",
                    value=commits,
                )
            )
        if unique_committers is not None and unique_committers <= 2:
            signals.append(
                Signal(
                    signal="community_resilience",
                    severity="high" if unique_committers <= 1 else "medium",
                    reason="Very few active committers are visible in the preferred window.",
                    source="apache-health",
                    recommended_action="Assess whether the podling has enough independent participation.",
                    value=unique_committers,
                )
            )
        if dev_posters is not None and dev_posters <= 3:
            signals.append(
                Signal(
                    signal="community_discussion",
                    severity="medium",
                    reason="Mailing list participation looks thin in the preferred window.",
                    source="apache-health",
                    recommended_action="Check whether community discussion is healthy and happening on-list.",
                    value=dev_posters,
                )
            )
        if stall_window_releases == 0 and release_stall_age_eligible(months):
            signals.append(
                Signal(
                    signal="release_maturity",
                    severity="medium",
                    reason=(
                        f"No releases were observed in the {RELEASE_STALL_WINDOW} health window, "
                        f"and the podling is at least {RELEASE_STALL_MIN_MONTHS} months into incubation."
                    ),
                    source="apache-health",
                    recommended_action="Check whether release work is stalled or missing from the annual window.",
                    value=stall_window_releases,
                )
            )

    if months is not None and months >= INCUBATION_DURATION_MIN_MONTHS:
        severity = "medium"
        if metrics is None or (releases == 0 and (unique_committers or 0) <= 2):
            severity = "high"
        signals.append(
            Signal(
                signal="incubation_duration",
                severity=severity,
                reason="The podling has been in incubation for an extended period.",
                source="podlings",
                recommended_action="Review whether the podling needs a concrete graduation or intervention plan.",
                value=months,
            )
        )

    if (
        metrics is not None
        and unique_authors is not None
        and unique_authors >= 5
        and unique_committers is not None
        and unique_committers >= 4
        and releases is not None
        and releases >= 1
    ):
        if mentor_count >= 2 and signoffs is not None and signoffs >= 2.0 and (months or 0) >= 12:
            signals.append(
                Signal(
                    signal="graduation_momentum",
                    severity="low",
                    reason="The podling shows signals consistent with graduation progress.",
                    source="derived",
                    recommended_action="Consider whether a graduation conversation is timely.",
                )
            )

    top_severity = max((severity_value(signal.severity) for signal in signals), default=0)
    max_severity = [name for name, value in SEVERITY_ORDER.items() if value == top_severity][0]
    trend = trend_from_metrics(metrics, ["commits", "new_contributors", "dev_unique_posters", "prs_merged"])

    return {
        "signals": signals,
        "severity": max_severity,
        "trend": trend,
    }


def recent_change_events(record: OversightRecord) -> list[dict[str, Any]]:
    """Return only explicit non-flat recent deltas from source health trends."""
    metrics = record.preferred_metrics
    reporting_metrics = record.reporting_metrics
    events: list[dict[str, Any]] = []

    for field, label in (
        ("commits", "commits"),
        ("unique_committers", "unique_committers"),
    ):
        trend = _trend(metrics, field)
        if not trend:
            continue
        direction = "spike" if trend == "up" else "drop" if trend == "down" else "changed"
        events.append(
            {
                "change": f"{label}_{direction}",
                "field": field,
                "direction": trend,
                "current_value": _metric(metrics, field),
                "window": record.preferred_window,
                "why_it_matters": f"{label.replace('_', ' ').capitalize()} {direction} in the recent health window.",
            }
        )

    trend = _trend(reporting_metrics, "avg_mentor_signoffs")
    if trend:
        direction = "increased" if trend == "up" else "decreased" if trend == "down" else "changed"
        events.append(
            {
                "change": f"mentor_signoffs_{direction}",
                "field": "avg_mentor_signoffs",
                "direction": trend,
                "current_value": _metric(reporting_metrics, "avg_mentor_signoffs"),
                "window": record.reporting_window,
                "why_it_matters": f"Mentor sign-offs {direction} in the reporting window.",
            }
        )

    trend = _trend(reporting_metrics, "reports_count")
    if trend:
        reports_count = _metric(reporting_metrics, "reports_count")
        if trend == "down" and reports_count == 0:
            change = "reports_newly_missing"
            why = "Reporting presence dropped to zero in the reporting window."
        else:
            direction = "increased" if trend == "up" else "decreased" if trend == "down" else "changed"
            change = f"reporting_presence_{direction}"
            why = f"Reporting presence {direction} in the reporting window."
        events.append(
            {
                "change": change,
                "field": "reports_count",
                "direction": trend,
                "current_value": reports_count,
                "window": record.reporting_window,
                "why_it_matters": why,
            }
        )

    trend = _trend(metrics, "releases")
    if trend:
        releases = _metric(metrics, "releases")
        if trend == "up" and (releases or 0) > 0:
            change = "releases_appeared"
            why = "Release visibility appeared or increased in the recent health window."
        elif trend == "down" and releases == 0:
            change = "releases_disappeared"
            why = "Release visibility dropped to zero in the recent health window."
        else:
            direction = "increased" if trend == "up" else "decreased" if trend == "down" else "changed"
            change = f"releases_{direction}"
            why = f"Release visibility {direction} in the recent health window."
        events.append(
            {
                "change": change,
                "field": "releases",
                "direction": trend,
                "current_value": releases,
                "window": record.preferred_window,
                "why_it_matters": why,
            }
        )

    return events


def _activity_shift_values(record: OversightRecord, field: str) -> dict[str, Any] | None:
    metrics_3m = _window_metrics(record, "3m")
    metrics_12m = _window_metrics(record, "12m")
    value_3m = _metric(metrics_3m, field)
    value_12m = _metric(metrics_12m, field)
    if not isinstance(value_3m, int | float) or not isinstance(value_12m, int | float) or value_12m <= 0:
        return None

    annualized_3m = value_3m * 4
    ratio = annualized_3m / value_12m
    return {
        "value_3m": value_3m,
        "value_12m": value_12m,
        "annualized_3m": annualized_3m,
        "ratio": round(ratio, 2),
        "threshold_ratio": SIGNIFICANT_ACTIVITY_SHIFT_RATIO,
    }


def _activity_shift_event(record: OversightRecord, field: str, label: str) -> dict[str, Any] | None:
    evidence = _activity_shift_values(record, field)
    if not evidence or evidence["ratio"] > 1 / SIGNIFICANT_ACTIVITY_SHIFT_RATIO:
        return None

    reason = f"Annualized 3-month {label} is at most half the 12-month value."

    return {
        "change": f"{field}_activity_shift_down",
        "signal": "meaningful_activity_shift",
        "field": field,
        "direction": "down",
        "current_value": evidence["value_3m"],
        "comparison_value": evidence["value_12m"],
        "window": "3m",
        "comparison_window": "12m",
        "evidence": evidence,
        "why_it_matters": reason,
    }


def _mixed_activity_shift_event(record: OversightRecord) -> dict[str, Any] | None:
    commits = _activity_shift_values(record, "commits")
    committers = _activity_shift_values(record, "unique_committers")
    if (
        not commits
        or not committers
        or commits["ratio"] > 1 / SIGNIFICANT_ACTIVITY_SHIFT_RATIO
        or committers["ratio"] < SIGNIFICANT_ACTIVITY_SHIFT_RATIO
    ):
        return None

    return {
        "change": "commits_down_committers_up",
        "signal": "meaningful_activity_shift",
        "field": "activity_mix",
        "direction": "mixed",
        "current_value": {
            "commits_3m": commits["value_3m"],
            "unique_committers_3m": committers["value_3m"],
        },
        "comparison_value": {
            "commits_12m": commits["value_12m"],
            "unique_committers_12m": committers["value_12m"],
        },
        "window": "3m",
        "comparison_window": "12m",
        "evidence": {
            "commits": commits,
            "unique_committers": committers,
        },
        "why_it_matters": "Commit activity dropped while active committer breadth increased across health windows.",
    }


def significant_change_events(record: OversightRecord) -> list[dict[str, Any]]:
    """Return narrow factual recent changes that usually merit IPMC scan attention."""
    events: list[dict[str, Any]] = []

    releases_12m = release_stall_releases(record)
    if releases_12m == 0 and release_stall_age_eligible(record.months_in_incubation):
        events.append(
            {
                "change": "crossed_12m_without_release",
                "signal": "crossed_12m_without_release",
                "field": "releases",
                "direction": "down",
                "current_value": releases_12m,
                "window": RELEASE_STALL_WINDOW,
                "evidence": {
                    "releases_12m": releases_12m,
                    "months_in_incubation": record.months_in_incubation,
                    "minimum_months_in_incubation": RELEASE_STALL_MIN_MONTHS,
                },
                "why_it_matters": f"No releases are visible in the {RELEASE_STALL_WINDOW} health window.",
            }
        )

    mixed_activity = _mixed_activity_shift_event(record)
    if mixed_activity:
        events.append(mixed_activity)

    for field, label in SIGNIFICANT_ACTIVITY_FIELDS.items():
        if mixed_activity and field in {"commits", "unique_committers"}:
            continue
        event = _activity_shift_event(record, field, label)
        if event:
            events.append(event)

    for change in recent_change_events(record):
        if change["change"] in {"reports_newly_missing", "releases_disappeared"}:
            significant_change = {
                **change,
                "signal": change["change"],
            }
            events.append(significant_change)

    return events


def reporting_gap_signals(record: OversightRecord) -> list[dict[str, Any]]:
    """Return compliance-only reporting gaps; activity metrics are intentionally ignored."""
    if record.report_summary is None:
        return [
            {
                "gap": "missing_health_report",
                "severity": "high",
                "current_value": None,
                "window": None,
                "reason": "No apache-health report is available to verify recent Incubator reporting.",
            }
        ]

    reporting_metrics = record.reporting_metrics
    reports_count = _metric(reporting_metrics, "reports_count")
    trend = _trend(reporting_metrics, "reports_count")
    reporting_window = record.reporting_window
    reporting_window_too_short = reporting_window == "3m"
    signals: list[dict[str, Any]] = []

    if reports_count is None:
        signals.append(
            {
                "gap": "reporting_metric_missing",
                "severity": "medium",
                "current_value": None,
                "window": record.reporting_window,
                "reason": "Incubator report count is absent from the reporting health window.",
            }
        )
    elif reports_count == 0 and not reporting_window_too_short:
        signals.append(
            {
                "gap": "missing_recent_reports",
                "severity": "high",
                "current_value": reports_count,
                "window": record.reporting_window,
                "reason": "No Incubator reports were seen in the reporting health window.",
            }
        )

    if trend == "down" and reports_count == 0 and not reporting_window_too_short:
        signals.append(
            {
                "gap": "newly_missing_reports",
                "severity": "critical",
                "current_value": reports_count,
                "window": record.reporting_window,
                "reason": "Report presence declined and is now zero.",
            }
        )
    elif trend in {"down", "mixed"} and not reporting_window_too_short:
        signals.append(
            {
                "gap": "inconsistent_reporting_pattern",
                "severity": "medium",
                "current_value": reports_count,
                "window": record.reporting_window,
                "reason": "Report presence is not steady in the reporting trend data.",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for signal in signals:
        key = (signal["gap"], signal["reason"])
        if key not in seen:
            deduped.append(signal)
            seen.add(key)
    return deduped


def expected_reporting_count(months_in_incubation: int | None, window_months: int) -> int | None:
    """Return expected Incubator reports in a rolling window from ASF podling cadence."""
    if months_in_incubation is None:
        return None
    if months_in_incubation <= 0:
        return 0

    window_start = max(0, months_in_incubation - window_months)
    due_months = [month for month in range(1, months_in_incubation + 1) if month <= 3 or (month > 3 and month % 3 == 0)]
    return sum(1 for month in due_months if window_start < month <= months_in_incubation)


def reporting_reliability_pattern(record: OversightRecord) -> dict[str, Any]:
    """Classify reporting reliability using only report-count evidence across available windows."""
    if record.report_summary is None:
        age_note = (
            f" The podling has been incubating for {record.months_in_incubation} month(s)."
            if record.months_in_incubation is not None
            else ""
        )
        return {
            "category": "reporting_data_unavailable",
            "observed": {},
            "reason": f"No apache-health report is available to evaluate reporting reliability over time.{age_note}",
            "evidence": ["No apache-health report was found for this podling."],
        }

    latest_metrics = record.report_summary.get("latest_metrics") or {}
    observed = {
        window: metrics.get("reports_count")
        for window in ("3m", "6m", "12m")
        if isinstance((metrics := latest_metrics.get(window)), dict) and metrics.get("reports_count") is not None
    }
    trend = _trend(record.reporting_metrics, "reports_count")
    evidence = [f"{window}: {count} report(s)" for window, count in observed.items()]
    if trend:
        evidence.append(f"report count trend: {trend}")

    if not observed:
        return {
            "category": "reporting_data_unavailable",
            "observed": observed,
            "reason": "No Incubator report-count metrics are available across reporting windows.",
            "evidence": evidence or ["No report-count metrics were found."],
        }

    months = record.months_in_incubation
    if months is not None and months < 3 and not any(count and count > 0 for count in observed.values()):
        category = "reporting_data_unavailable"
        reason = "The podling is too new for a reliable reporting pattern, and no reports are visible yet."
    else:
        window = "12m" if "12m" in observed else "6m" if "6m" in observed else None
        expected = expected_reporting_count(months, 12 if window == "12m" else 6 if window == "6m" else 0)
        if window is None or expected is None or expected == 0:
            category = "reporting_data_unavailable"
            reason = "No medium or annual reporting window is available for an age-aware pattern."
        else:
            actual = observed[window] or 0
            missing = max(expected - actual, 0)
            evidence.append(f"expected in {window}: {expected} report(s)")
            if missing == 0:
                category = "consistently_on_time"
                reason = (
                    f"The {window} reporting window is on track by report count for podling age; "
                    "exact due-date timeliness is not visible in this source."
                )
            elif actual == 0 and expected >= 2:
                category = "repeated_missing"
                reason = f"The {window} reporting window shows no reports, with {expected} expected."
            elif missing == 1:
                category = "occasional_late"
                reason = (
                    f"The {window} reporting window is short by one expected report; "
                    "this matches a normal catch-up-next-month situation rather than a systemic pattern."
                )
            else:
                category = "repeated_late"
                reason = f"The {window} reporting window is short by {missing} expected reports."

    return {
        "category": category,
        "observed": observed,
        "reason": reason,
        "evidence": evidence,
    }


def release_visibility_signals(record: OversightRecord) -> list[dict[str, Any]]:
    """Return release-governance visibility concerns without general health scoring."""
    metrics_12m = _window_metrics(record, RELEASE_STALL_WINDOW)
    metrics = metrics_12m or record.preferred_metrics
    releases = _metric(metrics_12m, "releases")
    gap_days = _metric(metrics_12m, "median_gap_days")
    preferred = record.preferred_metrics or {}
    signals: list[dict[str, Any]] = []

    if releases == 0:
        signals.append(
            {
                "signal": "no_releases_12m",
                "severity": "high",
                "current_value": releases,
                "window": RELEASE_STALL_WINDOW,
                "reason": "No releases are visible in the 12-month health window.",
            }
        )
    if gap_days is not None and gap_days >= LONG_RELEASE_GAP_DAYS:
        signals.append(
            {
                "signal": "long_release_gap",
                "severity": "medium",
                "current_value": gap_days,
                "window": RELEASE_STALL_WINDOW,
                "reason": f"Median release gap is at least {LONG_RELEASE_GAP_MONTHS} months.",
            }
        )

    if releases == 0:
        commits = preferred.get("commits") or 0
        unique_committers = preferred.get("unique_committers") or 0
        unique_authors = preferred.get("unique_authors") or 0
        if commits >= HIGH_ACTIVITY_COMMITS:
            signals.append(
                {
                    "signal": "high_activity_no_releases",
                    "severity": "high",
                    "current_value": {"commits": commits, "releases": releases},
                    "window": record.preferred_window,
                    "reason": "Commit activity is high but no releases are visible in the 12-month window.",
                }
            )
        if max(unique_committers, unique_authors) >= CONTRIBUTOR_BREADTH_MIN:
            signals.append(
                {
                    "signal": "contributors_no_releases",
                    "severity": "medium",
                    "current_value": {
                        "unique_committers": unique_committers,
                        "unique_authors": unique_authors,
                        "releases": releases,
                    },
                    "window": record.preferred_window,
                    "reason": "Contributor breadth is visible but releases are not.",
                }
            )

    if metrics is None and record.report_summary is None:
        signals.append(
            {
                "signal": "release_visibility_unknown",
                "severity": "medium",
                "current_value": None,
                "window": RELEASE_STALL_WINDOW,
                "reason": "No health report is available to verify release visibility.",
            }
        )
    return signals


def stalled_podling_signal(record: OversightRecord) -> dict[str, Any] | None:
    """Return a strict 'nothing is moving' signal, not a general risk score."""
    metrics = record.preferred_metrics
    if not metrics:
        return None

    releases_12m = release_stall_releases(record)
    commits = metrics.get("commits")
    unique_committers = metrics.get("unique_committers")
    dev_messages = metrics.get("dev_messages")
    dev_posters = metrics.get("dev_unique_posters")
    low_discussion = dev_messages is not None and dev_messages <= STALLED_DISCUSSION_MESSAGES_MAX
    if (
        commits is not None
        and commits <= STALLED_COMMITS_MAX
        and unique_committers is not None
        and unique_committers <= STALLED_COMMITTERS_MAX
        and releases_12m == 0
    ):
        discussion_signal = "low_discussion" if low_discussion else "discussion_without_delivery"
        return {
            "signal": "stalled",
            "severity": "high",
            "definition_matched": [
                "low_commits",
                "low_committers",
                discussion_signal,
                "no_releases",
            ],
            "observed": {
                "commits": commits,
                "unique_committers": unique_committers,
                "dev_messages": dev_messages,
                "dev_unique_posters": dev_posters,
                "releases_12m": releases_12m,
            },
            "reason": (
                "Low commits, low committer breadth, and no 12-month releases are present; "
                "discussion is not translating into delivery."
            ),
        }
    return None


def confidence_for_record(record: OversightRecord) -> str:
    metrics = record.preferred_metrics
    reporting_metrics = record.reporting_metrics or {}
    if metrics is None:
        return "low"
    if record.mentor_count == 0:
        return "medium"
    required = ["commits", "unique_committers", "reports_count", "avg_mentor_signoffs", "dev_unique_posters"]
    combined_metrics = {**metrics, **reporting_metrics}
    populated = sum(1 for field in required if combined_metrics.get(field) is not None)
    if populated >= 4:
        return "high"
    if populated >= 2:
        return "medium"
    return "low"


def readiness_assessment(record: OversightRecord, strict_mode: bool = False) -> dict[str, Any]:
    metrics = record.preferred_metrics
    reporting_metrics = record.reporting_metrics or {}
    strengths: list[str] = []
    blockers: list[str] = []
    missing_evidence: list[str] = []

    if metrics is None:
        return {
            "assessment": "insufficient_data",
            "summary": "No apache-health report is available, so readiness cannot be assessed confidently.",
            "strengths": strengths,
            "blockers": ["No health report is available."],
            "missing_evidence": ["Recent community and reporting metrics."],
            "dimension_scores": {
                "community_independence": "unknown",
                "release_maturity": "unknown",
                "governance_health": "unknown",
                "mentor_confidence": "unknown",
                "sustained_activity": "unknown",
            },
            "recommended_next_steps": [
                "Gather recent health and reporting data before assessing graduation readiness."
            ],
        }

    unique_committers = metrics.get("unique_committers") or 0
    unique_authors = metrics.get("unique_authors") or 0
    releases = metrics.get("releases") or 0
    signoffs = reporting_metrics.get("avg_mentor_signoffs") or 0.0
    reports_count = reporting_metrics.get("reports_count") or 0
    commits = metrics.get("commits") or 0
    months = record.months_in_incubation or 0

    community_independence = (
        "strong" if unique_committers >= 4 and unique_authors >= 5 else "mixed" if unique_committers >= 3 else "weak"
    )
    release_maturity = "strong" if releases >= 1 else "mixed" if commits >= 15 else "weak"
    governance_health = (
        "strong" if reports_count >= 1 and record.mentor_count >= 2 else "mixed" if reports_count >= 1 else "weak"
    )
    mentor_confidence = (
        "strong" if signoffs >= 2.0 and record.mentor_count >= 2 else "mixed" if signoffs >= 1.0 else "weak"
    )
    sustained_activity = "strong" if commits >= 25 and months >= 12 else "mixed" if commits >= 10 else "weak"

    dimensions = {
        "community_independence": community_independence,
        "release_maturity": release_maturity,
        "governance_health": governance_health,
        "mentor_confidence": mentor_confidence,
        "sustained_activity": sustained_activity,
    }

    for label, value in dimensions.items():
        if value == "strong":
            strengths.append(label.replace("_", " ").capitalize())
        elif value == "weak":
            blockers.append(label.replace("_", " ").capitalize())

    if reports_count < 1:
        missing_evidence.append("Consistent incubator reporting in the recent window.")
    if signoffs < 2.0:
        missing_evidence.append("Stronger mentor sign-off evidence.")
    if releases < 1:
        missing_evidence.append("A visible recent release cadence.")

    strong_count = sum(1 for value in dimensions.values() if value == "strong")
    weak_count = sum(1 for value in dimensions.values() if value == "weak")
    ready_threshold = 4 if strict_mode else 3

    if strong_count >= ready_threshold and weak_count == 0:
        assessment = "ready"
        summary = "The podling shows strong readiness signals across community, governance, and delivery."
    elif strong_count >= 2 and weak_count <= 1:
        assessment = "near_ready"
        summary = "The podling appears close to graduation readiness but still has a small number of gaps to close."
    elif weak_count >= 3:
        assessment = "at_risk"
        summary = (
            "The podling shows several weak readiness dimensions and needs attention before graduation is realistic."
        )
    else:
        assessment = "not_yet_ready"
        summary = "The podling is progressing, but the evidence is not yet strong enough for graduation readiness."

    next_steps = []
    if assessment in {"near_ready", "ready"}:
        next_steps.append("Review the podling with mentors to confirm whether a graduation plan is timely.")
    if releases < 1:
        next_steps.append("Encourage a visible, policy-compliant release cadence.")
    if signoffs < 2.0:
        next_steps.append("Increase mentor engagement and report sign-off consistency.")
    if reports_count < 1:
        next_steps.append("Ensure the podling is reporting reliably to the Incubator.")
    if not next_steps:
        next_steps.append("Maintain current momentum and collect mentor feedback on graduation timing.")

    return {
        "assessment": assessment,
        "summary": summary,
        "strengths": strengths,
        "blockers": blockers,
        "missing_evidence": missing_evidence,
        "dimension_scores": dimensions,
        "recommended_next_steps": next_steps,
    }


def community_pattern(record: OversightRecord) -> str:
    evaluation = evaluate_record(record)
    severity = evaluation["severity"]
    metrics = record.preferred_metrics
    if metrics is None:
        return "missing_health_data"
    commits = metrics.get("commits") or 0
    unique_committers = metrics.get("unique_committers") or 0
    if severity in {"high", "critical"}:
        return "attention_needed"
    if commits >= 25 and unique_committers >= 4:
        return "strong_activity"
    if commits <= 10 or unique_committers <= 2:
        return "weak_activity"
    return "steady_progress"


def _normalize_report_issue(issue: str) -> str:
    return REPORT_ISSUE_NORMALIZE_RE.sub(" ", issue.casefold()).strip()


def _normalize_report_body(text: str | None) -> str:
    if not text:
        return ""
    return REPORT_BODY_WHITESPACE_RE.sub(" ", text.casefold()).strip()


def _copy_forward_signal(record: OversightRecord) -> dict[str, Any] | None:
    if len(record.incubator_reports) < 2:
        return None

    previous_report = record.incubator_reports[-2]
    latest_report = record.incubator_reports[-1]
    previous_body = _normalize_report_body(str(previous_report.get("body") or ""))
    latest_body = _normalize_report_body(str(latest_report.get("body") or ""))
    if min(len(previous_body), len(latest_body)) < REPORT_COPY_FORWARD_MIN_CHARS:
        return None

    similarity = SequenceMatcher(a=previous_body, b=latest_body).ratio()
    if similarity < REPORT_COPY_FORWARD_SIMILARITY:
        return None

    return {
        "signal": "possible_report_copy_forward",
        "severity": "low",
        "report_period": latest_report.get("report_period"),
        "report_id": latest_report.get("report_id"),
        "current_value": {
            "previous_report_period": previous_report.get("report_period"),
            "similarity_ratio": round(similarity, 3),
        },
        "reason": (
            "The two most recent cached Incubator report narratives are substantially similar, "
            "so the latest report may merit a quick human check for copy-forward text."
        ),
    }


def report_narrative_signals(record: OversightRecord) -> list[dict[str, Any]]:
    """Return explicit signals derived from cached report narrative fields."""
    if not record.incubator_reports:
        return []

    latest_report = record.incubator_reports[-1]
    latest_period = latest_report.get("report_period")
    latest_report_id = latest_report.get("report_id")
    latest_issues = [str(issue).strip() for issue in latest_report.get("issues") or [] if str(issue).strip()]
    signals: list[dict[str, Any]] = []

    if latest_issues:
        signals.append(
            {
                "signal": "latest_reported_issues",
                "severity": "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": latest_issues,
                "reason": f"The most recent cached Incubator report lists {len(latest_issues)} issue(s).",
            }
        )

    recurring_issues: dict[str, dict[str, Any]] = {}
    for report in record.incubator_reports:
        seen_in_report: set[str] = set()
        for raw_issue in report.get("issues") or []:
            issue = str(raw_issue).strip()
            if not issue:
                continue
            normalized = _normalize_report_issue(issue)
            if not normalized or normalized in seen_in_report:
                continue
            seen_in_report.add(normalized)
            if normalized not in recurring_issues:
                recurring_issues[normalized] = {"issue": issue, "count": 0}
            recurring_issues[normalized]["count"] += 1

    repeated = [
        {"issue": item["issue"], "report_count": item["count"]}
        for item in recurring_issues.values()
        if int(item["count"]) >= 2
    ]
    if repeated:
        repeated.sort(key=lambda item: (-item["report_count"], item["issue"].casefold()))
        signals.append(
            {
                "signal": "recurring_reported_issue",
                "severity": "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": repeated,
                "reason": "Some reported issues recur across multiple cached Incubator reports.",
            }
        )

    copy_forward_signal = _copy_forward_signal(record)
    if copy_forward_signal is not None:
        signals.append(copy_forward_signal)

    observed_signoffs = latest_report.get("observed_mentor_signoff_count")
    if isinstance(observed_signoffs, int | float) and observed_signoffs < 2:
        signals.append(
            {
                "signal": "low_observed_mentor_signoff",
                "severity": "high" if observed_signoffs == 0 else "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": observed_signoffs,
                "reason": "The most recent cached Incubator report shows fewer than two observed mentor sign-offs.",
            }
        )

    last_release = str(latest_report.get("last_release") or "").strip()
    if last_release and any(signal["signal"] == "no_releases_12m" for signal in release_visibility_signals(record)):
        signals.append(
            {
                "signal": "report_release_visibility_mismatch",
                "severity": "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": {
                    "last_release": last_release,
                    "release_visibility_signals": [signal["signal"] for signal in release_visibility_signals(record)],
                },
                "reason": (
                    "The most recent cached Incubator report mentions a last release, "
                    "but health data shows no releases in the 12-month window."
                ),
            }
        )

    return signals


def cross_source_mismatches(record: OversightRecord) -> list[dict[str, Any]]:
    """Return concrete mismatches between report narrative and health-derived evidence."""
    if not record.incubator_reports:
        return []

    latest_report = record.incubator_reports[-1]
    latest_period = latest_report.get("report_period")
    latest_report_id = latest_report.get("report_id")
    latest_issues = [str(issue).strip() for issue in latest_report.get("issues") or [] if str(issue).strip()]
    release_signals = release_visibility_signals(record)
    evaluation = evaluate_record(record)
    mismatches: list[dict[str, Any]] = []

    last_release = str(latest_report.get("last_release") or "").strip()
    if last_release and any(signal["signal"] == "no_releases_12m" for signal in release_signals):
        mismatches.append(
            {
                "signal": "report_release_visibility_mismatch",
                "severity": "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": {
                    "last_release": last_release,
                    "release_visibility_signals": [signal["signal"] for signal in release_signals],
                },
                "reason": (
                    "The most recent cached Incubator report mentions a last release, "
                    "but health data shows no releases in the 12-month window."
                ),
            }
        )

    high_health_signals = [
        signal
        for signal in evaluation["signals"]
        if signal.source == "apache-health" and severity_at_least(signal.severity, "high")
    ]
    high_release_signals = [signal for signal in release_signals if severity_at_least(str(signal["severity"]), "high")]
    if not latest_issues and (high_health_signals or high_release_signals):
        health_signal_names = [signal.signal for signal in high_health_signals]
        release_signal_names = [str(signal["signal"]) for signal in high_release_signals]
        mismatch_severity = "high"
        if health_signal_names:
            mismatch_severity = _highest_health_signal_severity(high_health_signals)
        mismatches.append(
            {
                "signal": "quiet_report_high_risk_mismatch",
                "severity": mismatch_severity,
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": {
                    "latest_reported_issues": latest_issues,
                    "health_signals": health_signal_names,
                    "release_visibility_signals": release_signal_names,
                },
                "reason": (
                    "The most recent cached Incubator report lists no explicit issues, "
                    "but current health or release evidence still shows elevated concerns."
                ),
            }
        )

    observed_signoffs = latest_report.get("observed_mentor_signoff_count")
    reporting_signoff_average = _metric(record.reporting_metrics, "avg_mentor_signoffs")
    if (
        isinstance(observed_signoffs, int | float)
        and observed_signoffs < 2
        and isinstance(reporting_signoff_average, int | float)
        and reporting_signoff_average >= 2
    ):
        mismatches.append(
            {
                "signal": "latest_signoff_drop_vs_average",
                "severity": "medium",
                "report_period": latest_period,
                "report_id": latest_report_id,
                "current_value": {
                    "observed_mentor_signoff_count": observed_signoffs,
                    "avg_mentor_signoffs": reporting_signoff_average,
                },
                "reason": (
                    "The latest cached Incubator report shows low observed mentor sign-off, "
                    "but the rolling health average remains at or above the usual expectation."
                ),
            }
        )

    return mismatches


def _highest_health_signal_severity(signals: list[Signal]) -> str:
    return max(signals, key=lambda signal: severity_value(signal.severity)).severity
