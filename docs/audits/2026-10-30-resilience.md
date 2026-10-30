# Resilience audit: local inference setup (local-inference-studio @ 0fd0cea)

- Date: 2026-10-30
- HEAD audited: `0fd0cea`
- Verdict: FAIL for unsupervised multi-hour tasks (no restart after a fault)

Date 2026-10-30. Read-only. Repo root `Z:\repos\kosm1x\local-inference-studio` (below:
`<repo>`). Probes run: `Get-ScheduledTask(Info)`, `Get-Process llama-server`, GET
`/health` `/slots` `/props` `/metrics`, `nvidia-smi`, Windows System/Application event
logs, `powercfg`, `bin/llama-server.exe --help` (help text only, no model load), greps of
`<repo>/logs/llama-server.log`, and two Python tabulators over
`<repo>/bench/results/ladder-*` (`<scratch>/tab.py`, `<scratch>/tab2.py`; analysis scripts
not committed; re-derivable from the artifacts). Nothing was stopped, started, edited or
committed.

## 1. Server uptime and restarts

| Item | Value | Source |
|---|---|---|
| Task LastRunTime | 2026-10-30 07:22:04 | `Get-ScheduledTaskInfo` |
| Task LastTaskResult | 267009 (0x41301 = task currently running) | same |
| llama-server PID / start | 23132 / 2026-10-30 07:22:06 | `Get-Process` |
| Last OS boot | 2026-10-24 13:14:20 (no reboot since) | `Win32_OperatingSystem`, System 6005/6006 |
| `/health` | `{"status":"ok"}` | GET /health |
| `/metrics` | HTTP 501 (not enabled: `endpoint_metrics:false`) | GET /metrics, /props |

Server starts in `<repo>/logs/llama-server.log` (45,463 lines, 5,507,216 bytes, no `.1`
rotation file): 19 starts, 15 `llama-server exited` lines, all `-1`. Starts per day: 10-24
14, 10-25 1, 10-26 3, 10-30 1 (running). Every logged exit code is -1, which is what
`Stop-Process -Force` (`scripts/stop.ps1`) produces; the log cannot tell a crash from a
stop. Three non-running starts have no exit line: 10-24 15:56 and 15:58 (lines 1, 19; each
followed directly by the next start) and 10-26 11:02:25 (line 32750, next start 12:22:00
at line 33851), so their pwsh wrapper died before llama-server's exit was logged (cause
UNVERIFIED). No server ran between 10-26 20:54:47 (exit) and 10-30 07:22:05 (start).
Longest instance under ladder load: 10-26 12:22 to 20:54 (about 8.5 h, all 10 long-fix
reps).

Log error census (whole file; level-E lines: 0):

| Pattern | Count | Note |
|---|---|---|
| `CUDA error`, `out of memory`, `GGML_ASSERT`, `abort`, `failed to` | 0 each | |
| context shift / `exceeds` / `truncated = <non-zero>` | 0 / 0 / 0 (of 2,827 slot releases) | |
| HTTP 5xx lines | 0 (llama-server logs no per-request status at this verbosity) | UNVERIFIED beyond that |
| `W srv stop: cancel task` (client disconnect) | 81: 9 in the 10-24 22:52 instance, 72 in the 10-25 00:37 instance, 0 since | |
| `W unauthorized: Invalid API Key` | 24, lines 1813-10173 (10-24/25 instances), 0 since | |
| `W making room for prompt cache entry` | 253 (largest evicted entry 6,644.75 MiB); 6 since 10-30 07:22 | RAM prompt cache at its limit; benign |
| Max `n_tokens` at slot release | 124,066 (of n_ctx 131,072); 13 releases >= 115K, lines 13488-31543 (10-25 00:37 instance, pre-ladder benches) | |

Windows events since 10-24: no Kernel-Power 41 / 6008 (no dirty shutdown), no `nvlddmkm` /
4101 TDR event. One Application 1001 `LiveKernelEvent` code 193 at 10-24 14:47 with
`C:\WINDOWS\LiveKernelReports\WATCHDOG\WATCHDOG-20261024-1447.dmp`, before the first
server log line (15:56); cause UNVERIFIED (0x193 is a graphics-kernel live dump class).

## 2. Session-level resilience (ladder artifacts)

