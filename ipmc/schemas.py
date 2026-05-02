from __future__ import annotations

from typing import Any

PODLINGS_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional HTTPS URL or local path for PodlingsMCP source data",
}
HEALTH_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional local path for apache-health report Markdown files",
}
REPORT_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional local path for ReportMCP cached ASF Incubator report files",
}
MAIL_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional local path for MailMCP cached ASF Incubator general-list message files",
}
MAIL_API_BASE_PROPERTY = {
    "type": "string",
    "description": "Optional MailMCP/Pony Mail API base URL for live Incubator general-list release evidence",
}
MAIL_TIMESPAN_PROPERTY = {
    "type": "string",
    "description": "Optional MailMCP timespan expression for live Incubator general-list release evidence",
}
RELEASE_DIST_BASE_PROPERTY = {
    "type": "string",
    "description": "Optional ReleaseMCP dist.apache.org base URL or local release directory",
}
RELEASE_ARCHIVE_BASE_PROPERTY = {
    "type": "string",
    "description": "Optional ReleaseMCP archive.apache.org base URL or local archive directory",
}
RELEASE_MAX_DEPTH_PROPERTY = {
    "type": "integer",
    "description": "Maximum ReleaseMCP traversal depth under the podling directory; defaults to 1",
}
AS_OF_DATE_PROPERTY = {
    "type": "string",
    "description": "Optional YYYY-MM-DD date to evaluate data as of a specific day",
}
REPORT_MONTH_PROPERTY = {
    "type": "string",
    "description": "Optional reporting month in YYYY-MM format",
}
LIMIT_PROPERTY = {
    "type": "integer",
    "description": "Optional maximum number of results to return",
}
YEARS_PROPERTY = {
    "type": "integer",
    "description": "Optional number of years of report history to cache",
}
FULL_HISTORY_PROPERTY = {
    "type": "boolean",
    "description": "Whether to cache full report history instead of a bounded recent window",
}
PODLING_PROPERTY = {
    "type": "string",
    "description": "Podling name",
}
SEVERITY_PROPERTY = {
    "type": "string",
    "description": "Optional minimum severity filter: low, medium, high, or critical",
}
URGENCY_PROPERTY = {
    "type": "string",
    "description": "Optional minimum urgency filter: low, medium, high, or critical",
}
FOCUS_ITEMS_PROPERTY = {
    "type": "array",
    "description": "Optional focus areas such as status, health, reporting, mentoring, releases, graduation, or risk",
    "items": {
        "type": "string",
        "enum": ["status", "health", "reporting", "mentoring", "releases", "graduation", "risk"],
    },
}


def input_schema(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def tool_definition(
    *,
    description: str,
    handler: Any,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "inputSchema": input_schema(properties, required=required),
        "handler": handler,
    }


def base_properties() -> dict[str, Any]:
    return {
        "podlings_source": PODLINGS_SOURCE_PROPERTY,
        "health_source": HEALTH_SOURCE_PROPERTY,
        "report_source": REPORT_SOURCE_PROPERTY,
        "mail_source": MAIL_SOURCE_PROPERTY,
        "mail_api_base": MAIL_API_BASE_PROPERTY,
        "as_of_date": AS_OF_DATE_PROPERTY,
    }


def source_defaults_properties() -> dict[str, Any]:
    return {
        "podlings_source": PODLINGS_SOURCE_PROPERTY,
        "health_source": HEALTH_SOURCE_PROPERTY,
        "report_source": REPORT_SOURCE_PROPERTY,
        "mail_source": MAIL_SOURCE_PROPERTY,
        "mail_api_base": MAIL_API_BASE_PROPERTY,
        "release_dist_base": RELEASE_DIST_BASE_PROPERTY,
        "release_archive_base": RELEASE_ARCHIVE_BASE_PROPERTY,
    }


def current_podlings_overview_properties() -> dict[str, Any]:
    return {
        "podlings_source": PODLINGS_SOURCE_PROPERTY,
        "as_of_date": AS_OF_DATE_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_descriptions": {
            "type": "boolean",
            "description": "Whether to include podling descriptions in each item; defaults to true",
        },
    }


def watchlist_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "limit": LIMIT_PROPERTY,
        "severity_at_least": SEVERITY_PROPERTY,
        "include_reasons": {
            "type": "array",
            "description": "Optional watchlist reason filters",
            "items": {"type": "string"},
        },
    }


def recent_changes_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
    }


def significant_changes_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_signals": {
            "type": "array",
            "description": "Optional significant-change signal filters",
            "items": {
                "type": "string",
                "enum": [
                    "crossed_12m_without_release",
                    "meaningful_activity_shift",
                    "reports_newly_missing",
                    "releases_disappeared",
                ],
            },
        },
    }


def reporting_gaps_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_gaps": {
            "type": "array",
            "description": "Optional reporting gap filters",
            "items": {
                "type": "string",
                "enum": [
                    "missing_health_report",
                    "missing_recent_reports",
                    "newly_missing_reports",
                    "inconsistent_reporting_pattern",
                    "reporting_metric_missing",
                ],
            },
        },
    }


