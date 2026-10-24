# Roadmap

Each phase lists its goal, steps, done-check and open rulings. A phase is done
only when its done-check passes on this machine.

## P0 — Evaluation + scaffold (DONE 2026-10-24)

- Goal: decide the backend and lay out the repo.
- Steps: evaluate the two reference repos; survey Claude Code wiring, backends
  and models; write scripts and docs.
- Done-check: `docs/evaluation-2026-10-24.md`, `docs/landscape-2026-10-24.md`
  and `scripts/*.ps1` exist; the scripts parse without errors.
- Open rulings: none.

## P1 — Install + smoke (DONE 2026-10-24)

- Goal: llama-server answers `/v1/messages` with a tool call.
- Steps:
  1. `scripts/install.ps1` (llama.cpp b11868, CUDA 13.4 zip + cudart). Check the
     asset names against the release page first.
  2. `scripts/serve.ps1` (Qwen3.6-35B-A3B UD-IQ3_XXS, `-c 131072`, q8_0 KV).
  3. Set NVIDIA control panel "Prefer No Sysmem Fallback" so VRAM overflow fails
     loudly instead of spilling into shared memory.
  4. `scripts/smoke.ps1`.
- Done-check: the `/v1/messages` request with a tool definition returns a
  `tool_use` block (`smoke.ps1` prints PASS).
- Open rulings: CUDA 13.4 vs 12.4 build if 13.4 misbehaves.

## P2 — Claude Code profile + first agentic task (DONE 2026-10-24)

- Goal: Claude Code runs a real task end to end against the local server.
- Steps:
  1. `scripts/claude-local.ps1` in a throwaway repo.
  2. Verify that `ANTHROPIC_MODEL` / `config/claude-settings.json` override the
     main-session `model` from `~/.claude/settings.json`, and that subagents do
     not request a cloud model (the operator's global settings pin other model
     names, including `CLAUDE_CODE_SUBAGENT_MODEL` with `_FORCE=1`). Check the
     llama-server log for the model names requested.
  3. Give it a small multi-step task (edit code, run tests, fix).
- Done-check: one multi-step edit + test loop completes without manual
  intervention.
- Open rulings: thinking on or off by default; `CLAUDE_CODE_MAX_OUTPUT_TOKENS`
  value.

## P3 — Bench matrix

- Goal: pick the default model on measured numbers.
- Steps: for Qwen3.6-35B-A3B, Qwen3.8-27B, Gemma 4 26B-A4B, GLM-4.7-Flash and
  gpt-oss-20b, measure decode tok/s, prefill ms at a 20K prompt, tool-call
  success over 20 prompts and whether the target context fits. Results as JSON
  per `bench/README.md`.
- Done-check: one result file per model in `bench/results/`, summary table in
  `config/models.md`.
- Open rulings: uploader per model (Unsloth vs Bartowski, given the tool-call
  gap reported for one quant).

## P4 — MoE CPU offload

- Goal: test whether a larger MoE with experts in RAM beats the all-GPU default.
- Steps: Qwen3-Coder-Next 80B-A3B UD-IQ4_XS with `scripts/serve.ps1 -NCpuMoe N`,
  sweep N; same bench as P3.
- Done-check: bench JSON for at least two N values, compared with the P3 winner.
- Open rulings: whether ~40 tok/s is acceptable for agentic use.

## P5 — SGLang / vLLM in WSL2 (optional)

- Goal: only if a safetensors-only model justifies it.
- Steps: run the backend in WSL2/Docker with its Anthropic endpoint; same bench.
- Done-check: `smoke.ps1` PASS against the WSL2 endpoint, plus bench JSON.
- Open rulings: whether any candidate needs it at all on 16 GB.

## P6 — Speculative decoding / MTP

- Goal: speed-up from MTP heads once Qwen MTP GGUFs load in stock llama.cpp.
- Steps: `-ExtraArgLine '--spec-type draft-mtp --spec-draft-n-max 2'`;
  compare against P3 numbers.
