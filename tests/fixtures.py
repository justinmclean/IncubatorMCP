from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterator
from unittest import mock

from ipmc import data

SAMPLE_XML = dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <podlings>
      <podling name="Alpha" status="current" sponsor="Apache Incubator" startdate="2024-01-01">
        <description>Healthy podling with good momentum.</description>
        <champion>Champion Alpha</champion>
        <mentors>
          <mentor>Mentor One</mentor>
          <mentor>Mentor Two</mentor>
          <mentor>Mentor Three</mentor>
        </mentors>
      </podling>
      <podling name="Bravo" status="current" sponsor="Apache Incubator" startdate="2025-03-01">
        <description>Podling with weaker activity.</description>
        <champion>Champion Bravo</champion>
        <mentors>
          <mentor>Mentor Four</mentor>
          <mentor>Mentor Five</mentor>
        </mentors>
      </podling>
      <podling name="Charlie" status="current" sponsor="Apache Incubator" startdate="2023-01-01">
        <description>Podling with no visible mentor coverage.</description>
        <champion>Champion Charlie</champion>
      </podling>
      <podling name="Delta" status="current" sponsor="Apache Incubator" startdate="2023-06-01">
        <description>Older podling with strong graduation signals.</description>
        <champion>Champion Delta</champion>
        <mentors>
          <mentor>Mentor Six</mentor>
          <mentor>Mentor Seven</mentor>
          <mentor>Mentor Eight</mentor>
        </mentors>
      </podling>
    </podlings>
    """
)

ALPHA_REPORT = """# Alpha - Incubator Health
_Generated on 2026-04-18_

