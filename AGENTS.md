# AGENTS

## Purpose

This repository contains a small dependency-light MCP server for Apache Incubator PMC (IPMC) oversight views.

It composes lifecycle data from the `apache-podlings-mcp` package and health-report data from the `apache-health-mcp` package into opinionated Incubator-level tools for podling risk, readiness, mentoring needs, and community-health summaries.

This is an IPMC / Incubator oversight MCP, not a board tool.

## Project Layout

- `ipmc/data.py`
  - Source loading, source MCP package imports, record composition, date helpers, and preferred health-window selection
- `ipmc/analysis.py`
  - Opinionated IPMC scoring, risk signals, readiness assessment, confidence, and community pattern helpers
- `ipmc/tools.py`
  - MCP tool handlers, argument validation helpers, and `TOOLS` registration
- `ipmc/schemas.py`
  - Shared tool schema fragments and schema-builder helpers
- `ipmc/protocol.py`
  - JSON-RPC/MCP stdio protocol handling
- `server.py`
  - Thin entrypoint
- `tests/`
  - Unit and integration tests
- `tests/fixtures.py`
  - Shared Python test fixtures and temporary source helpers
- `IPMCMCP.md`
  - Conceptual design and positioning notes
- `docs/architecture.md`
  - Module layout, runtime flow, design notes, and testing structure

## Key Defaults And Concepts

- `podlings_source` defaults to the ASF Incubator `podlings.xml` URL through `PodlingsMCP`.
- `health_source` defaults to the `--health-source` startup argument, or `reports` if unset.
- Source MCP modules are imported from installed packages; local sibling checkouts are not required.
- Oversight views focus on current podlings unless a lower-level helper explicitly includes non-current records.
- Health analysis prefers the freshest available window in this order: `3m`, `6m`, `12m`, `to-date`.
- Outputs should keep source facts separate from derived IPMC opinions.
- Tool names and descriptions should use IPMC / Incubator oversight language, not board language.

## Developer Workflow

Use these commands before finishing changes:

- `make check-format`
- `make lint`
- `make typecheck`
- `make test`

Coverage is available via:

- `make coverage`

Coverage is scoped to the local `ipmc` package so imported source MCP libraries do not dilute the report.

## Contribution Guidelines

- Keep source loading and composition in `ipmc/data.py`.
- Keep scoring heuristics and derived opinions in `ipmc/analysis.py`.
- Keep user-facing MCP tool behavior in `ipmc/tools.py`.
- Keep MCP tool schema definitions in `ipmc/schemas.py`.
- Keep protocol wiring in `ipmc/protocol.py`.
- Keep `server.py` minimal.
- Add tests for any new tool, filter, output shape, or scoring branch.
- Update `README.md` when changing public MCP tools or defaults.
- Update `IPMCMCP.md` when changing the conceptual framing or oversight model.
- Update `docs/architecture.md` when changing module boundaries or runtime flow.
- Avoid duplicating raw source MCP APIs without adding IPMC-level interpretation.

## Testing Notes

- Data composition behavior belongs in `tests/test_data.py`.
- Scoring and readiness behavior belongs in `tests/test_analysis.py`.
- Direct tool behavior belongs in `tests/test_tools.py`.
- Protocol helper behavior belongs in `tests/test_protocol.py`.
- End-to-end MCP stdio coverage belongs in `tests/test_mcp_integration.py`.
