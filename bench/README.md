# bench

Phase 3 measures, per model and quant on this machine: decode speed (tok/s),
prefill time for a 20K-token prompt, tool-call success over 20 fixed
`/v1/messages` prompts, peak VRAM, and whether the target context fits without
spilling into shared memory. Each run writes one JSON file to `bench/results/`
(gitignored).

## Usage

`bench/run.ps1` measures the server that is already running; it does not start or
stop one. Start the candidate with `scripts/serve.ps1` (or the logon task), then:

```powershell
pwsh bench/run.ps1 -Label qwen3.6-35b-a3b -Quant UD-IQ3_XXS -Ctx 131072 -NCpuMoe 0
```

Parameters: `-Port 8080`, `-ApiKey local`, `-Label` (required, model label),
`-Quant`, `-Ctx`, `-Ngl` (default `auto`), `-NCpuMoe` (these five are recorded as
given), `-ToolTrials 20`, `-PrefillTokens 20000`, `-OutDir bench/results`. It
prints one line per measurement, then a one-line summary with the result path.

Method:

- Decode: `/completion` with a fixed 200-token prompt, `n_predict` 256,
  `ignore_eos`, `cache_prompt` false; one warm-up request is sent and discarded
  (the first request after a server start decodes slower), then median of 3
  `timings.predicted_per_second`.
- Prefill: a deterministic English prompt (seeded word lists), tokenized with
  `/tokenize` and cut to exactly `-PrefillTokens` tokens, sent as a token array
  with `n_predict` 1, `cache_prompt` false; median of 3 `timings.prompt_ms` and
  `timings.prompt_per_second`. No warm-up request: `cache_prompt` false makes every
  run a cold prefill by design, and the decode warm-up has already run. Cached: the same prompt twice with `cache_prompt`
  true; the second request is recorded.
- Tool calls: `-ToolTrials` `/v1/messages` requests (`max_tokens` 4096) with two
  tools, `get_weather{city}` and `run_tests{path}`, rotating over 20 fixed user
  messages that each need exactly one of them. Pass = a `tool_use` block with the
  expected name and a non-empty required field.
- VRAM: `nvidia-smi` `memory.used` every 500 ms for the whole run; the maximum is
  whole-GPU usage, so other GPU processes count too.

`-Backend vllm` (default `llama`) measures a running vLLM OpenAI server, for example
vLLM in WSL2 on :8081 (`docs/ROADMAP.md` P5). Same prompts, token counts, trials and
VRAM sampler. Status 2026-10-24: the script parses and its llama path was re-run
unchanged, but the vLLM path has never run against a live server (the P5 spike
could not start one), so it is UNVERIFIED. What differs:

- Server info: `/health` must answer HTTP 200 (vLLM returns an empty body);
  `server_build` is `vllm <version>` from `/version`; `flags` is `-ServerFlags` as
  given (the Windows listener is a WSL relay, not the vLLM process).
- Tokens: vLLM `/tokenize` (`add_special_tokens` false).
- Decode: streamed `/v1/completions` with the 200-token array, `max_tokens` 256,
  `ignore_eos`, temperature 0.6 / top-p 0.95 / top-k 20 (the `serve.ps1` sampling);
  tok/s = `usage.completion_tokens` / (time of the last streamed chunk - time of the
  first), timed client-side. One warm-up discarded, median of 3.
