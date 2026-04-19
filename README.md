# IPMC MCP

A small MCP server for Apache Incubator PMC oversight views.

It composes:

- podling lifecycle data from `apache-podlings-mcp`
- community and report signals from `apache-health-mcp`

It exposes opinionated Incubator-level tools to help the IPMC:

- identify podlings needing attention
- scan recent podling-level changes
- find Incubator reporting gaps
- review release visibility through a governance lens
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
ipmc-mcp --health-source /path/to/incubator/tools/health/reports
```

For local development without installing first, you can still run:

```bash
PYTHONPATH=/path/to/HealthMCP/src:/path/to/PodlingsMCP python3 server.py --health-source /path/to/incubator/tools/health/reports
```

The server uses `stdio`, so it is intended to be launched by an MCP client.

## Example MCP client config

```json
{
  "mcpServers": {
    "ipmc": {
      "command": "ipmc-mcp",
      "args": [
        "--health-source",
        "/Users/justinmclean/incubator/tools/health/reports"
      ]
    }
  }
}
```

The default runtime imports its source MCP libraries from installed packages:

- `apache-podlings-mcp`
- `apache-health-mcp`

When installed with `pip`, these dependencies are pulled from their Git repositories. If you run `server.py` directly from a checkout instead, make the source packages importable with `PYTHONPATH` or install them first. Tool calls can still override the source data paths with `podlings_source` and `health_source`.

Configure the default health reports directory with `--health-source`. If unset, it defaults to `reports`.

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

## Tools

### `recent_changes`

Return per-podling recent deltas the IPMC should scan. This is delta-based only: unchanged/static fields are excluded.

Arguments:

- `podlings_source`: optional URL or local file path for `podlings.xml`
- `health_source`: optional reports directory for apache-health markdown reports
- `as_of_date`: optional `YYYY-MM-DD` date for duration-sensitive views
- `podling`: optional podling name filter
- `limit`: optional max number of results

### `reporting_gaps`

Return podlings with Incubator reporting compliance gaps. Activity signals are intentionally excluded.

Arguments:

- `podlings_source`
- `health_source`
- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_gaps`: optional gap filter list

### `release_visibility`

Return release-governance visibility concerns, including no releases in 12 months, release gaps of at least 6 months, and activity-without-release mismatches.

Arguments:

- `podlings_source`
- `health_source`
- `as_of_date`
- `podling`: optional podling name filter
- `limit`: optional max number of results
- `include_signals`: optional release visibility signal filter list

### `stalled_podlings`

Return podlings matching the strict stalled definition: low commits, low committers, low discussion, and no 12-month releases. This is a narrow subset signal, not a replacement for the watchlist.

Arguments:

- `podlings_source`
- `health_source`
- `as_of_date`
- `limit`: optional max number of results

### `ipmc_watchlist`

Return podlings that most need IPMC attention based on combined lifecycle and health signals.

Arguments:

- `podlings_source`: optional URL or local file path for `podlings.xml`
- `health_source`: optional reports directory for apache-health markdown reports
- `as_of_date`: optional `YYYY-MM-DD` date for duration-sensitive views
- `limit`: optional max number of results
- `severity_at_least`: optional minimum severity filter
- `include_reasons`: optional reason filter list

### `graduation_readiness`

Assess whether a podling appears ready, near ready, or not yet ready for graduation.

Arguments:

- `podling`: required podling name
- `podlings_source`
- `health_source`
- `as_of_date`
- `include_evidence`: optional boolean, defaults to true
- `strict_mode`: optional boolean

### `podling_brief`

Return an IPMC-oriented briefing for one podling.

Arguments:

- `podling`: required podling name
- `podlings_source`
- `health_source`
- `as_of_date`
- `focus`: optional area list
- `brief_format`: optional `summary` or `detailed`

### `mentoring_attention_needed`

Return podlings where mentoring intervention appears necessary.

Arguments:

- `podlings_source`
- `health_source`
- `as_of_date`
- `limit`: optional max number of results
- `urgency_at_least`: optional minimum urgency filter
- `include_causes`: optional cause filter list

### `community_health_summary`

Return an IPMC-level summary of community-health patterns across podlings.

Arguments:

- `podlings_source`
- `health_source`
- `as_of_date`
- `scope`: optional `all_podlings`, `active_podlings`, or `reporting_podlings`
- `group_by`: optional `none`, `risk_band`, `mentor_load`, or `age_band`
- `include_examples`: optional boolean

## Defaults

- When omitted, `podlings_source` defaults to the ASF `podlings.xml` URL.
- When omitted, `health_source` uses `--health-source`, or `reports` if that startup argument is unset.
- Oversight views focus on current podlings by default.
- Health analysis prefers the freshest available window in this order: `3m`, `6m`, `12m`, `to-date`.

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

- `source_data_used`: the podlings and apache-health fields that informed the opinion
- `reasoning`: human-readable explanation of why the opinion was reached
- `confidence`: high, medium, or low confidence in the opinion based on source coverage
- `missing`: source evidence that is absent or would improve the assessment

Per-podling tools attach this to podling-level judgments and supporting signals. The community-health summary attaches it to the overall summary and each derived risk theme.
