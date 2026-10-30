# Web access prep: local-inference-studio (HEAD 0fd0cea), DISARMED

- Date: 2026-10-30
- HEAD audited: `0fd0cea`
- Verdict: DISARMED; prep only, arming waits on the security blockers B1-B7

## Recommendation (applies only after the audit blockers are closed)

- Fetch, primary: A, Claude Code's built-in WebFetch, behind a proposed opt-in wrapper
  switch `-LisWeb`. It changes only the per-run settings: drops `WebFetch` from the deny,
  adds WebFetch to `--tools`, sets `skipWebFetchPreflight`, and adds one sentence to the
  policy saying web content is untrusted. Nothing gets installed and no new process runs.
- Fetch, fallback: C, Playwright MCP `@playwright/mcp@0.0.75`. It is already in the npx
  cache and its integrity was checked. Chrome and Edge are installed. Use it only for
  pages that need JavaScript to render, and only through an explicit `--mcp-config`.
- Not recommended: B, `mcp-server-fetch`. It is not cached, its latest release
  (2026.10.28) is 2 days old, its dependencies are unpinned, and by default it can reach
  loopback.
- Search: run SearXNG in Docker bound to 127.0.0.1, queried by Bash `curl`. lis-guard
  already allows a GET to loopback. It needs no key, but it needs a Docker image pull and
  a config, both done by the operator. The fallback is Brave
  (`@brave/brave-search-mcp-server` 2.1.4) or Tavily (`tavily-mcp` 0.2.22), which need an
  API key. All search options are UNVERIFIED.

## Step 1 findings

Evidence: strings read from `claude.exe` 2.1.314 as a file. It was never run. Behaviour is
UNVERIFIED.

- **WebSearch** puts `web_search_20250305` in a second model request. That is an Anthropic
  server-side tool, so llama-server cannot serve it.
- **WebFetch:**
  - It runs on the client and upgrades `http` to `https`.
  - Before fetching it calls `https://api.anthropic.com/api/web/domain_info?domain=`. It
    skips that call only when `skipWebFetchPreflight` is set, and a failed check blocks
    the fetch.
  - It converts the page to Markdown with Turndown, then makes a model call to summarise
    it. In local sessions that call goes to llama-server.
- **`--tools` help text** says it applies to "the built-in set". Whether it hides MCP
  tools is UNVERIFIED.

Current repo treatment:

- **Deny in every local session:** `config/claude-settings.json:242-247`. It comes from
  `docs/ROADMAP.md` `### Overlay: deny WebSearch and WebFetch`, which assumed both tools
  run on Anthropic's side; that is true only for WebSearch. `docs/SETUP.md:306` and
  `docs/landscape-2026-10-24.md:36-38` describe the same thing.
- **Lean set:** `scripts/claude-local.ps1:212` and `:224-225` allow 7 tools with no web
  tool. `:320` writes an empty MCP config, which combined with `--strict-mcp-config` loads
  no MCP servers.
- **`-LisTask`** refuses `--mcp-config` (`:166-168`), so the ladder runs never had web
  access.
- **Benches:** `bench/compact/run.ps1:55` and `scripts/verify-claims.ps1:60` disallow both
  tools.
- **lis-guard `curl_ok`** (`scripts/hooks/lis-guard.py:609`) auto-allows only a GET to
  127.0.0.1 or localhost.
- **User settings (read only):**
  - `defaultMode` is `auto`.
  - The allow list holds `WebFetch(domain:...)` for 11 hosts plus `WebSearch`.
  - `enabledMcpjsonServers` is context7, sequential-thinking and playwright, all from
    `Z:\repos\.mcp.json`.
  - Playwright there is pinned to 0.0.75 with `--headless --isolated --blocked-origins`
    covering loopback and private ranges.
  - `~/.claude.json` has an empty top-level `mcpServers`.

## Step 2 inventory (nothing installed)

- **npx cache (`Z:\packages\npm\_npx`):**
  - `@playwright/mcp@0.0.75` with integrity
    `sha512-oBjzVXfEGZ9Ev45tKKQULNDVdF83B82lg0uPejEK3xsp/zWmdNdNVnPi032fmd/o20ZZXs+LX7cr77qRNbV4VA==`
  - `@upstash/context7-mcp` 4.4.4
  - `server-sequential-thinking`
  - `node`
- **No fetch server is cached** in uv (`Z:\packages\uv`), npm `_cacache` or pnpm.
- **`@modelcontextprotocol/server-fetch` does not exist** on npm (404). The official fetch
  server is Python-only.
- **No `ms-playwright` browsers are downloaded.** Chrome and Edge exist on the system.

## Built (untracked, nothing commits, nothing auto-loads)

