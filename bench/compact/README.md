# bench/compact

Question: does Claude Code's auto-compaction produce a usable summary on this local
backend, and under which env settings? One run is one read-only `-p` session that grows
its context past the compaction threshold, with every request and response captured on
the wire by a pass-through proxy, then measured by `analyze.py`.

## Established facts (read-only investigation, 2026-10-26)

- Compaction fires between about 92K and 107K prompt tokens (baseline) on the 131,072
  window
  (`scripts/claude-local.ps1` sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 131072).
- Ten summary requests in three sessions returned no text block. Claude Code 2.1.310
  takes `content.find(type == "text").text.trim()`; on no text it reports
  "summarization produced empty response". 4 of 10 hit max_tokens 16,384 while
  reasoning; 6 ended on their own with no text.
- The summary request inherits the session's thinking configuration (docs:
  context-window, "What survives compaction"), here adaptive thinking at effort high.
  Its prompt begins "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."
- What those responses contained (thinking only, a tool_use) is UNVERIFIED: the server
  log does not record content. The capture here does.
- On the 65536 window an earlier run got a non-empty summary at 39,098 tokens
  (`docs/ROADMAP.md`, ruling 12), so summaries can work at smaller sizes.

## Run one case

From the repo root, in PowerShell 7, with no other session on the server:

```powershell
pwsh bench/compact/run.ps1 -Case baseline -DryRun   # prints env and command lines only
pwsh bench/compact/run.ps1 -Case baseline
```

Parameters: `-Case` (required, table below), `-ProxyPort 8081`, `-OutDir bench/results`,
`-Pad 0`, `-MaxTurns 60`, `-TimeoutMin 120`, `-DryRun`.

What `run.ps1` does:

1. Refuses to start if `logs/llama-server.log` was written in the last 60 s, a
   `/slots` entry is processing, or the proxy port is already listening.
2. Builds a scratch tree: `git archive HEAD` extracted to
   `<OS temp>\lis-compact-<case>-<stamp>` (uncommitted changes are not in it). The
   session runs there, so nothing it does lands in this repo.
3. Applies the case env. The tree's `scripts\claude-local.ps1` sets
   `ANTHROPIC_BASE_URL` and `CLAUDE_CODE_MAX_OUTPUT_TOKENS` itself, which would win
   over a plain process env, so the proxy URL and the case variables are inserted as
   `$set[...]` lines before its `$unset` line, written into the tree's
   `config\claude-settings.json` env block (CLI-level `--settings`), and set in the
   child process env. Every case variable is first removed from the inherited env.
4. Starts `proxy.js` as a thread job, waits for `/health` through it, then runs:
   `pwsh -NoProfile -File <tree>\scripts\claude-local.ps1 -p <prompt> --max-turns 60
   --output-format json --permission-mode auto --disallowedTools
   "Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Agent,Skill,Workflow"
   --debug-file <base>.debug.log` (exact line: `-DryRun`).
5. In `finally`: stops the proxy job and deletes the tree. Then copies the session
   transcript (found by the envelope's session id under the Claude Code projects
   dir) and runs `analyze.py`.

The fixed prompt: "Read every file under scripts/, bench/, docs/ and config/ one by
one with the Read tool, whole files, largest first (use Glob to list them). After each
file, state its line count in one sentence. Do not stop until you have read every
file; then answer: how many files did you read and what is the total line count?"

