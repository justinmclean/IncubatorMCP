"""Tool handlers and registration for the IPMC oversight MCP server."""

from __future__ import annotations

from typing import Any

from . import schemas
from .analysis import (
    confidence_for_record,
    evaluate_record,
    readiness_assessment,
    severity_at_least,
)
from .data import build_records

SEVERITIES = {"low", "medium", "high", "critical"}
BRIEF_FORMATS = {"summary", "detailed"}
SCOPES = {"all_podlings", "active_podlings", "reporting_podlings"}
GROUPINGS = {"none", "risk_band", "mentor_load", "age_band"}
FOCUS_AREAS = {"status", "health", "reporting", "mentoring", "releases", "graduation", "risk"}
MENTORING_CAUSES = {
    "missing_mentors",
    "inactive_mentors",
    "missed_reports",
    "weak_releases",
    "governance_confusion",
    "community_stall",
    "mentor_overload",
    "low_signoffs",
}
WATCHLIST_REASONS = {
    "missing_reports",
    "late_reports",
    "low_mentor_engagement",
    "low_community_activity",
    "release_stall",
    "governance_concern",
    "community_fragility",
    "unknown_status",
}


def require_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return value.strip()


def optional_string(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string")
    stripped = value.strip()
    return stripped or None


def optional_boolean(arguments: dict[str, Any], key: str, default: bool | None = None) -> bool | None:
    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"'{key}' must be a boolean")
    return value


def optional_integer(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"'{key}' must be an integer")
    return value


def optional_choice(arguments: dict[str, Any], key: str, choices: set[str]) -> str | None:
    value = optional_string(arguments, key)
    if value is None:
        return None
    if value not in choices:
        raise ValueError(f"'{key}' must be one of: {', '.join(sorted(choices))}")
    return value


def optional_list_of_choices(arguments: dict[str, Any], key: str, choices: set[str]) -> list[str] | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"'{key}' must be a list")
    resolved: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"'{key}' entries must be non-empty strings")
        stripped = item.strip()
        if stripped not in choices:
            raise ValueError(f"'{key}' entries must be one of: {', '.join(sorted(choices))}")
        resolved.append(stripped)
    return resolved


def _resolve_sources(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "podlings_source": optional_string(arguments, "podlings_source"),
        "health_source": optional_string(arguments, "health_source"),
        "as_of_date": optional_string(arguments, "as_of_date"),
    }


def _record_by_name(records: list[Any], podling: str) -> Any:
    for record in records:
        if record.name.casefold() == podling.casefold():
            return record
    raise ValueError(f"Podling '{podling}' not found")


