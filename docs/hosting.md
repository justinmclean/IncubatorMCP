# Hosting

IPMC MCP can be hosted as a public, unauthenticated HTTP MCP endpoint because its tools expose public Apache Incubator oversight data.

## Lean Setup

Run the server on a host that can reach the configured source data:

```bash
ipmc-mcp \
  --http \
  --host 127.0.0.1 \
  --port 8765 \
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
  reverse_proxy 127.0.0.1:8765
}
```

Use `GET /health` for uptime checks.

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
- The `/mcp` endpoint accepts JSON-RPC MCP `POST` requests. It does not provide a server-initiated event stream for `GET /mcp`.
