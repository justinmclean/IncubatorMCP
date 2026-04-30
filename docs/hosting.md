# Hosting

IPMC MCP can be hosted as a public, unauthenticated HTTP MCP endpoint because its tools expose public Apache Incubator oversight data.

## Lean Setup

Run the server on a host that can reach the configured source data:

```bash
ipmc-mcp \
  --http \
  --host 127.0.0.1 \
  --port 8080 \
  --health-source /path/to/incubator/tools/health/reports \
  --report-source /path/to/ReportMCP/.cache/incubator-reports \
  --mail-source /path/to/MailMCP/.cache/incubator-general-mail
```

Expose it through HTTPS at a stable public URL, for example:

```text
https://ipmc-mcp.example.org/mcp
```

A small reverse proxy such as Caddy is enough:

```caddyfile
ipmc-mcp.example.org {
  reverse_proxy 127.0.0.1:8080
}
```

Use `GET /health` for uptime checks.

## Fly.io

This repository includes a `Dockerfile` and `fly.toml` for a small Fly deployment.

Create the persistent volume before the first deploy:

```bash
fly volumes create ipmc_data --size 1 --region lax --app incubatormcp
```

Deploy from the repository root:

```bash
fly deploy
```

## Claude Connector

In Claude, add a custom connector using:

```text
Name: IPMC MCP
URL: https://ipmc-mcp.example.org/mcp
```

No authentication is required.

## Notes

- Keep the Python process bound to localhost when using a reverse proxy.
- Use `--host 0.0.0.0` only when the hosting platform requires the app process to listen on all interfaces.
- The `/mcp` endpoint uses the official MCP Streamable HTTP transport from the MCP Python SDK.