def reporting_reliability_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_categories": {
            "type": "array",
            "description": "Optional reporting reliability category filters",
            "items": {
                "type": "string",
                "enum": [
                    "consistently_on_time",
                    "occasional_late",
                    "repeated_late",
                    "repeated_missing",
                    "reporting_data_unavailable",
                ],
            },
        },
    }


def reporting_schedule_properties() -> dict[str, Any]:
    return {
        "podlings_source": PODLINGS_SOURCE_PROPERTY,
        "podling": PODLING_PROPERTY,
        "as_of_date": AS_OF_DATE_PROPERTY,
        "report_month": REPORT_MONTH_PROPERTY,
        "due_this_month": {
            "type": "boolean",
            "description": "Optional filter to keep only podlings due in the selected report month",
        },
        "limit": LIMIT_PROPERTY,
    }


def release_visibility_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_signals": {
            "type": "array",
            "description": "Optional release visibility signal filters",
            "items": {
                "type": "string",
                "enum": [
                    "no_releases_12m",
                    "long_release_gap",
                    "high_activity_no_releases",
                    "contributors_no_releases",
                    "release_visibility_unknown",
                ],
            },
        },
    }


def release_vote_evidence_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "mail_api_base": MAIL_API_BASE_PROPERTY,
        "mail_timespan": MAIL_TIMESPAN_PROPERTY,
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
    }


def release_artifact_evidence_properties() -> dict[str, Any]:
    return {
        "release_dist_base": RELEASE_DIST_BASE_PROPERTY,
        "release_archive_base": RELEASE_ARCHIVE_BASE_PROPERTY,
        "release_max_depth": RELEASE_MAX_DEPTH_PROPERTY,
        "podling": PODLING_PROPERTY,
    }


def report_cache_properties() -> dict[str, Any]:
    return {
        "report_source": REPORT_SOURCE_PROPERTY,
        "years": YEARS_PROPERTY,
        "full_history": FULL_HISTORY_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "report_url": {
            "type": "string",
            "description": "Optional single Incubator report URL to cache instead of refreshing recent reports",
        },
        "report_id": {
            "type": "string",
            "description": "Optional report id to use when caching a single report URL",
        },
    }


def mail_cache_properties() -> dict[str, Any]:
    return {
        "mail_source": MAIL_SOURCE_PROPERTY,
        "mail_api_base": MAIL_API_BASE_PROPERTY,
        "mail_timespan": MAIL_TIMESPAN_PROPERTY,
        "query": {
            "type": "string",
            "description": "Optional general-list search query to cache",
        },
        "limit": LIMIT_PROPERTY,
    }


def reporting_cohort_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
    }


def report_narrative_signals_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_signals": {
            "type": "array",
            "description": "Optional report narrative signal filters",
            "items": {
                "type": "string",
                "enum": [
                    "latest_reported_issues",
                    "recurring_reported_issue",
                    "possible_report_copy_forward",
                    "low_observed_mentor_signoff",
                    "report_release_visibility_mismatch",
                ],
            },
        },
    }


def cross_source_mismatches_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
        "limit": LIMIT_PROPERTY,
        "include_signals": {
            "type": "array",
            "description": "Optional cross-source mismatch filters",
            "items": {
                "type": "string",
                "enum": [
                    "report_release_visibility_mismatch",
                    "quiet_report_high_risk_mismatch",
                    "latest_signoff_drop_vs_average",
                ],
            },
        },
    }


def stalled_podlings_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "limit": LIMIT_PROPERTY,
    }


def podling_lookup_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "podling": PODLING_PROPERTY,
    }


def readiness_properties() -> dict[str, Any]:
    return {
        **podling_lookup_properties(),
        "include_evidence": {
            "type": "boolean",
            "description": "Whether to include supporting evidence in the readiness assessment",
        },
        "strict_mode": {
            "type": "boolean",
            "description": "Whether to use a more conservative readiness interpretation",
        },
    }


def brief_properties() -> dict[str, Any]:
    return {
        **podling_lookup_properties(),
        "focus": {
            **FOCUS_ITEMS_PROPERTY,
        },
        "brief_format": {
            "type": "string",
            "description": "Optional output density: summary or detailed",
            "enum": ["summary", "detailed"],
        },
    }


def mentoring_attention_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "limit": LIMIT_PROPERTY,
        "urgency_at_least": URGENCY_PROPERTY,
        "include_causes": {
            "type": "array",
            "description": "Optional mentoring concern filters",
            "items": {
                "type": "string",
                "enum": [
                    "missing_mentors",
                    "inactive_mentors",
                    "missed_reports",
                    "weak_releases",
                    "community_stall",
                    "low_signoffs",
                ],
            },
        },
    }


def community_summary_properties() -> dict[str, Any]:
    return {
        **base_properties(),
        "scope": {
            "type": "string",
            "description": "Optional scope filter such as all_podlings, active_podlings, or reporting_podlings",
            "enum": ["all_podlings", "active_podlings", "reporting_podlings"],
        },
        "group_by": {
            "type": "string",
            "description": "Optional grouping such as none, risk_band, mentor_load, or age_band",
            "enum": ["none", "risk_band", "mentor_load", "age_band"],
        },
        "include_examples": {
            "type": "boolean",
            "description": "Whether to include example podlings for patterns and themes",
        },
    }
