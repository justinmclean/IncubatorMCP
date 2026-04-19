"""Data loading and composition helpers for the IPMC oversight MCP server."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from apache_health_mcp import parser as health_parser
from podlings import data as podlings_data

DEFAULT_HEALTH_SOURCE = "reports"
_CONFIGURED_HEALTH_SOURCE: str | None = None

PREFERRED_WINDOW_ORDER = ("3m", "6m", "12m", "to-date")
REPORTING_WINDOW_ORDER = ("12m", "6m", "to-date", "3m")
TREND_FIELD_LABELS = {
    "Releases (from list votes/results)": "releases",
    "Unique committers": "unique_committers",
    "Commits": "commits",
}
TREND_SECTION_RE = re.compile(r"^## Trends \(short vs medium\)\s*(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
TREND_LINE_RE = re.compile(r"^-\s+\*\*(?P<label>[^*]+):\*\*.*\((?P<trend>[^)]*)\)\s*$", re.MULTILINE)


def configure_defaults(
    *,
    podlings_repo: str | None = None,
    health_repo: str | None = None,
    health_source: str | None = None,
) -> None:
    global _CONFIGURED_HEALTH_SOURCE

    _ = podlings_repo, health_repo
    if health_source:
        _CONFIGURED_HEALTH_SOURCE = health_source


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def months_since(start_date: str | None, as_of_date: str | None = None) -> int | None:
    start = parse_iso_date(start_date)
    end = parse_iso_date(as_of_date) if as_of_date else date.today()
    if start is None or end is None or end < start:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


@dataclass
class OversightRecord:
    podling: dict[str, Any]
    report_summary: dict[str, Any] | None
    preferred_window: str | None
    preferred_metrics: dict[str, Any] | None
    reporting_window: str | None
    reporting_metrics: dict[str, Any] | None
    as_of_date: str | None

    @property
    def name(self) -> str:
        return str(self.podling.get("name", ""))

    @property
    def status(self) -> str:
        return str(self.podling.get("status") or "unknown").lower()

    @property
    def mentor_count(self) -> int:
        mentors = self.podling.get("mentors") or []
        return len(mentors)

    @property
    def months_in_incubation(self) -> int | None:
        return months_since(self.podling.get("startdate"), self.as_of_date)


def _select_window(
    summary: dict[str, Any] | None,
    window_order: tuple[str, ...],
) -> tuple[str | None, dict[str, Any] | None]:
    if not summary:
        return None, None
    latest_metrics = summary.get("latest_metrics") or {}
    for window in window_order:
        metrics = latest_metrics.get(window)
        if metrics:
            return window, metrics
    return None, None


def _preferred_window(summary: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    return _select_window(summary, PREFERRED_WINDOW_ORDER)


def _reporting_window(summary: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    return _select_window(summary, REPORTING_WINDOW_ORDER)


def _normalize_health_source_meta(overview: dict[str, Any], requested_source: str) -> dict[str, Any]:
    meta = dict(overview)
    source = meta.get("source") or meta.get("reports_dir") or requested_source
    meta["source"] = source
    meta.setdefault("reports_dir", source)
    return meta


def _trend_label(value: str) -> str | None:
    stripped = value.strip()
    if not stripped or stripped == "—":
        return None
    if stripped.startswith(("↗", "↑", "▲")):
        return "up"
    if stripped.startswith(("↘", "↓", "▼")):
        return "down"
    if stripped.startswith(("→", "↔", "▶", "◀")):
        return "flat"
    return "mixed"


def _fallback_trends_from_report_text(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    match = TREND_SECTION_RE.search(text)
    if not match:
        return {}

    trends: dict[str, str] = {}
    for line in TREND_LINE_RE.finditer(match.group(1)):
        field = TREND_FIELD_LABELS.get(line.group("label").strip())
        trend = _trend_label(line.group("trend"))
        if field and trend:
            trends[field] = trend
    return trends


def _with_fallback_trends(summary: dict[str, Any], raw_text: str | None) -> dict[str, Any]:
    fallback_trends = _fallback_trends_from_report_text(raw_text)
    if not fallback_trends:
        return summary

    latest_metrics = summary.get("latest_metrics") or {}
    short_metrics = latest_metrics.get("3m")
    if not isinstance(short_metrics, dict):
        return summary

    existing_trends = short_metrics.get("trends")
    if not isinstance(existing_trends, dict):
        existing_trends = {}
        short_metrics["trends"] = existing_trends
    for field, trend in fallback_trends.items():
        existing_trends.setdefault(field, trend)
    return summary


def load_podlings(podlings_source: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = podlings_source or podlings_data.DEFAULT_SOURCE
    podlings, meta = podlings_data.parse_podlings(source)
    return [asdict(item) for item in podlings], meta


def load_health_summaries(health_source: str | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    reports_dir = health_source or _CONFIGURED_HEALTH_SOURCE or DEFAULT_HEALTH_SOURCE
    overview = health_parser.reports_overview(reports_dir)
    reports = health_parser.load_reports(reports_dir)
    summaries = {
        report.podling.casefold(): _with_fallback_trends(
            health_parser.summarize_report(report),
            getattr(report, "raw_text", None),
        )
        for report in reports
    }
    return summaries, _normalize_health_source_meta(overview, reports_dir)


def build_records(
    *,
    podlings_source: str | None = None,
    health_source: str | None = None,
    as_of_date: str | None = None,
    include_non_current: bool = False,
) -> dict[str, Any]:
    podlings, podlings_meta = load_podlings(podlings_source)
    summaries, health_meta = load_health_summaries(health_source)

    records: list[OversightRecord] = []
    for podling in podlings:
        status = str(podling.get("status") or "unknown").lower()
        if not include_non_current and status != "current":
            continue
        summary = summaries.get(str(podling.get("name", "")).casefold())
        preferred_window, preferred_metrics = _preferred_window(summary)
        reporting_window, reporting_metrics = _reporting_window(summary)
        records.append(
            OversightRecord(
                podling=podling,
                report_summary=summary,
                preferred_window=preferred_window,
                preferred_metrics=preferred_metrics,
                reporting_window=reporting_window,
                reporting_metrics=reporting_metrics,
                as_of_date=as_of_date,
            )
        )

    return {
        "records": sorted(records, key=lambda item: item.name.casefold()),
        "podlings_source": podlings_meta,
        "health_source": health_meta,
    }
