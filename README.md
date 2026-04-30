# IPMC MCP

A small MCP server for Apache Incubator PMC oversight views.

It composes:

- podling lifecycle data from `apache-podlings-mcp`
- community and report signals from `apache-health-mcp`
- cached Incubator report entries from `apache-incubator-reports-mcp`
- cached Incubator general-list messages from `apache-incubator-mail-mcp`
- live Incubator release vote/result thread evidence from `apache-incubator-mail-mcp`
- release artifact, signature, checksum, and cadence evidence from `apache-incubator-releases-mcp`

It exposes opinionated Incubator-level tools to help the IPMC:

- identify podlings needing attention
- scan recent podling-level changes
- find Incubator reporting gaps
- surface recurring or unresolved report-narrative issues from cached Incubator reports
- highlight concrete mismatches between report narrative and current health or release evidence
- review release visibility and Incubator release vote evidence through a governance lens
- identify tightly-defined stalled podlings
- assess graduation readiness
- generate podling briefings
- flag mentoring intervention needs
- summarize community-health patterns across podlings

## Requirements

- Python 3.12+

## Install

```bash
python3 -m pip install .
```

For development tools:

```bash
python3 -m pip install -e .[dev]
```

## Run

After installation, run the stdio MCP server with:

```bash
ipmc-mcp \
  --health-source /path/to/incubator/tools/health/reports \
  --report-source /path/to/ReportMCP/.cache/incubator-reports \
  --mail-source /path/to/MailMCP/.cache/incubator-general-mail
```

For local development without installing first, you can still run:

```bash
PYTHONPATH=/path/to/HealthMCP/src:/path/to/PodlingsMCP/src:/path/to/ReportMCP/src:/path/to/MailMCP/src:/path/to/ReleaseMCP/src \
  python3 server.py \
  --health-source /path/to/incubator/tools/health/reports \
  --report-source /path/to/ReportMCP/.cache/incubator-reports \
  --mail-source /path/to/MailMCP/.cache/incubator-general-mail
```

By default the server uses `stdio`, so it is intended to be launched by an MCP client.

To serve the same JSON-RPC/MCP protocol over HTTP instead, pass `--http`:

```bash
ipmc-mcp \
  --http \
  --host 127.0.0.1 \
  --port 8080 \
  --health-source /path/to/incubator/tools/health/reports \
  --report-source /path/to/ReportMCP/.cache/incubator-reports \
  --mail-source /path/to/MailMCP/.cache/incubator-general-mail
```

HTTP mode uses the official MCP Streamable HTTP transport at `/mcp` and exposes a simple `GET /health` endpoint. `--host` and `--port` only affect HTTP mode. For public hosting and Claude connector setup, see [docs/hosting.md](docs/hosting.md).

## Example MCP client config

```json
{
  "mcpServers": {
    "ipmc": {
      "command": "ipmc-mcp",
      "args": [
        "--health-source",
        "/path/to/incubator/tools/health/reports",
        "--report-source",
        "/path/to/ReportMCP/.cache/incubator-reports",
        "--mail-source",
        "/path/to/MailMCP/.cache/incubator-general-mail"
      ]
    }
  }
}
```

The default runtime imports its source MCP libraries from installed packages:

- `apache-podlings-mcp`
- `apache-health-mcp`
- `apache-incubator-reports-mcp`
- `apache-incubator-mail-mcp`
- `apache-incubator-releases-mcp`

When installed with `pip`, these dependencies are pulled from their Git repositories. If you run `server.py` directly from a checkout instead, make the source packages importable with `PYTHONPATH` or install them first.

Configure startup defaults with command-line arguments or environment variables:

