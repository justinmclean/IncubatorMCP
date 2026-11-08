"""Data loading and composition helpers for the IPMC oversight MCP server."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from apache_health_mcp import parser as health_parser
from apache_incubator_mail_mcp import client as incubator_mail_client  # type: ignore[import-not-found]
from apache_incubator_releases_mcp import releases as incubator_releases  # type: ignore[import-not-found]
from apache_incubator_reports_mcp import parser as incubator_report_parser  # type: ignore[import-not-found]
from apache_trademark_mcp import compliance as trademark_compliance  # type: ignore[import-not-found]
from apache_trademark_mcp import policy as trademark_policy  # type: ignore[import-not-found]
from apache_trademark_mcp import projects as trademark_projects  # type: ignore[import-not-found]
from apache_trademark_mcp import search as trademark_search  # type: ignore[import-not-found]
from apache_trademark_mcp import web as trademark_web  # type: ignore[import-not-found]
from podlings import data as podlings_data
from podlings import tools as podlings_tools

DEFAULT_HEALTH_SOURCE = "reports"
DEFAULT_REPORT_SOURCE = ".cache/incubator-reports"
DEFAULT_MAIL_SOURCE = ".cache/incubator-general-mail"
DEFAULT_MAIL_API_BASE = "https://lists.apache.org/api"
DEFAULT_MAIL_SEARCH_TIMESPAN = "lte=12M"
DEFAULT_MAIL_QUERY_LIMIT = 20
# Vote threads and their replies can fill the general search, so release
# results get a search of their own with a larger limit.
RESULT_MAIL_QUERY_LIMIT = 50
# A podling's own dev@ list is read for the year before the reference date.
# A busy list has a few hundred messages a year, one request of a few seconds.
DEV_MAIL_LOOKBACK_DAYS = 365
# The podling status page's News section lists new committers and PPMC members.
DEFAULT_STATUS_PAGE_BASE = "https://incubator.apache.org/projects"
# Podling name searches are PODLINGNAMESEARCH issues in the ASF Jira.
DEFAULT_NAME_SEARCH_API = "https://issues.apache.org/jira/rest/api/2/search"
LIVE_FETCH_TIMEOUT_SECONDS = 20
DEFAULT_RELEASE_DIST_BASE = "https://dist.apache.org/repos/dist/release/incubator"
DEFAULT_RELEASE_ARCHIVE_BASE = "https://archive.apache.org/dist/incubator"
RELEASE_PAGE_LINK_LIMIT = 50
# ReleaseMCP traversal depth below the podling directory. Two levels reach
# <version>/<subproject>/<file> trees such as Toree's; one level missed them.
RELEASE_MAX_DEPTH = 2
DEFAULT_TRADEMARK_BRANDING_STAGE = "podling"
DEFAULT_TRADEMARK_NAME_SIMILARITY = 0.5
PODLINGS_SOURCE_ENV = "IPMC_PODLINGS_SOURCE"
HEALTH_SOURCE_ENV = "IPMC_HEALTH_SOURCE"
REPORT_SOURCE_ENV = "IPMC_REPORT_SOURCE"
MAIL_SOURCE_ENV = "IPMC_MAIL_SOURCE"
MAIL_API_BASE_ENV = "IPMC_MAIL_API_BASE"
RELEASE_DIST_BASE_ENV = "IPMC_RELEASE_DIST_BASE"
RELEASE_ARCHIVE_BASE_ENV = "IPMC_RELEASE_ARCHIVE_BASE"
TRADEMARK_CACHE_ENV = "IPMC_TRADEMARK_CACHE"


@dataclass
class SourceDefaults:
    podlings_source: str | None = None
    health_source: str | None = None
    report_source: str | None = None
    mail_source: str | None = None
    mail_api_base: str | None = None
    release_dist_base: str | None = None
    release_archive_base: str | None = None
    trademark_cache: str | None = None


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
_PODLING_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


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
    trademark_cache: str | None = None,
    trademark_cache_dir: str | None = None,
) -> None:
    resolved_podlings_source = podlings_source or podlings_repo
    resolved_health_source = health_source or health_repo
    resolved_report_source = report_source or reports_source
    resolved_mail_source = mail_source or mail_cache_dir
    resolved_trademark_cache = trademark_cache or trademark_cache_dir
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
    if resolved_trademark_cache:
        _CONFIGURED_DEFAULTS.trademark_cache = resolved_trademark_cache
        if trademark_projects is not None:
            try:
                trademark_projects.cache_dir_from_env(resolved_trademark_cache)
                from apache_trademark_mcp import tools as _tm_tools  # type: ignore[import-not-found]

                _tm_tools.configure_defaults(cache_dir=resolved_trademark_cache)
            except Exception:  # pragma: no cover - defensive
                pass


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
    mail_loaded: bool = True
    podling_dev_mail: list[dict[str, Any]] = field(default_factory=list)
    dev_mail_loaded: bool = False
    # Why dev@ could not be read, when a read was attempted and failed.
    dev_mail_error: str | None = None
    # Dated News entries from the podling's Incubator status page.
    status_news: list[dict[str, Any]] = field(default_factory=list)
    status_page_loaded: bool = False
    # Why the status page could not be read, when a read was attempted and failed.
    status_page_error: str | None = None
    # PODLINGNAMESEARCH issues for the podling's name.
    name_searches: list[dict[str, Any]] = field(default_factory=list)
    name_search_loaded: bool = False
    name_search_error: str | None = None

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


def _resolved_trademark_cache(trademark_cache: str | None = None) -> str | None:
    return trademark_cache or _CONFIGURED_DEFAULTS.trademark_cache or _env_default(TRADEMARK_CACHE_ENV)


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
            "trademark_cache": _resolved_trademark_cache(),
        },
    }


def load_incubator_reports(report_source: str | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    reports_dir, explicit = _resolved_report_source(report_source)
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


def _podling_name_pattern(podling_name: str) -> re.Pattern[str]:
    """Regex that matches a podling name as a whole word, however it is spaced.

    The name is split into tokens on separators and on CamelCase boundaries
    ("Pony Mail" and "PonyMail" both give pony, mail; "GraphAr" gives graph,
    ar). Tokens may be joined by nothing or by a space, hyphen or underscore,
    and the whole must sit on word boundaries, so "KIE" does not match
    "cookie" and "Burr" does not match "Burroughs".
    """
    pattern = _PODLING_PATTERN_CACHE.get(podling_name)
    if pattern is not None:
        return pattern
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", podling_name)
    tokens = [tok for tok in re.split(r"[^A-Za-z0-9]+", camel_split) if tok]
    if not tokens:
        tokens = [podling_name]
    body = r"[\s\-_]?".join(re.escape(tok) for tok in tokens)
    pattern = re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)
    _PODLING_PATTERN_CACHE[podling_name] = pattern
    return pattern


def _mail_matches_podling(message: dict[str, Any], podling_name: str) -> bool:
    """True when the message subject names the podling as a whole word.

    Only the subject is searched. Sender addresses and Pony Mail ids are
    random with respect to the podling and produced false matches.
    """
    subject = str(message.get("subject", ""))
    return bool(subject) and _podling_name_pattern(podling_name).search(subject) is not None


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


def _store_live_mail(cache_root: str, emails: list[dict[str, Any]], *, query: str, timespan: str) -> int:
    """Write live search results into the MailMCP cache so the next run has a fallback.

    Uses the same per-message JSON layout MailMCP writes itself. Best effort: a
    failure to write never affects the evidence returned.
    """
    key_fn = getattr(incubator_mail_client, "cache_key", None)
    if key_fn is None:
        return 0
    base = Path(cache_root).expanduser()
    if not base.is_dir():
        return 0
    cached_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    for email in emails:
        message_id = email.get("id")
        if not message_id:
            continue
        payload = {
            **email,
            "cached_at": cached_at,
            "source_query": query,
            "source_timespan": timespan,
            "source_list": "general@incubator.apache.org",
        }
        try:
            (base / f"{key_fn(str(message_id))}.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8"
            )
            written += 1
        except OSError:
            continue
    return written


def load_incubator_general_mail(
    mail_source: str | None = None,
    podlings: list[dict[str, Any]] | None = None,
    *,
    mail_api_base: str | None = None,
    live: bool = True,
    timespan: str = DEFAULT_MAIL_SEARCH_TIMESPAN,
    limit: int = DEFAULT_MAIL_QUERY_LIMIT,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Return general@incubator mail per podling, live first.

    For every podling in scope the Pony Mail API is searched now, so the
    evidence is as recent as the list itself. The MailMCP cache directory is a
    fallback for podlings whose live search fails, and a store for the live
    results so the fallback is as fresh as the last successful fetch. Cached
    messages older than the live window are kept alongside the live ones.
    With ``live=False`` only the cache is read.
    """
    cache_dir, explicit = _resolved_mail_source(mail_source)
    api_base = _resolved_mail_api_base(mail_api_base)
    cache_exists = Path(cache_dir).expanduser().exists()
    if explicit and not cache_exists:
        raise FileNotFoundError(f"MailMCP source path does not exist: {cache_dir}")

    cached: dict[str, Any] = {"cache_dir": cache_dir, "count": 0, "emails": []}
    if cache_exists:
        cached = incubator_mail_client.load_cached_mail(cache_dir=cache_dir)
    cached_messages = cached.get("emails") or []
    cache_root = str(cached.get("cache_dir") or cache_dir)

    by_podling: dict[str, list[dict[str, Any]]] = {}
    source_by_podling: dict[str, str] = {}
    live_failures: dict[str, str] = {}
    live_attempted = 0
    live_succeeded = 0
    written = 0

    fetcher = getattr(incubator_mail_client, "fetch_mail_stats", None) if live else None
    fetcher_missing = live and fetcher is None

    for podling in podlings or []:
        podling_name = str(podling.get("name", ""))
        if not podling_name:
            continue
        key = _podling_key(podling_name)
        cached_slice = [message for message in cached_messages if _mail_matches_podling(message, podling_name)]

        live_slice: list[dict[str, Any]] | None = None
        if fetcher is not None:
            live_attempted += 1
            try:
                fetched: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for query, query_limit in (
                    (podling_name, limit),
                    (f"{podling_name} result", max(limit, RESULT_MAIL_QUERY_LIMIT)),
                ):
                    result = fetcher(api_base=api_base, timespan=timespan, query=query, limit=query_limit)
                    for message in result.get("emails", []):
                        message_id = str(message.get("id") or "")
                        if message_id and message_id in seen_ids:
                            continue
                        if not _mail_matches_podling(message, podling_name):
                            continue
                        if message_id:
                            seen_ids.add(message_id)
                        fetched.append(message)
                live_slice = fetched
                live_succeeded += 1
                if live_slice and cache_exists:
                    written += _store_live_mail(cache_root, live_slice, query=podling_name, timespan=timespan)
            except Exception as exc:  # noqa: BLE001 - any live failure falls back to the cache
                live_failures[key] = str(exc)

        if live_slice is not None:
            seen = {str(message.get("id")) for message in live_slice if message.get("id")}
            merged = list(live_slice) + [m for m in cached_slice if str(m.get("id")) not in seen]
            if merged:
                by_podling[key] = merged
                source_by_podling[key] = "live+cache" if len(merged) > len(live_slice) else "live"
        elif cached_slice:
            by_podling[key] = cached_slice
            source_by_podling[key] = "cache"

    meta = _normalize_mail_source_meta(cached, cache_dir)
    meta["cache_dir"] = cache_root if cache_exists else cache_dir
    meta["cache_message_count"] = cached.get("count", len(cached_messages))
    meta["api_base"] = api_base
    meta["timespan"] = timespan
    meta["live_requested"] = bool(live)
    meta["live_podling_count"] = live_succeeded
    meta["live_failures"] = live_failures
    meta["source_by_podling"] = source_by_podling
    meta["cached_messages_written"] = written
    meta["message_count"] = sum(len(messages) for messages in by_podling.values())
    meta["podling_count"] = len(by_podling)

    if live_succeeded:
        meta["source"] = api_base
        meta["mode"] = "live" if not any(v != "live" for v in source_by_podling.values()) else "live+cache"
        meta["available"] = True
    elif live and live_attempted and not cached_messages:
        first_error = next(iter(live_failures.values()), "no response")
        meta["mode"] = "unavailable"
        meta["available"] = False
        meta["reason"] = (
            f"MailMCP cache holds no messages and live MailMCP search failed: {first_error}"
            if live_failures
            else "MailMCP cache holds no messages and live MailMCP search returned nothing."
        )
    else:
        meta["mode"] = "cache"
        meta["available"] = cache_exists
        if fetcher_missing:
            meta["reason"] = "Installed MailMCP does not provide fetch_mail_stats for live general-list search."
        elif not cache_exists:
            meta["reason"] = "Default MailMCP cache directory does not exist."
    return by_podling, meta


