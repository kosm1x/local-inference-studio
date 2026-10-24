# Landscape (2026-10-24)

Items marked UNVERIFIED were not confirmed against a primary source or on
this machine.

## Claude Code wiring

Sources: code.claude.com/docs/en/env-vars, /llm-gateway-protocol,
/cli-reference (fetched 2026-10-24).

- `ANTHROPIC_BASE_URL=http://127.0.0.1:8080` (no `/v1`; Claude Code appends
  `/v1/messages`).
- `ANTHROPIC_AUTH_TOKEN=<any non-empty>` is sent as Bearer. Effectively
  required: without it the claude.ai login stays active.
  `ANTHROPIC_API_KEY` goes as `x-api-key` and overrides the subscription login.
- `ANTHROPIC_MODEL` plus `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` /
  `_HAIKU_MODEL` (Haiku is also used for background tasks): point ALL tiers at
  the local alias. `ANTHROPIC_SMALL_FAST_MODEL` is deprecated.
- Context trap: for an unknown model id Claude Code assumes 200K. Set
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS=<-c value>`.
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` accepts only 100K-1M, so windows under
  100K are UNVERIFIED; plan `-c >= 100K`.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS` (a higher value shrinks effective context).
  `API_TIMEOUT_MS` defaults to 600000; raise it for slow prefill.
- Set: `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`,
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_PROMPT_CACHING=1`
  (optional), `ENABLE_TOOL_SEARCH=false`, `CLAUDE_CODE_ATTRIBUTION_HEADER=0`
  (Anthropic says stable since v2.1.181; Unsloth and SGLang still recommend 0,
  and Unsloth claims ~90% slowdowns without it).
- Breaks locally:
  - `count_tokens` absent: character-estimate fallback.
  - `cache_control` ignored.
  - Adaptive thinking, `output_config.effort` and a mid-conversation
    `role: system` may be rejected (Claude Code retries without them).
  - The 1M beta is a no-op.
  - Fast mode and the WebFetch domain safety check call api.anthropic.com
    directly.
  - WebSearch is server-side and will not work (UNVERIFIED).
- `--bare` skips hooks / skills / MCP / CLAUDE.md;
  `--exclude-dynamic-system-prompt-sections` improves cache reuse. System
  prompt size ~15-25K tokens (UNVERIFIED).

## Backends with native /v1/messages

- **llama.cpp `llama-server`: YES.** Latest release b11868 (2026-10-24), with
  Windows x64 zips for CUDA 12.4 and 13.4
  (github.com/ggml-org/llama.cpp/releases). Flags:
  - `--jinja` is now the default; `--reasoning-format auto`, `--reasoning-budget`.
  - `-ngl auto`, `-c`, `-fa on`, `-ctk/-ctv q8_0`.
  - `--cache-reuse N`, `-np 1`, `-kvu`.
  - `--n-cpu-moe N`, `--cpu-moe`, `-ot`.
  - `--fit on` is the default.
  - Speculative: `-md`, `--spec-type`, `--spec-draft-n-max` (`--draft-max`
    removed). Qwen MTP: `--spec-type draft-mtp --spec-draft-n-max 2`.
- **SGLang: YES** (on by default, `--tool-call-parser`, count_tokens;
  docs.sglang.io/docs/basic_usage/anthropic_api). Linux only, so WSL2/Docker.
- **vLLM: YES** (AnthropicServingMessages, v0.11.1-v0.24.0; the route docs
  fetch returned HTTP 429). Linux only, so WSL2/Docker; Windows native
  UNVERIFIED.
- TabbyAPI / exllamav3: OpenAI and KoboldAI APIs only.
- KoboldCpp, ik_llama.cpp: no Anthropic endpoint found (UNVERIFIED).
- Proxies (not needed now): LiteLLM `/v1/messages` passthrough + translation;
  claude-code-router (@musistudio).

Ranking: (1) llama-server native on Windows; (2) SGLang in WSL2/Docker;
(3) vLLM in WSL2/Docker, only worth it for full-GPU safetensors + MTP, and
16 GB rules out most; proxies last.

## Model candidates

Speeds are from an RTX 4080 16 GB llama.cpp bench at 19K / 64K context
(glukhov.org, 2026). The 4070 Ti SUPER has ~6% less memory bandwidth.

| Model | Quant / size | tok/s 19K / 64K | Notes |
|---|---|---|---|
| Qwen3.6-35B-A3B (2026-04-16, Apache-2.0, 262K ctx, hybrid DeltaNet) | UD-IQ3_XXS 13.2 GB, all-GPU | 147 / 146 | SWE-bench Verified 73.4, Pro 49.5, TB2 51.5 (HF card); community: "gets lost" on long multi-step runs |
| Qwen3.6-35B-A3B | UD-IQ4_XS 17.7 GB, partial offload | 95 / 86 | |
| Qwen3.8-27B dense (2026-08-14, Apache-2.0) | 3-bit 12-14 GB | not benched; dense ~27B IQ3 on 16 GB ≈ 30 tok/s, collapses when KV spills (Gemma 4 31B: 29 to 8) | SWE-Pro 61.7 measured WITH the Claude Code harness (HF card); one report of tool-call/JSON failures under Ollama |
| Gemma 4 26B-A4B | IQ4_XS 13.4 GB | 122 / 96 | |
| GLM-4.7-Flash | IQ4_XS 16.3 GB | 92 / 73 | |
| Qwen3-Coder-Next 80B-A3B (MoE CPU offload) | UD-IQ4_XS 38.4 GB | 41 / 38 | uses the 64 GB RAM |
| Nemotron Super 120B (MoE offload) | IQ3_XXS 56 GB | 17.5 | |
| gpt-oss-20b | ~13 GB | 178-190 on a 5080 (Ollama test, not llama.cpp) | older |

- gpt-oss-120b ≈ 15 tok/s on a 3090 + 64 GB with `--n-cpu-moe 24`; no 16 GB
  figure (UNVERIFIED).
- Too big: Qwen3.8-Flash-Next 125B-A6B (>= 75 GB at 1-bit), Kimi, MiniMax,
  DeepSeek-V4, Muse Spark.
- Devstral Small 2: not verified.

## Gotchas

- **Tool calls:** the Qwen card names parser `qwen3_coder`; keep `--jinja`.
  Quant quality varies by uploader (one test: Unsloth IQ3_XXS Qwen3.5-27B 5%
  vs Bartowski 100% tool-call success). The llama.cpp function-calling doc
  lags newer model families (UNVERIFIED).
- **Thinking:** Qwen3.6/3.8 think by default. Control via
  `--chat-template-kwargs` with `enable_thinking` / `preserve_thinking` /
  `reasoning_effort` (PowerShell needs `\"` escaping). Sampling: temp 0.6-1.0,
  top_p 0.95, top_k 20.
- **CUDA:** avoid CUDA 13.2 (Unsloth: gibberish). CUDA 13.4 needs driver
  R615+, so 617 is OK; 12.4 builds also work. `-fa on` is fine on Ada.
- **Context / cache:** hybrid Qwen KV is small; 128K with `-ctk/-ctv q8_0`
  should fit next to the 13.2 GB quant (estimate, UNVERIFIED). Use `-np 1` so
  the prefix cache is reused.

## Suggested start

```
llama-server -hf unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS -c 131072 -fa on -ctk q8_0 -ctv q8_0 -np 1 --alias local --temp 0.6 --top-p 0.95 --top-k 20
```

Then the Claude Code env block with every model tier = `local` and
`CLAUDE_CODE_MAX_CONTEXT_TOKENS=131072` (see `scripts/claude-local.ps1`).