- Done-check: bench JSON with and without MTP on the same model.
- Open rulings: none until the GGUFs exist upstream.

## Phase 1 run 2026-10-24

- Install: `scripts/install.ps1` defaults (b11868, CUDA 13.4). No `.sha256`
  sidecars are published; the script now checks the GitHub API asset `digest`
  instead, and both zips matched. `llama-server --version`: 0.7.0-dev (build
  11868, commit 78a8ae14b). cudart64_13, cublas64_13 and cublasLt64_13 DLLs sit
  next to it in `bin/`. `--list-devices`: CUDA0 RTX 4070 Ti SUPER (16375 MiB,
  15111 MiB free).
- Model: `-hf` pulled `Qwen3.6-35B-A3B-UD-IQ3_XXS.gguf` (13,211,155,424 B) plus
  `mmproj-BF16.gguf` (902,822,624 B, vision projector, loaded by default) into
  `%USERPROFILE%\.cache\huggingface\hub`, about 5 min. Load from cache: about 7 s.
- Architecture `qwen35moe`: 40 layers, 10 of them with a KV cache (hybrid), 256
  experts / 8 active, n_ctx_train 262144.
- Context: n_ctx 131072 allocated as requested (`--fit` left it unchanged).
- KV cache: q8_0 K and V, 1360 MiB (680 + 680) on CUDA0, 131072 cells over 10
  layers; recurrent state 62.81 MiB.
- `--fit` trimmed: yes. The full GPU load was projected at 14049 MiB against a
  free target of 2133 MiB (margin plus 1134 MiB mmproj worst case), so `--fit`
  kept 41/41 layers on GPU but moved part of the MoE expert tensors of 6 layers
  to CPU (overflow type GATE). Buffers: CUDA0 model 10968 MiB, CPU_Mapped about
  1621 MiB, CUDA0 compute 444 MiB, mmproj compute 248 MiB. The log warns
  "tensor overrides to CPU are used with mmap enabled".
- VRAM (`nvidia-smi --query-gpu=memory.used`): 15594 MiB on first load, 15408 to
  15432 MiB after restarts, of 16376 MiB. That includes about 1.3 to 2.4 GB used
  by the desktop and other apps before load (1694 to 2400 MiB observed).
- Smoke: FAIL at the old default `-MaxTokens 256` (stop_reason max_tokens, one
  1029-char thinking block). PASS 4/4 at 2048 (stop_reason tool_use,
  `get_weather {"city":"Mexico City"}`, thinking 230 to 1041 chars).
  `smoke.ps1` default raised to 2048. count_tokens: input_tokens=305 or 306.
- Speed (305-306-token prompt, `-np 1`): prompt processing 459 to 1421 tok/s
  (cold or partly cached, too short to compare with anything); generation
  108 to 121 tok/s.
- No thinking or template flags were needed. Startup warnings: no API key / CORS
  allows all origins; reasoning preserve is on by default; Qwen-VL image-token
  minimum.
- Not done: step 3 (NVIDIA control panel "Prefer No Sysmem Fallback") is a GUI
  setting for the operator.
- Found (FIXED): `pwsh -File scripts/serve.ps1 -ExtraArgs '-lv','4'` passes the
  single string `-lv,4` (llama-server: invalid argument). `-ExtraArgs` worked only
  from inside pwsh (`& scripts/serve.ps1 -ExtraArgs ...`) or via `pwsh -Command`.
  `serve.ps1` now splits a single space-separated string, so
  `pwsh -File scripts/serve.ps1 -ExtraArgs '-lv 4'` works (used for the re-run below).
  Superseded: that split broke a single value with spaces, so `-ExtraArgs` is now
  passed verbatim and the `pwsh -File` form is `-ExtraArgLine '-lv 4'`.
