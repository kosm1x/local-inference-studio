# Roadmap

Each phase lists its goal, steps, done-check and open rulings. A phase is done
only when its done-check passes on this machine.

## Status 2026-10-24 (end of day)

- Default server (ruling 6): Orca Qwen3.8-27B-Uncensored IQ3_XXS, ctx 131072, KV
  q4_0, patched chat template; logon task Running (PID 27540, restarted 22:37 after
  Phase 3e), smoke PASS, one-turn
  Claude Code call PASS. Tip `ef5e65c`.
- P0-P3 DONE; Phase 3d loop comparison DONE (8 rows, all 3/3); P5 spike BLOCKED
  (KV capacity); P4 not started; P6 measured (GSQ-RCO, Phase 3b; the default's file,
  Phase 3e).
- The revised `serve.ps1` (`ef5e65c`) run by the task: proven 22:37 by the
  `Start-ScheduledTask` after Phase 3e (default command line in `logs/llama-server.log`,
  `/health` ok after 4 s, smoke PASS). UNPROVEN until it happens: the logon start itself
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
- Open rulings: adopt Orca + MTP at 65536 (q4_0 KV, `claude-local.ps1
  -LisContextTokens 65536`) as the default (Phase 3e; recommended on the numbers,
  `serve.ps1` defaults unchanged); (9) Bonsai revisit (a dense 27B now IS the default
  and VRAM headroom is 1,630 MiB, so the deferral condition is met); P4 go/no-go; whether a harder,
  multi-file loop fixture should settle the accuracy question that the 3-test
  fixture could not (every contender passed it).

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
  131072 with q4_0 KV and the patched chat template; the logon task serves it.
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
- Open rulings: for the default, whether to serve 65536 + MTP (81.6 tok/s) instead of
  131072 without (45.3 tok/s) (operator; Phase 3e recommends it on the numbers); for
  other models the same context-for-MTP trade stays open.

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
  separate MTP decision. The ruled default runs without MTP (see P6).
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
