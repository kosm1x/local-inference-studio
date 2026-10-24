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

## P2 — Claude Code profile + first agentic task

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
  value; whether `--bare` is the default local profile.

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
- Steps: `-ExtraArgs '--spec-type draft-mtp --spec-draft-n-max 2'`;
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