- 2026-10-24, re-run with `--no-mmproj` (now the `serve.ps1` default, plus
  `--api-key local`):
  - `--fit` still offloads: projected 14049 MiB against 15047 MiB free missed
    the 1024 MiB target by 26 MiB, so 41/41 layers stay on GPU with part of the
    MoE expert tensors of 2 layers on CPU (overflow type GATE; 6 layers with the
    mmproj). Buffers: CUDA0 model 12054 MiB, CPU_Mapped 398 + 137 MiB, CUDA0
    compute 436 MiB; KV and recurrent state unchanged (1360 + 62.81 MiB).
  - VRAM: 15575 to 15598 MiB used after load (1617 to 1809 MiB before load).
  - Smoke: PASS 3/3 at the new default `-MaxTokens 4096` (`get_weather
    {"city":"Mexico City"}`, thinking 615 to 868 chars).
  - Speed (305-306-token prompt): generation 137.2 to 137.9 tok/s (was 108 to
    121); prompt processing 795 to 2083 tok/s.
  - Auth: `x-api-key: local` and `Authorization: Bearer local` return 200; no key
    or a wrong key returns 401.

## Phase 2 run 2026-10-24

Claude Code 2.1.310, PowerShell 7.6, server from the P1 re-run (PID 20548,
`--api-key local`, alias `local`, ctx 131072). Sandbox: throwaway git repo in the
session scratchpad, `src/slugify.js` (no lowercasing, one `-` per character, no
trimming) plus `test/slugify.test.js` (4 `node:test` cases, 0/4 pass). No change
to `scripts/claude-local.ps1` or `config/claude-settings.json` was needed.

- Run A (wiring): `pwsh -NoProfile -File scripts/claude-local.ps1 -p "Reply with
  exactly: READY" --output-format json --max-turns 1 --debug-file <f>`. Result
  `READY`, 1 turn, 7.2 s wall. One `/v1/messages` request; debug log
  `dispatching to firstParty model=local`; `modelUsage` has only `local`
  (contextWindow 131072). Server log: one task, prompt 21162 tokens, the same as
  the client's `input_tokens` (prompt processing about 4000 tok/s).
  `--max-turns` is not in `claude --help` but is accepted.
- Run B (agentic loop): `pwsh -NoProfile -File scripts/claude-local.ps1 -p "Run
  `node --test`, fix src/slugify.js so all tests pass without changing the tests,
  run the tests again and confirm they pass." --permission-mode acceptEdits
  --max-turns 25 --output-format json --debug-file <f>`. Finished without
  intervention: `subtype success`, 22 turns, 17 API requests (all
  `model=local`), 65.3 s wall (API 58.2 s), 6205 output tokens. Tool calls: 10
  Bash, 4 Read, 3 Glob, 1 Edit dispatched (6 ended in error), plus 3 denied: two
  Bash heredoc/printf writes and one Write, all using Git Bash `/tmp/...` paths
  that the Write tool read as `\tmp\...` (outside the working dir). The model then
  used Edit. `node --test` afterwards: 4/4 pass. Fix: `.toLowerCase()`,
  `/[^a-z0-9]+/g` to `-`, strip a leading/trailing `-`; tests unchanged.
  `--allowedTools` was not needed, but Bash `node --test` ran without a prompt
  because the operator's `~/.claude/settings.json` allow list applied; on a
  profile without those rules it may prompt (UNVERIFIED).
- Run C (fork subagent): asked for a `general-purpose` subagent; the model
  spawned a `fork` (inherits the main model). 11 dispatches, all `model=local`.
  Sources: `sdk`, `agent:builtin:fork`, `side_query` (the side queries log no
  model name in the debug log). TCP connections of the new `claude.exe`, sampled
  every 150 ms for the whole run: only `127.0.0.1:8080`.
- Run D (model names on the wire): a pass-through Node proxy on 127.0.0.1:8081
  logged the request body of a scratch copy of the launcher that differs only in
  `ANTHROPIC_BASE_URL` (and an absolute `--settings` path). Prompt: use the
  built-in `Explore` subagent (Haiku tier by default). 11 requests, all
  `"model":"local"`, all HTTP 200: main session (24 tools, `max_tokens` 16384),
  Explore subagent (`agent:builtin:Explore`, 14 tools, 16384) and tool-less side
  queries (`max_tokens` 2112 and 10240). Result correct, `by_type {"Explore":1}`.
