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

## P1 — Install + smoke

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
  2. Verify that `ANTHROPIC_MODEL` / `config/claude-settings.json` override
     `model: fable` from `~/.claude/settings.json`, and that subagents do not
     request Opus (the user settings pin `CLAUDE_CODE_SUBAGENT_MODEL=opus` with
     `_FORCE=1`). Check the llama-server log for the model names requested.
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
- Steps: `-ExtraArgs '--spec-type','draft-mtp','--spec-draft-n-max','2'`;
  compare against P3 numbers.
- Done-check: bench JSON with and without MTP on the same model.
- Open rulings: none until the GGUFs exist upstream.
