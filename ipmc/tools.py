"""Tool handlers and registration for the IPMC oversight MCP server."""

from __future__ import annotations

from typing import Any

from . import schemas
from .analysis import (
    confidence_for_record,
    cross_source_mismatches,
    evaluate_record,
    readiness_assessment,
    recent_change_events,
    release_visibility_signals,
    report_narrative_signals,
    reporting_gap_signals,
    reporting_reliability_pattern,
    severity_at_least,
    severity_value,
    significant_change_events,
    stalled_podling_signal,
)
from .data import (
    _podling_key,
    build_records,
    configure_defaults,
    load_incubator_general_mail,
    load_podling_release_artifacts,
    load_podling_release_vote_history,
    load_podlings,
    months_since,
    refresh_incubator_general_mail_cache,
    refresh_incubator_report_cache,
    source_defaults,
)

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
REPORT_NARRATIVE_SIGNALS = {
    "latest_reported_issues",
    "recurring_reported_issue",
    "possible_report_copy_forward",
    "low_observed_mentor_signoff",
    "report_release_visibility_mismatch",
}
CROSS_SOURCE_MISMATCH_SIGNALS = {
    "report_release_visibility_mismatch",
    "quiet_report_high_risk_mismatch",
    "latest_signoff_drop_vs_average",
}


def _highest_severity(items: list[dict[str, Any]], field: str = "severity") -> str:
    return max(items, key=lambda item: severity_value(str(item[field])))[field]


def _sort_by_severity_then_podling(items: list[dict[str, Any]], field: str = "severity") -> None:
    items.sort(key=lambda item: (-severity_value(str(item[field])), item["podling"].casefold()))


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


def optional_depth(arguments: dict[str, Any], key: str, default: int = 1) -> int:
    value = optional_integer(arguments, key)
    if value is None:
        return default
    if value < 0 or value > 1:
        raise ValueError(f"'{key}' must be 0 or 1")
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
        "mail_source": optional_string(arguments, "mail_source"),
        "mail_api_base": optional_string(arguments, "mail_api_base"),
        "as_of_date": optional_string(arguments, "as_of_date"),
    }


