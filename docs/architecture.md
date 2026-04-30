# Architecture

## Overview

`IPMC MCP` exposes Apache Incubator PMC oversight views through a small MCP-compatible server. It defaults to stdio and can optionally serve the same JSON-RPC/MCP behavior over HTTP.

It does not replace the source MCPs. Instead, it composes:

- `apache-podlings-mcp` for podling lifecycle and status data
- `apache-health-mcp` for parsed health-report metrics
- `apache-incubator-reports-mcp` for cached Incubator report entries
- `apache-incubator-mail-mcp` for cached Incubator general-list message summaries and live release vote/result thread evidence
- `apache-incubator-releases-mcp` for release artifact, signature, checksum, cadence, and Incubator naming evidence

The resulting tools provide IPMC-oriented synthesis: recent-change scans, reporting-gap checks, reporting-reliability patterns, release-visibility checks, release vote evidence, release artifact evidence, stalled-podling detection, watchlists, graduation readiness, podling briefs, mentoring attention, and community-health summaries.

## Runtime Flow

1. An MCP client launches `server.py` over stdio, or the server is started with `--http` to accept HTTP JSON-RPC requests.
2. `server.py` delegates to `ipmc.protocol.main`.
3. `ipmc.protocol` handles JSON-RPC/MCP messages from the selected transport and dispatches tool calls.
4. `ipmc.tools` validates arguments and calls the relevant oversight tool handler.
5. `ipmc.data` loads and composes source data from installed source MCP libraries.
6. `ipmc.analysis` derives IPMC-level risk, readiness, confidence, and community signals.
7. `ipmc.protocol` wraps the tool result for the MCP client, using `structuredContent` for structured payloads and a JSON text fallback in `content`.

## Modules

### `ipmc/data.py`

This module is responsible for source loading and composition.

It:

- imports `PodlingsMCP`, `HealthMCP`, ReportMCP, MailMCP, and ReleaseMCP modules
- resolves podlings data from the tool `podlings_source`, `--podlings-source`, `IPMC_PODLINGS_SOURCE`, or the ASF `podlings.xml` URL
- resolves the health reports directory from the tool `health_source`, `--health-source`, `IPMC_HEALTH_SOURCE`, or `reports`
- resolves cached Incubator reports from the tool `report_source`, `--report-source`, `IPMC_REPORT_SOURCE`, or `.cache/incubator-reports`
- resolves cached Incubator general-list mail from the tool `mail_source`, `--mail-source`, `IPMC_MAIL_SOURCE`, or `.cache/incubator-general-mail`
- resolves the live MailMCP/Pony Mail API base from the tool `mail_api_base`, `--mail-api-base`, `IPMC_MAIL_API_BASE`, or the public lists.apache.org API
- resolves ReleaseMCP dist/archive sources from tool arguments, startup defaults, environment variables, or public ASF URLs
- loads podling lifecycle records
- loads health report summaries
- loads ReportMCP podling report entries when cached reports are available
- loads MailMCP general-list message summaries when a tool needs them; if the default cache is missing, this uses read-only live MailMCP search
- loads MailMCP release vote/result thread history for the `release_vote_evidence` tool only
- loads ReleaseMCP artifact/cadence evidence for the `release_artifact_evidence` tool only
- refreshes ReportMCP and MailMCP caches through explicit cache tools
- joins source data into `OversightRecord` objects
- supports targeted single-podling fallback records when a requested podling is absent from the current podlings set but present in cached report, health, or mail source data
- selects the preferred health window in this order: `3m`, `6m`, `12m`, `to-date`

The default sources can be configured with startup arguments:

- `--podlings-source`
- `--health-source`
- `--report-source`
- `--mail-source`
- `--mail-api-base`
- `--release-dist-base`
- `--release-archive-base`

They can also be configured with environment variables:

