"""Tool handlers and registration for the IPMC oversight MCP server."""

from __future__ import annotations

from typing import Any

from . import schemas
from .analysis import (
    confidence_for_record,
    evaluate_record,
    readiness_assessment,
    recent_change_events,
    release_visibility_signals,
    reporting_gap_signals,
    reporting_reliability_pattern,
    severity_at_least,
    significant_change_events,
    stalled_podling_signal,
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
REPORTING_GAPS = {
    "missing_health_report",
    "missing_recent_reports",
    "newly_missing_reports",
    "inconsistent_reporting_pattern",
    "reporting_metric_missing",
}
REPORTING_RELIABILITY_CATEGORIES = {
    "consistently_on_time",
    "occasional_late",
    "repeated_late",
    "repeated_missing",
    "reporting_data_unavailable",
}
RELEASE_VISIBILITY_SIGNALS = {
    "no_releases_12m",
    "long_release_gap",
    "high_activity_no_releases",
    "contributors_no_releases",
    "release_visibility_unknown",
}
SIGNIFICANT_CHANGE_SIGNALS = {
    "crossed_12m_without_release",
    "meaningful_activity_shift",
    "reports_newly_missing",
    "releases_disappeared",
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
        "report_source": optional_string(arguments, "report_source"),
        "as_of_date": optional_string(arguments, "as_of_date"),
    }


def _source_location(source_meta: dict[str, Any]) -> str:
    return str(source_meta.get("source") or source_meta.get("reports_dir") or "")


def _report_source_meta(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(
        "report_source",
        {
            "source": "",
            "reports_dir": "",
            "report_count": 0,
            "podling_count": 0,
            "available": False,
        },
    )


def _record_by_name(records: list[Any], podling: str) -> Any:
    for record in records:
        if record.name.casefold() == podling.casefold():
            return record
    raise ValueError(f"Podling '{podling}' not found")


def _maybe_filter_podling(records: list[Any], podling: str | None) -> list[Any]:
    if podling is None:
        return records
    return [_record_by_name(records, podling)]


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


def _metric_snapshot(metrics: dict[str, Any] | None, fields: list[str]) -> dict[str, Any]:
    if not metrics:
        return {}
    return {field: metrics[field] for field in fields if metrics.get(field) is not None}


def _source_data_used(record: Any) -> list[dict[str, Any]]:
    podling_data = {
        "source": "podlings",
        "fields": ["name", "status", "mentors", "startdate"],
        "observed": {
            "name": record.name,
            "status": record.status,
            "mentor_count": record.mentor_count,
            "startdate": record.podling.get("startdate"),
            "months_in_incubation": record.months_in_incubation,
        },
    }
    health_fields = [
        "commits",
        "unique_committers",
        "unique_authors",
        "dev_unique_posters",
        "reports_count",
        "avg_mentor_signoffs",
        "releases",
    ]
    health_data: dict[str, Any] = {
        "source": "apache-health",
        "preferred_window": record.preferred_window,
        "reporting_window": record.reporting_window,
        "available": record.report_summary is not None,
        "observed": _metric_snapshot(record.preferred_metrics, health_fields),
    }
    reporting_snapshot = _metric_snapshot(record.reporting_metrics, ["reports_count", "avg_mentor_signoffs"])
    if reporting_snapshot:
        health_data["reporting_observed"] = reporting_snapshot
    report_data: dict[str, Any] = {
        "source": "apache-incubator-reports",
        "fields": [
            "report_id",
            "report_period",
            "issues",
            "observed_mentor_signoff_count",
            "last_release",
        ],
        "available": bool(record.incubator_reports),
        "observed": {
            "report_entry_count": len(record.incubator_reports),
            "latest_report_period": (
                record.incubator_reports[-1].get("report_period") if record.incubator_reports else None
            ),
        },
    }
    return [podling_data, health_data, report_data]


def _missing_context(record: Any, extra_missing: list[str] | None = None) -> list[str]:
    missing: list[str] = []
    if record.podling.get("startdate") is None:
        missing.append("Podling start date.")
    if record.report_summary is None:
        missing.append("Recent apache-health report.")
    if record.preferred_metrics is None:
        missing.append("Recent community activity metrics.")
    else:
        for label, field in [
            ("Commit activity count.", "commits"),
            ("Active committer count.", "unique_committers"),
            ("Mailing-list participation count.", "dev_unique_posters"),
            ("Release count.", "releases"),
        ]:
            if record.preferred_metrics.get(field) is None:
                missing.append(label)
    if record.reporting_metrics is None:
        missing.append("Recent Incubator reporting and mentor sign-off metrics.")
    else:
        for label, field in [
            ("Incubator report count.", "reports_count"),
            ("Average mentor sign-off count.", "avg_mentor_signoffs"),
        ]:
            if record.reporting_metrics.get(field) is None:
                missing.append(label)
    if not record.incubator_reports:
        missing.append("Cached Incubator report entries from ReportMCP.")
    if extra_missing:
        missing.extend(extra_missing)
    return sorted(set(missing)) or ["No obvious missing source data for this opinion."]


def _explainability(
    record: Any,
    reasoning: list[str],
    *,
    extra_missing: list[str] | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    return {
        "source_data_used": _source_data_used(record),
        "reasoning": reasoning,
        "confidence": confidence or confidence_for_record(record),
        "missing": _missing_context(record, extra_missing),
    }


def _summary_explainability(
    records: list[Any],
    reasoning: list[str],
    *,
    example_podlings: list[str] | None = None,
) -> dict[str, Any]:
    reporting_records = [record for record in records if record.report_summary is not None]
    incubator_report_records = [record for record in records if record.incubator_reports]
    missing_health = [record.name for record in records if record.report_summary is None]
    low_mentor = [record.name for record in records if record.mentor_count <= 1]
    return {
        "source_data_used": [
            {
                "source": "podlings",
                "fields": ["name", "status", "mentors", "startdate"],
                "observed": {
                    "podling_count": len(records),
                    "thin_mentor_coverage_count": len(low_mentor),
                    "example_podlings": (example_podlings or [record.name for record in records])[:5],
                },
            },
            {
                "source": "apache-health",
                "fields": ["preferred health metrics", "reporting metrics"],
                "observed": {
                    "reporting_podling_count": len(reporting_records),
                    "missing_health_report_count": len(missing_health),
                    "missing_health_report_examples": missing_health[:5],
                },
            },
            {
                "source": "apache-incubator-reports",
                "fields": ["cached Incubator report entries"],
                "observed": {
                    "podling_with_cached_report_count": len(incubator_report_records),
                    "missing_cached_report_examples": [
                        record.name for record in records if not record.incubator_reports
                    ][:5],
                },
            },
        ],
        "reasoning": reasoning,
        "confidence": "high"
        if records and len(reporting_records) == len(records)
        else "medium"
        if reporting_records
        else "low",
        "missing": (
            [
                item
                for item in [
                    "Health reports for all podlings in scope." if missing_health else None,
                    "Cached Incubator report entries for all podlings in scope."
                    if len(incubator_report_records) != len(records)
                    else None,
                ]
                if item
            ]
            or ["No obvious missing source data for this opinion."]
        ),
    }


def _supporting_signals(evaluation: dict[str, Any], record: Any) -> list[dict[str, Any]]:
    return [
        {
            **signal.to_dict(),
            "explainability": _explainability(record, [signal.reason]),
        }
        for signal in evaluation["signals"]
    ]


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
        reasoning = [signal.reason for signal in evaluation["signals"]] or [summary]
        items.append(
            {
                "podling": record.name,
                "severity": evaluation["severity"],
                "trend": evaluation["trend"],
                "watch_reasons": reasons,
                "summary": summary,
                "recommended_ipmc_action": action,
                "supporting_signals": _supporting_signals(evaluation, record),
                "confidence": confidence_for_record(record),
                "explainability": _explainability(record, reasoning),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["severity"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
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
    confidence = confidence_for_record(record)
    payload = {
        "podling": record.name,
        "assessment": readiness["assessment"],
        "confidence": confidence,
        "summary": readiness["summary"],
        "strengths": readiness["strengths"],
        "blockers": readiness["blockers"],
        "missing_evidence": readiness["missing_evidence"],
        "dimension_scores": readiness["dimension_scores"],
        "recommended_next_steps": readiness["recommended_next_steps"],
        "explainability": _explainability(
            record,
            [
                readiness["summary"],
                f"Dimension scores: {readiness['dimension_scores']}.",
                f"Strength count: {len(readiness['strengths'])}; blocker count: {len(readiness['blockers'])}.",
            ],
            extra_missing=readiness["missing_evidence"],
            confidence=confidence,
        ),
    }
    if include_evidence:
        evaluation = evaluate_record(record)
        payload["evidence"] = [
            {
                "statement": signal.reason,
                "source": signal.source,
                "explainability": _explainability(record, [signal.reason], confidence=confidence),
            }
            for signal in evaluation["signals"]
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
            _source_location(data["health_source"]),
            _source_location(_report_source_meta(data)),
        ],
        "explainability": _explainability(
            record,
            [
                status_summary,
                recent_trajectory,
                readiness["summary"],
                *concerns,
            ],
            extra_missing=readiness["missing_evidence"],
        ),
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
        reasoning = [signal.reason for signal in mentor_signals]
        items.append(
            {
                "podling": record.name,
                "urgency": urgency,
                "attention_reasons": causes,
                "summary": primary.reason,
                "suggested_follow_up": primary.recommended_action,
                "confidence": confidence_for_record(record),
                "explainability": _explainability(record, reasoning),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["urgency"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "items": items[:limit],
    }


def tool_recent_changes(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")
    limit = optional_integer(arguments, "limit") or 25

    data = build_records(**sources)
    records = _maybe_filter_podling(data["records"], podling)
    items = []
    for record in records:
        changes = recent_change_events(record)
        if not changes:
            continue
        items.append(
            {
                "podling": record.name,
                "preferred_window": record.preferred_window,
                "reporting_window": record.reporting_window,
                "changes": changes,
                "summary": f"{record.name} has {len(changes)} explicit recent change(s) in tracked IPMC scan fields.",
                "explainability": _explainability(
                    record,
                    [
                        "Only non-flat source trend fields are included.",
                        "Static metrics and unchanged fields are excluded from this tool.",
                    ],
                ),
            }
        )

    items.sort(key=lambda item: (-len(item["changes"]), item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "recent_changes",
        "as_of_date": sources["as_of_date"],
        "items": items[:limit],
    }


def tool_significant_changes(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", SIGNIFICANT_CHANGE_SIGNALS)

    data = build_records(**sources)
    records = _maybe_filter_podling(data["records"], podling)
    items = []
    for record in records:
        changes = significant_change_events(record)
        if include_signals:
            changes = [change for change in changes if change["signal"] in include_signals]
        if not changes:
            continue
        items.append(
            {
                "podling": record.name,
                "preferred_window": record.preferred_window,
                "reporting_window": record.reporting_window,
                "changes": changes,
                "summary": f"{record.name} has {len(changes)} significant factual change(s) in IPMC scan fields.",
                "explainability": _explainability(
                    record,
                    [
                        (
                            "This view filters recent changes to release-window crossings and review-worthy "
                            "activity shifts."
                        ),
                        "It reports source facts and transparent thresholds without ranking or recommendations.",
                    ],
                ),
            }
        )

    items.sort(key=lambda item: (-len(item["changes"]), item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "significant_changes",
        "as_of_date": sources["as_of_date"],
        "included_signals": include_signals,
        "items": items[:limit],
    }


def tool_reporting_gaps(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")
    limit = optional_integer(arguments, "limit") or 25
    include_gaps = optional_list_of_choices(arguments, "include_gaps", REPORTING_GAPS)

    data = build_records(**sources)
    records = _maybe_filter_podling(data["records"], podling)
    items = []
    for record in records:
        gaps = reporting_gap_signals(record)
        if include_gaps:
            gaps = [gap for gap in gaps if gap["gap"] in include_gaps]
        if not gaps:
            continue
        severity = max(gaps, key=lambda gap: SEVERITIES_ORDER[gap["severity"]])["severity"]
        items.append(
            {
                "podling": record.name,
                "severity": severity,
                "reporting_window": record.reporting_window,
                "gaps": gaps,
                "summary": gaps[0]["reason"],
                "recommended_ipmc_action": "Follow up on Incubator reporting compliance and report presence.",
                "explainability": _explainability(
                    record,
                    [
                        "Only Incubator reporting presence and reporting trend fields are considered.",
                        "Activity signals are intentionally excluded from this tool.",
                    ],
                    confidence=confidence_for_record(record),
                ),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["severity"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "reporting_gaps",
        "as_of_date": sources["as_of_date"],
        "items": items[:limit],
    }


def tool_reporting_reliability(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")
    limit = optional_integer(arguments, "limit") or 100
    include_categories = optional_list_of_choices(
        arguments,
        "include_categories",
        REPORTING_RELIABILITY_CATEGORIES,
    )
    category_order = [
        "repeated_missing",
        "repeated_late",
        "occasional_late",
        "consistently_on_time",
        "reporting_data_unavailable",
    ]

    data = build_records(**sources)
    records = _maybe_filter_podling(data["records"], podling)
    buckets: dict[str, list[dict[str, Any]]] = {category: [] for category in category_order}

    for record in records:
        pattern = reporting_reliability_pattern(record)
        category = pattern["category"]
        if include_categories and category not in include_categories:
            continue
        buckets[category].append(
            {
                "podling": record.name,
                "category": category,
                "observed": pattern["observed"],
                "evidence": pattern["evidence"],
                "summary": pattern["reason"],
                "explainability": _explainability(
                    record,
                    [
                        "Only Incubator report-count metrics across available reporting windows are considered.",
                        "Activity, release, mentor, and graduation signals are intentionally excluded.",
                        (
                            "Expected counts use monthly reporting for the first quarter and quarterly reporting "
                            "after that; a single missed expected report is treated as a catch-up-next-month case."
                        ),
                        "Exact due-date timeliness is not visible from rolling report counts.",
                    ],
                ),
            }
        )

    for category, items in buckets.items():
        items.sort(key=lambda item: item["podling"].casefold())
        buckets[category] = items[:limit]

    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "reporting_reliability",
        "as_of_date": sources["as_of_date"],
        "category_order": category_order,
        "counts": {category: len(items) for category, items in buckets.items()},
        "buckets": buckets,
        "explainability": _summary_explainability(
            records,
            [
                "Reporting reliability is grouped by report-count patterns over available rolling windows.",
                "The view separates one-off reporting slips from repeated missing reporting evidence.",
                "Buckets are non-ranked and sorted alphabetically inside each category.",
            ],
            example_podlings=[record.name for record in records[:5]],
        ),
    }


def tool_release_visibility(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", RELEASE_VISIBILITY_SIGNALS)

    data = build_records(**sources)
    records = _maybe_filter_podling(data["records"], podling)
    items = []
    for record in records:
        signals = release_visibility_signals(record)
        if include_signals:
            signals = [signal for signal in signals if signal["signal"] in include_signals]
        if not signals:
            continue
        severity = max(signals, key=lambda signal: SEVERITIES_ORDER[signal["severity"]])["severity"]
        items.append(
            {
                "podling": record.name,
                "severity": severity,
                "signals": signals,
                "summary": signals[0]["reason"],
                "recommended_ipmc_action": "Check whether release cadence and release governance are visible enough.",
                "explainability": _explainability(
                    record,
                    [
                        "Only release visibility and release-governance mismatch checks are considered.",
                        "General activity is used only to detect activity-without-release mismatches.",
                    ],
                ),
            }
        )

    items.sort(key=lambda item: (-SEVERITIES_ORDER[item["severity"]], item["podling"].casefold()))
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "release_visibility",
        "as_of_date": sources["as_of_date"],
        "items": items[:limit],
    }


def _cohort_bucket_item(record: Any, signals: list[dict[str, Any]], summary_key: str) -> dict[str, Any]:
    return {
        "podling": record.name,
        "signals": signals,
        "summary": signals[0][summary_key],
    }


def tool_reporting_cohort(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, "podling")

    data = build_records(**sources)
    records = [
        record for record in _maybe_filter_podling(data["records"], podling) if record.report_summary is not None
    ]
    buckets: dict[str, list[dict[str, Any]]] = {
        "reporting_issues": [],
        "release_visibility_issues": [],
        "recent_significant_changes": [],
        "no_obvious_concerns": [],
    }

    for record in records:
        reporting_gaps = reporting_gap_signals(record)
        release_signals = release_visibility_signals(record)
        recent_changes = significant_change_events(record)

        if reporting_gaps:
            buckets["reporting_issues"].append(_cohort_bucket_item(record, reporting_gaps, "reason"))
        if release_signals:
            buckets["release_visibility_issues"].append(_cohort_bucket_item(record, release_signals, "reason"))
        if recent_changes:
            buckets["recent_significant_changes"].append(_cohort_bucket_item(record, recent_changes, "why_it_matters"))
        if not reporting_gaps and not release_signals and not recent_changes:
            buckets["no_obvious_concerns"].append(
                {
                    "podling": record.name,
                    "summary": "No reporting, release visibility, or recent-change concerns were detected.",
                    "observed": {
                        "preferred_window": record.preferred_window,
                        "reporting_window": record.reporting_window,
                    },
                }
            )

    for items in buckets.values():
        items.sort(key=lambda item: item["podling"].casefold())

    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "reporting_cohort",
        "as_of_date": sources["as_of_date"],
        "cohort_definition": "Current podlings with apache-health report data in the selected health source.",
        "bucket_order": [
            "reporting_issues",
            "release_visibility_issues",
            "recent_significant_changes",
            "no_obvious_concerns",
        ],
        "counts": {name: len(items) for name, items in buckets.items()},
        "buckets": buckets,
        "explainability": _summary_explainability(
            records,
            [
                "The cohort includes current podlings with apache-health report data.",
                "Buckets are non-ranked and sorted alphabetically inside each bucket.",
                (
                    "Reporting issues, release visibility issues, and recent significant changes "
                    "are evaluated independently."
                ),
            ],
            example_podlings=[record.name for record in records[:5]],
        ),
    }


def tool_stalled_podlings(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    limit = optional_integer(arguments, "limit") or 25

    data = build_records(**sources)
    items = []
    for record in data["records"]:
        signal = stalled_podling_signal(record)
        if signal is None:
            continue
        items.append(
            {
                "podling": record.name,
                "severity": signal["severity"],
                "definition_matched": signal["definition_matched"],
                "observed": signal["observed"],
                "summary": signal["reason"],
                "recommended_ipmc_action": (
                    "Confirm whether the podling is effectively inactive or activity moved elsewhere."
                ),
                "explainability": _explainability(
                    record,
                    [
                        (
                            "The stalled signal is emitted only when low commits, low committers, "
                            "and no releases are all present, with low discussion or discussion "
                            "that is not translating into delivery."
                        ),
                        "This is intentionally narrower than the IPMC watchlist.",
                    ],
                ),
            }
        )

    items.sort(key=lambda item: item["podling"].casefold())
    return {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "generated_for": "stalled_podlings",
        "as_of_date": sources["as_of_date"],
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
            "explainability": _summary_explainability(
                records,
                [
                    "Podlings with high or critical evaluated severity were counted as watchlist overlap.",
                    (
                        "The theme is raised when at least one podling has high-risk activity, reporting, "
                        "or related signals."
                    ),
                ],
                example_podlings=weak_examples,
            ),
        }
        if include_examples:
            theme["example_podlings"] = weak_examples[:5]
        risk_themes.append(theme)
    if mentor_risk:
        theme = {
            "theme": "Mentor coverage and sign-off capacity appear uneven.",
            "severity": "medium",
            "explainability": _summary_explainability(
                records,
                [
                    "Podlings with zero or one listed mentor were counted as thin mentor coverage.",
                    "The theme is raised when mentor coverage suggests IPMC capacity or follow-up risk.",
                ],
                example_podlings=mentor_risk,
            ),
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
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
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
        "explainability": _summary_explainability(
            records,
            [
                overall_summary,
                (
                    "Community health summary combines evaluated podling severity, activity trends, "
                    "mentor coverage, and reporting coverage."
                ),
                f"Grouping requested: {group_by}. Scope requested: {scope}.",
            ],
            example_podlings=watchlist_overlap or mentor_risk or strong_examples,
        ),
    }


SEVERITIES_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


TOOLS: dict[str, dict[str, Any]] = {
    "recent_changes": schemas.tool_definition(
        description=("Return per-podling recent deltas the IPMC should scan, excluding unchanged or static fields."),
        handler=tool_recent_changes,
        properties=schemas.recent_changes_properties(),
    ),
    "significant_changes": schemas.tool_definition(
        description=(
            "Return a structured factual subset of recent changes: no 12-month releases, large activity shifts, "
            "and newly visible reporting or release transitions."
        ),
        handler=tool_significant_changes,
        properties=schemas.significant_changes_properties(),
    ),
    "reporting_gaps": schemas.tool_definition(
        description="Return podlings with Incubator reporting compliance gaps, excluding activity analysis.",
        handler=tool_reporting_gaps,
        properties=schemas.reporting_gaps_properties(),
    ),
    "reporting_reliability": schemas.tool_definition(
        description=(
            "Return objective reporting reliability patterns over time, separating one-off late reporting "
            "from repeated late or missing reporting."
        ),
        handler=tool_reporting_reliability,
        properties=schemas.reporting_reliability_properties(),
    ),
    "release_visibility": schemas.tool_definition(
        description=(
            "Return release-governance visibility concerns, including no releases and activity/release mismatches."
        ),
        handler=tool_release_visibility,
        properties=schemas.release_visibility_properties(),
    ),
    "reporting_cohort": schemas.tool_definition(
        description=(
            "Return current reporting podlings grouped into non-ranked IPMC review buckets: "
            "reporting issues, release visibility issues, recent significant changes, and no obvious concerns."
        ),
        handler=tool_reporting_cohort,
        properties=schemas.reporting_cohort_properties(),
    ),
    "stalled_podlings": schemas.tool_definition(
        description=("Return podlings that match the strict low-delivery, no-release stalled definition."),
        handler=tool_stalled_podlings,
        properties=schemas.stalled_podlings_properties(),
    ),
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
