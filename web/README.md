# lis-web

The stdio MCP server (name `lis-web`) that a `scripts/claude-local.ps1 -LisWeb` session
runs inside the lis-web container (`container/Dockerfile` copies this directory to
`/opt/lis-web`).
Plain JavaScript, no build step; the tools are ported from the Jarvis agent-controller's
`jarvis-web` server, which LIS no longer needs.

| Tool | Service | Key (env) |
| --- | --- | --- |
| `web_search` | Brave Search API | `BRAVE_SEARCH_API_KEY` |
| `exa_search` | Exa search API | `EXA_API_KEY` |
| `jina_search` | Jina search (s.jina.ai) | `JINA_API_KEY` |
| `web_read` | Jina Reader (r.jina.ai) | none (`JINA_API_KEY` raises the rate limit) |
| `web_read_tweet` | api.fxtwitter.com, then X's syndication endpoint | none |

- Keys come from the process environment only; the server reads no `.env`. A missing key
  makes its tool return an error naming the variable.
- The keys file is `<repo>\.env` (gitignored; the three names above). The `-LisWeb`
  launcher passes those three names, and no other line, to the container in its env file,
  and hides `/lis/.env` inside the container behind an empty read-only file.
- `LIS_WEB_LOG`: a file that gets one line per call (time, tool, outcome, result bytes,
  URL host, query cut to 80 chars and redacted). Unset: no log. The launcher sets
  `/lis/logs/web-calls.log` (the per-run logs directory).
- Arguments that look like credentials (token prefixes, a JWT, a bearer header, any
  string over 2,000 chars) are refused before the tool runs. This is a speed bump, not
  a guarantee:
  an encoded or split secret passes.
- No browser fallback: a Cloudflare challenge returns the tool's error. A page over 5,000
  chars is cut to its first 5,000 (`truncated: true`); nothing is written to disk.

Run the server: `node web/server.mjs` (after `npm ci --omit=dev --prefix web`).
Tests (fetch mocked, no network): `node --test web/test/*.test.mjs` from the repo root.