- `IPMC_PODLINGS_SOURCE`
- `IPMC_HEALTH_SOURCE`
- `IPMC_REPORT_SOURCE`
- `IPMC_MAIL_SOURCE`
- `IPMC_MAIL_API_BASE`
- `IPMC_RELEASE_DIST_BASE`
- `IPMC_RELEASE_ARCHIVE_BASE`

### `ipmc/analysis.py`

This module owns derived IPMC opinions.

It:

- evaluates podling risk signals
- identifies narrow recent-change, reporting-gap, reporting-reliability, release-visibility, and stalled-podling signals
- derives severity and trend
- estimates confidence
- assesses graduation readiness
- classifies community-health patterns

This is where scoring and heuristic changes should happen. Tool handlers should not duplicate scoring rules.

### `ipmc/tools.py`

This module provides user-facing MCP tool handlers.

It owns:

- argument validation helpers
- source argument resolution
- process-level source default configuration
- lookup helpers
- tool output shaping
- explainability envelopes for derived opinions
- the `TOOLS` registry

The public tools are:

- `recent_changes`
- `configure_sources`
- `significant_changes`
- `reporting_gaps`
- `reporting_reliability`
- `release_visibility`
- `release_vote_evidence`
- `release_artifact_evidence`
- `refresh_report_cache`
- `refresh_mail_cache`
- `reporting_cohort`
- `stalled_podlings`
- `ipmc_watchlist`
- `graduation_readiness`
- `podling_brief`
- `mentoring_attention_needed`
- `community_health_summary`

### `ipmc/schemas.py`

This module contains shared MCP input schema fragments and schema builder helpers.

New tool schema definitions should be added here rather than inline in `protocol.py`.

### `ipmc/protocol.py`

This module implements the MCP/JSON-RPC behavior and the supported transports.

It supports:

- stdio transport by default
- MCP SDK Streamable HTTP transport when started with `--http`
- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`
- JSON-RPC batch requests
- structured JSON-RPC errors for parse errors, invalid requests, invalid params, and unknown methods

The HTTP transport is backed by the official MCP Python SDK Streamable HTTP session manager at `/mcp`, exposes `GET /health`, and uses the same tool registry as stdio. The protocol layer should only orchestrate requests and responses. It should not own IPMC scoring or data composition logic. Structured tool results are returned as both MCP `structuredContent` and a JSON text fallback for clients that only read `content`.

### `server.py`

This file is intentionally tiny. It imports `main` from `ipmc.protocol` and exits with that return code.

## Testing

The tests mirror the runtime split:

- `tests/test_data.py`
  Data loading, source composition, startup configuration, and date/window helpers.
- `tests/test_analysis.py`
  Risk scoring, readiness assessment, confidence, trends, and community pattern behavior.
- `tests/test_tools.py`
  Direct tool behavior, filtering, validation, and output shaping.
- `tests/test_protocol.py`
  JSON-RPC/MCP helper behavior and protocol error handling.
- `tests/test_mcp_integration.py`
  End-to-end stdio tests that spawn `server.py`.

Tests are self-contained. They use temporary source data while importing the installed source MCP libraries, so CI does not need sibling repository checkouts.

## Design Notes

- This is an IPMC / Incubator oversight tool, not a board tool.
- Source facts should remain distinguishable from derived opinions.
- Source metadata should expose `source` consistently; package-specific metadata keys such as `reports_dir` and `cache_dir` may be retained as aliases.
- Narrow tools should stay narrow: recent changes are delta-only, significant changes are factual scan-worthy changes only, reporting gaps are compliance-only, release visibility is governance-only, and stalled podlings require all stall conditions.
- Tool outputs should be actionable but transparent about evidence and confidence.
- Each opinionated output should expose source data used, human-readable reasoning, confidence, and missing evidence.
- `ipmc/data.py` should stay free of MCP protocol concerns.
- `ipmc/analysis.py` should be the single place for opinionated scoring rules.
- `ipmc/protocol.py` should stay small and generic.
- `server.py` should remain a stable, minimal executable entrypoint.
