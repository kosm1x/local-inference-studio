# Evaluation of two reference repos (2026-10-24)

The operator asked whether either repo should be part of this project.
Short answer: neither serves the Anthropic API or knows Claude Code; neither
is adopted as a dependency. Both are kept as references.

## 1. sudoingX/local-ai-on-your-gaming-gpu

https://github.com/sudoingX/local-ai-on-your-gaming-gpu

**Verdict: REFERENCE ONLY.**

- Created 2026-09-19, last commit 2026-10-17, 167 stars.
- Contents: one-line installers (`irm | iex` / `curl | bash`), serve scripts,
  CUDA kernel patches, and GGUF "graft" tools for ONE model: Ternary Bonsai 2
  27B (ternary quant of Qwen 3.8 27B, PTQ1_0, 1.75 bpw, 5.95 GB) with a
  grafted MTP draft head.
- Runs on PrismML's llama.cpp fork; stock llama.cpp cannot load the file.
- API: OpenAI `/v1/chat/completions` only, on 127.0.0.1:8899. No Anthropic
  endpoint, no mention of Claude Code.
- No quality evals: speed and greedy-identity checks only. 1.75 bpw is a large
  quality give-up against the "most potent" goal.

Reusable findings:

- Flag set: `-fa on -np 1 -ctk q4_0 -ctv q4_0 --jinja --spec-type draft-mtp --spec-draft-n-max 1`.
- `GGML_CUDA_BATCH_INVARIANT=1`.
- `--fit on --fit-target 1024 --fit-ctx 16384`.
- `kernel/reasoning_effort.md`: default reasoning effort `xhigh` burned the
  whole 4096-token cap on thinking in 6/6 runs. Use `--reasoning-effort medium`
  and `max_tokens >= 8192`.
- `sweeps/rtx5070ti-16gb.md`: 84.7 tok/s with the MTP head vs 78.1 without;
  `-c 262144` ran 13-20% slower and spilled into shared memory, so pin
  `-c 131072`; spec n-max 2 helped code (111.9 vs 91.8 tok/s).
- README tips: set the NVIDIA control panel option "Prefer No Sysmem
  Fallback"; on WSL2 install no Linux driver and keep models under `~/`.