On disk: 23 runs, not ~35 (`<repo>/bench/results/ladder-*.json`, gitignored; 14 dated
10-26, 9 dated 10-30; none 10-27..29, matching the server gap above;
`~\AppData\Local\lis-ladder\` has the same 23 dirs). Peak prompt = largest per-request
input+cache tokens of an `assistant` event in each `.jsonl`.

| Rung (case) | Runs | Completed rc 0 | Crashed / timed out | Max wall s | Max turns | Max tokens in / out | Peak prompt | Compactions (fired / failed) | Claude Code |
|---|---|---|---|---|---|---|---|---|---|
| 1 fix-one | 2 | 2 | 0 / 0 | 31.3 | 6 | 75,929 / 650 | 16,449 | n/a | 2.1.310 |
| 1 fix-all | 2 | 2 | 0 / 0 | 47.5 | 10 | 111,212 / 1,201 | 17,234 | n/a | 2.1.310 |
| 2 long-fix | 10 | 9 | 1 / 0 | 2,532.7 | 180 | 6,172,953 / 23,920 | 52,884 | 50 / 1 | 2.1.310-311 |
| 3 stale-figure | 9 | 9 | 0 / 0 | 41.4 | 14 | 106,839 / 1,043 | 17,655 | 0 / 0 | 2.1.314 |

- The one failure: `ladder-long-fix-20261026-154601.json` `exit_code 1`, `is_error true`,
  `subtype success`, `compaction_failed true`, `compaction_fired 11`; its `.jsonl` result
  line has `"api_error":"autocompact_thrashing"` (`contextWindow 65536`). Claude Code
  ended the session itself; nothing resumed it.
- Max wall 2,532.7 s (42.2 min, `ladder-long-fix-20261026-132833.json`); max turns 180
  (`...-175551`); max tokens in 6,172,953 and out 23,920 (`...-181610`); peak prompt
  52,884 (`...-175551`). `timed_out` false in 23/23.
- Context windows exercised by long-fix: 65,536 (4 runs, 5-12 compactions each) and 81,920
  (5 runs, 1-6 each); one 131,072 rep (`...-122359`, peak 47,643, 0 compactions). The
  131,072 default has no long-fix rep that compacted. The 90,736-93,496 peaks are in
  `<repo>/docs/ROADMAP.md` under `### TEST 6 2026-10-25 (test-coverage audit)` (not
  `bench/ladder/README.md`); `### Compaction on this backend 2026-10-26` records
  compactions firing at 91,823-107,370 prompt tokens.
- `.stderr.txt`: non-empty in 23/23, but beyond the wrapper banner each holds only two
  lines, identical in all 23: `⚠ <web-app> connectors are disabled ...` and
  `[claude-code:unrecognized_model] {"model":"local","query_source":"sdk"}`.
- `.jsonl` API-error grep: no `system/api_retry` events, no `overloaded`, `rate_limit`,
  `ECONNRESET`/`ECONNREFUSED`, `api_error_status` null in 23/23. The `timeout` and ` 500 `
  hits are file content (`timeout.js`, `MAX_BATCH | 500`); `"is_error":true` hits (1-8 per
  run) are tool results, matching `denials.tool_error` 0-2.

## 3. Memory headroom

- GPU now: 15,518 / 16,376 MiB used (858 MiB free), 0 % util, 40 C, driver 617.42
  (`nvidia-smi`).
- Host: 33.2 GB free of 61.6 GB; llama-server private bytes 24,332,177,408 (prompt cache
  in RAM).
- `/props`: `total_slots 1`, `n_ctx 131072`; `/slots`: slot 0 idle, last task 6336 at
  14,344 tokens, `max_tokens 16384`. Log: `n_slots = 1, n_ctx_slot = 131072, kv_unified =
  'false'`. KV is allocated at load, so VRAM does not grow with context; KV-use percentage
  is not observable (`/metrics` disabled).