- Prefill: time to the first streamed chunk with `max_tokens` 1, client-side (it
  includes HTTP and scheduling; llama.cpp's `prompt_ms` is server-side). The server
  runs with prefix caching on, so each of the 3 cold runs replaces token 0 with a
  different token id, which changes every block hash; `prefill_tokens` is
  `prompt_tokens - cached_tokens` from the usage block (needs
  `--enable-prompt-tokens-details`), so a cache hit would show. Cached: the
  unmodified prompt twice, the second recorded.
- Tool calls: `/v1/chat/completions` with the same two tools in OpenAI form and the
  same sampling; pass = a `tool_calls` entry with the expected function name whose
  JSON `arguments` has a non-empty required field.

## Result schema

| Field | Meaning |
| --- | --- |
| `model`, `quant`, `ctx`, `ngl`, `n_cpu_moe` | as given on the command line |
| `decode_tps` | median decode tok/s of the 3 measured runs (warm-up excluded) |
| `prefill_ms_20k`, `prefill_tps` | median cold prefill ms and tok/s for the prompt |
| `prefill_tokens` | prompt tokens the server evaluated (`timings.prompt_n`) |
| `prefill_ms_20k_cached` | prefill ms for the same prompt with `cache_prompt` true |
| `prefill_cached_tokens_eval` | tokens evaluated on that cached request |
| `toolcall_pass`, `toolcall_total` | passing requests / requests sent |
| `toolcall_wrong_tool`, `toolcall_no_call`, `toolcall_bad_args` | failure breakdown |
| `toolcall_errors` | requests that failed at HTTP level |
| `toolcall_latency_ms_median` | median wall time of the completed tool requests |
| `vram_mb_peak` | max whole-GPU `memory.used` (MiB) during the run |
| `server_build` | `/props` `build_info` |
| `flags` | command line of the process listening on `-Port` |
| `date` | ISO 8601 |

## Agentic loop (Phase 3d)

`bench/loop/run.ps1` measures a real Claude Code loop instead of single requests:
`scripts/claude-local.ps1` has to fix a small Node project until its tests pass. Like
`bench/run.ps1` it uses the server already running on :8080 and does not start or stop
one. Start the contender, check `scripts/smoke.ps1` PASS, then:

```powershell
pwsh bench/loop/run.ps1 -Label gpt-oss-20b
pwsh bench/loop/run.ps1 -Label gsq-rco-mtp-c65k -LisContextTokens 65536
```

Parameters: `-Label` (required), `-Reps 3`, `-MaxTurns 40`, `-LisContextTokens`
(passed to `claude-local.ps1` when given; use the server's `-Ctx` when the server's
`-Ctx` differs from the wrapper default of 131072), `-TimeoutMin 30` per repetition (the process tree is killed),
`-WorkRoot %LOCALAPPDATA%\lis-loop`, `-OutDir bench/results`, `-Launcher` (only for a
dry run with a stub script).

Task (committed, `bench/loop/`):

- `fixture/`: `src/text.js` plus `test/text.test.js` (3 `node:test` cases, 0/3 pass as
  committed). No `package.json` on purpose: the operator's `~/.bashrc` runs
  `fnm env --use-on-cd`, so a `cd` into a dir with a `package.json` runs `fnm use`, which
  fails inside Claude Code's Bash tool ("We can't find the necessary environment
  variables to replace the Node version"); a model that prefixed `cd <dir> &&` lost
  every test run to it (GSQ-RCO template check, timed out at 30 min). `node --test`
  finds `test/*.test.js` without it. In order of
  difficulty: `truncate` has an off-by-one (`slice(0, max - 2)`), `wordCount` lacks a
  null/blank guard, `parseDuration` (`'1h30m'` to seconds; wrong order, repeats, no unit
  and unknown units throw) must be written from its test. A reference fix (not
  committed) passes 3/3.
- `prompt.txt`: run `node --test`, make every test pass by changing `src/text.js` only,
  touch nothing under `test/`, run the tests again and confirm.

Per repetition:

1. Copy `fixture/` to a fresh `<WorkRoot>/<stamp>-<Label>/r<N>/work`, `git init` and
   commit it (the P2 sandbox was a git repo), sha256 every file. `%TEMP%` is avoided on
   purpose: under it Git Bash shows the cwd as `/tmp/...`, which the Write tool then
   reads as `\tmp\...` (P2 run B lost three tool calls to that).
2. From that dir: `pwsh -NoProfile -File scripts/claude-local.ps1 [-LisContextTokens N]
   -p <prompt> --output-format json --max-turns 40 --permission-mode acceptEdits
   --allowedTools "Bash(node:*)" "Bash(npm:*)" --debug-file r<N>/out/debug.log`.
   Headless JSON needs no `--verbose` in Claude Code 2.1.310 (`--verbose` is required
   only for `stream-json`); `--max-turns` is not listed in `claude --help` but is
   accepted (P2). `acceptEdits` keeps the operator's `defaultMode` (auto, which would
   call a classifier model) out of the loop; `--allowedTools` makes `node --test` run
   without a prompt on a profile without the operator's allow list. The operator's
   global hooks, skills and CLAUDE.md still load (ruling 2, no `--bare`), so every run
   starts from the same ~21K-token first prompt. Session-identity variables of a calling
   Claude Code session (`CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_CODE_SESSION_ID`, ...) are
   removed from the child environment.
