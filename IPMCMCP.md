# IPMCMCP

## Purpose

`IPMCMCP` is an Incubator oversight MCP for the Apache Incubator PMC (IPMC).

It is not a board tool.

Its role is to help the IPMC:

- assess podling health, risk, and momentum
- identify where mentor or IPMC attention is needed
- evaluate graduation readiness
- combine multiple raw Incubator data sources into opinionated oversight views

## Position In The MCP Stack

This MCP sits above source/data MCPs.

- `PodlingsMCP`: raw podling lifecycle and status data
- `apache-health`: raw community and health-report data
- `IPMCMCP`: IPMC-oriented synthesis, scoring, and oversight views

In other words:

- source MCPs answer: "what happened?"
- `IPMCMCP` answers: "what should the IPMC pay attention to?"

## Non-Goals

`IPMCMCP` should avoid:

- board-level framing or governance language
- duplicating raw source data APIs without adding interpretation
- replacing podling reports, mentors, or IPMC judgment

It should be opinionated, but transparent about how it reaches its conclusions.

## Core Design Principles

- Use Incubator and IPMC terminology consistently.
- Keep source facts separate from derived opinions.
- Expose confidence, caveats, and missing data.
- Make outputs actionable for oversight rather than descriptive only.

## Primary Inputs

### From `PodlingsMCP`

- podling status and age
- incubation start date
- current mentors and champions
- report history and timeliness
- releases, votes, and milestone events
- graduation or retirement signals

### From `apache-health`

- community activity summaries
- committer and contributor trend signals
- mailing list or discussion activity
- issue/PR responsiveness patterns
- release cadence and development momentum
- health-report indicators and anomalies

## Derived Oversight Signals

`IPMCMCP` can combine raw inputs into a small set of derived signals such as:

- reporting reliability
- mentor coverage and mentor engagement risk
- community activity trend
- release/process maturity
- diversity and resilience of participation
- governance readiness
- graduation momentum
- stagnation or distress indicators

These should be explainable and linked back to source evidence.

## Proposed Tools

### `ipmc_watchlist`

Returns the podlings that most need IPMC attention right now.

Example focus areas:

- missing or late reports
- low mentor engagement
- weak community activity
- stalled releases
- repeated governance/process concerns

Suggested output shape:

- podling name
- watch reason
- severity
- trend
- recommended next IPMC action
- supporting signals

### `graduation_readiness`

Assesses whether a podling appears ready, near-ready, or not yet ready for graduation.

Suggested dimensions:

- community independence
- release maturity
- governance/process health
- mentor confidence indicators
- sustained activity over time

Suggested output shape:

- readiness assessment
- strengths
- blockers
- missing evidence
- recommended next steps

### `podling_brief`

Produces a concise IPMC-oriented briefing for a single podling.

This should summarize:

- current status
- recent trajectory
- key health indicators
- active concerns
- mentor/IPMC attention areas
- graduation or risk outlook

Suggested use:

- pre-meeting briefing
- quick triage
- mentor support context

### `mentoring_attention_needed`

Highlights podlings where mentoring intervention appears necessary.

Possible triggers:

- absent or overloaded mentor coverage
- repeated missed reports
- lack of releases or community progress
- unresolved governance confusion
- signs of low project energy

Suggested output shape:

- podling name
- attention reason
- urgency
- suggested mentor/IPMC follow-up

### `community_health_summary`

Returns an IPMC-level summary of community health across podlings.

This is not just a raw activity rollup; it should identify:

- strong community patterns
- weakening projects
- common risk themes
- improving podlings
- where Incubator mentoring capacity may be stretched

## Example MCP Questions

- Which podlings need IPMC attention this month?
- Which podlings look closest to graduation, and why?
- Which podlings have concerning combinations of weak activity and poor reporting?
- Where does mentor attention appear insufficient?
- Give me an IPMC briefing for podling `X`.

## Opinion Model

Each opinionated result should include:

- source systems used
- key signals considered
- confidence level
- rationale
- recommended action

That keeps the MCP useful for oversight while still auditable.

## Naming

Recommended names, in order:

1. `IPMCMCP`
2. `IncubatorOversightMCP`
3. `IncubatorIPMCMCP`

`IPMCMCP` is the clearest and shortest name if the audience already understands Apache Incubator governance.

## Short Positioning Statement

`IPMCMCP` is an Apache Incubator oversight MCP that synthesizes lifecycle and health data into actionable IPMC views about podling risk, health, mentoring needs, and graduation readiness.

## Concrete Tool Schema

A concrete MCP tool definition in the same Python form as `PodlingsMCP` is now provided in:

- [server.py](/Users/justinmclean/IncubatorMCP/server.py)
- [ipmc/protocol.py](/Users/justinmclean/IncubatorMCP/ipmc/protocol.py)
- [ipmc/schemas.py](/Users/justinmclean/IncubatorMCP/ipmc/schemas.py)
- [ipmc/tools.py](/Users/justinmclean/IncubatorMCP/ipmc/tools.py)

This mirrors the `PodlingsMCP` pattern:

- schema helper functions in `schemas.py`
- tool registration in a `TOOLS` dict
- MCP `tools/list` exposure through `protocol.py`

The handlers are schema placeholders for now and still need implementation.