Risks: fork drift (depends on unmerged PR #218); the uncensored variant and the
pipe-to-shell installer do not suit this project.

## 2. AlexsJones/llmfit

https://github.com/AlexsJones/llmfit

**Verdict: REFERENCE ONLY** (usable as a fit sanity-check tool, not infrastructure).

- Rust, ~39k LOC core plus TUI / web / REST / MCP / Python wheel. v1.1.17
  (2026-10-08), last commit 2026-10-24, 38k stars. Signed Windows binaries via
  winget/Scoop; also on crates.io and PyPI. GPU detection via `nvidia-smi` with
  WMI/registry fallback.
- Scores catalog models on fit / speed / quality / context and recommends a
  quant. Can download GGUFs and benchmark an already-running server. Does NOT
  launch a runtime.
- Memory formula: params × bytes/param + per-layer KV cache (MLA and hybrid
  linear-attention special cases) + 0.5 GB. Speed = bandwidth ÷ size × 0.55;
  MoE speed from active params.
- Partial offload: layer split only, for the speed estimate. MoE has an
  "active experts in VRAM" mode but no model of llama.cpp `--n-cpu-moe` / `-ot`.
- Main ranking assumes fp16 KV (pessimistic for long context on 16 GB);
  `plan` prints `--cache-type-k/v` alternatives.
- Quants: GGUF K, Unsloth UD, MXFP4, AWQ, GPTQ, AutoRound, MLX. README claims
  EXL2 but the source lacks it. No IQ quants.
- Coupling to Ollama / LM Studio is soft (optional providers); bare llama.cpp
  is first-class; vLLM appears as a sizing/bench target; SGLang, TabbyAPI and
  ik_llama are absent.
- No mention of Claude Code or the Anthropic API. The "tool-calling" quality
  role is regex-scored toy JSON.
- Catalog is fresh (17,700 HF entries, newest 2026-10-12) but noisy.
- The formulas are simple enough to re-implement in a few dozen lines if ever
  needed.

## 3. huggingface.co/orcarouter (asked 2026-10-24)

**Verdict: NOT A PROVIDER FOR THIS STACK.** OrcaRouter is a quantizer and
fine-tuner (gateway company OrcaRouter.ai, GitHub org Continuum-AI-Corp);
its hosted gateway is cloud inference and outside the aim. One repo is
tracked as a Phase 5 candidate, one as a fallback.

- HF org: 32 repos, 9 members, 3,487 followers, not verified. Most repos
  are gated (HF login + accepted terms needed to read cards or download).
- Three lines: (a) "Uncensored" abliterated re-releases of current open
  models (Qwen3.8-27B, Qwen3.8-Flash-Next, GLM-5.3-Flash, Gemma 4 26B-A4B,
  DeepSeek V4 / V4.1 Flash, Nex-N2.5-mini) in GGUF / FP8 / NVFP4 / MLX /
  INT8; (b) OrcaSAQ2, a proprietary sensitivity-aware mixed-precision 3-bit
  quant; (c) cyber-offense models (OrcaCyber-Nano, OrcaSAQ-2-Cyber), out of
  scope.

| Repo | Size | llama-server native? | Verdict |
|---|---|---|---|
| OrcaSAQ-2-27B (Qwen3.8-27B, 3.21 bpw avg) | 12.3 GB safetensors | No: vLLM + `Continuum-AI-Corp/OrcaSAQ2-kernel` | Phase 5 candidate (WSL2 vLLM) |
| Qwen3.8-27B-Uncensored-GGUF | IQ3_XXS 11.6 / IQ3_M 12.8 / IQ4_XS 15.3 GB | Yes, standard quants | Fallback only, if stock Qwen3.8-27B refuses coding tasks |
| GLM-5.3-Flash-Uncensored-GGUF | Q2_K 117 GB | Too big even with `--n-cpu-moe` | Skip |
| DeepSeek-V4.1-Flash-1017-abliterated-GGUF | Mix-128G 225 GB | Too big | Skip |
| Qwen3.8-Flash-Next-Uncensored-* (125B-A6B) | >= 75 GB at 1-bit | Too big | Skip |
| Gemma-4-26B-A4B-it-Uncensored-FP8 / *-NVFP4 | FP8 / NVFP4 safetensors | Ada has no FP8 units; vLLM falls back to slow kernels | Skip |

**OrcaSAQ-2-27B, the one interesting item.** Card claims (measured by the
vendor against BF16 on WikiText-2, 16,376 tokens): 54 GB -> 12.3 GB,
PPL 5.6468 -> 5.6482 (+0.02%), 93.2% top-1 agreement, 0.031 mean KLD, 262K
context, thinking, tool calling, MTP speculative decoding. The base model
is the one whose SWE-Pro 61.7 was measured with the Claude Code harness.
Caveats: these are fidelity metrics, not agentic benchmarks; serving needs
vLLM (WSL2 or Docker) plus a proprietary kernel installed from GitHub;
Ada (sm_89) support UNVERIFIED; the 90.1 tok/s MTP figure names no GPU.

**Why the Uncensored line is not a default.** Uncensoring is not a goal
here; abliteration usually costs capability; the cards are gated so method
and evals could not be read; tool-call reliability varies sharply by
uploader and these are re-quants of an abliterated finetune, an extra
unknown over the Unsloth / Bartowski stock quants.

## Conclusion

Neither GitHub repo serves the Anthropic API or knows Claude Code; neither is adopted
as a dependency. Harvested: the flag set and 16 GB tuning numbers from (1); the
fit sanity-check and the KV/offload caveats from (2). From (3), OrcaSAQ-2-27B
enters the candidate list for Phase 5 only and Qwen3.8-27B-Uncensored as a
fallback; nothing else.
