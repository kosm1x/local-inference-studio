# Roadmap

Each phase lists its goal, steps, done-check and open rulings. A phase is done
only when its done-check passes on this machine.

## Status 2026-10-25

- Default server (rulings 6 and 14; ruling 14 of 2026-10-25 reverted ruling 12): Orca
  Qwen3.8-27B-Uncensored IQ3_XXS, ctx 131072, KV q4_0, patched chat template, no MTP;
  `claude-local.ps1` and `config/claude-settings.json` default to a 131072 window.
  Cutover and the re-run grades: ruling (14), whose closing condition (disks and GPU
  correct, no compaction) RUN 5 met; CLOSE = operator ruling. Scripts tip: the ruling
  14 commit (`git log -1 -- scripts/serve.ps1`).
- Local sessions use the lean set (ruling 13): 7 tools, no MCP, the one-model policy
  appended, hooks on; `-LisFull` restores the full tool set and MCP. Fresh-session prompt
  12,347 tokens from a scratch dir (was 25,578) and 12,775 from the repo root (was 26,224
  to 32,988), both before the 2026-10-25 policy block (+388: about 12,735 and 13,163);
  absolute sizes vary by a few hundred tokens with the cwd path, the reproducible figure
  is the saving (about 9,172 against `-LisFull` in the same cwd, about 12,812 against
  the pre-ruling full set; 9,560 and 13,200 before the policy block; all measured
  before the 2026-10-25 loop guards, +101 tokens of policy). First agentic
  loop on 65536 + MTP + lean: PASS 3/3, 6 turns, 40.7 s, 0 tool errors (one rep,
  variance UNVERIFIED).
- Permissions (ruling 15): rule set A plus the lis-guard hook in every local session
  (`-LisNoGuard` leaves the hook out); on the 24-command bench the hook cut classifier
  requests from 41 to 11 and wall time from 1,868.7 to 803.8 s. Graded re-run (RUN 4):
  0 classifier requests, 0 timeouts, 162.1 s wall against RUN 3's 341.7 s, but the
  report scored 7 of 14 with 2 false statements, so (15) stayed OPEN. RUN 5 scored 13 of
  14 with 0 false statements and 8 of 8 Bash decisions by the hook, so (15) is CLOSED
  (2026-10-25; the operator ruled the 61.5 GiB figure a rounding imprecision).
- TEST 6 (test-coverage audit, below): the stopped old-config rep led to `3a2a5d8`
  (exact allow rules for the two test runs, loop-guard policy sentences). Two reps
  under it: 12 of 14 with 1 false statement (a CASES split that sums to 434 against its
  own 546), and 13 of 14 with 1 false statement ("11 PowerShell scripts" against the 10
  its own table lists). Status: two reps done, 12/14 and 13/14, bar (>= 12 of 14 and 0
  false on both) pending ruling (17). The hook-test run: rejected on a classifier
  timeout in the stopped rep (619/619 on the third attempt); first attempt, under a
  second, in both reps under `3a2a5d8`. Lever (4), a deterministic check on the written
  document, built the same day (Levers below).
- P0-P3 DONE; Phase 3d loop comparison DONE (8 rows, all 3/3); P5 spike BLOCKED
  (KV capacity); P4 not started; P6 measured (GSQ-RCO, Phase 3b; the default's file,
  Phase 3e); the default used it from ruling 12 until ruling 14 removed it.
- The revised `serve.ps1` run by the task: proven 2026-10-25 06:37 UTC by the
  `Start-ScheduledTask` of the ruling 14 cutover (default command line in
  `logs/llama-server.log`, `/health` ok after 6 s, smoke PASS). UNPROVEN until it happens: the logon start itself
  (`Get-ScheduledTaskInfo` LastRunTime + `/health` after a logon).
- Live session 2026-10-24 22:00-23:00 (operator's first real Claude Code session on the
  default, read from `logs/llama-server.log`): 32 turns, 0 errors, 0 truncations, max
  context 45,417. Decode 654 s for 24,320 tokens (37.2 tok/s avg, 45 -> 35 across the
  context range); prefill 76 s, of which 60 s were 3 full re-reads (prefix cache hit on
  29/32 turns). 13/32 answers exceeded 1,000 tokens. Lesson: in real use decode time,
  not prefill, is the cost of the dense 27B; verbosity is the lever. Phase 3e (measured):
  Orca + MTP (`--spec-type draft-mtp --spec-draft-n-max 2`) at ctx 65536 with q4_0 KV
  FITS all-GPU (66/66 layers, 1,684 MiB left free; the 131072 default leaves 1,630) and
  decodes at 81.6 tok/s against 45.4 without MTP at 65536 and 45.3 for the 131072
  default (1.80x); prefill 20K 11,876 vs 11,387 ms (+4 %), tool calls 20/20, p50 788 vs
  1,366 ms, cumulative draft acceptance 0.81. The cost is context: 65536 against the
  45,417 peak. Real-text and deep-context speed-up UNVERIFIED. Table and placement:
  [bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md) ("Phase 3e").