- `--podlings-source` or `IPMC_PODLINGS_SOURCE`: optional URL or local path for `podlings.xml`
- `--health-source` or `IPMC_HEALTH_SOURCE`: local path for apache-health report Markdown files
- `--report-source` or `IPMC_REPORT_SOURCE`: local path for ReportMCP cached ASF Incubator report files
- `--mail-source` or `IPMC_MAIL_SOURCE`: local path for MailMCP cached ASF Incubator general-list message files
- `--mail-api-base` or `IPMC_MAIL_API_BASE`: MailMCP/Pony Mail API base URL for live Incubator general-list search
- `--release-dist-base` or `IPMC_RELEASE_DIST_BASE`: ReleaseMCP `dist.apache.org` base URL or local release directory
- `--release-archive-base` or `IPMC_RELEASE_ARCHIVE_BASE`: ReleaseMCP `archive.apache.org` base URL or local archive directory
- `--http`: serve JSON-RPC/MCP over HTTP instead of stdio
- `--host`: HTTP bind host when `--http` is set; defaults to `127.0.0.1`
- `--port`: HTTP bind port when `--http` is set; defaults to `8080`

Source defaults can also be set once per MCP session with `configure_sources`. Normal tool calls should only pass task arguments such as `podling`, `limit`, or filters; per-tool source arguments are for one-off overrides.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Coverage

```bash
python3 -m coverage run -m unittest discover -s tests
python3 -m coverage report -m
```

Coverage is scoped to the local `ipmc` package so imported source MCP libraries do not dilute the report.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the module layout, runtime flow, and testing structure.

## Usage Examples

These examples show prompts an IPMC member or mentor could type into an MCP client.

### Monthly IPMC Review Workflow

Use this when preparing for a monthly Incubator oversight pass:

- "What changed across current podlings since the last IPMC review?"
- "Which podlings need IPMC attention this month, and why?"
- "Which podlings have crossed a year without a visible release, or show a meaningful activity shift?"
- "Group this reporting cohort into reporting issues, release visibility issues, recent changes, and no obvious concerns."
- "Show me current podlings with reporting gaps, but keep that separate from community health concerns."
- "Which podlings have repeated reporting reliability issues rather than a one-off late report?"
- "Which current podlings call out unresolved issues in their recent Incubator reports?"
- "Show me recurring issues from cached Incubator reports, and flag where the latest report still needs mentor follow-up."
- "Compare reported podling issues with health signals and tell me which podlings need follow-up."
- "Show me podlings where the latest report narrative and current health evidence point in different directions."
- "Which current podlings do not appear to have a recent Incubator report?"
- "Highlight podlings where the report narrative and recent health metrics point to different risks."
- "Which podlings have release visibility concerns that the IPMC should look at?"
- "Which podlings look genuinely stalled, based on low activity, low discussion, and no recent releases?"
- "Give me a detailed brief for the podlings that look most concerning."

This gives reviewers a short queue of what changed, what needs attention, and what evidence supports each opinion.

### Mentor Checking Their Podlings

Use this when a mentor wants a fast status check before following up with podling communities:

- "Give me a focused brief for FooPodling covering reporting, releases, mentoring, and community health."
- "What is FooPodling's current Incubator reporting schedule?"
- "Does FooPodling look ready for graduation, and what evidence is missing?"
- "Show the recent Incubator report evidence for FooPodling, including issues, last release, and observed mentor sign-offs."
- "For FooPodling, separate source facts from IPMC interpretation and tell me what I should verify with the community."
- "What has FooPodling reported as unfinished issues, and do the health metrics support those concerns?"
- "Show me FooPodling's mentor sign-off evidence without treating partial sign-off as a failure."
- "Which podlings appear to need mentor intervention?"
- "Show me podlings with missing mentor sign-offs or weak mentor coverage."

This keeps source facts, derived concerns, and confidence visible so mentors can decide what needs action versus clarification.

### General List Mail Evidence

Use this when a reviewer wants to check Incubator general-list discussion alongside podling reports and health signals:

- "Search general incubator mail for recent FooPodling graduation, release, or retirement discussion and summarize the relevant email evidence."
- "For FooPodling, compare Incubator report concerns with recent general-list email threads that mention the podling."
- "Show likely Incubator release vote and result threads for FooPodling and compare them with release visibility signals."
- "Show FooPodling release artifacts, signatures, checksums, and Incubator naming evidence."

### Generating a Board Summary

This server is not a board tool, but it can help assemble Incubator context for a human-written board report:

