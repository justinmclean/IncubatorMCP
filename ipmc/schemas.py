from __future__ import annotations

from typing import Any

PODLINGS_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional HTTPS URL or local path for PodlingsMCP source data",
}
HEALTH_SOURCE_PROPERTY = {
    "type": "string",
    "description": "Optional local path or source identifier for apache-health data",
}
AS_OF_DATE_PROPERTY = {
    "type": "string",
    "description": "Optional YYYY-MM-DD date to evaluate data as of a specific day",
}
LIMIT_PROPERTY = {
    "type": "integer",
    "description": "Optional maximum number of results to return",
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
        "as_of_date": AS_OF_DATE_PROPERTY,
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
                    "governance_confusion",
                    "community_stall",
                    "mentor_overload",
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
