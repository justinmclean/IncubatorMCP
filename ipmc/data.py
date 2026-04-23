"""Data loading and composition helpers for the IPMC oversight MCP server."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from apache_health_mcp import parser as health_parser
from podlings import data as podlings_data

try:
    from apache_incubator_reports_mcp import parser as incubator_report_parser  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when optional source package is absent locally
    incubator_report_parser = None  # type: ignore[assignment]

try:
    from apache_incubator_mail_mcp import client as incubator_mail_client  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when optional source package is absent locally
    incubator_mail_client = None  # type: ignore[assignment]

DEFAULT_HEALTH_SOURCE = "reports"
DEFAULT_REPORT_SOURCE = ".cache/incubator-reports"
DEFAULT_MAIL_SOURCE = ".cache/incubator-general-mail"
DEFAULT_MAIL_API_BASE = "https://lists.apache.org/api"
DEFAULT_MAIL_SEARCH_TIMESPAN = "lte=12M"
DEFAULT_MAIL_QUERY_LIMIT = 20
PODLINGS_SOURCE_ENV = "IPMC_PODLINGS_SOURCE"
HEALTH_SOURCE_ENV = "IPMC_HEALTH_SOURCE"
REPORT_SOURCE_ENV = "IPMC_REPORT_SOURCE"
MAIL_SOURCE_ENV = "IPMC_MAIL_SOURCE"
MAIL_API_BASE_ENV = "IPMC_MAIL_API_BASE"
_CONFIGURED_PODLINGS_SOURCE: str | None = None
_CONFIGURED_HEALTH_SOURCE: str | None = None
_CONFIGURED_REPORT_SOURCE: str | None = None
_CONFIGURED_MAIL_SOURCE: str | None = None
_CONFIGURED_MAIL_API_BASE: str | None = None

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
    podlings_source: str | None = None,
    podlings_repo: str | None = None,
    health_repo: str | None = None,
    health_source: str | None = None,
    report_source: str | None = None,
    reports_source: str | None = None,
    mail_source: str | None = None,
    mail_cache_dir: str | None = None,
    mail_api_base: str | None = None,
) -> None:
    global _CONFIGURED_HEALTH_SOURCE, _CONFIGURED_MAIL_API_BASE, _CONFIGURED_MAIL_SOURCE, _CONFIGURED_PODLINGS_SOURCE
    global _CONFIGURED_REPORT_SOURCE

    resolved_podlings_source = podlings_source or podlings_repo
    resolved_health_source = health_source or health_repo
    resolved_report_source = report_source or reports_source
    resolved_mail_source = mail_source or mail_cache_dir
    if resolved_podlings_source:
        _CONFIGURED_PODLINGS_SOURCE = resolved_podlings_source
    if resolved_health_source:
        _CONFIGURED_HEALTH_SOURCE = resolved_health_source
    if resolved_report_source:
        _CONFIGURED_REPORT_SOURCE = resolved_report_source
    if resolved_mail_source:
        _CONFIGURED_MAIL_SOURCE = resolved_mail_source
    if mail_api_base:
        _CONFIGURED_MAIL_API_BASE = mail_api_base


def _env_default(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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
    incubator_reports: list[dict[str, Any]] = field(default_factory=list)
    incubator_general_mail: list[dict[str, Any]] = field(default_factory=list)

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


def _normalize_report_source_meta(overview: dict[str, Any], requested_source: str) -> dict[str, Any]:
    meta = dict(overview)
    source = meta.get("source") or meta.get("reports_dir") or requested_source
    meta["source"] = source
    meta.setdefault("reports_dir", source)
    return meta


def _normalize_mail_source_meta(overview: dict[str, Any], requested_source: str) -> dict[str, Any]:
    meta = dict(overview)
    source = meta.get("source") or meta.get("cache_dir") or requested_source
    meta["source"] = source
    meta.setdefault("cache_dir", source)
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
    for metric_field, trend in fallback_trends.items():
        existing_trends.setdefault(metric_field, trend)
    return summary


def load_podlings(podlings_source: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = (
        podlings_source
        or _CONFIGURED_PODLINGS_SOURCE
        or _env_default(PODLINGS_SOURCE_ENV)
        or podlings_data.DEFAULT_SOURCE
    )
    podlings, meta = podlings_data.parse_podlings(source)
    return [asdict(item) for item in podlings], meta


def load_health_summaries(health_source: str | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    reports_dir = health_source or _CONFIGURED_HEALTH_SOURCE or _env_default(HEALTH_SOURCE_ENV) or DEFAULT_HEALTH_SOURCE
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


def _resolved_report_source(report_source: str | None = None) -> tuple[str, bool]:
    explicit = report_source or _CONFIGURED_REPORT_SOURCE or _env_default(REPORT_SOURCE_ENV)
    return explicit or DEFAULT_REPORT_SOURCE, explicit is not None


def _resolved_mail_source(mail_source: str | None = None) -> tuple[str, bool]:
    explicit = mail_source or _CONFIGURED_MAIL_SOURCE or _env_default(MAIL_SOURCE_ENV)
    return explicit or DEFAULT_MAIL_SOURCE, explicit is not None


def _resolved_mail_api_base(mail_api_base: str | None = None) -> str:
    return mail_api_base or _CONFIGURED_MAIL_API_BASE or _env_default(MAIL_API_BASE_ENV) or DEFAULT_MAIL_API_BASE


def load_incubator_reports(report_source: str | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    reports_dir, explicit = _resolved_report_source(report_source)
    if incubator_report_parser is None:
        return (
            {},
            {
                "source": reports_dir,
                "reports_dir": reports_dir,
                "report_count": 0,
                "podling_count": 0,
                "available": False,
                "reason": "apache-incubator-reports-mcp is not installed.",
            },
        )

    if not Path(reports_dir).expanduser().exists():
        if explicit:
            raise FileNotFoundError(f"ReportMCP source path does not exist: {reports_dir}")
        return (
            {},
            {
                "source": reports_dir,
                "reports_dir": reports_dir,
                "report_count": 0,
                "podling_count": 0,
                "available": False,
                "reason": "Default ReportMCP cache directory does not exist.",
            },
        )

    reports = incubator_report_parser.load_reports(reports_dir)
    overview = incubator_report_parser.reports_overview(reports_dir)
    by_podling: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        for item in report.podling_reports:
            entry = item.to_dict(include_body=False)
            entry.update(
                {
                    "report_id": report.report_id,
                    "report_period": report.report_period,
                    "title": report.title,
                    "path": report.path,
                    "source_url": report.source_url,
                    "cached_at": report.cached_at,
                }
            )
            by_podling.setdefault(item.podling.casefold(), []).append(entry)

    for entries in by_podling.values():
        entries.sort(key=lambda row: row.get("report_period") or "")
    meta = _normalize_report_source_meta(overview, reports_dir)
    meta["available"] = True
    return by_podling, meta


def _mail_matches_podling(message: dict[str, Any], podling_name: str) -> bool:
    needle = podling_name.casefold()
    haystack = "\n".join(
        str(message.get(field, "")) for field in ("subject", "from", "message_id", "id", "thread_id")
    ).casefold()
    return needle in haystack


def _mail_unavailable_meta(source: str, reason: str, *, api_base: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source": source,
        "cache_dir": source,
        "message_count": 0,
        "podling_count": 0,
        "available": False,
        "reason": reason,
    }
    if api_base:
        meta["api_base"] = api_base
    return meta


def _load_live_incubator_general_mail(
    podlings: list[dict[str, Any]] | None,
    *,
    api_base: str,
    timespan: str = DEFAULT_MAIL_SEARCH_TIMESPAN,
    limit: int = DEFAULT_MAIL_QUERY_LIMIT,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    fetcher = getattr(incubator_mail_client, "fetch_mail_stats", None)
    if fetcher is None:
        return (
            {},
            _mail_unavailable_meta(
                api_base,
                "Installed MailMCP does not provide fetch_mail_stats for live general-list search.",
                api_base=api_base,
            ),
        )

    by_podling: dict[str, list[dict[str, Any]]] = {}
    message_count = 0
    for podling in podlings or []:
        podling_name = str(podling.get("name", ""))
        if not podling_name:
            continue
        result = fetcher(
            api_base=api_base,
            timespan=timespan,
            query=podling_name,
            limit=limit,
        )
        messages = [message for message in result.get("emails", []) if _mail_matches_podling(message, podling_name)]
        if messages:
            by_podling[podling_name.casefold()] = messages
            message_count += len(messages)

    return (
        by_podling,
        {
            "source": api_base,
            "cache_dir": None,
            "api_base": api_base,
            "timespan": timespan,
            "mode": "live",
            "message_count": message_count,
            "podling_count": len(by_podling),
            "available": True,
        },
    )


def load_incubator_general_mail(
    mail_source: str | None = None,
    podlings: list[dict[str, Any]] | None = None,
    *,
    mail_api_base: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    cache_dir, explicit = _resolved_mail_source(mail_source)
    api_base = _resolved_mail_api_base(mail_api_base)
    if incubator_mail_client is None:
        return (
            {},
            _mail_unavailable_meta(cache_dir, "apache-incubator-mail-mcp is not installed.", api_base=api_base),
        )

    if not Path(cache_dir).expanduser().exists():
        if explicit:
            raise FileNotFoundError(f"MailMCP source path does not exist: {cache_dir}")
        try:
            live_mail, live_meta = _load_live_incubator_general_mail(podlings, api_base=api_base)
        except Exception as exc:
            return (
                {},
                _mail_unavailable_meta(
                    api_base,
                    f"Default MailMCP cache directory does not exist and live MailMCP search failed: {exc}",
                    api_base=api_base,
                ),
            )
        live_meta["fallback_reason"] = "Default MailMCP cache directory does not exist."
        return live_mail, live_meta

    cached = incubator_mail_client.load_cached_mail(cache_dir=cache_dir)
    messages = cached.get("emails") or []
    by_podling: dict[str, list[dict[str, Any]]] = {}
    for podling in podlings or []:
        podling_name = str(podling.get("name", ""))
        if not podling_name:
            continue
        matches = [message for message in messages if _mail_matches_podling(message, podling_name)]
        if matches:
            by_podling[podling_name.casefold()] = matches

    meta = _normalize_mail_source_meta(cached, cache_dir)
    meta["message_count"] = cached.get("count", len(messages))
    meta["podling_count"] = len(by_podling)
    meta["available"] = True
    return by_podling, meta


def load_podling_release_vote_history(
    podling: str,
    *,
    mail_api_base: str | None = None,
    timespan: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    api_base = _resolved_mail_api_base(mail_api_base)
    resolved_timespan = timespan or DEFAULT_MAIL_SEARCH_TIMESPAN
    unavailable = {
        "podling": podling,
        "source": "apache-incubator-mail",
        "api_base": api_base,
        "timespan": resolved_timespan,
        "available": False,
        "vote_count": 0,
        "result_count": 0,
        "votes": [],
        "results": [],
    }
    if incubator_mail_client is None:
        return unavailable | {"reason": "apache-incubator-mail-mcp is not installed."}

    history_loader = getattr(incubator_mail_client, "podling_release_vote_history", None)
    if history_loader is None:
        return unavailable | {"reason": "Installed MailMCP does not provide podling_release_vote_history."}

    history = history_loader(
        podling=podling,
        api_base=api_base,
        timespan=resolved_timespan,
        limit=limit,
    )
    history.setdefault("podling", podling)
    history.setdefault("timespan", resolved_timespan)
    history["source"] = "apache-incubator-mail"
    history["api_base"] = api_base
    history["available"] = True
    history.setdefault("vote_count", len(history.get("votes") or []))
    history.setdefault("result_count", len(history.get("results") or []))
    history.setdefault("votes", [])
    history.setdefault("results", [])
    return history


def build_records(
    *,
    podlings_source: str | None = None,
    health_source: str | None = None,
    report_source: str | None = None,
    mail_source: str | None = None,
    mail_api_base: str | None = None,
    as_of_date: str | None = None,
    include_non_current: bool = False,
) -> dict[str, Any]:
    podlings, podlings_meta = load_podlings(podlings_source)
    summaries, health_meta = load_health_summaries(health_source)
    report_entries, report_meta = load_incubator_reports(report_source)
    mail_entries, mail_meta = load_incubator_general_mail(mail_source, podlings, mail_api_base=mail_api_base)

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
                incubator_reports=report_entries.get(str(podling.get("name", "")).casefold(), []),
                incubator_general_mail=mail_entries.get(str(podling.get("name", "")).casefold(), []),
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
        "report_source": report_meta,
        "mail_source": mail_meta,
    }