def _watch_reasons(record: Any, evaluation: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    metrics = record.preferred_metrics
    if metrics is None:
        reasons.append("unknown_status")
    if record.mentor_count <= 1:
        reasons.append("low_mentor_engagement")
    if metrics and not metrics.get("reports_count"):
        reasons.append("missing_reports")
    if metrics and (metrics.get("commits") or 0) <= 10:
        reasons.append("low_community_activity")
    if any(signal.signal == "release_maturity" for signal in evaluation["signals"]):
        reasons.append("release_stall")
    if metrics and (metrics.get("unique_committers") or 0) <= 2:
        reasons.append("community_fragility")
    if any(
        signal.signal == "incubation_duration" and signal.severity in {"medium", "high"}
        for signal in evaluation["signals"]
    ):
        reasons.append("governance_concern")
    return sorted(set(reasons))


def _supporting_signals(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    return [signal.to_dict() for signal in evaluation["signals"]]


def tool_ipmc_watchlist(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    limit = optional_integer(arguments, "limit") or 10
    severity_minimum = optional_choice(arguments, "severity_at_least", SEVERITIES)
    include_reasons = optional_list_of_choices(arguments, "include_reasons", WATCHLIST_REASONS)

    data = build_records(**sources)
    items = []
    for record in data["records"]:
        evaluation = evaluate_record(record)
        reasons = _watch_reasons(record, evaluation)
        if include_reasons and not any(reason in include_reasons for reason in reasons):
            continue
        if not severity_at_least(evaluation["severity"], severity_minimum):
            continue
        summary = evaluation["signals"][0].reason if evaluation["signals"] else "No significant concerns detected."
        action = evaluation["signals"][0].recommended_action if evaluation["signals"] else "Continue normal oversight."
        items.append(
            {
                "podling": record.name,
                "severity": evaluation["severity"],
                "trend": evaluation["trend"],
                "watch_reasons": reasons,
                "summary": summary,
                "recommended_ipmc_action": action,
                "supporting_signals": _supporting_signals(evaluation),
                "confidence": confidence_for_record(record),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["severity"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "generated_for": "ipmc_watchlist",
        "as_of_date": sources["as_of_date"],
        "items": items[:limit],
    }


def tool_graduation_readiness(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = require_string(arguments, "podling")
    include_evidence = optional_boolean(arguments, "include_evidence", True)
    strict_mode = optional_boolean(arguments, "strict_mode", False) or False

    data = build_records(**sources)
    record = _record_by_name(data["records"], podling)
    readiness = readiness_assessment(record, strict_mode=strict_mode)
    payload = {
        "podling": record.name,
        "assessment": readiness["assessment"],
        "confidence": confidence_for_record(record),
        "summary": readiness["summary"],
        "strengths": readiness["strengths"],
        "blockers": readiness["blockers"],
        "missing_evidence": readiness["missing_evidence"],
        "dimension_scores": readiness["dimension_scores"],
        "recommended_next_steps": readiness["recommended_next_steps"],
    }
    if include_evidence:
        evaluation = evaluate_record(record)
        payload["evidence"] = [
            {"statement": signal.reason, "source": signal.source} for signal in evaluation["signals"]
        ]
    return payload


def tool_podling_brief(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = require_string(arguments, "podling")
    focus = optional_list_of_choices(arguments, "focus", FOCUS_AREAS) or []
    brief_format = optional_choice(arguments, "brief_format", BRIEF_FORMATS) or "summary"

    data = build_records(**sources)
    record = _record_by_name(data["records"], podling)
    evaluation = evaluate_record(record)
    readiness = readiness_assessment(record)
    metrics = record.preferred_metrics or {}

    indicators = []
    if record.preferred_window:
        indicators.append(f"Preferred health window: {record.preferred_window}")
    if metrics.get("commits") is not None:
        indicators.append(f"Commits: {metrics['commits']}")
    if metrics.get("unique_committers") is not None:
        indicators.append(f"Unique committers: {metrics['unique_committers']}")
    if metrics.get("releases") is not None:
        indicators.append(f"Releases: {metrics['releases']}")
    if metrics.get("avg_mentor_signoffs") is not None:
        indicators.append(f"Avg mentor sign-offs: {metrics['avg_mentor_signoffs']}")

    concerns = [signal.reason for signal in evaluation["signals"] if signal.severity in {"medium", "high", "critical"}]
    mentor_attention = [
        signal.recommended_action
        for signal in evaluation["signals"]
        if signal.signal in {"mentor_coverage", "mentor_engagement"}
    ]
    ipmc_attention = [
        signal.recommended_action for signal in evaluation["signals"] if signal.signal not in {"graduation_momentum"}
    ]
    if readiness["assessment"] in {"near_ready", "ready"}:
        ipmc_attention.append("Check with mentors whether a graduation discussion should be scheduled.")

    status_summary = f"{record.name} is a {record.status} podling with {record.mentor_count} listed mentor(s)."
    if record.months_in_incubation is not None:
        status_summary += f" It has been incubating for about {record.months_in_incubation} month(s)."

    recent_trajectory = f"Trend is {evaluation['trend']} based on the preferred health window."
    if brief_format == "detailed" and focus:
        recent_trajectory += f" Focus areas requested: {', '.join(focus)}."

    return {
        "podling": record.name,
        "status_summary": status_summary,
        "recent_trajectory": recent_trajectory,
        "key_health_indicators": indicators,
        "active_concerns": concerns,
        "mentor_attention_areas": mentor_attention,
        "ipmc_attention_areas": ipmc_attention,
        "outlook": readiness["summary"],
        "sources_used": [
            str(data["podlings_source"].get("source")),
            str(data["health_source"].get("reports_dir")),
        ],
    }


def tool_mentoring_attention_needed(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    limit = optional_integer(arguments, "limit") or 10
    urgency_minimum = optional_choice(arguments, "urgency_at_least", SEVERITIES)
    include_causes = optional_list_of_choices(arguments, "include_causes", MENTORING_CAUSES)

    data = build_records(**sources)
    items = []
    for record in data["records"]:
        evaluation = evaluate_record(record)
        causes: list[str] = []
        for signal in evaluation["signals"]:
            if signal.signal == "mentor_coverage":
                causes.append("missing_mentors" if record.mentor_count == 0 else "inactive_mentors")
            if signal.signal == "reporting_reliability":
                causes.append("missed_reports")
            if signal.signal == "release_maturity":
                causes.append("weak_releases")
            if signal.signal == "community_activity":
                causes.append("community_stall")
            if signal.signal == "mentor_engagement" and signal.severity != "low":
                causes.append("low_signoffs")
        causes = sorted(set(causes))
        if include_causes and not any(cause in include_causes for cause in causes):
            continue
        if not causes:
            continue
        urgency = evaluation["severity"]
        if not severity_at_least(urgency, urgency_minimum):
            continue
        mentor_signals = [
            signal
            for signal in evaluation["signals"]
            if signal.signal
            in {
                "mentor_coverage",
                "mentor_engagement",
                "reporting_reliability",
                "community_activity",
                "release_maturity",
            }
        ]
        primary = mentor_signals[0]
        items.append(
            {
                "podling": record.name,
                "urgency": urgency,
                "attention_reasons": causes,
                "summary": primary.reason,
                "suggested_follow_up": primary.recommended_action,
                "confidence": confidence_for_record(record),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["urgency"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "items": items[:limit],
    }


def tool_community_health_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    scope = optional_choice(arguments, "scope", SCOPES) or "all_podlings"
    group_by = optional_choice(arguments, "group_by", GROUPINGS) or "risk_band"
    include_examples = optional_boolean(arguments, "include_examples", True)

    data = build_records(**sources)
    records = data["records"]
    if scope == "reporting_podlings":
        records = [record for record in records if record.report_summary is not None]

    strong_patterns: list[str] = []
    risk_themes: list[dict[str, Any]] = []
    improving_podlings: list[str] = []
    watchlist_overlap: list[str] = []
    mentoring_capacity_observations: list[str] = []

    strong_examples = []
    weak_examples = []
    mentor_risk = []

    for record in records:
        evaluation = evaluate_record(record)
        metrics = record.preferred_metrics or {}
        if evaluation["severity"] in {"high", "critical"}:
            watchlist_overlap.append(record.name)
            weak_examples.append(record.name)
        if evaluation["trend"] == "improving":
            improving_podlings.append(record.name)
        if record.mentor_count <= 1:
            mentor_risk.append(record.name)
        if metrics and (metrics.get("commits") or 0) >= 25 and (metrics.get("unique_committers") or 0) >= 4:
            strong_examples.append(record.name)

    if strong_examples:
        strong_patterns.append("Some podlings show healthy recent contributor and commit activity.")
    if mentor_risk:
        mentoring_capacity_observations.append("A subset of podlings has thin mentor coverage that may need IPMC help.")

    if weak_examples:
        theme: dict[str, Any] = {
            "theme": "Low activity or weak reporting signals are concentrated in a subset of podlings.",
            "severity": "high",
        }
        if include_examples:
            theme["example_podlings"] = weak_examples[:5]
        risk_themes.append(theme)
    if mentor_risk:
        theme = {
            "theme": "Mentor coverage and sign-off capacity appear uneven.",
            "severity": "medium",
        }
        if include_examples:
            theme["example_podlings"] = mentor_risk[:5]
        risk_themes.append(theme)

    overall_summary = (
        f"Across {len(records)} podling(s), the main IPMC themes are community resilience, "
        "reporting reliability, and mentor coverage."
    )
    if group_by == "mentor_load":
        overall_summary += " Results are especially useful for reviewing mentoring capacity."
    elif group_by == "age_band":
        overall_summary += " Older podlings may warrant additional graduation or intervention discussion."

    return {
        "generated_at_scope": group_by,
        "scope": scope,
        "overall_summary": overall_summary,
        "strong_patterns": strong_patterns,
        "risk_themes": risk_themes,
        "improving_podlings": sorted(improving_podlings),
        "watchlist_overlap": sorted(watchlist_overlap),
        "mentoring_capacity_observations": mentoring_capacity_observations,
        "recommended_ipmc_focus": [
            "Review high-risk podlings with missing reports, thin mentor coverage, or weak activity.",
            "Use podling briefs and readiness checks to decide where graduation conversations are timely.",
        ],
    }


SEVERITIES_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


TOOLS: dict[str, dict[str, Any]] = {
    "ipmc_watchlist": schemas.tool_definition(
        description="Return podlings that most need IPMC attention based on combined lifecycle and health signals.",
        handler=tool_ipmc_watchlist,
        properties=schemas.watchlist_properties(),
    ),
    "graduation_readiness": schemas.tool_definition(
        description="Assess whether a podling appears ready, near ready, or not yet ready for graduation.",
        handler=tool_graduation_readiness,
        properties=schemas.readiness_properties(),
        required=["podling"],
    ),
    "podling_brief": schemas.tool_definition(
        description=(
            "Return an IPMC-oriented briefing for a single podling, including status, trajectory, and attention areas."
        ),
        handler=tool_podling_brief,
        properties=schemas.brief_properties(),
        required=["podling"],
    ),
    "mentoring_attention_needed": schemas.tool_definition(
        description="Return podlings where mentoring intervention appears necessary, with urgency and likely causes.",
        handler=tool_mentoring_attention_needed,
        properties=schemas.mentoring_attention_properties(),
    ),
    "community_health_summary": schemas.tool_definition(
        description=(
            "Return an IPMC-level summary of community health across podlings, "
            "including strong patterns, risks, and mentoring-capacity signals."
        ),
        handler=tool_community_health_summary,
        properties=schemas.community_summary_properties(),
    ),
}
