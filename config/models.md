# Model candidates

Tracked list from `docs/landscape-2026-10-24.md`. HF repo names other than the
default are UNVERIFIED until P3 downloads them. "Fits all-GPU" means weights fit
in 16 GB VRAM; KV cache at the target context is not yet measured.

| Model | HF repo | Quant | Size | Fits all-GPU? | Ctx target | Status |
|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B | unsloth/Qwen3.6-35B-A3B-GGUF | UD-IQ3_XXS | 13.2 GB | yes | 131072 | candidate |
| Qwen3.6-35B-A3B | unsloth/Qwen3.6-35B-A3B-GGUF | UD-IQ4_XS | 17.7 GB | no (partial offload) | 131072 | candidate |
| Qwen3.8-27B dense | UNVERIFIED | 3-bit | 12-14 GB | yes (KV tight) | 131072 | candidate |
| Gemma 4 26B-A4B | UNVERIFIED | IQ4_XS | 13.4 GB | yes | 131072 | candidate |
| GLM-4.7-Flash | UNVERIFIED | IQ4_XS | 16.3 GB | no | 131072 | candidate |
| Qwen3-Coder-Next 80B-A3B | UNVERIFIED | UD-IQ4_XS | 38.4 GB | no (`--n-cpu-moe`) | 131072 | candidate |
| Nemotron Super 120B | UNVERIFIED | IQ3_XXS | 56 GB | no (`--n-cpu-moe`) | 131072 (fit UNVERIFIED) | candidate |
| gpt-oss-20b | UNVERIFIED | native (~13 GB) | ~13 GB | yes | 131072 | candidate |
| Qwen3.8-27B OrcaSAQ2 (3.21 bpw, vLLM + vendor kernel) | orcarouter/OrcaSAQ-2-27B | OrcaSAQ2 safetensors | 12.3 GB | yes (WSL2 vLLM only) | 131072 | phase-5-only |
| Qwen3.8-27B-Uncensored (abliterated) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) | IQ3_M | 12.8 GB | yes (KV tight) | 131072 | fallback |
