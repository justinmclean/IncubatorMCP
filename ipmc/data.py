"""Data loading and composition helpers for the IPMC oversight MCP server."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from apache_health_mcp import parser as health_parser
from podlings import data as podlings_data
from podlings import tools as podlings_tools

try:
    from apache_incubator_reports_mcp import parser as incubator_report_parser  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when optional source package is absent locally
    incubator_report_parser = None  # type: ignore[assignment]

try:
    from apache_incubator_mail_mcp import client as incubator_mail_client  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when optional source package is absent locally
    incubator_mail_client = None  # type: ignore[assignment]

try:
    from apache_incubator_releases_mcp import releases as incubator_releases  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when optional source package is absent locally
    incubator_releases = None  # type: ignore[assignment]

DEFAULT_HEALTH_SOURCE = "reports"
DEFAULT_REPORT_SOURCE = ".cache/incubator-reports"
DEFAULT_MAIL_SOURCE = ".cache/incubator-general-mail"
DEFAULT_MAIL_API_BASE = "https://lists.apache.org/api"
DEFAULT_MAIL_SEARCH_TIMESPAN = "lte=12M"
DEFAULT_MAIL_QUERY_LIMIT = 20
DEFAULT_RELEASE_DIST_BASE = "https://dist.apache.org/repos/dist/release/incubator"
DEFAULT_RELEASE_ARCHIVE_BASE = "https://archive.apache.org/dist/incubator"
RELEASE_PAGE_LINK_LIMIT = 50
PODLINGS_SOURCE_ENV = "IPMC_PODLINGS_SOURCE"
HEALTH_SOURCE_ENV = "IPMC_HEALTH_SOURCE"
REPORT_SOURCE_ENV = "IPMC_REPORT_SOURCE"
MAIL_SOURCE_ENV = "IPMC_MAIL_SOURCE"
MAIL_API_BASE_ENV = "IPMC_MAIL_API_BASE"
RELEASE_DIST_BASE_ENV = "IPMC_RELEASE_DIST_BASE"
RELEASE_ARCHIVE_BASE_ENV = "IPMC_RELEASE_ARCHIVE_BASE"


@dataclass
class SourceDefaults:
    podlings_source: str | None = None
    health_source: str | None = None
    report_source: str | None = None
    mail_source: str | None = None
    mail_api_base: str | None = None
    release_dist_base: str | None = None
    release_archive_base: str | None = None


_CONFIGURED_DEFAULTS = SourceDefaults()
_RELEASE_PAGE_CHECK_PATCH_LOCK = threading.Lock()

PREFERRED_WINDOW_ORDER = ("3m", "6m", "12m", "to-date")
REPORTING_WINDOW_ORDER = ("12m", "6m", "to-date", "3m")
TREND_FIELD_LABELS = {
    "Releases (from list votes/results)": "releases",
    "Unique committers": "unique_committers",
    "Commits": "commits",
}
TREND_SECTION_RE = re.compile(r"^## Trends \(short vs medium\)\s*(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
TREND_LINE_RE = re.compile(r"^-\s+\*\*(?P<label>[^*]+):\*\*.*\((?P<trend>[^)]*)\)\s*$", re.MULTILINE)
PODLING_KEY_RE = re.compile(r"[^a-z0-9]+")


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
    release_dist_base: str | None = None,
    release_archive_base: str | None = None,
) -> None:
    resolved_podlings_source = podlings_source or podlings_repo
    resolved_health_source = health_source or health_repo
    resolved_report_source = report_source or reports_source
    resolved_mail_source = mail_source or mail_cache_dir
    if resolved_podlings_source:
        _CONFIGURED_DEFAULTS.podlings_source = resolved_podlings_source
    if resolved_health_source:
        _CONFIGURED_DEFAULTS.health_source = resolved_health_source
    if resolved_report_source:
        _CONFIGURED_DEFAULTS.report_source = resolved_report_source
    if resolved_mail_source:
        _CONFIGURED_DEFAULTS.mail_source = resolved_mail_source
    if mail_api_base:
        _CONFIGURED_DEFAULTS.mail_api_base = mail_api_base
    if release_dist_base:
        _CONFIGURED_DEFAULTS.release_dist_base = release_dist_base
    if release_archive_base:
        _CONFIGURED_DEFAULTS.release_archive_base = release_archive_base


def configured_defaults_snapshot() -> SourceDefaults:
    return SourceDefaults(**asdict(_CONFIGURED_DEFAULTS))


def restore_configured_defaults(snapshot: SourceDefaults) -> None:
    global _CONFIGURED_DEFAULTS
    _CONFIGURED_DEFAULTS = SourceDefaults(**asdict(snapshot))


def _env_default(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _podling_key(name: str) -> str:
    return PODLING_KEY_RE.sub("", name.casefold())


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
    meta.pop("emails", None)
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
        or _CONFIGURED_DEFAULTS.podlings_source
        or _env_default(PODLINGS_SOURCE_ENV)
        or podlings_data.DEFAULT_SOURCE
    )
    podlings, meta = podlings_data.parse_podlings(source)
    return [asdict(item) for item in podlings], meta


def _resolved_podlings_source(podlings_source: str | None = None) -> str:
    return (
        podlings_source
        or _CONFIGURED_DEFAULTS.podlings_source
        or _env_default(PODLINGS_SOURCE_ENV)
        or podlings_data.DEFAULT_SOURCE
    )


def load_reporting_schedules(
    podlings_source: str | None = None,
    *,
    as_of_date: str | None = None,
    report_month: str | None = None,
    podling: str | None = None,
    due_this_month: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = _resolved_podlings_source(podlings_source)
    schedule_tool = getattr(podlings_tools, "tool_reporting_schedule", None)
    if callable(schedule_tool):
        arguments: dict[str, Any] = {"source": source}
        if as_of_date:
            arguments["as_of_date"] = as_of_date
        if report_month:
            arguments["report_month"] = report_month
        if podling:
            arguments["name"] = podling
        if due_this_month is not None:
            arguments["due_this_month"] = due_this_month
        payload = schedule_tool(arguments)
        meta = dict(payload.get("source") or {})
        meta["report_month"] = payload.get("report_month")
        meta["count"] = payload.get("total_matching", payload.get("returned", 0))
        schedules = [dict(item) for item in payload.get("podlings") or []]
        return schedules, meta

    raise RuntimeError("Installed PodlingsMCP does not provide reporting_schedule.")


def load_health_summaries(health_source: str | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    reports_dir = (
        health_source or _CONFIGURED_DEFAULTS.health_source or _env_default(HEALTH_SOURCE_ENV) or DEFAULT_HEALTH_SOURCE
    )
    overview = health_parser.reports_overview(reports_dir)
    reports = health_parser.load_reports(reports_dir)
    summaries = {
        _podling_key(report.podling): _with_fallback_trends(
            health_parser.summarize_report(report),
            getattr(report, "raw_text", None),
        )
        for report in reports
    }
    return summaries, _normalize_health_source_meta(overview, reports_dir)


def _resolved_report_source(report_source: str | None = None) -> tuple[str, bool]:
    explicit = report_source or _CONFIGURED_DEFAULTS.report_source or _env_default(REPORT_SOURCE_ENV)
    return explicit or DEFAULT_REPORT_SOURCE, explicit is not None


def _resolved_mail_source(mail_source: str | None = None) -> tuple[str, bool]:
    explicit = mail_source or _CONFIGURED_DEFAULTS.mail_source or _env_default(MAIL_SOURCE_ENV)
    return explicit or DEFAULT_MAIL_SOURCE, explicit is not None


def _resolved_mail_api_base(mail_api_base: str | None = None) -> str:
    return (
        mail_api_base or _CONFIGURED_DEFAULTS.mail_api_base or _env_default(MAIL_API_BASE_ENV) or DEFAULT_MAIL_API_BASE
    )


def _resolved_release_dist_base(release_dist_base: str | None = None) -> str | None:
    return release_dist_base or _CONFIGURED_DEFAULTS.release_dist_base or _env_default(RELEASE_DIST_BASE_ENV)


def _resolved_release_archive_base(release_archive_base: str | None = None) -> str:
    return (
        release_archive_base
        or _CONFIGURED_DEFAULTS.release_archive_base
        or _env_default(RELEASE_ARCHIVE_BASE_ENV)
        or DEFAULT_RELEASE_ARCHIVE_BASE
    )


def _not_requested_release_page_checks(podling: str, release_page_url: str, files: list[Any]) -> dict[str, Any]:
    return {
        "location": release_page_url,
        "available": False,
        "links": [],
        "facts": {},
        "hints": [],
        "reason": "Release download page checks were not requested.",
    }


def _limit_release_page_check_links(evidence: dict[str, Any]) -> None:
    checks = evidence.get("release_page_checks")
    if not isinstance(checks, dict):
        return
    links = checks.get("links")
    if not isinstance(links, list) or len(links) <= RELEASE_PAGE_LINK_LIMIT:
        return
    checks["links"] = links[:RELEASE_PAGE_LINK_LIMIT]
    checks["links_truncated"] = True
    checks["link_count_returned"] = RELEASE_PAGE_LINK_LIMIT
    checks["omitted_link_count"] = len(links) - RELEASE_PAGE_LINK_LIMIT


def source_defaults() -> dict[str, Any]:
    report_source, report_explicit = _resolved_report_source()
    mail_source, mail_explicit = _resolved_mail_source()
    return {
        "configured": asdict(_CONFIGURED_DEFAULTS),
        "effective": {
            "podlings_source": (
                _CONFIGURED_DEFAULTS.podlings_source
                or _env_default(PODLINGS_SOURCE_ENV)
                or podlings_data.DEFAULT_SOURCE
            ),
            "health_source": _CONFIGURED_DEFAULTS.health_source
            or _env_default(HEALTH_SOURCE_ENV)
            or DEFAULT_HEALTH_SOURCE,
            "report_source": report_source,
            "report_source_explicit": report_explicit,
            "mail_source": mail_source,
            "mail_source_explicit": mail_explicit,
            "mail_api_base": _resolved_mail_api_base(),
            "release_dist_base": _resolved_release_dist_base(),
            "release_archive_base": _resolved_release_archive_base(),
        },
    }


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
            entry = item.to_dict(include_body=True)
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
            by_podling.setdefault(_podling_key(item.podling), []).append(entry)

    for entries in by_podling.values():
        entries.sort(key=lambda row: row.get("report_period") or "")
    meta = _normalize_report_source_meta(overview, reports_dir)
    meta["available"] = True
    return by_podling, meta


def refresh_incubator_report_cache(
    report_source: str | None = None,
    *,
    years: int | None = 2,
    limit: int | None = None,
    report_url: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    reports_dir, _explicit = _resolved_report_source(report_source)
    if incubator_report_parser is None:
        return {
            "source": reports_dir,
            "reports_dir": reports_dir,
            "available": False,
            "cached": False,
            "reason": "apache-incubator-reports-mcp is not installed.",
        }

    if report_url:
        cache_one = getattr(incubator_report_parser, "cache_report_url")
        result = cache_one(
            report_url,
            cache_dir=reports_dir,
            report_id=report_id,
        )
    else:
        cache_many = getattr(incubator_report_parser, "cache_reports_from_repo")
        result = cache_many(
            cache_dir=reports_dir,
            years=years,
            limit=limit,
        )
        if years is not None:
            result = _filter_report_cache_result_to_years(result, years)
    result.setdefault("source", reports_dir)
    result.setdefault("reports_dir", reports_dir)
    result["available"] = True
    return result


def _report_result_year(value: dict[str, Any]) -> int | None:
    report = value.get("report")
    if isinstance(report, dict):
        period = str(report.get("report_period") or "")
        if re.match(r"^\d{4}-\d{2}$", period):
            return int(period[:4])
        report_id = str(report.get("report_id") or "")
        match = re.search(r"(\d{4})-\d{2}-\d{2}", report_id)
        if match:
            return int(match.group(1))

    url_or_path = "\n".join(str(value.get(field, "")) for field in ("url", "source_url", "path"))
    match = re.search(r"(?:/|_|-)(\d{4})(?:/|_|-)\d{2}(?:_|-)\d{2}", url_or_path)
    if match:
        return int(match.group(1))
    return None


def _filter_report_cache_result_to_years(result: dict[str, Any], years: int) -> dict[str, Any]:
    filtered = dict(result)
    first_year = date.today().year - years + 1

    def in_range(item: dict[str, Any]) -> bool:
        item_year = _report_result_year(item)
        return item_year is None or item_year >= first_year

    cached_reports = filtered.get("cached_reports")
    if isinstance(cached_reports, list):
        filtered["cached_reports"] = [item for item in cached_reports if isinstance(item, dict) and in_range(item)]
        filtered["cached_count"] = len(filtered["cached_reports"])

    errors = filtered.get("errors")
    if isinstance(errors, list):
        filtered["errors"] = [item for item in errors if isinstance(item, dict) and in_range(item)]
        filtered["error_count"] = len(filtered["errors"])

    if "discovered_count" in filtered:
        filtered.setdefault("upstream_discovered_count", filtered["discovered_count"])
        filtered["discovered_count"] = len(filtered.get("cached_reports") or []) + len(filtered.get("errors") or [])

    filtered["filtered_to_years"] = {"years": years, "first_year": first_year}
    return filtered


def _mail_matches_podling(message: dict[str, Any], podling_name: str) -> bool:
    needle = podling_name.casefold()
    haystack = "\n".join(
        str(message.get(field, "")) for field in ("subject", "from", "message_id", "id", "thread_id")
    ).casefold()
    return needle in haystack or _podling_key(podling_name) in _podling_key(haystack)


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
            by_podling[_podling_key(podling_name)] = messages
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
    allow_live_fallback: bool = True,
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
        if not allow_live_fallback:
            return (
                {},
                _mail_unavailable_meta(
                    cache_dir,
                    "Default MailMCP cache directory does not exist.",
                    api_base=api_base,
                ),
            )
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
    if not messages and allow_live_fallback and podlings:
        try:
            live_mail, live_meta = _load_live_incubator_general_mail(podlings, api_base=api_base)
        except Exception as exc:
            meta = _normalize_mail_source_meta(cached, cache_dir)
            meta["message_count"] = 0
            meta["podling_count"] = 0
            meta["available"] = False
            meta["reason"] = f"MailMCP cache directory is empty and live MailMCP search failed: {exc}"
            meta["api_base"] = api_base
            return {}, meta
        live_meta["fallback_reason"] = "MailMCP cache directory is empty."
        live_meta["cache_dir"] = cache_dir
        return live_mail, live_meta

    by_podling: dict[str, list[dict[str, Any]]] = {}
    for podling in podlings or []:
        podling_name = str(podling.get("name", ""))
        if not podling_name:
            continue
        matches = [message for message in messages if _mail_matches_podling(message, podling_name)]
        if matches:
            by_podling[_podling_key(podling_name)] = matches

    meta = _normalize_mail_source_meta(cached, cache_dir)
    meta["message_count"] = cached.get("count", len(messages))
    meta["podling_count"] = len(by_podling)
    meta["available"] = True
    return by_podling, meta


def refresh_incubator_general_mail_cache(
    mail_source: str | None = None,
    *,
    mail_api_base: str | None = None,
    timespan: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    cache_dir, _explicit = _resolved_mail_source(mail_source)
    api_base = _resolved_mail_api_base(mail_api_base)
    resolved_timespan = timespan or DEFAULT_MAIL_SEARCH_TIMESPAN
    if incubator_mail_client is None:
        return _mail_unavailable_meta(cache_dir, "apache-incubator-mail-mcp is not installed.", api_base=api_base) | {
            "cached": False,
        }

    cacher = getattr(incubator_mail_client, "cache_mail_stats", None)
    if cacher is None:
        return _mail_unavailable_meta(
            cache_dir,
            "Installed MailMCP does not provide cache_mail_stats.",
            api_base=api_base,
        ) | {"cached": False}

    result = cacher(
        api_base=api_base,
        cache_dir=cache_dir,
        timespan=resolved_timespan,
        query=query,
        limit=limit,
    )
    upstream_source = result.get("source")
    if upstream_source is not None and not isinstance(upstream_source, str):
        result.setdefault("source_details", upstream_source)
        result["source"] = cache_dir
    result.setdefault("source", cache_dir)
    result.setdefault("cache_dir", cache_dir)
    result.setdefault("api_base", api_base)
    result.setdefault("timespan", resolved_timespan)
    result["available"] = True
    result["cached"] = True
    return result


def load_podling_release_vote_history(
    podling: str,
    *,
    mail_api_base: str | None = None,
    timespan: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    api_base = _resolved_mail_api_base(mail_api_base)
    resolved_timespan = timespan or DEFAULT_MAIL_SEARCH_TIMESPAN
    unavailable: dict[str, Any] = {
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


def load_podling_release_artifacts(
    podling: str,
    *,
    release_dist_base: str | None = None,
    release_archive_base: str | None = None,
    max_depth: int = 1,
    release_page_url: str | None = None,
    include_platforms: bool = False,
    github_project: str | None = None,
    docker_images: list[str] | None = None,
    pypi_packages: list[str] | None = None,
    maven_group_ids: list[str] | None = None,
) -> dict[str, Any]:
    dist_base = _resolved_release_dist_base(release_dist_base)
    archive_base = _resolved_release_archive_base(release_archive_base)
    unavailable: dict[str, Any] = {
        "podling": podling,
        "source": "apache-incubator-releases",
        "dist_base": dist_base,
        "archive_base": archive_base,
        "available": False,
        "release_count": 0,
        "source_artifact_count": 0,
        "signature_count": 0,
        "checksum_count": 0,
        "releases": [],
    }
    if incubator_releases is None:
        return unavailable | {
            "reason": (
                "apache-incubator-releases-mcp is not importable in the IPMC server environment. "
                "Install or update IPMC dependencies, or include the ReleaseMCP src directory on PYTHONPATH "
                "when running server.py from a checkout."
            )
        }

    try:
        release_kwargs: dict[str, Any] = {
            "archive_base": archive_base,
            "max_depth": max_depth,
        }
        if dist_base is not None:
            release_kwargs["dist_base"] = dist_base
        release_page_requested = bool(release_page_url)
        auto_release_page = release_page_url == "auto"
        platform_hints_requested = bool(
            include_platforms or github_project or docker_images or pypi_packages or maven_group_ids
        )
        if release_page_requested and not auto_release_page:
            release_kwargs["release_page_url"] = release_page_url
        if platform_hints_requested:
            release_kwargs |= {
                "include_platforms": True,
                "github_project": github_project,
                "docker_images": docker_images,
                "pypi_packages": pypi_packages,
                "maven_group_ids": maven_group_ids,
            }
        unsupported_release_page = False
        unsupported_platforms = False
        unsupported_maven = False
        original_release_page_checks = getattr(incubator_releases, "release_page_checks", None)
        while True:
            try:
                with _RELEASE_PAGE_CHECK_PATCH_LOCK:
                    if not release_page_requested and callable(original_release_page_checks):
                        setattr(incubator_releases, "release_page_checks", _not_requested_release_page_checks)
                    try:
                        evidence = incubator_releases.release_overview(podling, **release_kwargs)
                    finally:
                        if not release_page_requested and callable(original_release_page_checks):
                            setattr(incubator_releases, "release_page_checks", original_release_page_checks)
                break
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                if (
                    "'maven_group_ids'" in message or '"maven_group_ids"' in message
                ) and "maven_group_ids" in release_kwargs:
                    release_kwargs.pop("maven_group_ids")
                    unsupported_maven = True
                    continue
                if (
                    "'release_page_url'" in message or '"release_page_url"' in message
                ) and "release_page_url" in release_kwargs:
                    release_kwargs.pop("release_page_url")
                    unsupported_release_page = True
                    continue
                if (
                    "'include_platforms'" in message or '"include_platforms"' in message
                ) and "include_platforms" in release_kwargs:
                    platform_keys = (
                        "include_platforms",
                        "github_project",
                        "docker_images",
                        "pypi_packages",
                        "maven_group_ids",
                    )
                    for key in platform_keys:
                        release_kwargs.pop(key, None)
                    unsupported_platforms = True
                    continue
                raise

        if unsupported_platforms:
            evidence["platform_distribution_checks"] = {
                "included": True,
                "available": False,
                "reason": (
                    "Installed apache-incubator-releases-mcp does not support platform distribution hints. "
                    "Update ReleaseMCP to use include_platforms, github_project, docker_images, "
                    "pypi_packages, or maven_group_ids."
                ),
            }
        elif unsupported_maven:
            checks = evidence.setdefault("platform_distribution_checks", {})
            hints = checks.setdefault("hints", {})
            if isinstance(hints, dict):
                hints["maven"] = [
                    "Installed apache-incubator-releases-mcp does not support Maven distribution hints. "
                    "Update ReleaseMCP to use maven_group_ids."
                ]
        if unsupported_release_page:
            evidence["release_page_checks"] = {
                "location": release_page_url,
                "available": False,
                "reason": (
                    "Installed apache-incubator-releases-mcp does not support release download page checks. "
                    "Update ReleaseMCP to use release_page_url."
                ),
            }
        elif not release_page_requested:
            evidence.pop("release_page_checks", None)
        else:
            _limit_release_page_check_links(evidence)
    except Exception as exc:
        return unavailable | {"reason": f"ReleaseMCP dist/archive scan failed: {exc}"}

    evidence["source"] = "apache-incubator-releases"
    evidence["dist_base"] = (evidence.get("sources") or {}).get("dist") or dist_base
    evidence["archive_base"] = archive_base
    evidence["available"] = True
    evidence.setdefault("release_count", len(evidence.get("releases") or []))
    evidence.setdefault("source_artifact_count", 0)
    evidence.setdefault("signature_count", 0)
    evidence.setdefault("checksum_count", 0)
    evidence.setdefault("releases", [])
    return evidence


def build_records(
    *,
    podlings_source: str | None = None,
    health_source: str | None = None,
    report_source: str | None = None,
    mail_source: str | None = None,
    mail_api_base: str | None = None,
    as_of_date: str | None = None,
    include_non_current: bool = False,
    include_mail: bool = False,
    requested_podling: str | None = None,
) -> dict[str, Any]:
    podlings, podlings_meta = load_podlings(podlings_source)
    summaries, health_meta = load_health_summaries(health_source)
    report_entries, report_meta = load_incubator_reports(report_source)
    if include_mail:
        mail_entries, mail_meta = load_incubator_general_mail(mail_source, podlings, mail_api_base=mail_api_base)
    else:
        mail_entries = {}
        mail_meta = {
            "source": "not_loaded",
            "available": False,
            "reason": "General-list mail evidence was not needed for this tool call.",
        }

    records: list[OversightRecord] = []
    requested_podling_name = requested_podling.strip() if requested_podling else None
    requested_podling_key = _podling_key(requested_podling_name) if requested_podling_name else None
    for podling in podlings:
        podling_name = str(podling.get("name", ""))
        podling_key = _podling_key(podling_name)
        status = str(podling.get("status") or "unknown").lower()
        if not include_non_current and status != "current" and podling_key != requested_podling_key:
            continue
        summary = summaries.get(podling_key)
        preferred_window, preferred_metrics = _preferred_window(summary)
        reporting_window, reporting_metrics = _reporting_window(summary)
        records.append(
            OversightRecord(
                podling=podling,
                report_summary=summary,
                incubator_reports=report_entries.get(podling_key, []),
                incubator_general_mail=mail_entries.get(podling_key, []),
                preferred_window=preferred_window,
                preferred_metrics=preferred_metrics,
                reporting_window=reporting_window,
                reporting_metrics=reporting_metrics,
                as_of_date=as_of_date,
            )
        )

    record_names = {_podling_key(record.name) for record in records}
    if requested_podling_key and requested_podling_key not in record_names:
        summary = summaries.get(requested_podling_key)
        incubator_reports = report_entries.get(requested_podling_key, [])
        incubator_general_mail = mail_entries.get(requested_podling_key, [])
        if summary is not None or incubator_reports or incubator_general_mail:
            preferred_window, preferred_metrics = _preferred_window(summary)
            reporting_window, reporting_metrics = _reporting_window(summary)
            records.append(
                OversightRecord(
                    podling={
                        "name": requested_podling_name,
                        "status": "unknown",
                        "mentors": [],
                        "startdate": None,
                    },
                    report_summary=summary,
                    incubator_reports=incubator_reports,
                    incubator_general_mail=incubator_general_mail,
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