def podling_slug(podling: dict[str, Any]) -> str | None:
    """The podling's ASF slug, as used in <slug>.apache.org and its list addresses.

    podlings.xml carries it in ``resource``; without one the name is lowercased
    with anything other than letters and digits removed.
    """
    resource = podling.get("resource")
    if isinstance(resource, dict):
        resource = next(
            (resource.get(key) for key in ("href", "url", "value") if isinstance(resource.get(key), str)), None
        )
    if isinstance(resource, str) and resource.strip() and not resource.strip().startswith(("http://", "https://")):
        return resource.strip().lower()
    name = re.sub(r"[^a-z0-9]", "", str(podling.get("name") or "").casefold())
    return name or None


STATUS_NEWS_SECTION_RE = re.compile(r"id=['\"]News['\"].*?(?=<h2\b|\Z)", re.IGNORECASE | re.DOTALL)
STATUS_NEWS_ITEM_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
STATUS_NEWS_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\b[\s:.-]*(.*)$", re.DOTALL)


def parse_status_news(html: str) -> list[dict[str, Any]]:
    """Dated entries from the News section of an Incubator podling status page."""
    section = STATUS_NEWS_SECTION_RE.search(html)
    if section is None:
        return []
    entries = []
    for item in STATUS_NEWS_ITEM_RE.findall(section.group(0)):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item)).strip()
        match = STATUS_NEWS_DATE_RE.match(text)
        if match is None:
            continue
        try:
            when = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        entries.append({"date": when.isoformat(), "text": match.group(4).strip()})
    return entries