- "Summarize the main community-health themes across current podlings, with examples."
- "Which high-risk podlings may need narrative attention in the Incubator report?"
- "Use recent Incubator reports to identify repeated podling themes that may need IPMC follow-up."
- "Find podlings whose report narratives mention graduation blockers and summarize the supporting health evidence."
- "Which podlings have recurring issues across their Incubator report history?"
- "Give me an evidence-backed list of podlings where the report narrative and release visibility both need attention."
- "List reporting compliance issues separately from release-governance concerns."
- "Give me short evidence-backed briefs for the podlings most likely to be mentioned by name."

The intended output is briefing material for IPMC judgment, not text that should be copied into a board report without review.

## Tools

Set source paths once with `configure_sources`. After that, use the normal tool arguments below; only pass source paths
to an individual tool when you really want to override the session defaults for that one call.

### `configure_sources`

Set or inspect the source paths used by later tool calls.

### `recent_changes`

Return per-podling recent deltas the IPMC should scan. This is delta-based only: unchanged/static fields are excluded.

Arguments:

- `as_of_date`: optional `YYYY-MM-DD` date for duration-sensitive views
- `podling`: optional podling name filter
- `limit`: optional max number of results

### `significant_changes`

Return a structured factual subset of recent changes that usually merit IPMC scan attention. This currently includes
podlings with no visible releases in the 12-month health window, review-worthy activity shifts between the 3-month and
12-month windows, newly missing reports, and release visibility disappearing.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_signals`: optional signal filter list

### `reporting_gaps`

Return podlings with Incubator reporting compliance gaps. Activity signals are intentionally excluded.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_gaps`: optional gap filter list

### `reporting_reliability`

Return objective reporting reliability patterns over time, grouped into consistently on time, occasional late, repeated late, repeated missing, and reporting data unavailable. Categories compare observed report counts with the expected Incubator cadence: monthly for the first quarter, then quarterly after that. A single missed expected report is treated as an occasional catch-up-next-month case, not a systemic issue. Exact due-date timeliness is not visible from rolling report counts.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results per category
- `include_categories`: optional reporting reliability category filter list

### `release_visibility`

Return release-governance visibility concerns, including no releases in 12 months, release gaps of at least 6 months, and activity-without-release mismatches.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_signals`: optional release visibility signal filter list

### `release_vote_evidence`

Return likely MailMCP release vote/result thread evidence for one podling alongside IPMC release visibility signals.

Arguments:

- `podling`: required podling name
- `as_of_date`
- `mail_timespan`: optional MailMCP timespan expression, defaults to the MailMCP release-search window
- `limit`: optional max number of vote/result threads

### `release_artifact_evidence`

Return ReleaseMCP artifact, signature, checksum, cadence, and Incubator naming evidence for one podling.

Arguments:

- `podling`: required podling name
- `release_max_depth`: optional traversal depth under the podling directory, defaults to `1`; use `0` for a shallower scan

### `refresh_report_cache`

Refresh cached ASF Incubator report data used by the report-narrative and cross-source tools.

Arguments:

- `report_source`: optional cache directory override
- `years`: optional years of history to cache; `null` means full history
- `limit`: optional max number of reports to cache
- `report_url`: optional single report URL to cache instead of refreshing recent reports
- `report_id`: optional report id for a single report URL

### `refresh_mail_cache`

Refresh cached general@incubator.apache.org message summaries used by mail evidence tools.

Arguments:

- `mail_source`: optional cache directory override
- `mail_api_base`: optional Pony Mail API base URL
- `mail_timespan`: optional MailMCP timespan expression
- `query`: optional search query
- `limit`: optional max number of message summaries to cache

### `reporting_cohort`

Return current reporting podlings grouped into non-ranked IPMC review buckets: reporting issues, release visibility issues, recent significant changes, and no obvious concerns.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter

### `report_narrative_signals`

Return report-derived signals from cached Incubator reports, including latest reported issues, recurring issues across report history, possible copy-forward narrative text between consecutive reports, low observed mentor sign-off, and mismatches between report narrative release claims and health-based release visibility.

When `podling` is provided, this lookup can use non-current or report-cache-only podlings if matching source data is available.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_signals`: optional report narrative signal filter list

### `cross_source_mismatches`

Return concrete mismatches between cached report narrative and current health or release evidence, such as a quiet latest report despite elevated health risk, a reported last release with no 12-month release visibility, or a one-report mentor sign-off drop that differs from the rolling average.