def _resolve_source_defaults(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "podlings_source": optional_string(arguments, "podlings_source"),
        "health_source": optional_string(arguments, "health_source"),
        "report_source": optional_string(arguments, "report_source"),
        "mail_source": optional_string(arguments, "mail_source"),
        "mail_api_base": optional_string(arguments, "mail_api_base"),
        "release_dist_base": optional_string(arguments, "release_dist_base"),
        "release_archive_base": optional_string(arguments, "release_archive_base"),
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


def _mail_source_meta(data: dict[str, Any]) -> dict[str, Any]:
    return data.get(
        "mail_source",
        {
            "source": "",
            "cache_dir": "",
            "message_count": 0,
            "podling_count": 0,
            "available": False,
        },
    )


def _source_context(data: dict[str, Any], *, generated_for: str | None = None) -> dict[str, Any]:
    context = {
        "podlings_source": data["podlings_source"],
        "health_source": data["health_source"],
        "report_source": _report_source_meta(data),
        "mail_source": _mail_source_meta(data),
    }
    if generated_for is not None:
        context["generated_for"] = generated_for
    return context


def _record_by_name(records: list[Any], podling: str) -> Any:
    requested_key = _podling_key(podling)
    for record in records:
        if _podling_key(record.name) == requested_key:
            return record
    raise ValueError(f"Podling '{podling}' not found")


def _maybe_filter_podling(records: list[Any], podling: str | None) -> list[Any]:
    if podling is None:
        return records
    return [_record_by_name(records, podling)]


def _load_tool_records(
    arguments: dict[str, Any],
    *,
    include_mail: bool = False,
    include_non_current: bool = False,
    podling_key: str = "podling",
) -> tuple[dict[str, Any], dict[str, Any], list[Any], str | None]:
    sources = _resolve_sources(arguments)
    podling = optional_string(arguments, podling_key)
    data = build_records(
        **sources,
        include_mail=include_mail,
        include_non_current=include_non_current,
        requested_podling=podling,
    )
    records = _maybe_filter_podling(data["records"], podling)
    return sources, data, records, podling


def _load_single_podling_record(
    arguments: dict[str, Any],
    *,
    include_mail: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    sources = _resolve_sources(arguments)
    podling = require_string(arguments, "podling")
    data = build_records(
        **sources,
        include_mail=include_mail,
        requested_podling=podling,
    )
    record = _record_by_name(data["records"], podling)
    return sources, data, record


def _limit_sorted_items(
    items: list[dict[str, Any]],
    *,
    limit: int,
    sort_key: Any,
) -> list[dict[str, Any]]:
    items.sort(key=sort_key)
    return items[:limit]


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
    mail_data: dict[str, Any] = {
        "source": "apache-incubator-mail",
        "fields": ["id", "subject", "from", "date", "thread_id", "permalink"],
        "available": bool(record.incubator_general_mail),
        "observed": {
            "matching_general_mail_count": len(record.incubator_general_mail),
            "latest_message_date": (
                record.incubator_general_mail[0].get("date") if record.incubator_general_mail else None
            ),
        },
    }
    return [podling_data, health_data, report_data, mail_data]


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
    if not record.incubator_general_mail:
        missing.append("Cached Incubator general-list messages from MailMCP.")
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
    incubator_mail_records = [record for record in records if record.incubator_general_mail]
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
            {
                "source": "apache-incubator-mail",
                "fields": ["cached general@incubator.apache.org message summaries"],
                "observed": {
                    "podling_with_general_mail_count": len(incubator_mail_records),
                    "missing_general_mail_examples": [
                        record.name for record in records if not record.incubator_general_mail
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
                    "Cached Incubator general-list messages for all podlings in scope."
                    if len(incubator_mail_records) != len(records)
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


def tool_configure_sources(arguments: dict[str, Any]) -> dict[str, Any]:
    defaults = _resolve_source_defaults(arguments)
    configured = {key: value for key, value in defaults.items() if value is not None}
    if configured:
        configure_defaults(**configured)
    return {
        "generated_for": "configure_sources",
        "updated": sorted(configured),
        "source_defaults": source_defaults(),
    }


def tool_current_podlings_overview(arguments: dict[str, Any]) -> dict[str, Any]:
    podlings_source = optional_string(arguments, "podlings_source")
    as_of_date = optional_string(arguments, "as_of_date")
    limit = optional_integer(arguments, "limit")
    include_descriptions = optional_boolean(arguments, "include_descriptions", True)

    podlings, podlings_meta = load_podlings(podlings_source)
    current_podlings = [podling for podling in podlings if str(podling.get("status") or "").casefold() == "current"]
    current_podlings.sort(key=lambda podling: str(podling.get("name") or "").casefold())
    if limit is not None:
        current_podlings = current_podlings[:limit]

    items = []
    for podling in current_podlings:
        mentors = podling.get("mentors") or []
        item = {
            "podling": podling.get("name"),
            "status": podling.get("status"),
            "sponsor": podling.get("sponsor"),
            "sponsor_type": podling.get("sponsor_type"),
            "champion": podling.get("champion"),
            "mentors": mentors,
            "mentor_count": len(mentors),
            "startdate": podling.get("startdate"),
            "months_in_incubation": months_since(podling.get("startdate"), as_of_date),
            "resource": podling.get("resource"),
        }
        if include_descriptions:
            item["description"] = podling.get("description")
        items.append(item)

    return {
        "generated_for": "current_podlings_overview",
        "podlings_source": podlings_meta,
        "as_of_date": as_of_date,
        "total_podling_count": len(podlings),
        "current_podling_count": len(
            [podling for podling in podlings if str(podling.get("status") or "").casefold() == "current"]
        ),
        "returned_count": len(items),
        "items": items,
        "summary": (f"{len(items)} current podling(s) returned from podlings.xml-derived lifecycle metadata."),
    }


def tool_ipmc_watchlist(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    limit = optional_integer(arguments, "limit") or 10
    severity_minimum = optional_choice(arguments, "severity_at_least", SEVERITIES)
    include_reasons = optional_list_of_choices(arguments, "include_reasons", WATCHLIST_REASONS)

    data = build_records(**sources, include_mail=False)
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

    _sort_by_severity_then_podling(items)
    return {
        **_source_context(data, generated_for="ipmc_watchlist"),
        "as_of_date": sources["as_of_date"],
        "items": items[:limit],
    }


def tool_graduation_readiness(arguments: dict[str, Any]) -> dict[str, Any]:
    _, data, record = _load_single_podling_record(arguments, include_mail=False)
    include_evidence = optional_boolean(arguments, "include_evidence", True)
    strict_mode = optional_boolean(arguments, "strict_mode", False) or False

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
    brief_format = optional_choice(arguments, "brief_format", BRIEF_FORMATS) or "summary"
    focus = optional_list_of_choices(arguments, "focus", FOCUS_AREAS) or []
    _, data, record = _load_single_podling_record(arguments, include_mail=False)

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
            _source_location(_mail_source_meta(data)),
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

    data = build_records(**sources, include_mail=False)
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

    _sort_by_severity_then_podling(items, field="urgency")
    return {**_source_context(data), "items": items[:limit]}


def tool_recent_changes(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25

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

    return {
        **_source_context(data, generated_for="recent_changes"),
        "as_of_date": sources["as_of_date"],
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-len(item["changes"]), item["podling"].casefold()),
        ),
    }


def tool_significant_changes(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", SIGNIFICANT_CHANGE_SIGNALS)

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

    return {
        **_source_context(data, generated_for="significant_changes"),
        "as_of_date": sources["as_of_date"],
        "included_signals": include_signals,
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-len(item["changes"]), item["podling"].casefold()),
        ),
    }


def tool_reporting_gaps(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25
    include_gaps = optional_list_of_choices(arguments, "include_gaps", REPORTING_GAPS)

    items = []
    for record in records:
        gaps = reporting_gap_signals(record)
        if include_gaps:
            gaps = [gap for gap in gaps if gap["gap"] in include_gaps]
        if not gaps:
            continue
        severity = _highest_severity(gaps)
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

    return {
        **_source_context(data, generated_for="reporting_gaps"),
        "as_of_date": sources["as_of_date"],
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-severity_value(str(item["severity"])), item["podling"].casefold()),
        ),
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

    data = build_records(**sources, include_mail=False, requested_podling=podling)
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
        **_source_context(data, generated_for="reporting_reliability"),
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
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", RELEASE_VISIBILITY_SIGNALS)

    items = []
    for record in records:
        signals = release_visibility_signals(record)
        if include_signals:
            signals = [signal for signal in signals if signal["signal"] in include_signals]
        if not signals:
            continue
        severity = _highest_severity(signals)
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

    return {
        **_source_context(data, generated_for="release_visibility"),
        "as_of_date": sources["as_of_date"],
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-severity_value(str(item["severity"])), item["podling"].casefold()),
        ),
    }


def tool_release_vote_evidence(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, record = _load_single_podling_record(arguments, include_mail=False)
    mail_api_base = optional_string(arguments, "mail_api_base")
    mail_timespan = optional_string(arguments, "mail_timespan")
    limit = optional_integer(arguments, "limit") or 20

    cached_mail_entries, cached_mail_meta = load_incubator_general_mail(
        mail_source=sources["mail_source"],
        podlings=[record.podling],
        mail_api_base=mail_api_base,
        allow_live_fallback=False,
    )
    history = load_podling_release_vote_history(
        record.name,
        mail_api_base=mail_api_base,
        timespan=mail_timespan,
        limit=limit,
    )
    votes = history.get("votes") or []
    results = history.get("results") or []
    release_signals = release_visibility_signals(record)
    has_results = bool(results)
    cached_general_mail_matches = len(cached_mail_entries.get(_podling_key(record.name), []))
    summary = (
        f"MailMCP found {len(votes)} likely Incubator release vote thread(s) and "
        f"{len(results)} likely result thread(s) for {record.name}."
    )
    recommended_action = (
        "Compare the likely vote/result threads with release entries in reports and health metrics."
        if has_results
        else "Verify whether release votes reached general@incubator.apache.org and whether results were posted."
    )

    return {
        **_source_context(
            {
                **data,
                "mail_source": cached_mail_meta,
            },
            generated_for="release_vote_evidence",
        ),
        "mail_source": cached_mail_meta,
        "podling": record.name,
        "mail_history_source": {
            "source": history.get("source"),
            "api_base": history.get("api_base"),
            "timespan": history.get("timespan"),
            "available": history.get("available"),
            "reason": history.get("reason"),
            "sources": history.get("sources"),
        },
        "observed": {
            "vote_count": history.get("vote_count", len(votes)),
            "result_count": history.get("result_count", len(results)),
            "cached_general_mail_matches": cached_general_mail_matches,
            "health_release_metrics": _metric_snapshot(record.reporting_metrics, ["releases"])
            or _metric_snapshot(record.preferred_metrics, ["releases"]),
        },
        "votes": votes,
        "results": results,
        "release_visibility_signals": release_signals,
        "summary": summary,
        "recommended_ipmc_action": recommended_action,
        "explainability": _explainability(
            record,
            [
                summary,
                "Vote and result threads come from MailMCP live general@incubator.apache.org release-thread search.",
                "Release visibility signals remain derived from apache-health/report data and are shown separately.",
            ],
            confidence=confidence_for_record(record),
        ),
    }


def tool_release_artifact_evidence(arguments: dict[str, Any]) -> dict[str, Any]:
    podling = require_string(arguments, "podling")
    release_dist_base = optional_string(arguments, "release_dist_base")
    release_archive_base = optional_string(arguments, "release_archive_base")
    release_max_depth = optional_depth(arguments, "release_max_depth")

    evidence = load_podling_release_artifacts(
        podling,
        release_dist_base=release_dist_base,
        release_archive_base=release_archive_base,
        max_depth=release_max_depth,
    )
    cadence = evidence.get("cadence") or {}
    releases = evidence.get("releases") or []
    missing_sidecars = []
    for release in releases:
        for artifact in release.get("source_artifacts") or []:
            if not artifact.get("signatures"):
                missing_sidecars.append({"artifact": artifact.get("name"), "missing": "signature"})
            if not artifact.get("checksums"):
                missing_sidecars.append({"artifact": artifact.get("name"), "missing": "checksum"})
    incubating_hints = evidence.get("incubating_hints") or {}
    hint_text = incubating_hints.get("hints") or []
    release_count = int(evidence.get("release_count") or 0)
    summary = (
        f"ReleaseMCP found {release_count} release group(s) and "
        f"{evidence.get('source_artifact_count', 0)} source artifact(s) for {podling}."
    )

    recommended_action = "Compare ReleaseMCP artifact evidence with recent vote evidence and release visibility."
    if not evidence.get("available"):
        recommended_action = "Check ReleaseMCP availability or release source configuration."
    elif missing_sidecars or hint_text:
        recommended_action = "Review release artifact sidecars and Incubator naming/disclaimer hints."

    return {
        "generated_for": "release_artifact_evidence",
        "podling": podling,
        "release_source": {
            "source": evidence.get("source"),
            "dist_base": evidence.get("dist_base"),
            "archive_base": evidence.get("archive_base"),
            "available": evidence.get("available"),
            "reason": evidence.get("reason"),
            "sources": evidence.get("sources"),
        },
        "observed": {
            "release_count": release_count,
            "source_artifact_count": evidence.get("source_artifact_count", 0),
            "signature_count": evidence.get("signature_count", 0),
            "checksum_count": evidence.get("checksum_count", 0),
            "last_release_date": cadence.get("last_release_date"),
            "days_since_last_release": cadence.get("days_since_last_release"),
            "cadence": cadence.get("cadence"),
        },
        "releases": releases,
        "missing_sidecars": missing_sidecars,
        "incubating_hints": incubating_hints,
        "summary": summary,
        "recommended_ipmc_action": recommended_action,
        "explainability": {
            "source_data_used": [
                {
                    "source": "apache-incubator-releases",
                    "available": bool(evidence.get("available")),
                    "release_count": release_count,
                    "source_artifact_count": evidence.get("source_artifact_count", 0),
                }
            ],
            "reasoning": [
                summary,
                "Release artifact evidence comes from ReleaseMCP dist/archive inspection.",
                "Use release_visibility when apache-health/report-derived release signals are needed.",
            ],
            "confidence": "medium" if evidence.get("available") else "low",
            "missing": [] if evidence.get("available") else ["ReleaseMCP artifact evidence is unavailable."],
        },
    }


def tool_refresh_report_cache(arguments: dict[str, Any]) -> dict[str, Any]:
    report_source = optional_string(arguments, "report_source")
    full_history = optional_boolean(arguments, "full_history", False) or False
    years = None if full_history else optional_integer(arguments, "years") or 2
    limit = optional_integer(arguments, "limit")
    report_url = optional_string(arguments, "report_url")
    report_id = optional_string(arguments, "report_id")

    result = refresh_incubator_report_cache(
        report_source,
        years=years,
        limit=limit,
        report_url=report_url,
        report_id=report_id,
    )
    return {
        "generated_for": "refresh_report_cache",
        "report_source": {
            "source": result.get("source") or result.get("reports_dir"),
            "reports_dir": result.get("reports_dir") or result.get("cache_dir"),
            "available": result.get("available"),
            "reason": result.get("reason"),
        },
        "cache_result": result,
    }


def tool_refresh_mail_cache(arguments: dict[str, Any]) -> dict[str, Any]:
    mail_source = optional_string(arguments, "mail_source")
    mail_api_base = optional_string(arguments, "mail_api_base")
    mail_timespan = optional_string(arguments, "mail_timespan")
    query = optional_string(arguments, "query")
    limit = optional_integer(arguments, "limit") or 100

    result = refresh_incubator_general_mail_cache(
        mail_source,
        mail_api_base=mail_api_base,
        timespan=mail_timespan,
        query=query,
        limit=limit,
    )
    return {
        "generated_for": "refresh_mail_cache",
        "mail_source": {
            "source": result.get("source") or result.get("cache_dir"),
            "cache_dir": result.get("cache_dir"),
            "api_base": result.get("api_base"),
            "timespan": result.get("timespan"),
            "available": result.get("available"),
            "reason": result.get("reason"),
        },
        "cache_result": result,
    }


def _cohort_bucket_item(record: Any, signals: list[dict[str, Any]], summary_key: str) -> dict[str, Any]:
    return {
        "podling": record.name,
        "signals": signals,
        "summary": signals[0][summary_key],
    }


def tool_reporting_cohort(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    records = [record for record in records if record.report_summary is not None]
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
        **_source_context(data, generated_for="reporting_cohort"),
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


def tool_report_narrative_signals(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", REPORT_NARRATIVE_SIGNALS)

    items = []
    for record in records:
        signals = report_narrative_signals(record)
        if include_signals:
            signals = [signal for signal in signals if signal["signal"] in include_signals]
        if not signals:
            continue
        latest_report_period = record.incubator_reports[-1].get("report_period") if record.incubator_reports else None
        reasoning = [str(signal["reason"]) for signal in signals]
        items.append(
            {
                "podling": record.name,
                "severity": _highest_severity(signals),
                "latest_report_period": latest_report_period,
                "report_entry_count": len(record.incubator_reports),
                "signals": signals,
                "summary": signals[0]["reason"],
                "recommended_ipmc_action": (
                    "Review recent Incubator report concerns against current health and release evidence."
                ),
                "explainability": _explainability(record, reasoning, confidence=confidence_for_record(record)),
            }
        )

    return {
        **_source_context(data, generated_for="report_narrative_signals"),
        "as_of_date": sources["as_of_date"],
        "included_signals": include_signals,
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-severity_value(str(item["severity"])), item["podling"].casefold()),
        ),
    }


def tool_cross_source_mismatches(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25
    include_signals = optional_list_of_choices(arguments, "include_signals", CROSS_SOURCE_MISMATCH_SIGNALS)

    items = []
    for record in records:
        mismatches = cross_source_mismatches(record)
        if include_signals:
            mismatches = [mismatch for mismatch in mismatches if mismatch["signal"] in include_signals]
        if not mismatches:
            continue
        latest_report_period = record.incubator_reports[-1].get("report_period") if record.incubator_reports else None
        reasoning = [str(mismatch["reason"]) for mismatch in mismatches]
        items.append(
            {
                "podling": record.name,
                "severity": _highest_severity(mismatches),
                "latest_report_period": latest_report_period,
                "report_entry_count": len(record.incubator_reports),
                "mismatches": mismatches,
                "summary": mismatches[0]["reason"],
                "recommended_ipmc_action": (
                    "Review the latest report narrative against current health "
                    "and release evidence before drawing conclusions."
                ),
                "explainability": _explainability(record, reasoning, confidence=confidence_for_record(record)),
            }
        )

    return {
        **_source_context(data, generated_for="cross_source_mismatches"),
        "as_of_date": sources["as_of_date"],
        "included_signals": include_signals,
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: (-severity_value(str(item["severity"])), item["podling"].casefold()),
        ),
    }


def tool_stalled_podlings(arguments: dict[str, Any]) -> dict[str, Any]:
    sources, data, records, _ = _load_tool_records(arguments)
    limit = optional_integer(arguments, "limit") or 25

    items = []
    for record in records:
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

    return {
        **_source_context(data, generated_for="stalled_podlings"),
        "as_of_date": sources["as_of_date"],
        "items": _limit_sorted_items(
            items,
            limit=limit,
            sort_key=lambda item: item["podling"].casefold(),
        ),
    }


def _grouping_bucket(
    *,
    names: list[str],
    include_examples: bool,
) -> dict[str, Any]:
    bucket: dict[str, Any] = {"count": len(names)}
    if include_examples:
        bucket["example_podlings"] = names[:5]
    return bucket


def _community_summary_grouping(
    records: list[Any],
    evaluations: dict[str, dict[str, Any]],
    *,
    group_by: str,
    include_examples: bool,
) -> dict[str, Any] | None:
    if group_by == "none":
        return None

    if group_by == "risk_band":
        bands: dict[str, list[str]] = {"critical": [], "high": [], "medium": [], "low": []}
        for record in records:
            bands[evaluations[record.name]["severity"]].append(record.name)
        return {
            "group_by": group_by,
            "buckets": {
                band: _grouping_bucket(names=sorted(names), include_examples=include_examples)
                for band, names in bands.items()
            },
        }

    if group_by == "mentor_load":
        mentor_buckets: dict[str, list[str]] = {
            "no_mentors": [],
            "single_mentor": [],
            "two_mentors": [],
            "three_or_more_mentors": [],
        }
        for record in records:
            if record.mentor_count == 0:
                mentor_buckets["no_mentors"].append(record.name)
            elif record.mentor_count == 1:
                mentor_buckets["single_mentor"].append(record.name)
            elif record.mentor_count == 2:
                mentor_buckets["two_mentors"].append(record.name)
            else:
                mentor_buckets["three_or_more_mentors"].append(record.name)
        return {
            "group_by": group_by,
            "buckets": {
                name: _grouping_bucket(names=sorted(names), include_examples=include_examples)
                for name, names in mentor_buckets.items()
            },
        }

    if group_by == "age_band":
        age_buckets: dict[str, list[str]] = {
            "under_12m": [],
            "12_to_35m": [],
            "36m_plus": [],
            "unknown_age": [],
        }
        for record in records:
            months = record.months_in_incubation
            if months is None:
                age_buckets["unknown_age"].append(record.name)
            elif months < 12:
                age_buckets["under_12m"].append(record.name)
            elif months < 36:
                age_buckets["12_to_35m"].append(record.name)
            else:
                age_buckets["36m_plus"].append(record.name)
        return {
            "group_by": group_by,
            "buckets": {
                name: _grouping_bucket(names=sorted(names), include_examples=include_examples)
                for name, names in age_buckets.items()
            },
        }

    return None


def tool_community_health_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    sources = _resolve_sources(arguments)
    scope = optional_choice(arguments, "scope", SCOPES) or "all_podlings"
    group_by = optional_choice(arguments, "group_by", GROUPINGS) or "risk_band"
    include_examples = optional_boolean(arguments, "include_examples", True)

    data = build_records(
        **sources,
        include_mail=False,
        include_non_current=scope == "all_podlings",
    )
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
    evaluations: dict[str, dict[str, Any]] = {}

    for record in records:
        evaluation = evaluate_record(record)
        evaluations[record.name] = evaluation
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
    if scope == "all_podlings":
        overall_summary += " This scope includes non-current podlings when they are present in the source data."
    elif scope == "reporting_podlings":
        overall_summary += " This scope is limited to podlings with apache-health report data."

    if group_by == "mentor_load":
        overall_summary += " Results are especially useful for reviewing mentoring capacity."
    elif group_by == "age_band":
        overall_summary += " Older podlings may warrant additional graduation or intervention discussion."
    elif group_by == "risk_band":
        overall_summary += " Results are also grouped by evaluated risk severity."

    grouping = _community_summary_grouping(
        records,
        evaluations,
        group_by=group_by,
        include_examples=bool(include_examples),
    )

    return {
        **_source_context(data, generated_for="community_health_summary"),
        "scope": scope,
        "group_by": group_by,
        "overall_summary": overall_summary,
        "strong_patterns": strong_patterns,
        "risk_themes": risk_themes,
        "improving_podlings": sorted(improving_podlings),
        "watchlist_overlap": sorted(watchlist_overlap),
        "mentoring_capacity_observations": mentoring_capacity_observations,
        "grouping": grouping,
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


TOOLS: dict[str, dict[str, Any]] = {
    "configure_sources": schemas.tool_definition(
        description=(
            "Set or inspect process-level source defaults so later IPMC tool calls can omit source override arguments."
        ),
        handler=tool_configure_sources,
        properties=schemas.source_defaults_properties(),
    ),
    "current_podlings_overview": schemas.tool_definition(
        description=("Return a factual overview of current Incubator podlings from podlings.xml lifecycle metadata."),
        handler=tool_current_podlings_overview,
        properties=schemas.current_podlings_overview_properties(),
    ),
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
    "release_vote_evidence": schemas.tool_definition(
        description=(
            "Return MailMCP release vote/result thread evidence for one podling alongside "
            "IPMC release visibility signals."
        ),
        handler=tool_release_vote_evidence,
        properties=schemas.release_vote_evidence_properties(),
        required=["podling"],
    ),
    "release_artifact_evidence": schemas.tool_definition(
        description=("Return ReleaseMCP artifact, sidecar, cadence, and Incubator naming evidence for one podling."),
        handler=tool_release_artifact_evidence,
        properties=schemas.release_artifact_evidence_properties(),
        required=["podling"],
    ),
    "refresh_report_cache": schemas.tool_definition(
        description="Refresh cached ASF Incubator report data used by IPMC report-narrative tools.",
        handler=tool_refresh_report_cache,
        properties=schemas.report_cache_properties(),
    ),
    "refresh_mail_cache": schemas.tool_definition(
        description="Refresh cached general@incubator.apache.org message summaries used by IPMC mail evidence tools.",
        handler=tool_refresh_mail_cache,
        properties=schemas.mail_cache_properties(),
    ),
    "reporting_cohort": schemas.tool_definition(
        description=(
            "Return current reporting podlings grouped into non-ranked IPMC review buckets: "
            "reporting issues, release visibility issues, recent significant changes, and no obvious concerns."
        ),
        handler=tool_reporting_cohort,
        properties=schemas.reporting_cohort_properties(),
    ),
    "report_narrative_signals": schemas.tool_definition(
        description=(
            "Return report-derived narrative signals such as latest reported issues, recurring issues, "
            "low observed mentor sign-off, and release visibility mismatches."
        ),
        handler=tool_report_narrative_signals,
        properties=schemas.report_narrative_signals_properties(),
    ),
    "cross_source_mismatches": schemas.tool_definition(
        description=(
            "Return concrete mismatches between cached report narrative and current health or release evidence."
        ),
        handler=tool_cross_source_mismatches,
        properties=schemas.cross_source_mismatches_properties(),
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