- `Z:\repos\kosm1x\local-inference-studio\scripts\web-access.example.mcp.json` (LF): the
  path C server. It loads only through an explicit `--mcp-config`.
- `Z:\repos\kosm1x\local-inference-studio\scripts\web-smoke.ps1` (CRLF):
  - Checks connectivity: TCP 443 and a GET of `https://example.com/`.
  - Prints the MCP servers the repo declares and checks npx-cache integrity against the
    recorded hash.
  - FAILs if a root `.mcp.json` exists.
  - Prints which browsers exist and llama-server `/health`.
  - Prints the proof commands under a DISARMED banner. It never runs claude.
  - Mutation-tested in scratch: a wrong pin plus wrong expected text gave
    `integrity MISMATCH`, `FAIL: 2 check(s) failed` and exit 1.
- `Z:\repos\kosm1x\local-inference-studio\docs\web-access.md` (LF):
  - DISARMED status.
  - Step 1 findings with file:line references.
  - The options table.
  - The 7 audit blockers as `###` and `<h3>` headings, paraphrased from the audit's B1-B7.
  - The run-identity fix: a separate user, WSL distro or container with an outbound
    allow-list.
  - The proposed config (example MCP JSON plus the per-run settings additions, including
    Playwright denies for `browser_evaluate`, `browser_run_code_unsafe` and
    `browser_file_upload`).
  - The injection risk.
  - "After the blockers are closed" with the live proof.
  - All lines are 90 columns or fewer; the first blocker is an `<h3>` heading, none of
    its lines over 90 columns.
- No repo `.mcp.json` was added, and no deny was removed or weakened in the wrapper,
  settings or lis-guard.
- Proposed wrapper change, not applied:
  `<scratch>\webprep\claude-local-LisWeb.patch`
  (+20 lines). It was dry-run with `-LisPrintArgs` on a scratch copy: `--tools` became
  `...,Skill,WebFetch`, the deny became `WebSearch, Agent, Workflow`, and
  `skipWebFetchPreflight: true` was set. Without `-LisWeb` nothing changed.

## Step 5: web-smoke output (exit 0)

Long output lines are wrapped here; continuations are indented.

```
internet: tcp example.com:443 open
internet: GET https://example.com/ -> 200, 577 bytes, 'Example Domain' found
mcp: scripts/web-access.example.mcp.json declares 'playwright': cmd /c npx -y
    @playwright/mcp@0.0.75 --headless --isolated --blocked-origins
    http://127.0.0.1:*;...;http://192.168.*
mcp:   @playwright/mcp@0.0.75 cached, integrity matches the record
mcp: .mcp.json not present
mcp: the lean wrapper passes --strict-mcp-config, so a session loads only the --mcp-config
    files given
browser: C:\Program Files\Google\Chrome\Application\chrome.exe present
browser: C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe present
browser: <LOCALAPPDATA>\ms-playwright absent
llama-server: /health {"status":"ok"}
DISARMED: run these only after the blockers in docs/web-access.md are closed.
PASS
```

The full output, including the two printed proof lines, is in
`<scratch>\webprep\web-smoke-output.txt`.

## Done checks

- `python -I scripts/tests/verify-doc_test.py`: 85/85 passed. It has no doc list to
  update.
- `verify-doc docs/web-access.md`: 0 findings. README, SETUP and ROADMAP still have
  0 FAIL.
- `git status --short`: only `?? docs/web-access.md`, `??
  scripts/web-access.example.mcp.json` and `?? scripts/web-smoke.ps1`.
- The identity grep over the three files returns no matches (count 0).

## Operator, before arming

1. Close or rule on the 7 blockers in `docs/web-access.md`. They come from the audit and
   were not re-verified here. The real fix is a run identity: a separate user, distro or
   container with an outbound allow-list.
2. Ruling on `-LisWeb`, then apply
   `<scratch>\webprep\claude-local-LisWeb.patch`
   (`git apply` from the repo root, paths `a/scripts/...`).
3. Search, if wanted: either pull a SearXNG image pinned by digest, enable `json` in
   `settings.yml` and bind it to 127.0.0.1, or provide a Brave or Tavily key.
4. Optional: add Playwright deny rules to the per-run settings when using path C, as the
   doc proposes.

## Live proof (after the blockers are closed and the patch is applied)

```powershell
pwsh -NoProfile -File Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 `
  -LisWeb --allowedTools "WebFetch(domain:example.com)" --max-turns 4 `
  --output-format json `
  -p ("Use WebFetch on https://example.com/ and reply with only the text of " +
      "the page's h1 heading.")
```

It passes when `result` is `Example Domain` and the llama-server log shows two requests,
one from the main loop and one from the summariser. UNVERIFIED.