def _fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "apache-ipmc-mcp"})
    with urllib.request.urlopen(request, timeout=LIVE_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https bases
        return response.read().decode("utf-8", errors="replace")


def load_podling_status_page(
    podling: dict[str, Any], *, status_page_base: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the News entries from the podling's Incubator status page, live.

    A failure returns empty lists and says why.
    """
    empty: list[dict[str, Any]] = []
    slug = podling_slug(podling)
    base = (status_page_base or DEFAULT_STATUS_PAGE_BASE).rstrip("/")
    meta: dict[str, Any] = {"source": base, "podling": podling.get("name"), "slug": slug}
    if not slug:
        return empty, meta | {"available": False, "reason": "No slug is known for the podling."}
    url = f"{base}/{slug}.html"
    try:
        html = _fetch_url(url)
    except Exception as exc:  # noqa: BLE001 - status page evidence is optional; say why it is missing
        return empty, meta | {"available": False, "url": url, "reason": f"Status page could not be read: {exc}"}
    news = parse_status_news(html)
    return news, meta | {"available": True, "url": url, "news_count": len(news)}


def load_podling_name_search(
    podling: dict[str, Any], *, api_url: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the PODLINGNAMESEARCH issues whose summary names the podling, live."""
    name = str(podling.get("name") or "").strip()
    api = api_url or DEFAULT_NAME_SEARCH_API
    meta: dict[str, Any] = {"source": api, "podling": name}
    if not name:
        return [], meta | {"available": False, "reason": "No name is known for the podling."}
    query = urllib.parse.urlencode(
        {
            "jql": f'project = PODLINGNAMESEARCH AND summary ~ "\\"{name}\\""',
            "fields": "summary,status,resolution,resolutiondate,created",
            "maxResults": "20",
        }
    )
    url = f"{api}?{query}"
    try:
        payload = json.loads(_fetch_url(url))
    except Exception as exc:  # noqa: BLE001 - name search evidence is optional; say why it is missing
        return [], meta | {"available": False, "reason": f"PODLINGNAMESEARCH could not be read: {exc}"}
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    issues = []
    for issue in payload.get("issues") or []:
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or "")
        if not pattern.search(summary):
            continue
        issues.append(
            {
                "key": issue.get("key"),
                "summary": summary,
                "status": (fields.get("status") or {}).get("name"),
                "resolution": (fields.get("resolution") or {}).get("name"),
                "resolved": str(fields.get("resolutiondate") or "")[:10] or None,
                "created": str(fields.get("created") or "")[:10] or None,
            }
        )
    return issues, meta | {"available": True, "issue_count": len(issues)}


def load_podling_dev_mail(
    podling: dict[str, Any],
    *,
    mail_api_base: str | None = None,
    as_of_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the podling's dev@ list for the year before the reference date, live.

    The whole year is fetched and read locally rather than searched by
    keyword: Pony Mail searches bodies as well as subjects and does not match
    word stems, so "retire" misses "retirement" and "graduation" finds every
    report reminder. A failure returns no messages and says why.
    """
    api_base = _resolved_mail_api_base(mail_api_base)
    slug = podling_slug(podling)
    meta: dict[str, Any] = {"source": api_base, "list": "dev", "podling": podling.get("name"), "slug": slug}
    fetcher = getattr(incubator_mail_client, "fetch_podling_mail_stats", None)
    if fetcher is None:
        return [], meta | {
            "available": False,
            "reason": "Installed MailMCP does not provide fetch_podling_mail_stats.",
        }
    if not slug:
        return [], meta | {"available": False, "reason": "No slug is known for the podling."}
    reference = parse_iso_date(as_of_date) or date.today()
    start = date.fromordinal(reference.toordinal() - DEV_MAIL_LOOKBACK_DAYS)
    timespan = f"dfr={start.isoformat()}|dto={reference.isoformat()}"
    try:
        result = fetcher(podling=slug, list_name="dev", api_base=api_base, timespan=timespan)
    except Exception as exc:  # noqa: BLE001 - dev@ evidence is optional; say why it is missing
        return [], meta | {"available": False, "timespan": timespan, "reason": f"dev@ search failed: {exc}"}
    messages = list(result.get("emails") or [])
    return messages, meta | {
        "available": True,
        "list": result.get("list") or f"dev@{slug}.apache.org",
        "timespan": timespan,
        "message_count": len(messages),
    }


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
    max_depth: int = RELEASE_MAX_DEPTH,
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

    requested_podling_name = requested_podling.strip() if requested_podling else None
    requested_podling_key = _podling_key(requested_podling_name) if requested_podling_name else None

    if include_mail:
        # Search mail only for the podlings this call is about: the requested
        # one, or the podlings that will become records. podlings.xml lists
        # every podling that ever existed, and a live search per entry would
        # be hundreds of API calls.
        if requested_podling_key:
            mail_scope = [p for p in podlings if _podling_key(str(p.get("name", ""))) == requested_podling_key] or [
                {"name": requested_podling_name}
            ]
        else:
            mail_scope = [
                p for p in podlings if include_non_current or str(p.get("status") or "unknown").lower() == "current"
            ]
        mail_entries, mail_meta = load_incubator_general_mail(mail_source, mail_scope, mail_api_base=mail_api_base)
    else:
        mail_entries = {}
        mail_meta = {
            "source": "not_loaded",
            "available": False,
            "reason": "General-list mail evidence was not needed for this tool call.",
        }

    records: list[OversightRecord] = []
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
                mail_loaded=include_mail,
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
                    mail_loaded=include_mail,
                    preferred_window=preferred_window,
                    preferred_metrics=preferred_metrics,
                    reporting_window=reporting_window,
                    reporting_metrics=reporting_metrics,
                    as_of_date=as_of_date,
                )
            )

    # The podling's own dev@ list is read only for single-podling calls: a
    # year of one list is one request of a few seconds, too slow to repeat for
    # every podling in an overview.
    dev_mail_meta: dict[str, Any] = {
        "source": "not_loaded",
        "available": False,
        "reason": "Podling dev@ mail is read only for single-podling mail views.",
    }
    status_page_meta: dict[str, Any] = {
        "source": "not_loaded",
        "available": False,
        "reason": "The podling status page is read only for single-podling mail views.",
    }
    name_search_meta: dict[str, Any] = {
        "source": "not_loaded",
        "available": False,
        "reason": "PODLINGNAMESEARCH is read only for single-podling mail views.",
    }
    if include_mail and requested_podling_key:
        target = next((record for record in records if _podling_key(record.name) == requested_podling_key), None)
        if target is not None:
            target.podling_dev_mail, dev_mail_meta = load_podling_dev_mail(
                target.podling, mail_api_base=mail_api_base, as_of_date=as_of_date
            )
            target.dev_mail_loaded = bool(dev_mail_meta.get("available"))
            if not target.dev_mail_loaded:
                target.dev_mail_error = str(dev_mail_meta.get("reason") or "dev@ could not be read.")
            # The status page and name search are read with dev@, for the same
            # single-podling views.
            target.status_news, status_page_meta = load_podling_status_page(target.podling)
            target.status_page_loaded = bool(status_page_meta.get("available"))
            if not target.status_page_loaded:
                target.status_page_error = str(status_page_meta.get("reason") or "Status page could not be read.")
            target.name_searches, name_search_meta = load_podling_name_search(target.podling)
            target.name_search_loaded = bool(name_search_meta.get("available"))
            if not target.name_search_loaded:
                target.name_search_error = str(name_search_meta.get("reason") or "PODLINGNAMESEARCH could not be read.")

    return {
        "records": sorted(records, key=lambda item: item.name.casefold()),
        "podlings_source": podlings_meta,
        "health_source": health_meta,
        "report_source": report_meta,
        "mail_source": mail_meta,
        "dev_mail_source": dev_mail_meta,
        "status_page_source": status_page_meta,
        "name_search_source": name_search_meta,
    }


def _trademark_unavailable_meta(reason: str) -> dict[str, Any]:
    return {
        "source": "apache-trademark",
        "available": False,
        "reason": reason,
    }


def _trademark_cache_path() -> Any:
    """Return the cache dir Path that the trademark package should use."""
    explicit = _resolved_trademark_cache()
    return trademark_projects.cache_dir_from_env(explicit)


def load_proposed_name_check(
    proposed_name: str,
    *,
    technical_description: str | None = None,
    include_external_search: bool = False,
    asf_min_similarity: float = DEFAULT_TRADEMARK_NAME_SIMILARITY,
    trademark_cache: str | None = None,
) -> dict[str, Any]:
    """Run the trademark MCP's name-related checks for a proposed podling/project name.

    Combines ``validate_name`` (reserved marks, format, Native American check, ASF
    project-list conflicts) with optional GitHub/PyPI/npm external lookups
    (``perform_name_search``) and a fuzzy ASF project-list search
    (``search_asf_projects``). Returns a uniform IPMC-shaped payload so callers
    do not need to know the upstream tool layout.
    """
    if trademark_cache:
        configure_defaults(trademark_cache=trademark_cache)

    cache_dir = _trademark_cache_path()

    asf_projects = trademark_projects.fetch_projects(cache_dir=cache_dir)
    asf_conflicts, nearby_asf_names = trademark_projects.find_name_conflicts(proposed_name, asf_projects)

    blocking: list[str] = []
    blocking.extend(trademark_policy.check_reserved(proposed_name))
    for flag in trademark_policy.check_native_american(proposed_name):
        blocking.append(
            f"'{flag}' is a Native American tribal or cultural name. "
            "ASF policy: names with Native American connections will not be approved."
        )
    format_blocking, warnings = trademark_policy.check_format(proposed_name)
    blocking.extend(format_blocking)
    for match in asf_conflicts:
        if match["match_type"] == "exact":
            blocking.append(
                f"Exact name conflict with existing ASF project '{match['name']}'. "
                "The same name cannot be reused for a new podling."
            )
        else:
            blocking.append(
                f"Near-exact name match with existing ASF project '{match['name']}' "
                f"(similarity {match['similarity']:.0%})."
            )
    verdict = "FAIL" if blocking else ("WARN" if warnings else "PASS")

    similar = trademark_projects.find_similar(
        proposed_name, asf_projects, threshold=max(0.0, min(1.0, asf_min_similarity))
    )
    descriptions = trademark_projects.project_descriptions(asf_projects)
    fuzzy_results: list[dict[str, Any]] = []
    for match in similar:
        norm_key = trademark_policy.normalize(match["name"]).replace(" ", "-")
        fuzzy_results.append(
            {
                "name": match["name"],
                "similarity": match["similarity"],
                "url": match["url"],
                "description": descriptions.get(norm_key, ""),
            }
        )

    external_search: dict[str, Any] | None = None
    if include_external_search:
        try:
            results = trademark_search.run_external_searches(proposed_name)
            github, pypi, npm = results["github"], results["pypi"], results["npm"]
            external_search = {
                "available": True,
                "github": github,
                "pypi": pypi,
                "npm": npm,
                "suitability_assessment": trademark_search.assess_findings(
                    proposed_name, github, pypi, npm, technical_description or ""
                ),
                "trademark_search_urls": trademark_search.trademark_search_urls(proposed_name),
                "jira_ticket_template": trademark_search.jira_template(
                    proposed_name, technical_description or "", github, pypi, npm
                ),
            }
        except Exception as exc:  # pragma: no cover - network failure
            external_search = {"available": False, "reason": f"External name search failed: {exc}"}

    return {
        "source": "apache-trademark",
        "available": True,
        "proposed_name": proposed_name,
        "apache_form": f"Apache {proposed_name}",
        "technical_description": technical_description or None,
        "verdict": verdict,
        "blocking_issues": blocking,
        "warnings": warnings,
        "asf_name_conflicts": asf_conflicts,
        "nearby_asf_names": nearby_asf_names,
        "fuzzy_asf_results": fuzzy_results,
        "external_search": external_search,
        "cache_dir": str(cache_dir) if cache_dir else None,
        "cache_age_hours": trademark_projects.cache_age_hours(cache_dir=cache_dir),
        "policy_citations": trademark_policy.policy_citations(),
    }


def load_project_website_branding_check(
    url: str,
    *,
    project_name: str | None = None,
    stage: str = DEFAULT_TRADEMARK_BRANDING_STAGE,
    trademark_cache: str | None = None,
) -> dict[str, Any]:
    """Fetch a project website and run the trademark MCP's branding-compliance rules."""
    if stage not in trademark_policy.VALID_BRANDING_STAGES:
        raise ValueError(f"'stage' must be one of: {', '.join(sorted(trademark_policy.VALID_BRANDING_STAGES))}")

    if trademark_cache:
        configure_defaults(trademark_cache=trademark_cache)
    cache_dir = _trademark_cache_path()

    try:
        page = trademark_web.fetch_page(url)
    except Exception as exc:
        return _trademark_unavailable_meta(f"Failed to fetch project website: {exc}") | {
            "target_url": url,
            "available": False,
        }

    asf_projects = trademark_projects.fetch_projects(cache_dir=cache_dir)
    known_marks = trademark_compliance.project_names_for_bare_scan(asf_projects)
    report = trademark_compliance.check_project_website(
        page,
        project_name=project_name or None,
        stage=stage,
        known_marks=known_marks,
    )

    payload = report.to_dict()
    payload.update(
        {
            "source": "apache-trademark",
            "available": True,
            "project_name": project_name or trademark_compliance._infer_project_name(page),
            "stage": stage,
            "checklist": trademark_policy.branding_checklist(stage),
            "policy_references": dict(trademark_compliance.POLICY_URLS),
            "cache_dir": str(cache_dir) if cache_dir else None,
        }
    )
    return payload


def load_third_party_use_check(
    url: str,
    *,
    mark: str | None = None,
    trademark_cache: str | None = None,
) -> dict[str, Any]:
    """Fetch a third-party page and run the trademark MCP's policy rules."""
    if trademark_cache:
        configure_defaults(trademark_cache=trademark_cache)
    cache_dir = _trademark_cache_path()

    try:
        page = trademark_web.fetch_page(url)
    except Exception as exc:
        return _trademark_unavailable_meta(f"Failed to fetch third-party page: {exc}") | {
            "target_url": url,
            "available": False,
        }

    asf_projects = trademark_projects.fetch_projects(cache_dir=cache_dir)
    known_marks = trademark_compliance.project_names_for_bare_scan(asf_projects)
    report = trademark_compliance.check_third_party_use(page, mark=mark or None, known_marks=known_marks)

    payload = report.to_dict()
    payload.update(
        {
            "source": "apache-trademark",
            "available": True,
            "mark": mark or "",
            "policy_references": dict(trademark_compliance.POLICY_URLS),
            "cache_dir": str(cache_dir) if cache_dir else None,
        }
    )
    return payload


def refresh_trademark_project_cache(trademark_cache: str | None = None) -> dict[str, Any]:
    """Force a fresh fetch of the ASF committees+podlings list used by the trademark MCP."""
    if trademark_cache:
        configure_defaults(trademark_cache=trademark_cache)
    cache_dir = _trademark_cache_path()

    result = dict(trademark_projects.refresh_cache(cache_dir=cache_dir))
    result.setdefault("source", "apache-trademark")
    result["cache_dir"] = str(cache_dir) if cache_dir else None
    result["available"] = True
    result["cached"] = True
    return result
