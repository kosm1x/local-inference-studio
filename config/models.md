# Model candidates

Tracked list from `docs/landscape-2026-10-24.md`. Repo + filename + size were
verified against the HF API (`/api/models/<repo>?blobs=true`; all ungated except
orcarouter/Qwen3.8-27B-Uncensored-GGUF, read with a token) on
2026-10-24 for the rows with a Local file; downloaded byte counts match
the API exactly. Repo names still marked UNVERIFIED have not been checked.
"Fits all-GPU" is measured for the benched rows (P3 part B, Phase 3b and Phase 3c, 2026-10-24): whether
`--fit` kept every tensor on GPU at the target context with the `serve.ps1`
defaults (q8_0 KV). "Decode tok/s" (median of 3 after one discarded warm-up) and
"Prefill 20K ms" (cold, median of 3) are the P3 bench numbers; the full table is
`bench/summary-2026-10-24.md`. Unbenched rows are the weights-only estimate.
"lastModified" is the repo's, not the file's.

| Model | HF repo | Quant | Size | Fits all-GPU? | Decode tok/s | Prefill 20K ms | Ctx target | Status | Local file |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B | unsloth/Qwen3.6-35B-A3B-GGUF | UD-IQ3_XXS | 13.2 GB | no, measured: `--fit` keeps 41/41 layers on GPU but moves part of 2 layers' experts to CPU (~535 MiB) at 131072 ctx with `--no-mmproj` and q8_0 KV | 134.0 | 5,351 | 131072 | benched (default) | - |
| Qwen3.6-35B-A3B | unsloth/Qwen3.6-35B-A3B-GGUF | UD-IQ4_XS | 17.7 GB | no (partial offload) | - | - | 131072 | candidate | - |
| Qwen3.8-27B dense | unsloth/Qwen3.8-27B-GGUF `Qwen3.8-27B-UD-Q3_K_XL.gguf` (lastModified 2026-08-20) | UD-Q3_K_XL | 13.15 GB (13146393504 B) | no, measured: `--fit` puts 50/66 layers on GPU, 2921 MiB CPU_Mapped, 1088 MiB of the 4352 MiB KV on CPU at 131072 ctx | 11.7 | 19,001 | 131072 | benched | `models\qwen3.8-27b\Qwen3.8-27B-UD-Q3_K_XL.gguf` |
| Underdog Saluki 27B 1.0 (Qwen3.8-27B, see provenance note) | ConwayResearch/Underdog-Saluki-27B-1.0 `Underdog-Saluki-27B-1.0-IQ2-mix.gguf` (lastModified 2026-10-15) | IQ2-mix | 7.90 GB (7898369152 B) | yes, measured: `--fit` made no change at 131072 ctx (65/65 layers, full 4352 MiB KV on GPU, 2462 MiB left free; 265 MiB CPU_Mapped) | 57.5 (57.1 at 65536) | 12,335 | 131072 | benched | `models\saluki-27b\Underdog-Saluki-27B-1.0-IQ2-mix.gguf` |
| Qwen3.8-27B GSQ-RCO (with MTP layer) | ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` (lastModified 2026-09-02) | IQ3_XXS | 10.44 GB (10442827840 B) | no at 131072 with q8_0 KV, measured: 61/66 layers on GPU, 967 MiB CPU_Mapped, 272 MiB of the 4352 MiB KV on CPU (52/66 with MTP); with q4_0 KV + MTP still no: 64/66 layers, 603 MiB CPU_Mapped, full 2304 MiB KV on GPU, 124 MiB short (Phase 3d); yes at 65536 with q8_0 KV (66/66, with or without MTP) | 26.4 at 131072 (18.0 with MTP; 56.4 with MTP and q4_0 KV); 48.8 at 65536 (83.7 with MTP `draft-mtp`, n-max 2) | 17,021 (12,227 at 65536) | 131072 | benched | `models\qwen3.8-27b-gsq-rco\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` |
| Gemma 4 26B-A4B | unsloth/gemma-4-26B-A4B-it-GGUF `gemma-4-26B-A4B-it-UD-IQ4_XS.gguf` (lastModified 2026-07-17) | UD-IQ4_XS | 13.60 GB (13597177568 B) | no, measured: 31/31 layers on GPU, 4 layers overflowing (experts), 1964 MiB CPU_Mapped at 131072 ctx | 96.9 | 4,653 | 131072 | benched | `models\gemma-4-26b-a4b\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf` |
| GLM-4.7-Flash | unsloth/GLM-4.7-Flash-GGUF `GLM-4.7-Flash-UD-Q3_K_XL.gguf` (lastModified 2026-02-12) | UD-Q3_K_XL (substitute; IQ4_XS 16.27 GB needs offload) | 13.78 GB (13782004064 B) | no, measured: 48/48 layers on GPU, 12 layers overflowing (experts), 3026 MiB CPU_Mapped at 131072 ctx | 89.9 | 13,755 | 131072 | benched | `models\glm-4.7-flash\GLM-4.7-Flash-UD-Q3_K_XL.gguf` |
| Qwen3-Coder-Next 80B-A3B | UNVERIFIED | UD-IQ4_XS | 38.4 GB | no (`--n-cpu-moe`) | - | - | 131072 | candidate | - |
| Nemotron Super 120B | UNVERIFIED | IQ3_XXS | 56 GB | no (`--n-cpu-moe`) | - | - | 131072 (fit UNVERIFIED) | candidate | - |
| gpt-oss-20b | ggml-org/gpt-oss-20b-GGUF `gpt-oss-20b-MXFP4.gguf` (lastModified 2026-10-19) | native MXFP4 | 12.11 GB (12109566624 B) | yes, measured: `--fit` made no change at 131072 ctx (2096 MiB left free; 587 MiB CPU_Mapped) | 170.4 | 2,977 | 131072 | benched | `models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf` |
| Qwen3.8-27B OrcaSAQ2 (3.21 bpw, vLLM + vendor kernel) | orcarouter/OrcaSAQ-2-27B (4 safetensors shards, EXL3 `quant_method`, lastModified 2026-10-12) | EXL3 3.21 bpw (OrcaSAQ2) | 12.27 GB safetensors (12.32 GB / 12323397010 B all files, incl. a 29 MB mp4) | no, measured (vLLM 0.30.0, WSL2): weights 11.26 GiB of a 14.55 GiB budget leave a 0.33-0.49 GiB KV pool; 32768 needs 1.29 GiB, so no context >= 4096 starts | - | - | 131072 | blocked: vLLM KV pool too small on this 16 GB card with the desktop's 1.3-2.0 GiB (Phase 5 spike, `bench/summary-2026-10-24.md`) | `models\orcasaq-2-27b\` |
| Qwen3.8-27B-Uncensored (abliterated) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) | IQ3_M | 12.8 GB (12768331360 B) | no at 131072 (weights-only estimate: the smaller IQ3_XXS below already misses by 1441 MiB, measured) | - | - | 131072 | fallback | - |
| Qwen3.8-27B-Uncensored (abliterated, with MTP layer) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) `Qwen3.8-27B-Uncensored-IQ2_XXS.gguf` (lastModified 2026-10-12) | IQ2_XXS | 8.88 GB (8884504160 B) | yes, measured: `--fit` made no change at 131072 ctx (66/66 layers, full 4352 MiB KV on GPU, 2084 MiB left free; 398 MiB CPU_Mapped) | 55.0 (55.2 at 65536) | 11,369 (11,268 at 65536) | 131072 | benched (Phase 3c; quality and refusal removal UNVERIFIED) | `models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ2_XXS.gguf` |
| Qwen3.8-27B-Uncensored (abliterated, with MTP layer) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) `Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` (lastModified 2026-10-12) | IQ3_XXS | 11.64 GB (11637692000 B) | no at 131072 with q8_0 KV, measured: 58/66 layers on GPU, 1684 MiB CPU_Mapped, 544 MiB of the 4352 MiB KV on CPU (`--fit` cut 1441 MiB); yes at 131072 with q4_0 KV (66/66, 2304 MiB KV, 1630 MiB left free; Phase 3d); yes at 65536 with q8_0 KV (66/66, 2078 MiB left free) | 20.2 at 131072 (45.3 with q4_0 KV); 44.6 at 65536 | 14,750 (11,520 at 65536) | 131072 | benched (Phase 3c; quality and refusal removal UNVERIFIED) | `models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` |

Agentic loop (Phase 3d, `bench/loop/run.ps1`: Claude Code fixes a 3-test Node fixture,
3 repetitions; median wall s / median turns; table and failure modes in
`bench/summary-2026-10-24.md`, "Phase 3d"):

| Contender | Ctx / KV | Loop | Template |
|---|---|---|---|
| gpt-oss-20b MXFP4 | 131072 / q8_0 | 3/3, 26.6 s / 8 | embedded |
| gpt-oss-20b MXFP4 | 131072 / q4_0 | 3/3, 37.3 s / 10 | embedded |
| Qwen3.6-35B-A3B UD-IQ3_XXS (logon task) | 131072 / q8_0 | 3/3, 45.6 s / 16 | embedded |
| Qwen3.8-27B GSQ-RCO IQ3_XXS + MTP | 65536 / q8_0 | 3/3, 68.8 s / 9 | patched, REQUIRED |
| Qwen3.8-27B GSQ-RCO IQ3_XXS + MTP | 131072 / q4_0 | 3/3, 121.1 s / 8 | patched, REQUIRED |
| Underdog Saluki 27B IQ2-mix | 131072 / q8_0 | 3/3, 120.9 s / 8 | patched, REQUIRED |
| Qwen3.8-27B-Uncensored IQ3_XXS | 131072 / q4_0 | 3/3, 127.7 s / 8 | patched, REQUIRED |
| Qwen3.8-27B-Uncensored IQ2_XXS | 131072 / q8_0 | 3/3, 156.1 s / 11 | patched, REQUIRED |

The Qwen3.8-27B rows (Saluki, GSQ-RCO and both Uncensored quants embed the same
template, md5 `519239a4908bb1f805bbce5fa8c8a242`) REQUIRE the patched template under
Claude Code: the embedded one raises "System message must be at the beginning." (HTTP
500) because the SessionStart hook output arrives as a second system message. Serve
with `-ExtraArgs '--chat-template-file', '<repo>/config/chat-templates/qwen3.8-27b.jinja'`
(from `pwsh -File`: the single token `"-ExtraArgLine:--chat-template-file <abs path>"`).
Without it every loop repetition failed (0/3 Saluki, 0/1 GSQ-RCO).

GGUF header (read locally from each downloaded file, GGUF v3):

| Local file | general.architecture | general.name | block_count | context_length | expert_count / used |
|---|---|---|---|---|---|
| qwen3.8-27b | qwen35 | Qwen3.8-27B | 65 | 262144 | - (dense) |
| saluki-27b | qwen35 | Qwen3.8-27B GSQ-RCO (sic, see provenance note) | 64 (no MTP layer) | 262144 | - (dense) |
| qwen3.8-27b-gsq-rco | qwen35 | Qwen3.8-27B GSQ-RCO | 65 (incl. MTP, `nextn_predict_layers` 1) | 262144 | - (dense) |
| qwen3.8-27b-uncensored (IQ2_XXS and IQ3_XXS) | qwen35 | Qwen3.8 27B Abliterated (`general.finetune` abliterated) | 65 (incl. MTP, `nextn_predict_layers` 1) | 262144 | - (dense) |
| gemma-4-26b-a4b | gemma4 | Gemma-4-26B-A4B-It | 30 | 262144 | 128 / 8 |
| glm-4.7-flash | deepseek2 | Glm-4.7-Flash | 47 | 202752 | 64 / 4 |
| gpt-oss-20b | gpt-oss | gpt-oss-20b | 24 | 131072 | 32 / 4 |

Selection notes:

- Qwen3.8-27B: UD-IQ3_XXS (10.93 GB) and UD-Q3_K_XL (13.15 GB) both fit the
  14.5 GB cap; took UD-Q3_K_XL (higher quality, inside the recorded 12-14 GB).
- Gemma 4: unsloth UD-IQ4_XS is 13.60 GB, not the recorded 13.4 GB
  (bartowski IQ4_XS is 14.21 GB).
- GLM-4.7-Flash: largest Unsloth UD-* quant <= 15.0 GB. The largest file of
  any kind <= 15.0 GB is bartowski `zai-org_GLM-4.7-Flash-Q3_K_XL.gguf`
  14.78 GB (less KV headroom); bartowski IQ3_M is 13.98 GB.
- gpt-oss-20b: ggml-org ships the native MXFP4 file; unsloth has no MXFP4
  file (its `F16` is 13.79 GB).
- Underdog Saluki 27B 1.0 provenance: its GGUF `general.*` metadata is ISTA
  DASLab's (`general.name` "Qwen3.8-27B GSQ-RCO", `general.quantized_by` "ISTA
  DASLab", `general.repo_url` ISTA-DASLab), not ConwayResearch's. Its size matches
  none of the eight model files in ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF (smallest
  IQ2_XS 8.42 GB). The card names that repo as a base model (`base_model_relation:
  quantized`) and says the file is "tuned to keep tool calling intact"; derivative
  status (re-quant, different mix, or tuned weights) is UNVERIFIED, as are the
  card's benchmark claims. Details: `bench/summary-2026-10-24.md` (Phase 3b).
- Qwen3.8-27B GSQ-RCO: took the IQ3_XXS `-mtp` file (10.44 GB) to test the MTP
  head; the plain IQ3_XXS file is 10.09 GB.
- Qwen3.8-27B-Uncensored: abliterated (refusal direction removed, per its card) GGUF
  of `orcarouter/Qwen3.8-27B-Uncensored-FP8`; took the two smallest IQ files to
  compare with Saluki (2-bit) and GSQ-RCO (3-bit). The card's refusal and retention
  figures are for the FP8 build, not these quants (UNVERIFIED here). Details:
  `bench/summary-2026-10-24.md` (Phase 3c).
