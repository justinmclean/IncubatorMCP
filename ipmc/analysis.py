"""Opinionated scoring and summary helpers for IPMC oversight views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .data import OversightRecord

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RELEASE_STALL_MIN_MONTHS = 6
RELEASE_STALL_WINDOW = "12m"
INCUBATION_DURATION_MIN_MONTHS = 36


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


def release_stall_age_eligible(months_in_incubation: int | None) -> bool:
    return months_in_incubation is None or months_in_incubation >= RELEASE_STALL_MIN_MONTHS


def release_stall_releases(record: OversightRecord) -> Any:
    latest_metrics = (record.report_summary or {}).get("latest_metrics") or {}
    return _metric(latest_metrics.get(RELEASE_STALL_WINDOW), "releases")


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