3. Run `node --test --test-reporter=tap test/text.test.js` in the work dir and read
   `# pass` / `# fail`; re-hash the files.
4. Read the JSON result (stdout), stderr, the debug log and the main session's
   transcript (`~/.claude/projects/*/<session_id>.jsonl`, copied to `r<N>/out/`;
   subagent transcripts are not read).

PASS per repetition: 3/3 tests pass, no file under `test/` changed, added or removed,
`is_error` false; a timeout or stdout that is not a JSON result is a FAIL. Work dirs
(`work/`, `out/` with stdout, stderr, debug log, transcript, test output) are kept.
Each call writes `bench/results/<stamp>-loop-<Label>.json` and its console log
`<stamp>-loop-<Label>.log` (both gitignored).

Result schema (top level): `label`, `date`, `server_build` (`/props`), `flags` (command
line of the :8080 listener), `claude_version`, `node_version`, `lis_context_tokens`,
`max_turns`, `timeout_min`, `prompt`, `reps`, `runs_passed`, `median_turns`,
`median_wall_s`, `median_api_s`, `median_tokens_in`, `median_tokens_out` (medians over
repetitions that returned a JSON result; wall over all), `tool_errors_total`,
`tool_format_errors_total`, `vram_mb_peak`, `runs`. Per run:

| Field | Meaning |
| --- | --- |
| `pass`, `tests_pass`, `tests_fail`, `tests_expected` | criterion above; TAP counts after the run |
| `test_files_touched`, `files_changed`, `files_added`, `files_removed` | sha256 diff of the work dir (`.git/` excluded) |
| `exit_code`, `timed_out`, `wall_s` | launcher process; wall = process start to exit |
| `num_turns`, `duration_ms`, `duration_api_ms`, `is_error`, `subtype`, `terminal_reason`, `stop_reason` | from the Claude Code JSON result |
| `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `tokens_in_total`, `output_tokens` | `usage` of the result; `tokens_in_total` is the sum of the three input fields |
| `models` | `modelUsage` keys (expected: only `local`) |
| `permission_denials` | tool names of `permission_denials` |
| `tool_use` | tool_use blocks per tool name in the transcript |
| `tool_errors`, `tool_format_errors`, `tool_error_samples` | `is_error` tool results in the transcript; "format" = text matching `InputValidationError`, `No such tool`, `Invalid tool`, `unexpected parameter`, `required parameter`, `is missing` or `Invalid input` (a heuristic); up to 10 samples, 200 chars each |
| `dispatch`, `dispatch_error_codes` | debug-log `tool_dispatch_end` calls and non-ok outcomes per tool; `tool error ... code=` counts |
| `debug_error_lines`, `debug_error_samples` | `[ERROR]` lines in the debug log (in P2 run B: two lines from the TypeScript LSP plugin, which finds no `typescript` in the work dir) |
| `stderr_unrecognized_model`, `stderr_other` | stderr lines with `unrecognized_model`; other stderr lines except the claude.ai-connectors notice |
| `vram_mb_peak` | max whole-GPU `memory.used` during the Claude Code run (500 ms sampling) |
| `result_text`, `session_id`, `work_dir`, `transcript` | first 400 chars of the final answer; where the artifacts are |