`-Pad N`: the tracked files under those four dirs total about 490 KB, roughly 120K
to 140K tokens (UNVERIFIED estimate at 3.5 to 4 chars per token), so the baseline
should pass 100K without padding. Use `-Pad 2` (or more) when a run reports
`fired 0` with a peak prompt below the threshold, for example after the wrapper's
"read a line range of a file over 300 lines" policy shortened the reads. Each pad
file is 60 KB of seeded words in `docs\pad\` of the tree.

## Outputs (under `-OutDir`, gitignored)

Base name `compact-<case>-<stamp>`: `.capture.jsonl` (proxy), `.result.json` (stdout
envelope), `.stderr.txt`, `.debug.log`, `.proxy.log`, `.run.log`, `.transcript.jsonl`,
`.analysis.txt` (analyze output) and `.json` (case, env, pad, exit code, timed_out,
wall_s, is_error, num_turns, paths).

Capture line (one per request, written when the response ends):

| field | content |
| --- | --- |
| `ts` | request start, ISO 8601 UTC |
| `method`, `path` | as sent by Claude Code |
| `request` | body parsed as JSON, or raw text |
| `request_kind` | `json`, `text` or `empty` |
| `status` | upstream HTTP status; 502 on a proxy error |
| `response` | parsed JSON, the message assembled from the SSE events, or raw text |
| `response_kind` | `json`, `sse-assembled`, `sse-raw`, `text`, `empty`, `proxy-error` |
| `complete`, `client_aborted` | upstream ended cleanly; Claude Code hung up first |
| `duration_ms` | request start to response end |

SSE assembly: `message_start` gives the message, `content_block_start` opens each
block, `text_delta`, `thinking_delta`, `signature_delta` and `input_json_delta` append
(tool input parsed at `content_block_stop`), `message_delta` sets `stop_reason` and
merges `usage`. A stream without `message_start` is stored raw as `sse-raw`. A client
hang-up also closes the upstream request.

`analyze.py` output (`python -I bench/compact/analyze.py <capture> [--result R]
[--transcript T]`, exit 0 always):

- `capture:` requests, `/v1/messages` calls, peak prompt tokens.
- One row per compaction request: ts, status, prompt tokens (`input_tokens` plus
  cache fields from the response usage), output tokens, stop reason, accepted, summary,
  thinking chars, block types in order with lengths (`thinking(n)`, `text(n)`,
  `tool_use(name)`); then the marker that matched, the request's `max_tokens`, `thinking`,
  `output_config`, `stream` and tool count, and the first 300 chars of the text.
- Compaction request: the last user message or the system text contains
  "CRITICAL: Respond with TEXT ONLY" or "Do NOT call any tools", or both "summary" and
  "<analysis>". Accepted: the FIRST text block has non-empty trimmed text, the
  Claude Code test above. Summary (summary-shaped): that text contains `<summary>` or
  starts with `<analysis>`; an accepted row with summary `NO` is a stray text block
  Claude Code took as the summary.
- `effect: max_tokens V, effort V|absent, thinking V`: the distinct values the
  compaction requests sent, so a case whose env changed nothing on the wire shows the
  baseline values.
- `compaction: fired N, accepted M (summary-shaped K), empty E; max_tokens hits J`
- `session:` is_error, subtype, num_turns, permission_denials, first 200 chars of the
  result. `transcript:` counts of `compact_boundary` and `isCompactSummary` records.
- `consistency: accepted M vs compact_boundary B` (with a transcript), `(MISMATCH)`
  appended when they differ.

## Cases

Definitions quoted from https://code.claude.com/docs/en/env-vars (2026-10-26). The
model is always the server's default; every case also runs on the wrapper defaults.

| case | env | doc definition (quoted, shortened) |
| --- | --- | --- |
| `baseline` | none | wrapper defaults: the setting that failed |
| `pct50` | `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=50` | A |
| `effort-low` | `CLAUDE_CODE_EFFORT_LEVEL=low` | B |
| `pct50-effort-low` | both of the above | A and B |
| `nothink` | `MAX_THINKING_TOKENS=0` | C |
| `out32k` | `CLAUDE_CODE_MAX_OUTPUT_TOKENS=32768` | D |
| `effort-low-forced` | `effort-low` plus `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` | B and E |

- A: "Set the percentage (1-100) of the auto-compact window at which auto-compaction
  triggers. Use lower values like `50` to compact earlier; the variable can't raise
  the threshold". It "applies only in sessions that compact before the model's
  context limit"; whether that holds with the window set is shown by the prompt
  tokens of the first compaction row.
- B: "Set the effort level for supported models. Values: `low`, `medium`, `high`,
  `xhigh`, `max`, or `auto`". The model ID `local` is not a model Claude Code knows;
  the docs list `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` to send effort for such IDs
  (note E). Whether `output_config` reaches the wire is in each analyze row;
  whether llama-server acts on effort is UNVERIFIED.
- C: "Set to `0` to disable thinking on the Anthropic API ... On third-party
  providers, `0` omits the `thinking` parameter instead." The Qwen template opens
  `<think>` unless `enable_thinking=false`, so this probably changes nothing here.
  `CLAUDE_CODE_DISABLE_THINKING=1` is documented to behave the same on third-party
  providers, so it is not a separate case.
- D: "Set the maximum number of output tokens for most requests ... Increasing this
  value reduces the effective context window available before auto-compaction
  triggers", so this case also compacts earlier.
- E (reason, not a doc quote): Claude Code applies the effort level only to model IDs
  it recognises; `local` is not one, so `effort-low` may be a no-op.
  `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` is meant to force it (UNVERIFIED). The name is
  in the installed 2.1.310 bundle: its effort-support check returns true when the
  variable is set, after the per-model lookups and the list of models without effort.
  Whether `output_config` then reaches the wire is in each analyze row.

Not a case: a "# Compact instructions" section in CLAUDE.md (a content change, not an
env var; it would need a patched CLAUDE.md in the tree). The five case variables and
`CLAUDE_CODE_DISABLE_THINKING` are listed in the docs; none is UNVERIFIED as a name.

## Results

| case | fired | accepted | summary-shaped | empty | max_tokens hits | finished | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | 4 | 3 | 2 | 1 | 0 | yes, 65 turns | note 1 |

1. `baseline`, 2026-10-26, pad 0, wall 2,467 s. The four compaction requests sent
   adaptive thinking, effort high, max_tokens 16,384, three tools. Request 1 (prompt
   91,823) got thinking, a 120-char per-file line and a Read call; Claude Code took
   that line as the summary. Request 2 (101,887) got thinking and a Read call, no
   text. Requests 3 (107,370) and 4 (103,626) ended on end_turn with `<analysis>`
   summaries of 10,621 and 11,429 chars. One non-compaction turn hit max_tokens.
   Answer: 31 files, 7,664 lines; HEAD has 31 files, 7,661 lines by `wc -l`.
   `effect:` max_tokens 16384, effort high, thinking adaptive; `consistency:` accepted
   3 vs compact_boundary 3. num_turns 65 exceeds `--max-turns 60`; the envelope count
   is not bounded by the cap as passed (cause UNVERIFIED).

## Rules

- One case at a time: the server has one slot.
- Never while another session uses the server: check that `logs/llama-server.log`
  has no request in the last 60 s (`run.ps1` refuses on a write in that window or on a
  busy `/slots`). It never starts, stops or restarts the server.
- The proxy listens on 127.0.0.1 only and forwards every header (Authorization
  included) except two: `accept-encoding` is dropped, so captured bodies are plain
  text, and `host` is set to the upstream `127.0.0.1:8080`.
- The tree is under the OS temp dir and `run.ps1` deletes it in `finally`. Claude Code
  still writes its own transcript under its projects dir, as for any session.
- On `-TimeoutMin`, `run.ps1` kills the session's process tree through its own
  process object, never a looked-up pid.

## Permissions

The proxy is reached by Claude Code, not by the Bash tool, so no allow rule is needed
for it; `run.ps1` is launched by the operator or an orchestrator from PowerShell. The
session uses only Read, Glob and Grep inside its working directory (the tree), which
need no permission rule beyond rule set A of `config/claude-settings.json`; a non-zero
`permission_denials` in the `session:` line would show otherwise.