When `podling` is provided, this lookup can use non-current or report-cache-only podlings if matching source data is available.

Arguments:

- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_signals`: optional cross-source mismatch filter list

### `stalled_podlings`

Return podlings matching the strict stalled definition: low commits, low committers, low discussion, and no 12-month releases. This is a narrow subset signal, not a replacement for the watchlist.

Arguments:

- `as_of_date`
- `limit`: optional max number of results

### `ipmc_watchlist`

Return podlings that most need IPMC attention based on combined lifecycle and health signals.

Arguments:

- `as_of_date`: optional `YYYY-MM-DD` date for duration-sensitive views
- `limit`: optional max number of results
- `severity_at_least`: optional minimum severity filter
- `include_reasons`: optional reason filter list

### `graduation_readiness`

Assess whether a podling appears ready, near ready, or not yet ready for graduation.

Arguments:

- `podling`: required podling name
- `as_of_date`
- `include_evidence`: optional boolean, defaults to true
- `strict_mode`: optional boolean

### `podling_brief`

Return an IPMC-oriented briefing for one podling.

Arguments:

- `podling`: required podling name
- `as_of_date`
- `focus`: optional area list
- `brief_format`: optional `summary` or `detailed`

### `mentoring_attention_needed`

Return podlings where mentoring intervention appears necessary.

Arguments:

- `as_of_date`
- `limit`: optional max number of results
- `urgency_at_least`: optional minimum urgency filter
- `include_causes`: optional cause filter list

### `community_health_summary`

Return an IPMC-level summary of community-health patterns across podlings.

Arguments:

- `as_of_date`
- `scope`: optional `all_podlings`, `active_podlings`, or `reporting_podlings`
- `group_by`: optional `none`, `risk_band`, `mentor_load`, or `age_band`
- `include_examples`: optional boolean

## Defaults

- When omitted, `podlings_source` uses `--podlings-source`, `IPMC_PODLINGS_SOURCE`, or the ASF `podlings.xml` URL.
- When omitted, `health_source` uses `--health-source`, `IPMC_HEALTH_SOURCE`, or `reports` if no startup default is set.
- When omitted, `report_source` uses `--report-source`, `IPMC_REPORT_SOURCE`, or `.cache/incubator-reports` if no startup default is set.
- When omitted, `mail_source` uses `--mail-source`, `IPMC_MAIL_SOURCE`, or `.cache/incubator-general-mail` if no startup default is set. If the default cache is missing, IPMC tools use live MailMCP search as a read-only fallback.
- When omitted, `mail_api_base` uses `--mail-api-base`, `IPMC_MAIL_API_BASE`, or the public lists.apache.org API.
- When omitted, `release_dist_base` uses `--release-dist-base`, `IPMC_RELEASE_DIST_BASE`, or the public Incubator dist release URL.
- When omitted, `release_archive_base` uses `--release-archive-base`, `IPMC_RELEASE_ARCHIVE_BASE`, or the public Incubator archive URL.
- Oversight views focus on current podlings by default.
- Single-podling lookups can still return non-current or report-cache-only podlings when matching source data is available.
- Health analysis prefers the freshest available window in this order: `3m`, `6m`, `12m`, `to-date`.
- Source metadata consistently exposes a `source` field. Health and ReportMCP metadata also preserve the upstream
  `reports_dir` field, and MailMCP metadata preserves `cache_dir`, for compatibility with their source MCPs.

## Opinion Model

This server keeps source facts separate from derived opinions. Risk and readiness views are derived from:

- mentor coverage
- reporting reliability
- mentor sign-off signals
- community activity
- release visibility
- incubation duration
- participation breadth

The resulting outputs are intended to support IPMC judgment, not replace it.

Opinionated outputs include an `explainability` object so IPMC members can challenge the result:

- `source_data_used`: the podlings, apache-health, ReportMCP, and MailMCP fields that informed the opinion
- `reasoning`: human-readable explanation of why the opinion was reached
- `confidence`: high, medium, or low confidence in the opinion based on source coverage
- `missing`: source evidence that is absent or would improve the assessment

Per-podling tools attach this to podling-level judgments and supporting signals. The community-health summary attaches it to the overall summary and each derived risk theme.