- Context limit: `serve.ps1` passes no `--context-shift`; `llama-server --help` says
  `--context-shift ... (default: disabled)`. So the server will not slide the window; a
  prompt over 131,072 is refused and generation stops at the limit (exact response on
  b11868 UNVERIFIED: never hit, 0 `truncated != 0`). `claude-local.ps1` lines 89 and
  184-186 set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` = `CLAUDE_CODE_AUTO_COMPACT_WINDOW` =
  131072 (same as server n_ctx) and `CLAUDE_CODE_MAX_OUTPUT_TOKENS` 16384, so Claude
  Code's own budget has zero margin over the server's. Headroom observed: 124,066 /
  131,072 (94.7 %) on the server; ladder peaks 52,884 (40 %).

## 4. Failure modes not yet exercised

| Mode | Current behaviour (evidence) | Status |
|---|---|---|
| Concurrent sessions | `-np 1` (`serve.ps1` line `'-np', '1'`). `bench/ladder/run.ps1` lines 365-381 refuse to start when `/slots` shows `is_processing`; `scripts/claude-local.ps1` has no `/health` or `/slots` call (grep of `Invoke-RestMethod|Invoke-WebRequest|curl|/health|/slots` matches only policy prose, line 207). A second session queues behind the slot; Claude Code waits up to `API_TIMEOUT_MS = '1800000'` (line 187); server `-to` default 3600 s (`--help`). | Not exercised |
| Long idle | No idle unload; model stays resident. AC standby = 0 (never), hibernate off, S3 only (`powercfg`). | Not exercised; low risk on AC |
| GPU driver reset / TDR | A reset kills the CUDA context; serve.ps1 then logs `exited <code>` and exits; no restart (next row). | Not exercised (one unexplained LiveKernelEvent 193 on 10-24) |
| llama-server crash | Task `RestartCount 3`, `RestartInterval PT1M` only retry a failed launch; `register-task.ps1` docstring: "a crash or scripts/stop.ps1 leaves it down until the next logon or Start-ScheduledTask". | Not exercised |
| Logoff | `LogonType Interactive`, trigger at logon: server runs only while the user is logged on. | Not exercised |
| Disk full on `logs/` | `*>> $LogFile` append; Z: 171 GB free. Write failure behaviour UNVERIFIED. | Not exercised; low risk |
| Log rotation | Only at serve.ps1 start, file > 50 MB -> `.1`. A running instance grows unbounded; observed 5.5 MB in 6 days. | Low risk |
| Context overflow (prompt + output > 131,072) | See section 3. | Not exercised |
| Autocompact at the 131,072 default on a long task | Thrash path seen once at 65,536. | Not exercised at default |
| Session longer than 42 min | Longest was 2,532.7 s. | Not exercised |

## 5. Recovery paths

| Failure | Automatic | Operator action |
|---|---|---|
| llama-server crash / TDR | Nothing; task ends with llama-server's exit code | `Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server` (serve.ps1 refuses if the port is held; then `pwsh scripts/stop.ps1` first). Restart the Claude Code session; the in-flight session has errored. |
| Hung server (port held, no answers) | Nothing (no health watchdog) | `pwsh scripts/stop.ps1` then `Start-ScheduledTask ...` |
| Claude Code exits (autocompact_thrashing, rc 1) | Nothing | Start a new session; work state only in the repo and the `lis-facts-*.md` file |
| Second session started | Queues (UNVERIFIED) | Avoid; only the ladder harness checks `/slots` |
| Logoff / reboot | Task restarts at next logon (`StartWhenAvailable`) | Log back on |
| Config change | n/a | `stop.ps1` + `Start-ScheduledTask` covers it |

`stop.ps1` + task start covers every server-side class above; nothing covers session-side
recovery.

## Findings (by severity)

### Critical (for unsupervised multi-hour use)
C1. No automatic restart after the server dies. Evidence: task Settings `RestartCount 3 /
PT1M` plus `register-task.ps1` docstring quoted above; `serve.ps1` ends with `exit
$LASTEXITCODE` (single run, no loop). Any crash or driver reset ends every remaining hour
of an unattended task. Fix: a bounded restart loop in `serve.ps1` (backoff, cap per hour,
log each restart) or a second task that polls `/health` every minute and runs
`Start-ScheduledTask`; enable `Microsoft-Windows-TaskScheduler/Operational` (currently
`IsEnabled False`) for history.
C2. Multi-hour single sessions have never run. Longest session 42.2 min
(`ladder-long-fix-20261026-132833.json`); 23 sessions on disk, not ~35. Fix: one
supervised 2-4 h run at the 131,072 default before claiming unsupervised use.

### Warnings
W1. Claude Code budget = server n_ctx with no margin (`claude-local.ps1` lines 89, 184-186
vs `-c 131072`, context shift disabled). Overflow behaviour is untested. Fix: default
`-LisContextTokens` to 131072 - 16384 (114,688) or test the overflow response once.
W2. Session death is terminal: 1/10 long-fix reps ended `autocompact_thrashing`
(`ladder-long-fix-20261026-154601.jsonl`); no resume. Fix: a supervisor that relaunches
with `--continue` (or a fresh session reading the facts file) on rc != 0.
W3. `claude-local.ps1` starts sessions without checking `/health` or slot busy (`run.ps1`
lines 365-381 do). Fix: copy that preflight into the wrapper; refuse or wait when
`is_processing`.
W4. VRAM 858 MiB free with the model loaded. A reload after a crash can fail if another
app takes VRAM. Fix: log `nvidia-smi` at serve.ps1 start; document that GPU apps must be
closed during unattended runs.
W5. Log cannot distinguish crash from stop (all 15 exits `-1`) and exit lines are missing
for 3 instances (10-24 15:56 and 15:58 start lines 1 and 19, 10-26 11:02 line 32750; 19
starts - 15 exits - 1 running). Fix: `stop.ps1` appends a "stopped by stop.ps1" marker
before `Stop-Process`.

### Recommendations
R1. Enable `--metrics` (or keep polling `/slots`) so KV fill and queue depth are
observable during long runs.
R2. Logon-only interactive task: fine for this workstation, but a logoff ends the server;
note it in the README.
R3. The `[claude-code:unrecognized_model]` stderr line (23/23) is benign; filter it in
reports.

## Verdict: FAIL
For "unsupervised multi-hour tasks": the server's steady state is clean (8.5 h under
ladder load, 0 error-level log lines, 0 CUDA/OOM, 0 truncations), but nothing restarts the
server or the session after a fault (C1, W2) and no session has run past 42 min (C2), so a
single fault ends the task unattended.