- Open rulings: (14) closing condition (disks and GPU correct, no compaction) met by
  RUN 5; CLOSE = operator ruling; (9) Bonsai revisit (a dense 27B now IS the default
  and VRAM headroom is 1,630 MiB, so the deferral condition is met); P4 go/no-go;
  whether a harder, multi-file loop fixture should settle the accuracy question that
  the 3-test fixture could not (every contender passed it); (16) serve a second,
  smaller model for the auto-mode classifier via `CLAUDE_CODE_AUTO_MODE_MODEL` (same
  endpoint; whether llama-server b11868's router mode can serve it is UNVERIFIED;
  nvidia-smi on 2026-10-25 showed 653 MiB free with every process counted, a
  point-in-time value, while the 1,630 MiB in (9) is llama's projected fit for the
  model alone), or keep the classifier on the main model (TEST 6 below); (17) whether
  a figure that contradicts the report's own figures is a false statement under the
  bar (TEST 6: rep 1's CASES split sums to 434 against its stated 546; rep 2 says "11
  PowerShell scripts" against the 10 it lists), which decides whether TEST 6 met it
  (TEST 6 below).

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

## P3 — Bench matrix (DONE (measurement); default model RULED 2026-10-24, ruling 6)

- Goal: pick the default model on measured numbers.
- Steps: for Qwen3.6-35B-A3B, Qwen3.8-27B, Gemma 4 26B-A4B, GLM-4.7-Flash and
  gpt-oss-20b, measure decode tok/s, prefill ms at a 20K prompt, tool-call
  success over 20 prompts and whether the target context fits. Results as JSON
  per `bench/README.md`.
- Done-check: one result file per model in `bench/results/`, summary table in
  `config/models.md`. Passed: five result files from the warm-up-fixed re-run
  (see "Phase 3 part B"); the full table is `bench/summary-2026-10-24.md`, and
  `config/models.md` carries the measured fit, decode tok/s, prefill 20K ms and
  status per row.
- UNVERIFIED: prefill only at 20K tokens; the 20 tool prompts are synthetic (two
  tools, one turn); one run per model, no variance; every model ran with the
  Qwen-tuned `serve.ps1` sampling; decode text quality not inspected.
- Default model: RULED 2026-10-24 (ruling 6), Orca Qwen3.8-27B-Uncensored IQ3_XXS at
  131072 with q4_0 KV and the patched chat template; ruling 12 moved it to 65536 with
  MTP on, ruling 14 moved it back to 131072 without MTP; the logon task serves that.
- Open rulings: uploader per model (Unsloth vs Bartowski, given the tool-call gap
  reported for one quant).

## P4 — MoE CPU offload

- Goal: test whether a larger MoE with experts in RAM beats the all-GPU default.
- Steps: Qwen3-Coder-Next 80B-A3B UD-IQ4_XS with `scripts/serve.ps1 -NCpuMoe N`,
  sweep N; same bench as P3.
- Done-check: bench JSON for at least two N values, compared with the P3 winner.
- Open rulings: whether ~40 tok/s is acceptable for agentic use.
- Status 2026-10-24: not started. Ruling 6 accepted 45 tok/s for accuracy, so the
  bar for P4 is correctness on the loop fixture against the Orca default, not speed.

## P5 — SGLang / vLLM in WSL2 (optional)

- Goal: only if a safetensors-only model justifies it.
- Steps: run the backend in WSL2/Docker with its Anthropic endpoint; same bench.
- Done-check: `smoke.ps1` PASS against the WSL2 endpoint, plus bench JSON.
- Status 2026-10-24 (spike, see "Phase 5 spike 2026-10-24"): OrcaSAQ-2-27B is
  BLOCKED on this box. vLLM 0.30.0 runs the EXL3 checkpoint on sm_89 in WSL2, but after
  11.26 GiB of weights its KV pool is 0.33 to 0.49 GiB, and 32768 ctx needs 1.29 GiB.
  Done-check not met (no server came up, so no smoke and no bench JSON).
- Open rulings: whether any candidate needs it at all on 16 GB; for OrcaSAQ-2-27B,
  accept "blocked" or authorize one of the untried levers listed in the spike section.

## P6 — Speculative decoding / MTP

- Goal: speed-up from MTP heads once Qwen MTP GGUFs load in stock llama.cpp.
- Steps: `-ExtraArgLine '--spec-type draft-mtp --spec-draft-n-max 2'`;
  compare against P3 numbers.
- Done-check: bench JSON with and without MTP on the same model.
- Status 2026-10-24 (Phase 3b): stock b11868 runs the Qwen MTP head, so P6 needs
  no custom build or fork: `--spec-type draft-mtp --spec-draft-n-max 2` loaded the
  `blk.64.nextn.*` layer of ISTA-DASLab `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` on
  the first try. With and without MTP on that model: 48.8 -> 83.7 tok/s at 65536
  ctx (both all-GPU; draft acceptance 0.67 to 1.00 per request), but 26.4 -> 18.0
  tok/s at 131072, where the MTP layer weights, draft KV and extra recurrent state
  (about 1.34 GB projected) plus 300 MiB less free memory at start pushed `--fit`
  from 61 to 52 GPU layers. The done-check is met for that model;
  speed-up on real agent text is UNVERIFIED.
- Status 2026-10-24 (ruling 6): the new default, Orca Qwen3.8-27B-Uncensored
  IQ3_XXS, carries an MTP layer (`nextn_predict_layers` 1; the server logs
  `blk.64.*` as unused tensors), but MTP is not tried on it and not planned for the
  default: at 131072 with q4_0 KV it has 1,630 MiB left free, and GSQ-RCO + MTP with
  1.2 GB smaller weights already missed all-GPU there by 124 MiB, so the default
  would lose GPU layers with MTP on (estimate, UNVERIFIED). P6 does not apply to the
  default as served.
- Status 2026-10-24 (Phase 3e): measured on the default's file at 65536 with q4_0 KV.
  With MTP: 66/66 layers, 1,684 MiB left free, 81.55 tok/s, prefill 20K 11,876 ms,
  20/20 tools (p50 788 ms), 1,302 / 1,611 drafted tokens accepted (mean acc len 2.62);
  without: 66/66, 3,102 MiB free, 45.37 tok/s, 11,410 ms, 20/20 (p50 1,362 ms). MTP
  costs 1,118 MiB projected at 65536. Done-check met for this model too. Speed-up on
  real agent text, at deep context and at 131072 UNVERIFIED.
- Status 2026-10-24 (ruling 12): the default now serves 65536 + MTP (`serve.ps1` adds
  the two flags for the default file unless `-NoMtp`). First live request after the
  cutover: 73 tokens at 64.6 tok/s, draft acceptance 0.74 (43 / 58) on a 25,578-token
  prompt (one short answer, not a decode benchmark).
- Status 2026-10-25 (ruling 14): the default no longer uses MTP (131072, no MTP flags);
  `serve.ps1 -Ctx 65536` still adds them for the default file. MTP is not blamed for the
  wrong recon report (the 65536 window's early compaction is; one rep per arm; cwd, tool
  set and interactivity also differed between RUN 1 and RUN 2); see ruling (14).
- Open rulings: for other models the same context-for-MTP trade stays open.

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

### Rulings 2026-10-24, second batch (after Phases 3b, 3c and the P5 spike)

- (6) Default model: decided by a real agentic-loop comparison (Phase 3d), not by
  tok/s. Contenders: Qwen3.6-35B-A3B (current default), gpt-oss-20b, Saluki 27B,
  GSQ-RCO IQ3_XXS with MTP at 65536. Qwen3.6 keeps serving until then.
  RECOMMENDATION from Phase 3d (the ruling stays with the operator): gpt-oss-20b
  MXFP4 at 131072 with q8_0 KV. Every final row passed 3/3, so pass rate did not
  separate them; gpt-oss-20b was the fastest on the final fixture (median 26.6 s, 8 turns,
  no template patch, all-GPU with 2 GB free, 170 tok/s). Qwen3.6-35B-A3B stays the
  fallback (3/3, 45.6 s, but 16 turns and 15 tool errors from guessed paths). The
  Qwen3.8-27B rows (69 to 156 s) work only with the patched chat template. The
  evidence is one small task at n=3; harder tasks are UNVERIFIED.
  RULED 2026-10-24 by the operator, CLOSED: the default is Orca Qwen3.8-27B-Uncensored
  IQ3_XXS (`models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ3_XXS.gguf`) at
  131072 with q4_0 KV and `--chat-template-file config/chat-templates/qwen3.8-27b.jinja`
  (REQUIRED). Reason: accuracy over speed; it is the only final Phase 3d row at 131072
  with 0 tool errors and 0 denials (3/3, median 8 turns; the other 0-error row,
  GSQ-RCO + MTP, holds that only at 65536), and the operator accepts its cost
  (median loop wall 127.7 s against gpt-oss-20b's 26.6 s; 45.3 tok/s decode).
  `scripts/serve.ps1` defaults now produce this command line, so the logon task
  (action unchanged, `-LogFile` only) serves it. Cutover 2026-10-24 21:22: `stop.ps1`,
  `Start-ScheduledTask`, `/health` ok after 5 s; a `-lv 4` start on :8081 read 66/66
  layers on GPU, 10,137 MiB CUDA0 model buffer, 521 MiB CPU_Mapped, 2,304 MiB q4_0 KV,
  1,630 MiB left free (projected 13,330 of 14,961 MiB); `smoke.ps1` PASS
  (`get_weather {"city":"Mexico City"}`); `claude-local.ps1 -p ... --max-turns 1`
  returned `is_error` false, result "ok", `modelUsage` `local` only. Quality and
  refusal removal of the abliterated build stay UNVERIFIED. Fallbacks: gpt-oss-20b
  MXFP4 (fastest) and Qwen3.6-35B-A3B UD-IQ3_XXS (`-Model
  unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS -KvType q8_0`).
- (7) Phase 6 (MTP): folded into that comparison as the fourth contender; no
  separate MTP decision. The ruled default ran without MTP until ruling 12 (see P6).
- (8) vLLM/WSL2 stack from the P5 spike: REMOVED 2026-10-24 (`~/lis-vllm` 9.9 GB,
  `~/lis-vllm-dl` 402 MB, `~/.cache/vllm` 1.1 GB, `models/orcasaq-2-27b` 12 GB).
  The install recipe in the Phase 5 section stays for a larger GPU.
- (9) Bonsai 2 27B (PrismML fork): DEFERRED until after the loop comparison;
  revisit only if a dense 27B wins and VRAM headroom becomes the bottleneck.
  2026-10-24 later: a dense 27B is now the default (ruling 6) with 1,630 MiB free,
  so the condition is met; revisit is an OPEN ruling (fork = separate binary, no
  `/v1/messages` guarantee; see `docs/evaluation-2026-10-24.md`).
- (10) Egress proof: RUN 2026-10-24 19:03 by the operator, PASS after attribution
  (8 keepalive lines from the operator's own cloud session, 0 from the local run);
  details in "Phase 3 part A" (Egress). CLOSED.
- (11) Phase 3d scope widened during the run: Orca Qwen3.8-27B-Uncensored IQ2_XXS
  added as a fifth contender; KV q4_0 variants added for GSQ-RCO+MTP at 131072,
  Orca IQ3_XXS at 131072 and gpt-oss-20b (control), each with a loop and a
  throughput pass. The idle Radeon iGPU is NOT a lever: three 4K monitors cannot
  move to it and the desktop's VRAM is mostly application rendering. The KV cache
  type is the lever (q8_0 KV = 4.35 GB at 131072 on a dense 27B; q4_0 about half).
- (12) Default context and MTP (after Phase 3e): RULED 2026-10-24 by the operator,
  ADOPT, CLOSED; REVERTED 2026-10-25 by ruling (14) (report accuracy: on the 65536
  window Claude Code auto-compacted at 39,098 tokens and the model's own summary rewrote
  the disk facts it had read; MTP exonerated, the 65536 window is the problem (one rep
  per arm; cwd, tool set and interactivity also differed between RUN 1 and RUN 2)). The record
  below is kept as history. The default became Orca IQ3_XXS at ctx 65536, q4_0 KV, patched chat
  template (unchanged) and MTP ON (`--spec-type draft-mtp --spec-draft-n-max 2`), on
  the Phase 3e numbers (66/66 layers, 1,684 MiB left free, 81.6 tok/s against 45.3).
  `serve.ps1`: `-Ctx` defaults to 65536 and the MTP flags are added for the default
  file only unless `-NoMtp` (any other `-Model` unchanged); `claude-local.ps1
  -LisContextTokens` and `config/claude-settings.json` `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
  default to 65536. Cutover 2026-10-24 22:52: single-tenant check (only the task's
  llama-server PID 27540 on the GPU, :8081 free, slot idle), `stop.ps1`,
  `Start-ScheduledTask`, `/health` ok after 6 s, PID 15328; the task log's command line
  carries `-c 65536`, `-ctk q4_0 -ctv q4_0`, `--chat-template-file
  ...\qwen3.8-27b.jinja` and `--spec-type draft-mtp --spec-draft-n-max 2`, the log shows
  "creating MTP draft context", `/slots` reports `n_ctx` 65536 and `speculative` true;
  `smoke.ps1` PASS (`get_weather {"city":"Mexico City"}`); `claude-local.ps1 -p ...
  --output-format json --max-turns 1` from a scratch dir returned `is_error` false,
  result "ok", `usage.input_tokens` 25,578, `modelUsage` `local` only with
  `contextWindow` 65536. An agentic loop on this configuration, real-text and
  deep-context MTP speed-up, and sessions that need more than 65536 tokens (Claude Code
  compacts earlier) stay UNVERIFIED. Revert: `serve.ps1 -Ctx 131072 -NoMtp` with
  `claude-local.ps1 -LisContextTokens 131072` (the wrapper rewrites
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` in its per-run settings copy to the same value, so
  the settings env and the process env cannot disagree).
- (13) Lean set for local sessions (after the fresh-session context audit,
  [context-audit-2026-10-24.md](context-audit-2026-10-24.md)): RULED 2026-10-24 by the
  operator, ADOPT, CLOSED. One local model runs long unsupervised tasks here, so
  `claude-local.ps1` now adds, before the forwarded arguments, `--tools
  Bash,Read,Edit,Write,Glob,Grep,Skill` (Skill is never dropped alone: the Workflow
  schema then grows by about 4,000 tokens), `--strict-mcp-config --mcp-config` with a
  per-run empty `{"mcpServers":{}}` file (`%TEMP%\lis-mcp-<pid>.json`, deleted with the
  settings copy) and `--append-system-prompt` with the 112-word one-model policy (audit
  section 5). `config/claude-settings.json` `permissions.deny` gains `Agent` and
  `Workflow`. Hooks stay on (no `disableAllHooks`); no `--bare` (ruling 2). The wrapper
  switch `-LisFull` omits the three additions for a session that needs the full tool set
  or MCP; the settings deny of Agent and Workflow still applies there. Measured
  2026-10-24 on the live server (PID 15328, Orca 65536 + MTP), `claude-local.ps1 -p
  "reply with the single word ok" --output-format json --max-turns 1`, prompt =
  `usage.input_tokens` + `cache_read_input_tokens` (= the server's `prompt eval` count):
  scratch dir outside `Z:\repos` 25,578 -> 12,347 (-13,231); repo root 26,224 (MCP
  connecting) / 32,988 (MCP connected) -> 12,775; `-LisFull` from the scratch dir 21,908
  (not the old 25,578: the settings deny removes the Agent and Workflow schemas and the
  agent listing, matching audit run (b) 21,911). Absolute sizes depend on the cwd path and
  environment text: the qa-auditor's re-run from a longer scratch path measured 12,644
  and 22,205 (+297 in both). The reproducible figure is the lean saving, 9,561 against
  `-LisFull` in the same cwd (about 13,200 against the pre-ruling full set). Every run `is_error` false, result "ok",
  `modelUsage` `local` only. First agentic loop on 65536 + MTP + lean
  (`bench/loop/run.ps1 -Reps 1`, fresh fixture copy under `%LOCALAPPDATA%\lis-loop`):
  PASS, tests 3/3 (`node --test` re-run in the copy: 3 pass, 0 fail), 6 turns, wall
  40.7 s (api 36.5 s), tokens in 72,370 / out 2,017, 0 tool errors, 0 denials,
  `is_error` false, VRAM peak 15,457 MiB, first request 12,587 tokens. Phase 3d's Orca
  row (131072, no MTP, full tool set) had a median of 8 turns and 127.7 s; one rep, so
  the variance and the share of the speed-up owed to MTP versus the smaller prompt are
  UNVERIFIED. The policy text is in the session's `prompt_snapshot` system prompt
  (transcript, last of 10 blocks); the server log runs at verbosity 3 and records no
  prompt text, so server-side receipt rests on the token delta (scratch 12,347 against
  the audit's 12,193 for `--tools` alone plus its measured 148 for the append).
  Interactive sessions on the lean set and harder tasks are UNVERIFIED.

### Rulings 2026-10-25

- (14) Default context back to 131072, no MTP: RULED 2026-10-25 by the operator, OPEN
  after the re-run (RUN 3, below: no compaction, but the report misses 6 of 8 volumes,
  J and K included, and the GPU). Reason: report accuracy. The operator's "Make a recon of
  this PC" session on 65536 + MTP + lean set, auto permission mode (RUN 2), produced a
  wrong report: Claude Code auto-compacted at 39,098 tokens, the local model's own
  summary turned the disk tool output (J: 135 of 4,657 GiB free, K: 328 of 14,902) into
  "mostly free", and the final report was written from that summary, wrong on J and K
  and silent on the GPU. The earlier run of the same request on 131072, no MTP, full tool
  set (RUN 1) was correct. MTP is exonerated (speculative decoding keeps the target
  model's output distribution; nothing in the transcript points to it); the 65536 window
  is the problem (one rep per arm; cwd, tool set and interactivity also differed between
  RUN 1 and RUN 2). Invocations: RUN 1 was an interactive session in this repo ("Recon
  this PC" after an "Introduce yourself" turn); RUN 2 an interactive session in
  `Z:\repos\kosm1x\PC` ("Make a recon of this PC", with operator `/permissions` grants
  mid-session); the invocation differences are a confound. Kept: the lean set (ruling 13), auto permission mode and hooks on.
  `serve.ps1`: `-Ctx` defaults to 131072; MTP stays available for the default file at
  `-Ctx` 65536 or below unless `-NoMtp` (the default start adds no MTP flags and no
  warning; an explicit `-Ctx` above 65536 still warns). `claude-local.ps1
  -LisContextTokens` and `config/claude-settings.json` `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
  default to 131072; the lean policy text now names a 131,072-token window. The Phase 3e
  numbers above stay as history. Cutover 2026-10-25 06:37 UTC: slot idle, only the
  task's llama-server PID 15328 on the GPU, :8081 free; `stop.ps1`,
  `Start-ScheduledTask`, `/health` ok after 6 s, PID 20400; the task log's command line
  carries `-c 131072`, `-ctk q4_0 -ctv q4_0`, `--chat-template-file
  ...\qwen3.8-27b.jinja` and no `--spec-type` (no "MTP draft context" line); `/slots`
  reports `n_ctx` 131072 and `speculative` false; `smoke.ps1` PASS (`get_weather
  {"city":"Mexico City"}`). Re-run (RUN 3) 2026-10-25 06:38 to 06:44 UTC, the only
  non-interactive run (`claude-local.ps1 -p "Make a recon of this PC" --output-format
  json --permission-mode auto --max-turns 60`) from the same cwd as RUN 2: `is_error`
  false, 10 turns, 341.7 s wall, 9 Bash calls, 3 tool errors (1 classifier timeout, 0
  classifier denials (the result JSON's `permission_denials` lists the one timed-out
  call), 2 real; the timeout was a queueing effect: two parallel tool calls produced two
  classifier requests on the single slot (`-np 1`), and the client cancelled the second
  after 1 s of waiting behind a 59 s decode),
  no compaction, main-loop peak 18,048 tokens (classifier requests 36K to 38K), decode
  35.5 to 40.5 tok/s. Grade against the machine: OS, CPU, RAM, C and Z, toolchain,
  Docker (daemon down), WSL and repo counts CORRECT; D, E, F, G, J and K OMITTED, so J
  (135 of 4,657 GiB free) and K (328 of 14,902) are not flagged; GPU OMITTED (the
  report says it was not checked); one minor WRONG (the cwd called a repo). No false
  disk or GPU claim, so the compaction defect is gone; the new gap is tool use, with three causes
  across the three drive queries: (a) one never executed (the single classifier
  timeout); (b) one ran as `powershell -Command "... $_ ..."` through Git Bash with `$_`
  unescaped, and bash expanded it; (c) one used an escaped `\$_` and failed inside
  PowerShell on operator precedence (`-f $_.Size/1GB, $_.FreeSpace/1GB`: the comma binds
  tighter than `/`, "Index (zero based) must be greater than or equal to zero..."),
  hidden by `2>/dev/null`. The fallback `df -BG /c /z` named only C and Z. One rep, variance UNVERIFIED. Numbers: bench/summary-2026-10-24.md
  ("Recon task, 3 runs"). Stays OPEN: the closing condition (correct on disks and GPU
  with no compaction) is not met. Next levers are for the operator to rule on: the
  `$_`-through-bash trap (policy text, or a PowerShell tool for the local session),
  which covers only (b); silenced stderr (`2>/dev/null`), which hid (c); and a recon
  checklist.

- (15) Permissions, only writes and deletes of critical files block or ask: RULED
  2026-10-25 by the operator, built the same day, OPEN after the graded recon re-run
  (RUN 4, plan section 6), CLOSED 2026-10-25 after RUN 5 (61.5 GiB ruled a rounding
  imprecision; RUN 4 and RUN 5 results end this entry). Plan and measurements:
  [docs/permissions-assessment-plan-2026-10-25.md](permissions-assessment-plan-2026-10-25.md)
  (sections 0a and 5a). Built: rule set A in `config/claude-settings.json` (read-only
  allow prefixes, critical-write ask rules; `Bash(*)` cannot be used, auto mode strips it)
  and `scripts/hooks/lis-guard.py`, a PreToolUse Bash hook the wrapper adds unless
  `-LisNoGuard` (critical write anywhere, payloads and ssh included -> deny with "not
  retryable; report it to the operator"; read-only -> allow; else no decision). The
  hook's deterministic scan is the judge of record for script execution and interpreter
  payloads (operator ruling 2026-10-25): critical line -> deny quoting it, all lines
  read-only -> allow, unparseable -> the classifier judges. Verified: V12 a hook allow
  skips the classifier (2 requests, 16 s); V13 the not-retryable deny ends the `-p` loop
  after one attempt (V7: four retries to `error_max_turns`); V14 a mid-pattern ask rule
  sees inside a quoted payload. Bench (`bench/perm/run.ps1 -Sample 24`, the same 24
  corpus commands): set A 11 rule, 6 classified, 7 blocked, 41 classifier requests,
  1,868.7 s; set A + hook 18 hook, 1 rule, 4 classified, 1 blocked, 11 classifier
  requests, 803.8 s (median run 49.0 vs 16.0 s). One rep per set. Not covered by any
  rule or the hook: `python -c` pipes, `for` loops, `wsl --default`, quoted program paths,
  and ssh by rule (a trailing `*` spans the remote command, so ssh is the hook's job).
  Reads of any file stay unguarded (ruling 15).
  RUN 4 (2026-10-25, one rep, `-p` auto mode, RUN 3's prompt and cwd, wrapper defaults):
  the permission targets are met, the report targets are not. 16 Bash calls: 15 hook
  allow, 1 rule allow, 0 classifier requests (RUN 3: 7), 0 timeouts (RUN 3: 1), 0
  denials; hook 91 to 119 ms per call. Wall 162.1 s (RUN 3: 341.7 s), api 132.6 s, 17
  turns, no compaction, peak context 21,880, decode 38.5 to 41.4 tok/s. Checklist 7 of
  14 (RUN 3: 8): volumes D to K, the J/K nearly-full flag, the GPU and llama-server
  missing. Two false statements: "Docker Desktop is not installed" (it is installed, the
  daemon is stopped; a script RUN 2 left in the cwd tests a path that does not exist and
  printed `False`) and 46 repos against the sweep's own 47. Stays OPEN: the remaining
  gaps are recon coverage and an unchecked probe, not permissions; the next lever is the
  recon checklist named under (14). Table: [bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md)
  ("Recon task, 4 runs"). Live C (interactive, one rep): 0 classifier requests, checklist
  9 of 14, 1 false statement (repo counts); stays OPEN.
  Policy-text levers (2026-10-25, the follow-up named under (14) and above): the wrapper's
  appended policy gains an evidence block (numbers copied from tool output, counts via
  `wc -l` / `Measure-Object`, read a script before citing it, no `2>/dev/null` on probes,
  single-quoted PowerShell payloads in Bash, UNVERIFIED marks) and a machine-survey
  checklist (every volume with free space, GPU, llama-server process and model via
  `/props` `model_path`, VPS reachability by IP); policy 152 -> 540 tokens on the server
  tokenizer, and the fresh-session prompt from one scratch cwd 12,634 -> 13,022 (+388,
  same `-p` call, one rep). Effect on the report UNVERIFIED until RUN 5.
  RUN 5 (2026-10-25 23:43 UTC, one rep, interactive from the wrapper with its defaults,
  tip `f8aa94a`, an empty non-git cwd, the single turn "Recon this PC"): the permission
  and report targets are both met. 8 Bash calls in two parallel batches of 4, exactly
  the policy checklist's commands (`df -h`, a single-quoted `Get-Volume` payload,
  `nvidia-smi`, a CIM one-liner, the toolchain line, `docker version` + `wsl -l -v`,
  `tasklist` + `/props`, ssh `uptime`): 8 hook allow, 0 rule, 0 classifier requests, 0
  denials, 0 tool errors, 0 prompts. Wall 161.8 s, 3 main-loop requests plus a title
  and an away-summary side request, no compaction, peak context 19,252 of 131,072.
  Checklist 13 of 14 (RUN 4: 7): all 9 volumes (a new M: included) with J and K flagged
  at 98 %, the GPU, CPU, RAM and OS, six toolchain versions, the Docker daemon down (no
  "not installed" claim), WSL state, the llama-server PID and model path, VPS uptime.
  The one miss is the repo sweep count, which the policy checklist does not ask for. 0
  false statements, one rounding imprecision (61.5 GiB RAM against 61.64 in the tool
  output). RUN 5 met the bar (>= 13 of 14, 0 false statements); the operator ruled the
  61.5 GiB figure a rounding imprecision and closed (15) on 2026-10-25. Variance
  UNVERIFIED.

### TEST 6 2026-10-25 (test-coverage audit)

- Rep 1 (one rep, through `claude-local.ps1` with rule set A, the lis-guard hook, auto
  permission mode, Orca IQ3_XXS at 131072; this was the only user turn): "Audit this
  repo's test coverage: which scripts have tests, which do not, how the existing tests
  run, and what is missing. Write the findings and a prioritised plan to
  docs/planning/test-coverage-2026-10-25.md. Change no other file." The operator stopped
  the session at 39 minutes because it was looping: no file written, repo clean after.
  Rep 2 was NOT run under the old config. Tally from the transcript's permission records:

| Item | Count |
| --- | --- |
| Tool calls (Bash 39, Read 15, Grep 3) | 57 |
| Bash decided by the hook (all correct, instant) | 14 |
| Bash matched by Claude Code's per-subcommand rule check | 5 |
| Bash sent to the auto-mode classifier | 19 |
| of those allowed | 8 |
| of those rejected (10 timeouts at the 60 s budget, 1 stage 2 error) | 11 |
| Bash rejected by the operator when stopping the session | 1 |
| Read/Grep decided by user-level allow rules | 18 |
| Tool errors | 16 |
| Peak prompt, tokens (no compaction) | 93,496 |

- Findings. (a) The classifier is two-stage, each stage a ~38K-token prompt on the
  single server slot, alternating with the ~90K main prompt, so the caches evict:
  early single verdicts took 17 to 29 s, and once the main context passed ~70K stage 1
  alone took 45 to 60 s, so 10 of the 19 classifier-bound commands hit the 60 s
  budget (`classifier:auto-mode:unavailable`; the server requests outnumber the
  commands, stage 1 plus stage 2). (b) Both rejection texts tell the model to retry: the
  timeout text says the check is "temporarily unavailable (timed out) ... Wait a
  moment and then try this action again", the stage 2 error text says "usually
  transient - retrying often succeeds". With no retry cap the model wrote "classifier
  timeouts have been transient" and retried: that is the loop. (c) Scope creep: from
  minute 26 it issued a WSL "Linux CI proxy" re-run of the same test suite 10 times:
  2 ran and failed on Git Bash path conversion of `/mnt/z/...`, 7 hit classifier
  timeouts (the other 3 of the 10 timeouts were other commands), and 1 was rejected by
  the operator when stopping the session; the task asked for no such check.
  (d) Read-everything research: 14 Read calls took every script in full, the 49 KB
  hook test file included, in the first two minutes, reaching 61K context before any
  command needed the classifier. The first classifier-bound commands (the hook tests
  and the fixture `node --test`) went out in one parallel batch; the first timed out,
  the retry failed on a stale shell cwd, the third got `619/619 passed` at minute 8.
  (e) Counts by tool held, but the test count came out three ways (619 from the run,
  418 and 546 from Grep counts of tuple patterns) and was never reconciled; two inline
  `python -c` counters were also rejected.
- Permission layer: the hook decided 14 Bash calls, all correct and instant. It
  allowed a `pwsh -NoProfile -Command '(Get-Module -ListAvailable -Name Pester ...) |
  ForEach-Object { "$($_.Version) - $($_.Path)" }'` probe; two mutants with
  `$(New-Item ...)` and `$(Invoke-Expression ...)` inside the payload, fed to the hook
  on stdin, got no decision: sound. Context for the audit itself: Pester 3.4.0 is
  installed under Windows PowerShell; the repo has no Pester tests, no CI, no `.github/`.
- Levers. (1) Narrow allow rules, shipped: `Bash(python -I
  scripts/hooks/tests/lis-guard_test.py)` and `Bash(node --test
  bench/loop/fixture/test/text.test.js)` in rule set A (the fixture form runs from the
  repo root, no `cd`). The docs say a narrow rule stays in effect in auto mode and is
  resolved before the classifier, while broad ones (`Bash(*)`, `Bash(python*)`) are
  dropped; whether an exact interpreter rule with arguments counts as narrow was not in
  the docs. Proven for the hook-test rule (one `-p` run through the wrapper, auto mode):
  the transcript records `"decision":"accept","source":"config","reasonType":"rule",
  "ruleSource":"flagSettings"`, the debug log has no classifier request and
  `permissionDecisionMs=8`, and the run printed `619/619 passed`. The fixture rule
  survived the auto-mode rule filter (absent from the debug log's removal list); its
  decision at call time was proven on 2026-10-25 (config rules decided it in both reps
  under `3a2a5d8`, below). That list does drop set A's `Bash(node -v*)`,
  `Bash(node --version*)` and `Bash(python --version*)` ("Ignoring dangerous permission
  ... (bypasses classifier)"), so those three never apply in auto mode. (2) Policy
  sentences, shipped (+432 characters, 101 tokens on the server tokenizer; the whole
  policy 540 -> 641): plain reads may run in parallel, but at most one command per
  Bash batch that executes a program, writes or changes state; after a
  permission-check timeout retry once, and if that also fails mark the figure
  UNVERIFIED and move on; no checks the task does not need (no re-runs on other
  platforms, no side investigations); grep or read a line range of a file over 300
  lines. (3) Operator ruling (16): serve a second, smaller model for the classifier via
  `CLAUDE_CODE_AUTO_MODE_MODEL`, which goes through the same endpoint (whether
  llama-server b11868's router mode can serve it is UNVERIFIED; nvidia-smi on
  2026-10-25 showed 653 MiB free with every process counted, a point-in-time value,
  while the 1,630 MiB in (9) is llama's projected fit for the model alone), or keep
  the classifier on the main model. No
  setting exists for the classifier timeout or for skipping stage 2, and
  `autoMode.classifyAllShell` stays unset. (4) Verification of the written document, as
  the orchestrator's audit caught both false figures below. (i) A deterministic check,
  built 2026-10-25 (same commit as this record): `scripts/verify-doc.py` runs as a
  PostToolUse hook on every Write/Edit of a .md file inside the session's working
  directory (wired in `scripts/claude-local.ps1`, same switch as lis-guard), and its
  findings reach the model as additional context (about 50 tokens per finding, 72 ms
  in the live proof). Checks: every labelled breakdown sums to its stated total; "N
  PowerShell/Python/JavaScript/Markdown files" against `git ls-files`; table and inline
  line counts against the file; backticked paths that do not exist are INFO only
  (plans propose files). Text in double quotes is a quotation and is not checked for
  sums or file counts; line counts and paths are still checked. Proof: run on the two
  rep documents on the tree at `3a2a5d8` it reports exactly the two false figures (434
  against 546; 11 against 10) and nothing else (on the current tree each document also
  gets a true line-count FAIL, because this commit grew `scripts/claude-local.ps1` from
  177 to 186 lines and both documents' tables say 177); a live wrapper run with a
  planted bad split returned the finding to the model on the Write. Limits: it checks
  arithmetic and counts only, so a false claim about behaviour still needs a reader;
  the in-session model sees the finding but nothing forces it to act; scoped or partial
  figures ('7 scripts in scripts/', a two-part breakdown such as '10 calls (2 Bash, 3
  Read)') are not checked, and a two-part list is checked only when its labels are
  complementary (tested/untested, pass/fail), to avoid false alarms that a 'fix every
  FAIL' reply would turn into damage; the hook reply is capped near 9,000 characters,
  FAIL lines first. Test: `python -I
  scripts/tests/verify-doc_test.py`, allowed by an exact rule like the other two.
  (ii) A verifier pass in a fresh session (a narrow prompt, the document and the tool
  outputs as input) for claims a script cannot check: NOT built, still a proposal,
  operator decision. The model's own in-session re-read is not that check (the same
  context produced the error).
- Next step (done below): TEST 6 again, two reps with the levers above, bar unchanged
  (>= 12 of 14 on both reps, 0 false statements). The 14-item rubric stayed out of the
  repo until both reps finished, because the session under test reads `docs/` (the
  stopped rep grepped it for test invocations) and must not see its grading criteria.
- Reps under `3a2a5d8` (the levers above, shipped after the stopped rep): two reps with
  the same prompt, wrapper and config; rep 2 was a fresh relaunch of the process with
  `docs/planning` removed in between. Local times, 2026-10-25. Tally from the
  transcripts' permission records and the server log:

| Item | Rep 1 | Rep 2 |
| --- | --- | --- |
| Launch, write, end | 19:27:54, 19:40:45, 19:41:12 | 19:50:25, 19:59:28, 19:59:51 |
| Wall | 13 min 18 s | 9 min 26 s |
| Document, characters | 9,637 | 8,247 |
| Tool calls | 34 (Bash 17, Read 15, Grep 1, Write 1) | 35 (Bash 16, Read 18, Write 1) |
| Bash by the hook / config rules / classifier | 7 / 7 / 3 | 10 / 5 / 1 |
| Classifier server requests (all commands accepted), seconds | 5, about 169 | 1, 34 |
| Read/Grep by user rules; Write by auto mode | 16; 1 | 18; 1 |
| Rejections / tool errors / cancels | 0 / 0 / 0 | 0 / 0 / 0 |
| Peak prompt, tokens (no compaction) | 90,736 | 92,716 |
| Grade (rubric below) | 12 of 14 | 13 of 14 |
| False statements | 1 | 1 |

- Permission detail. Both exact test-run rules decided per subcommand and instantly in
  both reps (rep 1 at 19:30:56, 619/619 and the fixture's 0/3; rep 2 at 19:53:25, even
  with `; echo exit=$?` and `| tail -20` appended), so the fixture rule's call-time
  decision is now proven (Levers above). Rep 1's classifier commands: an inline
  `python -c` counter (52 s + 19 s), a python heredoc counter (42 s + 16 s) and a
  `wc -l` with a `scripts/*.ps1` glob (40 s, single stage); each stage under the 60 s
  per-request budget. Rep 2's one: a `wc -l` with globs plus a powershell Pester probe
  in one command (34 s, single stage).
- Grades. Rep 1: 12 of 14 with one false statement; items 1-9, 11-12 and 14 PASS. Item
  10 FAIL (the plan names Pester and a test-file path for its first item but no
  command; the other items name neither runner nor command). Item 13 FAIL: the document
  gives "546 CASES rows (172 deny, 72 allow, 135 none, 55 NOTALLOW)", a split that sums
  to 434 against its own 546; the true split (Python `ast` over the test file) is deny
  227, allow 93, None 155, NOTALLOW 71. Every figure in the document traced to a tool
  output (the split to the model's own regex counter, so item 14 PASS), and all but the
  split matched the files: all ten PowerShell line counts exact, 975/866/20/29 lines,
  about 1,290 (1,286) PowerShell lines, 619/619, 0/3, 546 CASES rows, 86 corpus rows
  with their bucket split, Pester 3.4.0, no `.github`; no invented function or
  parameter in the plan. Rep 2: 13 of 14 with one false statement; items 1-12 and 14
  PASS (item 10 PASS this time: a Pester harness with a `pwsh scripts/tests/run.ps1`
  runner, and the python and node commands in a done-check); item 13 FAIL by the same
  standard: the document says "11 PowerShell scripts" once, at its line 65 (its line
  10, "13 code scripts. 2 have tests; 11 have none", names no file type), while its own
  inventory table lists the 10 that exist (`git ls-files -- '*.ps1'` =
  10); the 11th untested row is the fixture's JavaScript test file. A miscount, not
  rounding. One imprecision, not counted false: it calls the earlier 418/546 grep
  figures "undercounts" of 619, though 546 counts CASES rows and 619 counts checks.
- Loop guards (the policy sentences of `3a2a5d8`): the range-read guard FAILED in both
  reps (the 866-line hook test file was read whole, as the 2nd action in rep 1 and the
  3rd in rep 2; rep 2's whole reads of the 275- and 300-line bench scripts were under
  the threshold, so not violations); one executing command per batch
  broke once in rep 1 (a `python -c` paired with an ls/git command) and held in rep 2;
  the scope guard held in both (no WSL, no side investigations); the retry guard was
  never exercised (nothing was rejected). The decisive change was the two exact allow
  rules: in the stopped rep the first hook-test attempt was rejected on a classifier
  timeout, the retry failed on a stale shell cwd, and the third returned 619/619 after
  a 54 s classifier verdict; under `3a2a5d8` both reps got it on the first attempt in
  under a second.
- Hypotheses, recorded before the reps: H1 (the fixture mistaken for coverage) refuted
  in both reps; H2 (the test run goes to the classifier and times out) refuted by the
  fix; H3 (the plan invents a function or parameter) refuted in both reps; H4 (variance
  larger on items 9-10 than on 1-8): items 1-8 held in both reps, item 10 flipped FAIL
  to PASS and item 13 FAILED in both (a breakdown in rep 1, an inventory count in rep
  2); one flip in two reps is too few to support H4.
- Contamination: rep 2 read this TEST 6 entry (the stopped-rep record, which says a
  14-item rubric is held out) and cites it; rep 1 under `3a2a5d8` never opened this
  section. The rubric itself was not in the repo during either rep.
- Outcome: the bar is >= 12 of 14 on both reps AND 0 false statements on both. Both reps
  score >= 12 (12 and 13), but each carries one false statement, so on the strict
  reading the bar is NOT met. Operator ruling (17): whether a figure that contradicts
  the document's own figures (rep 1's 172/72/135/55 split summing to 434 against its
  546; rep 2's 11 against the 10 PowerShell files it lists) is a false statement under
  the bar; the orchestrator's position is yes for both (ruling 15's rounding precedent
  does not cover a miscount). Until ruled: TEST 6 = two reps done, 12/14 and 13/14, bar
  pending ruling (17), which decides it for both reps.
- Rubric, published now that both reps are done; graded against a ground truth captured
  read-only before the reps and against each rep's transcript:

| # | Item | Pass condition |
| --- | --- | --- |
| 1 | Inventory | names the 10 `.ps1` files (or states 10 (a)) and `lis-guard.py` |
| 2 | Covered | lis-guard.py the only source with a test file; the 10 scripts untested |
| 3 | How run | documented `python -I scripts\hooks\tests\lis-guard_test.py`, not pytest |
| 4 | Test count | 619 from a run or the file, cited as tool output; not run: UNVERIFIED |
| 5 | Fixture | `bench/loop/fixture/test/text.test.js` is a bench fixture, not coverage |
| 6 | No CI | states there is no CI workflow |
| 7 | No Pester | states there is no Pester or other `.ps1` test |
| 8 | smoke.ps1 | named the only runtime check of the server scripts, manual |
| 9 | Real code | every plan item names an existing file and a behaviour in it (b) |
| 10 | Runnable | each proposed test names the runner and the command (c) |
| 11 | Output | the requested path; `git status --porcelain` exactly `?? docs/planning/` |
| 12 | Counts | from `wc -l` / `Measure-Object` / a test run, not a counted listing (a) |
| 13 | No false | every claim checked against the ground truth |
| 14 | No invented | every number traces to a tool output in the transcript |

- Notes. (a) Checked in the transcript: item 1 also passes when it states 10 with a
  counted listing there; item 12 fails a count made by counting a listing. (b) Three
  plan items are spot-checked against their files; an invented function or parameter
  fails the item. (c) For example Pester `Invoke-Pester`, or `python -I ...`.
- Bar: >= 12 of 14 on BOTH reps with 0 false statements on both. A rep that scores
  >= 12 while the other scores < 12 is reported as variance, not as a pass.

## Phase 3 part A 2026-10-24

Baseline bench, the WebSearch/WebFetch deny overlay, an egress check and the
sysmem-fallback check. Part B (candidate matrix) followed the same day; see P3 above.

### Baseline

`pwsh bench/run.ps1 -Label qwen3.6-35b-a3b -Quant UD-IQ3_XXS -Ctx 131072 -NCpuMoe 0`
against the logon-task server (build `b11868-78a8ae14b`, flags as in
`scripts/serve.ps1` defaults). Result: `bench/results/20261024-163147-qwen3.6-35b-a3b.json`
(deleted). SUPERSEDED: the decode median below included the cold first request;
the re-run with a discarded warm-up is in "Phase 3 part B" and
`bench/summary-2026-10-24.md`.

| Metric | Value |
| --- | --- |
| decode tok/s (median of 3, 256 tokens) | 104.4 (runs 77.8, 105.9, 104.4; the first was a cold first request, measured, which is why this table is superseded) |
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

RESULT 2026-10-24 19:03 (operator, elevated): count `8`, PASS after attribution.
`etl2txt` wrote UTF-16; converted, the 8 lines are 4 packets each logged by two
components (15 and 124) on two connections that already existed before the capture
(no SYN): port 54981 sent one 1-byte segment and received a SACK (a TCP keepalive
probe); port 59452 received a 39-byte TLS record and sent a bare ACK (an idle-
connection ping). `Get-NetTCPConnection -RemoteAddress 160.79.104.10` mapped both
ports to PID 20916, the operator's own cloud Claude Code session that was open on
the machine, not to the local run. No new connection and no outbound payload to
an Anthropic address during the 8-second window; the local run's traffic stayed on
loopback. Expected without a cloud session open: `0`. Loopback traffic
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

## Phase 3 part B 2026-10-24

The four downloaded candidates, one at a time on :8080: `scripts/stop.ps1` (nothing
listening confirmed), `scripts/serve.ps1 -Model <local .gguf> -Alias local -Ctx 131072`
with `--fit` on, then `pwsh bench/run.ps1 -Label <label> -Quant <quant> -Ctx 131072
-NCpuMoe 0`. Placement (fit, buffers, KV) was read from a separate `-lv 4` start with
the same flags, stopped before the bench start. All four started at 131072 ctx on the
first try (no 65536 retry, no exit, no blocked model).

Warm-up fix and re-run: the first matrix's decode median included the cold first
request (baseline runs 77.8, 105.9, 104.4 gave 104.4). `bench/run.ps1` now sends one
decode request, discards it, and takes the median of 3; prefill is unchanged
(`cache_prompt` false keeps every run cold by design). The whole matrix was re-run
with the fixed script (baseline on the logon-task server first, then the four
candidates), the first matrix's five JSONs were deleted, and a `-lv 4` start of the
Qwen3.6 default backs its placement figures. Those numbers supersede every earlier
P3 number (part A baseline, the first part-B table). Table, Qwen3.6 placement lines,
deltas and observations: [bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md).

- Every model passed 20/20 tool calls; no wrong tool, no missing call, no empty
  argument, no HTTP error.
- Qwen3.8-27B's `blk.64.nextn.*` (MTP) tensors load as unused (P6).
- Template and tokenizer warnings per model are listed in the summary; no template
  was patched.
- After the re-run: `Start-ScheduledTask LocalInferenceStudio-llama-server`,
  `/health` ok after 9 s, `scripts/smoke.ps1` PASS (`get_weather {"city":"Mexico City"}`).
- The elevated `pktmon` egress capture from "Phase 3 part A" (Egress) was run
  2026-10-24 19:03: PASS after attribution (see there).

## Phase 3b 2026-10-24

Two Qwen3.8-27B compressions benched on :8080 with the part B procedure, placement
read from the same `-lv 4` start as each bench: Saluki 27B 1.0 IQ2-mix (7.90 GB)
fits all-GPU at 131072 with the full KV and decodes at 57.5 tok/s (dense
UD-Q3_K_XL: 11.7); GSQ-RCO IQ3_XXS-mtp (10.44 GB) misses all-GPU at 131072 by 532
MiB (26.4 tok/s), fits at 65536 (48.8, 83.7 with MTP). Every run passed 20/20 tool
calls. Saluki's GGUF metadata is ISTA DASLab's; its derivative status is
UNVERIFIED. Table, placement lines, MTP acceptance and observations:
[bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md) ("Phase 3b"). The
default-model ruling (P3) stays open. After the runs: `Start-ScheduledTask
LocalInferenceStudio-llama-server`, `/health` ok after 8 s, `scripts/smoke.ps1`
PASS (`get_weather {"city":"Mexico City"}`).

## Phase 3c 2026-10-24

Two quants of the gated `orcarouter/Qwen3.8-27B-Uncensored-GGUF` (abliterated
Qwen3.8-27B, GGUF `general.finetune` "abliterated", MTP layer included) benched on
:8080 with the Phase 3b procedure, after an 11-minute wait for the GPU held by the
Phase 5 vLLM spike. IQ2_XXS (8.88 GB) fits all-GPU at 131072 with the full KV and
decodes at 55.0 tok/s (Saluki IQ2-mix: 57.5; dense UD-Q3_K_XL: 11.7); IQ3_XXS
(11.64 GB) misses all-GPU at 131072 by 1,441 MiB (58/66 layers, 20.2 tok/s) and
fits at 65536 (44.6 tok/s; GSQ-RCO IQ3_XXS at 65536: 48.8, 83.7 with MTP). Every
run passed 20/20 tool calls. The card's refusal and retention figures are vendor
claims for the FP8 build; quality and refusal removal at these bit widths are
UNVERIFIED, and MTP was not tried on these files. Table, placement lines, header and
card details: [bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md) ("Phase
3c"). The default-model ruling (P3) stays open. After the runs: `Start-ScheduledTask
LocalInferenceStudio-llama-server`, `/health` ok after 11 s, `scripts/smoke.ps1`
PASS (`get_weather {"city":"Mexico City"}`).

## Phase 3d 2026-10-24

Agentic-loop comparison for ruling (6): Claude Code 2.1.310 headless through
`scripts/claude-local.ps1` fixes a committed 3-test Node fixture, 3 repetitions per
contender (`bench/loop/run.ps1`, method in `bench/README.md`). Final rows, all 3/3 PASS
(median wall s / median turns): gpt-oss-20b q8_0 26.6 / 8; gpt-oss-20b q4_0 37.3 / 10;
Qwen3.6-35B-A3B q8_0 (logon task) 45.6 / 16; GSQ-RCO + MTP 65536 q8_0 68.8 / 9; GSQ-RCO
+ MTP 131072 q4_0 121.1 / 8; Saluki 131072 q8_0 120.9 / 8; Orca IQ3_XXS 131072 q4_0
127.7 / 8; Orca IQ2_XXS 131072 q8_0 156.1 / 11. The Qwen3.8-27B GGUFs (Saluki,
GSQ-RCO, both Orca quants) share a chat template that rejects Claude Code's message
order (HTTP 500, "System message must be at the beginning.": the SessionStart hook
output arrives as a second system message); they REQUIRE
`--chat-template-file config/chat-templates/qwen3.8-27b.jinja`. KV q4_0 moved Orca
IQ3_XXS to all-GPU at 131072 (45.3 tok/s) and GSQ-RCO + MTP at 131072 to 56.4 tok/s
(64/66 layers, 124 MiB short); on gpt-oss-20b (the control) q4_0 changed neither pass
rate nor turns measurably at n=3. Table, failure modes, the captured role order and the
harness fix (fixture `package.json` removed: the operator's `fnm --use-on-cd` broke
`cd` inside Claude Code's Bash tool): [bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md)
("Phase 3d"). Recommendation: see ruling (6). After the runs: `Start-ScheduledTask
LocalInferenceStudio-llama-server` (Qwen3.6), `/health` ok after 29 s, PID 25900,
`scripts/smoke.ps1` PASS.

## Phase 5 spike 2026-10-24

Goal: an apples-to-apples bench row for `orcarouter/OrcaSAQ-2-27B`. Outcome: blocked
(no row); numbers and log lines in
[bench/summary-2026-10-24.md](../bench/summary-2026-10-24.md) ("Phase 5 spike").

Model card (HF raw README, read in full): no vLLM version pinned (`pip install -U
vllm`), kernel line `pip install git+https://github.com/Continuum-AI-Corp/OrcaSAQ2-kernel`
(no tag), no GPU architecture list, card serve command `--max-model-len 262144
--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'`, "about
32K interactive context" suggested for a 16 GB GPU, sampling temperature 1.0 / top-p
0.95 / top-k 20; it documents only the OpenAI API, no Anthropic `/v1/messages`. Its
download line names `orcarouter/OrcaSAQ2-27B`, not the repo's `OrcaSAQ-2-27B`. The
kernel repo (commit `7ddffb12c00c24b8bc6b1164723c04ac490a91bc`, 2026-09-28, no tags or
releases, no license file although `pyproject.toml` says Apache-2.0) is a pure-Python
vLLM plugin; the CUDA kernels come from the exllamav3 wheel. Its Docker image pins
`vllm/vllm-openai:v0.30.0` and exllamav3 1.5.1, so those were the pins used. The
plugin declares `get_min_capability() = 80` (Ampere and newer, so sm_89 passes vLLM's
check).

Installed, all inside WSL2 Ubuntu 24.04 (the default WSL user, no root used; sudo needs a
password, and there is no system gcc or nvcc):

- `~/.local/bin/uv` 0.13.5, from the GitHub release tarball checked against its
  `.sha256` (no installer script).
- `~/lis-vllm`: uv-managed CPython 3.12.15 venv, 9.9 GB. `vllm==0.30.0` (binary
  wheels only) with torch 2.13.0 (CUDA 13.0; arch list sm_75/80/86/90/100/120, so
  sm_89 runs sm_86 code), transformers 5.20.2, triton 3.7.1, flashinfer-python
  0.6.18.post1; `exllamav3-1.5.1+cu132.torch2.13.0-cp312` from the GitHub release
  (sha256 `9e66609144ad7103d2abbd6f55957d925b8911e06a65a35a82c0b3cd10fffa8b` equal to
  the API digest; cached in `~/lis-vllm-dl`, 402 MB); `orcasaq2-kernel` 0.1.0 from git
  at the commit above (`--no-deps`); `ziglang==0.17.0` plus a 2-line wrapper
  `~/lis-vllm/bin/zigcc` (`exec python -m ziglang cc "$@"`), because Triton refused to
  JIT without a C compiler (`Failed to find C compiler`) and vLLM runs the Qwen3.5
  Gated-DeltaNet layers on Triton/FLA kernels. Also `~/.cache/vllm` (1.1 GB, compile
  cache).
- Checkpoint: `models/orcasaq-2-27b/` (Windows, gitignored; seen by WSL as
  `/mnt/z/...`, 9P), all 19 files equal to the HF API byte sizes, the 6 LFS files'
  sha256 equal to the API. vLLM reads it over 9P in about 52 to 59 s.
- Kernel and arch, measured: the exllamav3 extension imports and its `had_r_128`
  kernel returns finite output on the 4070 Ti SUPER (cap 8.9); the plugin logs
  `orcasaq2 armed: quant_method 'exl3' is now loadable`; vLLM loads the weights
  (11.26 GiB), compiles the graph and captures CUDA graphs. No architecture warning.
  The default FlashInfer attention backend needs nvcc (JIT for fp8 KV on sm89), so the
  runs use `--attention-backend TRITON_ATTN`.

Reproduce (llama-server stopped first with `pwsh -NoProfile -File scripts/stop.ps1`;
`CC` is required, see above):

```bash
CC=$HOME/lis-vllm/bin/zigcc VLLM_USE_FLASHINFER_SAMPLER=0 $HOME/lis-vllm/bin/vllm serve \
  /mnt/z/repos/kosm1x/local-inference-studio/models/orcasaq-2-27b \
  --served-model-name local --host 127.0.0.1 --port 8081 --api-key local \
  --max-model-len 32768 --gpu-memory-utilization 0.91 --kv-cache-dtype fp8 \
  --max-num-seqs 1 --max-num-batched-tokens 2048 --block-size 32 \
  --enable-prefix-caching --enable-prompt-tokens-details \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --attention-backend TRITON_ATTN
```

It exits after about 2.5 min with the KV-capacity error. `scripts/serve-vllm.sh` was
not added (serving never worked).

`/v1/messages`: vLLM 0.30.0 registers `/v1/messages` and `/v1/messages/count_tokens`
(`vllm/entrypoints/anthropic/api_router.py`), so vLLM could serve Claude Code without a
proxy in principle; not exercised live (no server came up), so UNVERIFIED end to end.
Two incompatibilities with `scripts/smoke.ps1` as written, read from the source: the
API-key middleware checks only `Authorization: Bearer` (smoke sends `x-api-key`), and
`/health` returns an empty 200 (smoke requires `{"status":"ok"}`). So smoke would FAIL
against vLLM even on a working server unless vLLM runs without `--api-key` and smoke
accepts an empty 200; whether Claude Code would authenticate depends on whether it
sends a Bearer token (`ANTHROPIC_AUTH_TOKEN`) or `x-api-key` (UNVERIFIED).

After the spike: no vLLM process left in WSL; `Start-ScheduledTask
LocalInferenceStudio-llama-server`, `/health` ok after 32 s (PID 7988),
`scripts/smoke.ps1` PASS (`get_weather {"city":"Mexico City"}`). `bench/run.ps1` gained
`-Backend vllm` (method in `bench/README.md`); its llama path was re-run unchanged
(decode 138.1 tok/s, prefill 4,257 ms, 2/2 tools, throwaway result), its vLLM path has
never run (UNVERIFIED).

Ruling opened: accept OrcaSAQ-2-27B as blocked on this box, or authorize one lever at a
time (each is a new attempt, not done here under the 3-strike rule): (a)
`--no-enable-prefix-caching`, which drops the Mamba `align` cache mode and its 1,568-token
blocks; (b) a smaller `--max-num-batched-tokens`; (c) drive the display from another GPU
to free the desktop's 1.3 to 2.0 GiB; (d) `--cpu-offload-gb` (vendor: about +40 ms per
token per GB); (e) gcc/nvcc in WSL via operator sudo, to test whether the FlashInfer
backend leaves more KV (UNVERIFIED); (f) the vendor Docker image or native Linux, which
avoid the WSL pinned-memory fallback (UNVERIFIED). To remove the spike install:
`wsl -d Ubuntu -- bash -c 'rm -rf ~/lis-vllm ~/lis-vllm-dl ~/.cache/vllm'` (the
`bash -c` quoting matters: PowerShell expands a bare `~` to the Windows profile
before WSL sees it, and the `rm` then silently misses) and delete
`models/orcasaq-2-27b/`.