- Overlay vs pins: the debug log lists the settings env keys
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW, CLAUDE_CODE_SUBAGENT_MODEL,
  CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, so `_FORCE=1` from the global settings is
  still active. It forces the `CLAUDE_CODE_SUBAGENT_MODEL` value, which the
  `--settings` overlay sets to `local`. Global `model: fable` was overridden:
  no request named any model other than `local`.
- Traffic: no request URL other than `/v1/messages?beta=true` was seen at the
  proxy; no `count_tokens` call. Debug: `[Bootstrap] Skipped: Nonessential traffic
  disabled`, telemetry off. The 150 ms TCP sampling can miss very short
  connections, so "nothing went to api.anthropic.com" is UNVERIFIED beyond that.
- Requests carry `thinking: {"type":"adaptive"}` and `?beta=true` even with
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`; llama-server accepted both (200),
  and the client reported 0 thinking tokens. `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16384`
  is honored on the wire; the `maxOutputTokens 32000` in `modelUsage` is client
  metadata only. `total_cost_usd` is a list-price estimate, not a real cost.
- Warnings (stderr): `[claude-code:unrecognized_model] {"model":"local"}`;
  "claude.ai connectors are disabled because ... another auth source is set".
  Debug: skill listing over budget (32 skills), TypeScript LSP plugin failed to
  start (no `typescript` in the sandbox), `shell cwd read-back is not readable`.
  No rejected `thinking` / `output_config` and no retries were logged.
- Not `--bare`: the operator's global hooks (SessionStart orientation, PreToolUse
  reminders), skills and CLAUDE.md loaded; that makes the 21162-token first
  prompt. Ruled 2026-10-24: no `--bare` (see Rulings 2026-10-24).

## Rulings 2026-10-24

- (1) Ollama is paused, not uninstalled: its Startup-folder entry is disabled the
  way Task Manager does it and its processes are stopped. Details and the revert
  command: [ollama-paused.md](ollama-paused.md).
- (2) No `--bare`. The operator's global config (hooks, skills, CLAUDE.md, memory)
  stands in local sessions, and the 21K-token first prompt is accepted. P3
  measures its prefill cost instead.
- (4) The ~535 MiB of MoE expert tensors that `--fit` offloads to CPU (398 + 137
  MiB CPU_Mapped, 2 layers, P1 re-run) stays for now; revisit after the P3 numbers.
- (5) llama-server runs as the logon task `LocalInferenceStudio-llama-server`
  (`scripts/register-task.ps1`, log `logs/llama-server.log`). Cutover 2026-10-24:
  the shell-started server (PID 20548) was stopped, the task registered without
  elevation and started; `smoke.ps1` PASS. The task's restart settings only retry
  a launch that fails: a llama-server crash or `scripts/stop.ps1` stays down until
  the next logon or `Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server`
  (after a stop it did not come back within 85 s). It runs on battery too.
  Re-run `register-task.ps1` after moving the repo (paths are absolute).

## Phase 3 part A 2026-10-24

Baseline bench, the WebSearch/WebFetch deny overlay, an egress check and the
sysmem-fallback check. P3 stays open: part B (candidate matrix) is pending.

### Baseline

`pwsh bench/run.ps1 -Label qwen3.6-35b-a3b -Quant UD-IQ3_XXS -Ctx 131072 -NCpuMoe 0`
against the logon-task server (build `b11868-78a8ae14b`, flags as in
`scripts/serve.ps1` defaults). Result: `bench/results/20261024-163147-qwen3.6-35b-a3b.json`.

| Metric | Value |
| --- | --- |
| decode tok/s (median of 3, 256 tokens) | 104.4 (runs 77.8, 105.9, 104.4; the first is a warm-up) |
| prefill 20,000 tokens, cold (median of 3) | 4,859 ms (4,116 tok/s) |
| prefill 20,000 tokens, prefix cached | 30.5 ms (4 tokens evaluated) |
| tool calls (2 tools, 20 prompts) | 20/20 pass (0 wrong tool, 0 no call, 0 bad args, 0 errors) |
| tool-call latency, median | 1,583 ms |
| VRAM peak (whole GPU, nvidia-smi) | 15,797 MiB of 16,376 (idle with the server loaded: 15,698) |

The 128K context fits with the default `--fit` placement (ruling 4: about 535 MiB
of experts on CPU); 579 MiB of VRAM stays free at peak.

### Overlay: deny WebSearch and WebFetch

`config/claude-settings.json` gains `"permissions": {"deny": ["WebSearch", "WebFetch"]}`
(those tools run on Anthropic's side and cannot work against the local server).
VERIFIED from the `system/init` event of `--output-format stream-json --verbose`,
run through `scripts/claude-local.ps1` from a throwaway git repo:

- With the overlay: 22 tools, no WebSearch, no WebFetch.
- Control (scratch copy of the launcher with the old settings file): 24 tools,
  WebFetch and WebSearch present.
- Debug log: `Adding 2 deny rule(s) to destination 'flagSettings': ["WebSearch","WebFetch"]`.
  The operator's user settings allow `WebSearch`; the `--settings` deny wins.

### Egress (pktmon)

NOT RUN: `pktmon` needs elevation (`Failed to communicate with the PktMon driver:
Access is denied.` from a non-elevated shell). Weaker evidence, VERIFIED: during run A
(`-p "Reply with exactly: READY" --max-turns 1`, result `READY`) the new `claude.exe`
TCP connections, sampled every 100 ms (21 samples), showed only `127.0.0.1:8080`.
Short-lived connections between samples can be missed, so "no other egress" is
UNVERIFIED. Operator, from an elevated PowerShell 7 (one line):

```powershell
$d="$env:TEMP\p3-egress"; New-Item -ItemType Directory -Force $d | Out-Null; git -C $d init -q; (Resolve-DnsName api.anthropic.com -Type A).IPAddress | Set-Content "$d\anthropic-ips.txt"; pktmon start --capture --comp nics --pkt-size 0 -f "$d\p3.etl"; Push-Location $d; pwsh -NoProfile -File Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -p "Reply with exactly: READY" --max-turns 1; Pop-Location; pktmon stop; pktmon etl2txt "$d\p3.etl" -o "$d\p3.txt"; Select-String -Path "$d\p3.txt" -Pattern (Get-Content "$d\anthropic-ips.txt") -SimpleMatch | Measure-Object | % Count
```

Expected: `0` (no packet to an api.anthropic.com address). Loopback traffic
(`127.0.0.1:8080`) does not cross a NIC, so `--comp nics` cannot show it; pktmon
does not attribute packets to a PID (UNVERIFIED for this build), so other traffic on
the machine in the same window (for example model downloads) also appears in `p3.txt`.

### Sysmem fallback

The task server was stopped (`scripts/stop.ps1`), then `bin\llama-server.exe` ran
directly with the `serve.ps1` default flags plus `-c 1048576 --fit off --port 8090`.
It failed loudly in about 6 s, exit code 1, peak VRAM 15,629 MiB:

```
W llama_context: n_ctx_seq (1048576) > n_ctx_train (262144) -- possible training context overflow
E ggml_backend_cuda_buffer_type_alloc_buffer: allocating 10880.00 MiB on device 0: cudaMalloc failed: out of memory
E ggml_backend_buft_alloc_buffer_n_default: failed to allocate CUDA0 buffer of size 11408506880
E llama_init_from_model: failed to initialize the context: failed to allocate buffer for kv cache
E srv  server_run_i: exiting due to model loading error
```

No slow start that spilled into shared memory: consistent with "Prefer No Sysmem
Fallback" being in effect for `llama-server.exe` (the driver setting itself was not
read). Then `Start-ScheduledTask LocalInferenceStudio-llama-server`: `/health` ok after
10 s, `scripts/smoke.ps1` PASS (`get_weather {"city":"Mexico City"}`).
