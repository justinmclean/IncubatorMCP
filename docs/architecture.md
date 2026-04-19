# Architecture

## Overview

`IPMC MCP` exposes Apache Incubator PMC oversight views through a small MCP-compatible stdio server.

It does not replace the source MCPs. Instead, it composes:

- `PodlingsMCP` for podling lifecycle and status data
- `HealthMCP` for parsed health-report metrics

The resulting tools provide IPMC-oriented synthesis: watchlists, graduation readiness, podling briefs, mentoring attention, and community-health summaries.

## Runtime Flow

1. An MCP client launches `server.py` over stdio.
2. `server.py` delegates to `ipmc.protocol.main`.
3. `ipmc.protocol` handles JSON-RPC/MCP messages and dispatches tool calls.
4. `ipmc.tools` validates arguments and calls the relevant oversight tool handler.
5. `ipmc.data` loads and composes source data from the sibling MCPs.
6. `ipmc.analysis` derives IPMC-level risk, readiness, confidence, and community signals.
7. `ipmc.protocol` serializes the tool result back to the MCP client.

## Modules

### `ipmc/data.py`

This module is responsible for source loading and composition.

It:

- imports `PodlingsMCP` and `HealthMCP` modules
- resolves sibling repository locations
- resolves the health reports directory from the tool `health_source`, `--health-source`, or `reports`
- loads podling lifecycle records
- loads health report summaries
- joins source data into `OversightRecord` objects
- selects the preferred health window in this order: `3m`, `6m`, `12m`, `to-date`

Sibling repository locations and the default health reports directory can be configured with startup arguments:

- `--podlings-mcp-repo`
- `--health-mcp-repo`
- `--health-source`

### `ipmc/analysis.py`

This module owns derived IPMC opinions.

It:

- evaluates podling risk signals
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
- lookup helpers
- tool output shaping
- the `TOOLS` registry

The public tools are:

- `ipmc_watchlist`
- `graduation_readiness`
- `podling_brief`
- `mentoring_attention_needed`
- `community_health_summary`

### `ipmc/schemas.py`

This module contains shared MCP input schema fragments and schema builder helpers.

New tool schema definitions should be added here rather than inline in `protocol.py`.

### `ipmc/protocol.py`

This module implements the stdio MCP/JSON-RPC behavior.

It supports:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`

The protocol layer should only orchestrate requests and responses. It should not own IPMC scoring or data composition logic.

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

Tests are self-contained. They create temporary fake sibling MCP modules so CI does not need real `PodlingsMCP` or `HealthMCP` checkouts.

## Design Notes

- This is an IPMC / Incubator oversight tool, not a board tool.
- Source facts should remain distinguishable from derived opinions.
- Tool outputs should be actionable but transparent about evidence and confidence.
- `ipmc/data.py` should stay free of MCP protocol concerns.
- `ipmc/analysis.py` should be the single place for opinionated scoring rules.
- `ipmc/protocol.py` should stay small and generic.
- `server.py` should remain a stable, minimal executable entrypoint.