## Window Details
### 3m  (2026-01-18 -> 2026-04-18)
- **Releases (from list votes/results):** 2 ↑  |  **Median gap (days):** 31.5 ↓
- **New contributors:** 4 ↑  |  **Unique committers:** 6 ↑  |  **Commits:** 40 ↑
- **Issues:** opened 9 ↑ / closed 8 →
- **PRs:** opened 12 ↑ / merged 10 ↑  |  **Median merge time (days):** 2.5 ↓
- **Reviews (sampled):** median reviewers/PR **2.0** →  |
  reviewer diversity (eff.#) **3.1** ↑  |
  PR author diversity (eff.#) **5.2** ↑  |
  unique reviewers **5** ↑, unique authors **6** ↑
- **Bus factor proxy (50% / 75%):** 2 ↑ / 4 →
- **Incubator reports:** 1 →  |  **Avg mentor sign-offs:** 2.5 ↑
- **Mailing lists:** dev messages **25** ↑, dev unique posters **9** ↑
"""

BRAVO_REPORT = """# Bravo - Incubator Health
_Generated on 2026-04-18_

## Window Details
### 3m  (2026-01-18 -> 2026-04-18)
- **Releases (from list votes/results):** 0 →  |  **Median gap (days):** — →
- **New contributors:** 1 ↓  |  **Unique committers:** 2 →  |  **Commits:** 8 ↓
- **Issues:** opened 2 → / closed 1 ↓
- **PRs:** opened 3 → / merged 2 ↓  |  **Median merge time (days):** 9.0 ↑
- **Reviews (sampled):** median reviewers/PR **1.0** →  |
  reviewer diversity (eff.#) **1.5** →  |
  PR author diversity (eff.#) **2.0** →  |
  unique reviewers **2** →, unique authors **2** →
- **Bus factor proxy (50% / 75%):** 1 → / 2 →
- **Incubator reports:** 0 →  |  **Avg mentor sign-offs:** 1.0 ↓
- **Mailing lists:** dev messages **6** ↓, dev unique posters **3** →
"""

DELTA_REPORT = """# Delta - Incubator Health
_Generated on 2026-04-18_

## Window Details
### 3m  (2026-01-18 -> 2026-04-18)
- **Releases (from list votes/results):** 1 ↑  |  **Median gap (days):** 28.0 ↓
- **New contributors:** 3 ↑  |  **Unique committers:** 5 ↑  |  **Commits:** 32 ↑
- **Issues:** opened 8 ↑ / closed 8 ↑
- **PRs:** opened 9 ↑ / merged 9 ↑  |  **Median merge time (days):** 2.0 ↓
- **Reviews (sampled):** median reviewers/PR **2.0** →  |
  reviewer diversity (eff.#) **3.0** ↑  |
  PR author diversity (eff.#) **4.5** ↑  |
  unique reviewers **4** ↑, unique authors **5** ↑
- **Bus factor proxy (50% / 75%):** 2 ↑ / 4 ↑
- **Incubator reports:** 1 →  |  **Avg mentor sign-offs:** 2.5 ↑
- **Mailing lists:** dev messages **18** ↑, dev unique posters **7** ↑
"""


@dataclass
class FixtureSources:
    podlings_source: str
    health_source: str

    def __iter__(self) -> Iterator[str]:
        yield self.podlings_source
        yield self.health_source


@contextmanager
def make_fixture_sources() -> Iterator[FixtureSources]:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        xml_path = base / "sample-podlings.xml"
        reports_dir = base / "reports"
        reports_dir.mkdir()
        xml_path.write_text(SAMPLE_XML, encoding="utf-8")
        (reports_dir / "Alpha.md").write_text(ALPHA_REPORT, encoding="utf-8")
        (reports_dir / "Bravo.md").write_text(BRAVO_REPORT, encoding="utf-8")
        (reports_dir / "Delta.md").write_text(DELTA_REPORT, encoding="utf-8")

        mail_dir = base / "mail"
        mail_dir.mkdir()

        configured_defaults = data.configured_defaults_snapshot()
        data.configure_defaults(health_source=str(reports_dir), mail_source=str(mail_dir))
        try:
            # Tools built from these fixtures must never reach lists.apache.org:
            # the stub answers every live search with no messages and the empty
            # mail directory above stands in for the MailMCP cache. Status
            # pages and name searches come from STATUS_PAGES and NAME_SEARCHES
            # rather than incubator.apache.org and issues.apache.org.
            with (
                mock.patch.object(data, "incubator_mail_client", _OfflineMailClient()),
                mock.patch.object(data, "_fetch_url", _offline_fetch),
            ):
                yield FixtureSources(
                    podlings_source=str(xml_path),
                    health_source=str(reports_dir),
                )
        finally:
            data.restore_configured_defaults(configured_defaults)


def status_page(*entries: str) -> str:
    """A podling status page whose News section holds the given entries."""
    items = "".join(f"<li>{entry}</li>" for entry in entries)
    return f"<h2 id='News'>News</h2><div><ul>{items}</ul></div><h2 id='Project+info'>Project info</h2>"


# Status pages for the fixture podlings, keyed by slug.
STATUS_PAGES = {
    "delta": status_page("2024-02-10 New committer: Dana Delta.", "2023-06-01 Project enters incubation."),
}

# PODLINGNAMESEARCH issues for the fixture podlings, keyed by name.
NAME_SEARCHES = {
    "Delta": [
        {
            "key": "PODLINGNAMESEARCH-1",
            "fields": {
                "summary": 'Establish whether "Apache Delta" is a suitable name',
                "status": {"name": "Resolved"},
                "resolution": {"name": "Fixed"},
                "resolutiondate": "2023-09-01T00:00:00.000+0000",
                "created": "2023-08-01T00:00:00.000+0000",
            },
        }
    ],
}


def _offline_fetch(url: str) -> str:
    if url.startswith(data.DEFAULT_NAME_SEARCH_API):
        issues = [issue for name, found in NAME_SEARCHES.items() if f"%5C%22{name}%5C%22" in url for issue in found]
        return json.dumps({"issues": issues})
    slug = url.rsplit("/", 1)[-1].removesuffix(".html")
    return STATUS_PAGES.get(slug, status_page())


class _OfflineMailClient:
    @staticmethod
    def load_cached_mail(*, cache_dir: str, **_: object) -> dict[str, object]:
        return {"cache_dir": cache_dir, "count": 0, "emails": []}

    @staticmethod
    def fetch_mail_stats(**_: object) -> dict[str, object]:
        return {"hits": 0, "emails": []}

    @staticmethod
    def fetch_podling_mail_stats(**_: object) -> dict[str, object]:
        return {"hits": 0, "emails": []}

    @staticmethod
    def cache_key(message_id: str) -> str:
        return message_id


FAKE_PODLINGS_DATA = dedent(
    """\
    from __future__ import annotations

    import os
    import xml.etree.ElementTree as ET
    from dataclasses import dataclass
    from typing import Any

    DEFAULT_SOURCE = "https://incubator.apache.org/podlings.xml"


    @dataclass
    class Podling:
        name: str
        status: str | None = None
        description: str | None = None
        resource: str | None = None
        sponsor: str | None = None
        sponsor_type: str | None = None
        champion: str | None = None
        mentors: list[str] | None = None
        startdate: str | None = None
        enddate: str | None = None


    def _text(node: ET.Element, tag: str) -> str | None:
        child = node.find(tag)
        return child.text.strip() if child is not None and child.text else None


    def _mentors(node: ET.Element) -> list[str]:
        mentors = node.find("mentors")
        if mentors is None:
            return []
        return [item.text.strip() for item in mentors.findall("mentor") if item.text and item.text.strip()]


    def _sponsor_type(value: str | None) -> str:
        if not value:
            return "unknown"
        return "incubator" if value.lower() in {"apache incubator", "incubator"} else "project"


    def parse_podlings(source: str) -> tuple[list[Podling], dict[str, Any]]:
        root = ET.parse(source).getroot()
        podlings = []
        for node in root.findall("./podling"):
            name = node.attrib.get("name")
            if not name:
                continue
            sponsor = node.attrib.get("sponsor")
            podlings.append(
                Podling(
                    name=name,
                    status=node.attrib.get("status"),
                    description=_text(node, "description"),
                    sponsor=sponsor,
                    sponsor_type=_sponsor_type(sponsor),
                    champion=_text(node, "champion"),
                    mentors=_mentors(node),
                    startdate=node.attrib.get("startdate"),
                    enddate=node.attrib.get("enddate"),
                )
            )
        podlings.sort(key=lambda item: item.name.lower())
        return podlings, {"source": os.path.abspath(source), "kind": "file", "count": len(podlings)}
    """
)


FAKE_HEALTH_PARSER = dedent(
    """\
    from __future__ import annotations

    from dataclasses import dataclass
    from pathlib import Path
    from typing import Any

    METRICS = {
        "Alpha": {
            "releases": 2,
            "new_contributors": 4,
            "unique_committers": 6,
            "commits": 40,
            "prs_merged": 10,
            "unique_authors": 6,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.5,
            "dev_unique_posters": 9,
            "trends": {"commits": "up", "new_contributors": "up", "prs_merged": "up", "dev_unique_posters": "up"},
        },
        "Bravo": {
            "releases": 0,
            "new_contributors": 1,
            "unique_committers": 2,
            "commits": 8,
            "prs_merged": 2,
            "unique_authors": 2,
            "reports_count": 0,
            "avg_mentor_signoffs": 1.0,
            "dev_unique_posters": 3,
            "trends": {
                "commits": "down",
                "new_contributors": "down",
                "prs_merged": "down",
                "dev_unique_posters": "flat",
            },
        },
        "Delta": {
            "releases": 1,
            "new_contributors": 3,
            "unique_committers": 5,
            "commits": 32,
            "prs_merged": 9,
            "unique_authors": 5,
            "reports_count": 1,
            "avg_mentor_signoffs": 2.5,
            "dev_unique_posters": 7,
            "trends": {"commits": "up", "new_contributors": "up", "prs_merged": "up", "dev_unique_posters": "up"},
        },
    }


    @dataclass
    class ParsedReport:
        podling: str
        path: str
        generated_on: str | None = "2026-04-18"


    def load_reports(reports_dir: str | Path) -> list[ParsedReport]:
        base = Path(reports_dir)
        return [
            ParsedReport(path.stem, str(path))
            for path in sorted(base.glob("*.md"))
            if path.stem in METRICS
        ]


    def summarize_report(report: ParsedReport) -> dict[str, Any]:
        metrics = dict(METRICS[report.podling])
        return {
            "podling": report.podling,
            "path": report.path,
            "generated_on": report.generated_on,
            "available_windows": ["3m", "12m"],
            "latest_metrics": {"3m": metrics, "6m": None, "12m": metrics, "to-date": None},
        }


    def reports_overview(reports_dir: str | Path) -> dict[str, Any]:
        reports = load_reports(reports_dir)
        return {
            "reports_dir": str(Path(reports_dir).resolve()),
            "report_count": len(reports),
            "podlings": sorted(report.podling for report in reports),
            "latest_generated_on": "2026-04-18" if reports else None,
        }
    """
)
