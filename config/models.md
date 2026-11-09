# Model candidates

Tracked list from `docs/landscape-2026-10-24.md`. Repo + filename + size were
verified against the HF API (`/api/models/<repo>?blobs=true`; all ungated except
orcarouter/Qwen3.8-27B-Uncensored-GGUF, read with a token) on
2026-10-24 for the rows with a Local file; downloaded byte counts match
the API exactly.
"Fits all-GPU" is measured for the benched rows (P3 part B, Phase 3b and Phase 3c, 2026-10-24): whether
`--fit` kept every tensor on GPU at the target context with the `serve.ps1`
defaults of the time (q8_0 KV, still the default for every model except the default and
fallback files; until 2026-11-08 the ruling 6 file only). "Decode tok/s" (median of 3
after one discarded warm-up) and
"Prefill 20K ms" (cold, median of 3) are the P3 bench numbers; the full table is
`bench/summary-2026-10-24.md`. Unbenched rows are the weights-only estimate.
"lastModified" is the repo's, not the file's.

Default (Model test 2 ruling of 2026-11-08 22:27 in docs/ROADMAP.md; the
`scripts/serve.ps1` defaults and the logon task from that commit): Qwen3.8-27B
OrcaRouter GSQ-RCO IQ3_XXS v2.1 (RentedNoodle), local file
`models\qwen3.8-27b-uncensored\Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf`, ctx
131072, KV q4_0, chat template `config/chat-templates/qwen3.8-27b.jinja` (`serve.ps1`
adds it for this folder; the file's own embedded template is untested), no MTP at any
`-Ctx` (its MTP head is present, UNVERIFIED here), server thinking off. Fit and decode
come from Model test 2 only (its row below): whole card 14,736 of 16,376 MiB idle after
load, layer split UNVERIFIED, 43.8 tok/s ladder-log decode at 0 to 20K; no bench. The
uncensored property is taken from provenance (card claim, UNVERIFIED). Ladder evidence:
Model test 2 results in docs/ROADMAP.md.

Fallback (the default 2026-10-24 to 2026-11-08; rulings 6 and 14; ruling 14 of
2026-10-25 reverted ruling 12's 65536 + MTP; until 2026-11-08 the `scripts/serve.ps1`
defaults and the logon task; started with `scripts\stop.ps1`, then
`scripts\serve.ps1 -Model <this file> -LogFile logs\llama-server.log`, launch lines in
the README): Qwen3.8-27B-Uncensored IQ3_XXS,
local file `models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf`, ctx
131072, KV q4_0, chat template `config/chat-templates/qwen3.8-27b.jinja` REQUIRED
(`serve.ps1` adds it for this folder), no MTP, server thinking off (`--reasoning off`,
RULED 2026-10-26); measured 45.3 tok/s decode, 66/66 layers
on GPU with 1,630 MiB left free (Phase 3d). History: at 65536 + MTP (ruling 12) it
measured 81.6 tok/s with 1,684 MiB free (Phase 3e), and one lean-set loop rep passed 3/3
in 6 turns, 40.7 s wall, 0 tool errors (variance UNVERIFIED). The Phase 3d loop (3/3,
0 tool errors, median 127.7 s wall) ran this file at 131072 without MTP.
Quality and refusal removal UNVERIFIED. MTP rule: `serve.ps1` adds the two MTP flags
only for this file (the default until 2026-11-08, the fallback since), only at `-Ctx`
65536 or below and only without `-NoMtp`; every other `-Model`, the new default
included, runs without MTP. A start of this file without `-Ctx` (131072) adds none
and warns nothing; an explicit `-Ctx` above 65536 skips them with a warning (`-NoMtp`
silences it): MTP costs about 1.1 GB, so `--fit` would move layers to CPU (estimate,
UNVERIFIED at 131072). `config/claude-settings.json` and `scripts/claude-local.ps1`
default to a 114688 context window, a margin below the server's 131072 (the ladder and
benches pass 131072 explicitly); the wrapper passes a per-run copy of the
settings file with `CLAUDE_CODE_AUTO_COMPACT_WINDOW` rewritten to `-LisContextTokens`
and, unless `-LisFull`, the lean set (7 tools, no MCP, one-model policy; ruling 13; it
saves about 9,172 prompt tokens against `-LisFull` in the same cwd, 9,560 before the
2026-10-25 policy block, measured before the loop guards (+101 tokens), while absolute
sizes vary by a few hundred tokens with the cwd path). KV rule: `serve.ps1` uses
q4_0 only for this file and the default and q8_0 for any other `-Model` (the KV those
rows were benched with) unless `-KvType` is passed.

Pins: `models/manifest.json` holds each local file's HF repo, revision (commit), byte
size and SHA256; for the default file, revision
`2113bb22c43635fcdaad4b728c914db4c2ec1d3b` and SHA256
`ab955b5083d9cdf0bf55c37acdcae359b78756c4544d97960c23d8fca98feb9b`; for the fallback,
revision `34e7cb013d66af05f668fe8a37087585de2e85f0` and SHA256
`0d91ad7b2c57f545a030b1d391375a5f9a822423b90923d91cf744e717e80d03`.
`pwsh scripts/install.ps1 -VerifyModels` checks every file present. `serve.ps1` hashes
the `-Model` it starts against its entry at most once per boot (20 s for the fallback
file cold, 8.9 s from the OS cache; marker `logs/model-verify.json`) and refuses a
mismatch; a file not in the manifest starts with a warning.

Local files 2026-11-08 (operator): four files were deleted after the November HF
survey (report kept outside the repo): unsloth `Qwen3.8-27B-UD-Q3_K_XL` (spills 16
layers), Saluki IQ2-mix (licence CC BY-NC 4.0 since 2026-11-05), gemma-4-26B-A4B
UD-IQ4_XS and GLM-4.7-Flash UD-Q3_K_XL (experts on the CPU at 131072). Their rows keep
the measurements. On disk: the then default (the fallback since 22:27 that day), the
GSQ-RCO IQ3_XXS-mtp file (test arm 2),
and two other alternates, Uncensored IQ2_XXS and gpt-oss-20b MXFP4. `models/manifest.json`
lists only these four; `pwsh scripts/install.ps1 -VerifyModels` passed 4 of 4 that day.
Added the same day: the queue item 6 file (OrcaRouter GSQ-RCO v2.1 row below; the
default since 22:27 that day); the manifest then listed five and `-VerifyModels` passed
5 of 5.

| Model | HF repo | Quant | Size | Fits all-GPU? | Decode tok/s | Prefill 20K ms | Ctx target | Status | Local file |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B | unsloth/Qwen3.6-35B-A3B-GGUF | UD-IQ3_XXS | 13.2 GB | no, measured: `--fit` keeps 41/41 layers on GPU but moves part of 2 layers' experts to CPU (~535 MiB) at 131072 ctx with `--no-mmproj` and q8_0 KV | 134.0 | 5,351 | 131072 | benched (default until ruling 6; fallback) | - |
| Qwen3.8-27B dense | unsloth/Qwen3.8-27B-GGUF `Qwen3.8-27B-UD-Q3_K_XL.gguf` (lastModified 2026-08-20) | UD-Q3_K_XL | 13.15 GB (13146393504 B) | no, measured: `--fit` puts 50/66 layers on GPU, 2921 MiB CPU_Mapped, 1088 MiB of the 4352 MiB KV on CPU at 131072 ctx | 11.7 | 19,001 | 131072 | benched | deleted 2026-11-08 (was `models\qwen3.8-27b\Qwen3.8-27B-UD-Q3_K_XL.gguf`) |
| Underdog Saluki 27B 1.0 (Qwen3.8-27B, see provenance note) | ConwayResearch/Underdog-Saluki-27B-1.0 `Underdog-Saluki-27B-1.0-IQ2-mix.gguf` (lastModified 2026-10-15) | IQ2-mix | 7.90 GB (7898369152 B) | yes, measured: `--fit` made no change at 131072 ctx (65/65 layers, full 4352 MiB KV on GPU, 2462 MiB left free; 265 MiB CPU_Mapped) | 57.5 (57.1 at 65536) | 12,335 | 131072 | benched | deleted 2026-11-08 (was `models\saluki-27b\Underdog-Saluki-27B-1.0-IQ2-mix.gguf`) |
| Qwen3.8-27B GSQ-RCO (with MTP layer) | ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF `Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` (lastModified 2026-09-02) | IQ3_XXS | 10.44 GB (10442827840 B) | no at 131072 with q8_0 KV, measured: 61/66 layers on GPU, 967 MiB CPU_Mapped, 272 MiB of the 4352 MiB KV on CPU (52/66 with MTP); with q4_0 KV + MTP still no: 64/66 layers, 603 MiB CPU_Mapped, full 2304 MiB KV on GPU, 124 MiB short (Phase 3d); yes at 65536 with q8_0 KV (66/66, with or without MTP); yes at 131072 with q4_0 KV and no MTP, measured 2026-11-08: 12,648 + 248 MiB for the process, VRAM peak 15,418 MB (bench `20261108-125456`) | 26.4 at 131072 (18.0 with MTP; 56.4 with MTP and q4_0 KV; 49.03 with q4_0 KV and no MTP, 2026-11-08); 48.8 at 65536 (83.7 with MTP `draft-mtp`, n-max 2) | 17,021 (12,227 at 65536; 12,120 at 131072 with q4_0 KV and no MTP, 2026-11-08) | 131072 | benched | `models\qwen3.8-27b-gsq-rco\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` |
| Gemma 4 26B-A4B | unsloth/gemma-4-26B-A4B-it-GGUF `gemma-4-26B-A4B-it-UD-IQ4_XS.gguf` (lastModified 2026-07-17) | UD-IQ4_XS | 13.60 GB (13597177568 B) | no, measured: 31/31 layers on GPU, 4 layers overflowing (experts), 1964 MiB CPU_Mapped at 131072 ctx | 96.9 | 4,653 | 131072 | benched | deleted 2026-11-08 (was `models\gemma-4-26b-a4b\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf`) |
| GLM-4.7-Flash | unsloth/GLM-4.7-Flash-GGUF `GLM-4.7-Flash-UD-Q3_K_XL.gguf` (lastModified 2026-02-12) | UD-Q3_K_XL (substitute; IQ4_XS 16.27 GB needs offload) | 13.78 GB (13782004064 B) | no, measured: 48/48 layers on GPU, 12 layers overflowing (experts), 3026 MiB CPU_Mapped at 131072 ctx | 89.9 | 13,755 | 131072 | benched | deleted 2026-11-08 (was `models\glm-4.7-flash\GLM-4.7-Flash-UD-Q3_K_XL.gguf`) |
| Qwen3.8-27B-TURBO-Fable-Cold-Fusion-735-882-Heretic-Uncensored-NEO-CODER-MAX-MTP (DavidAU) | DavidAU/Qwen3.8-27B-TURBO-Fable-Cold-Fusion-735-882-Heretic-Uncensored-NEO-CODER-MAX-MTP-GGUF (card and file list read 2026-11-04, sizes from the file list, not the API) | IQ2_M 11.7 GB or MTP-IQ2_M 12.1 GB (the only files in the fit class; no IQ3_XXS) | 11.7 / 12.1 GB (file list) | estimate: yes at 131072 with q4_0 KV, like the fallback (UNVERIFIED) | - | - | 131072 | candidate, top of the queue (operator, 2026-11-04); card read; test arm 1 in docs/ROADMAP.md | - |
| gpt-oss-20b | ggml-org/gpt-oss-20b-GGUF `gpt-oss-20b-MXFP4.gguf` (lastModified 2026-10-19) | native MXFP4 | 12.11 GB (12109566624 B) | yes, measured: `--fit` made no change at 131072 ctx (2096 MiB left free; 587 MiB CPU_Mapped) | 170.4 | 2,977 | 131072 | benched | `models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf` |
| Qwen3.8-27B OrcaSAQ2 (3.21 bpw, vLLM + vendor kernel) | orcarouter/OrcaSAQ-2-27B (4 safetensors shards, EXL3 `quant_method`, lastModified 2026-10-12) | EXL3 3.21 bpw (OrcaSAQ2) | 12.27 GB safetensors (12.32 GB / 12323397010 B all files, incl. a 29 MB mp4) | no, measured (vLLM 0.30.0, WSL2): weights 11.26 GiB of a 14.55 GiB budget leave a 0.33-0.49 GiB KV pool; 32768 needs 1.29 GiB, so no context >= 4096 starts | - | - | 131072 | blocked: vLLM KV pool too small on this 16 GB card with the desktop's 1.3-2.0 GiB (Phase 5 spike, `bench/summary-2026-10-24.md`) | `models\orcasaq-2-27b\` |
| Qwen3.8-27B-Uncensored (abliterated) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) | IQ3_M | 12.8 GB (12768331360 B) | no at 131072 (weights-only estimate: the smaller IQ3_XXS below already misses by 1441 MiB, measured) | - | - | 131072 | fallback | - |
| Qwen3.8-27B-Uncensored (abliterated, with MTP layer) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) `Qwen3.8-27B-Uncensored-IQ2_XXS.gguf` (lastModified 2026-10-12) | IQ2_XXS | 8.88 GB (8884504160 B) | yes, measured: `--fit` made no change at 131072 ctx (66/66 layers, full 4352 MiB KV on GPU, 2084 MiB left free; 398 MiB CPU_Mapped) | 55.0 (55.2 at 65536) | 11,369 (11,268 at 65536) | 131072 | benched (Phase 3c; quality and refusal removal UNVERIFIED) | `models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ2_XXS.gguf` |
| Qwen3.8-27B-Uncensored (abliterated, with MTP layer) | orcarouter/Qwen3.8-27B-Uncensored-GGUF (gated) `Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` (lastModified 2026-10-12) | IQ3_XXS | 11.64 GB (11637692000 B) | no at 131072 with q8_0 KV, measured: 58/66 layers on GPU, 1684 MiB CPU_Mapped, 544 MiB of the 4352 MiB KV on CPU (`--fit` cut 1441 MiB); yes at 131072 with q4_0 KV (66/66, 2304 MiB KV, 1630 MiB left free; Phase 3d); yes at 65536 with q8_0 KV (66/66, 2078 MiB left free); yes at 65536 with q4_0 KV + MTP (66/66, 1684 MiB left free; Phase 3e) | 20.2 at 131072 (45.3 with q4_0 KV); 44.6 at 65536 (45.4 with q4_0 KV, 81.6 with q4_0 KV + MTP `draft-mtp` n-max 2, Phase 3e) | 14,750 (11,520 at 65536) | 131072 | FALLBACK (default 2026-10-24 to 2026-11-08; q4_0 KV by rule, MTP at 65536); benched (Phase 3c; quality and refusal removal UNVERIFIED); ladder rerun 2026-11-08 under client 2.1.319 (Model test 2, Default rerun) | `models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` |
| Qwen3.8-27B OrcaRouter GSQ-RCO v2.1 (orcarouter abliterated base per its card, with MTP layer; see provenance note) | RentedNoodle/Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-Uncensored `Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf` (lastModified 2026-11-06) | IQ3_XXS (GSQ-RCO map, 3.04 bpw per card) | 10.38 GB (10382717184 B; sha256 verified against the manifest) | UNVERIFIED layer split (no offload summary at the log level used); whole-card figures at 131072 with q4_0 KV and no MTP, 2026-11-08, nvidia-smi read in the session, not saved: 14,736 of 16,376 MiB idle after load, 15,065 MiB during a 48-module rep | 43.8 at 0 to 20K (ladder log median, not the bench; 37.2 at 40K to 65,536, 31.0 at 80K to 95K) | - | 131072 | DEFAULT (ruling 2026-11-08 22:27, Model test 2 strict comparison: q4_0 KV, patched template applied automatically with the file's own embedded template untested, no MTP, UNVERIFIED layer split); ladder n=3 2026-11-08, Model test 2; no bench; refusal removal UNVERIFIED | `models\qwen3.8-27b-uncensored\Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf` |

Agentic loop (Phase 3d, `bench/loop/run.ps1`: Claude Code fixes a 3-test Node fixture,
3 repetitions; median wall s / median turns; table and failure modes in
`bench/summary-2026-10-24.md`, "Phase 3d"):

| Contender | Ctx / KV | Loop | Template |
|---|---|---|---|
| gpt-oss-20b MXFP4 | 131072 / q8_0 | 3/3, 26.6 s / 8 | embedded |
| gpt-oss-20b MXFP4 | 131072 / q4_0 | 3/3, 37.3 s / 10 | embedded |
| Qwen3.6-35B-A3B UD-IQ3_XXS (logon task until ruling 6) | 131072 / q8_0 | 3/3, 45.6 s / 16 | embedded |
| Qwen3.8-27B GSQ-RCO IQ3_XXS + MTP | 65536 / q8_0 | 3/3, 68.8 s / 9 | patched, REQUIRED |
| Qwen3.8-27B GSQ-RCO IQ3_XXS + MTP | 131072 / q4_0 | 3/3, 121.1 s / 8 | patched, REQUIRED |
| Underdog Saluki 27B IQ2-mix | 131072 / q8_0 | 3/3, 120.9 s / 8 | patched, REQUIRED |
| Qwen3.8-27B-Uncensored IQ3_XXS (fallback; default 2026-10-24 to 2026-11-08, ruling 6) | 131072 / q4_0 | 3/3, 127.7 s / 8 | patched, REQUIRED |
| Qwen3.8-27B-Uncensored IQ2_XXS | 131072 / q8_0 | 3/3, 156.1 s / 11 | patched, REQUIRED |

The Qwen3.8-27B rows (Saluki, GSQ-RCO and both Uncensored quants embed the same
template, md5 `519239a4908bb1f805bbce5fa8c8a242`) REQUIRE the patched template under
Claude Code: the embedded one raises "System message must be at the beginning." (HTTP
500) because the SessionStart hook output arrives as a second system message.
`serve.ps1` adds it on its own for files under `models/qwen3.8-27b-uncensored` and
(since 2026-11-08) `models/qwen3.8-27b-gsq-rco`; for the others pass
`-ChatTemplateFile <repo>/config/chat-templates/qwen3.8-27b.jinja` or serve
with `-ExtraArgs '--chat-template-file', '<repo>/config/chat-templates/qwen3.8-27b.jinja'`
(from `pwsh -File`: the single token `"-ExtraArgLine:--chat-template-file <abs path>"`).
Without it every loop repetition failed (0/3 Saluki, 0/1 GSQ-RCO). The path must not
contain spaces (`serve.ps1` splits `-ExtraArgLine` on whitespace). The unsloth
`Qwen3.8-27B-UD-Q3_K_XL.gguf` has a different template with the same check and is NOT
covered by this patch (not run).

GGUF header (read locally from each downloaded file, GGUF v3):

| Local file | general.architecture | general.name | block_count | context_length | expert_count / used |
|---|---|---|---|---|---|
| qwen3.8-27b | qwen35 | Qwen3.8-27B | 65 | 262144 | - (dense) |
| saluki-27b | qwen35 | Qwen3.8-27B GSQ-RCO (sic, see provenance note) | 64 (no MTP layer) | 262144 | - (dense) |
| qwen3.8-27b-gsq-rco | qwen35 | Qwen3.8-27B GSQ-RCO | 65 (incl. MTP, `nextn_predict_layers` 1) | 262144 | - (dense) |
| qwen3.8-27b-uncensored (OrcaRouter GSQ-RCO v2.1) | qwen35 | Staged_Tmpl (no `general.finetune` or `basename`; 866 tensors) | 65 (incl. MTP, `nextn_predict_layers` 1) | 262144 | - (dense) |
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
- Qwen3.8-27B OrcaRouter GSQ-RCO v2.1 (queue item 6, survey 2026-11-08, downloaded
  2026-11-08 at revision `2113bb22c43635fcdaad4b728c914db4c2ec1d3b`, Apache-2.0, not
  gated; sha256 `ab955b5083d9cdf0bf55c37acdcae359b78756c4544d97960c23d8fca98feb9b`,
  equal to the LFS etag and the repo's SHA256SUMS.txt). Card, vendor text,
  UNVERIFIED: a quantization of the OrcaRouter Qwen3.8-27B checkpoint, "not a new
  fine-tune", with ISTA-DASLab's GSQ/RCO per-tensor allocation map reproduced on that
  base; v2.1 raised two IQ1 FFN tensors (`ffn_gate` IQ1_S, `ffn_up` IQ1_M) and is 84 MB
  smaller than v2.0 (which tensors went down: UNVERIFIED); custom imatrix
  (`quantize.imatrix.file` imatrix_orca_istacorpus.dat, 496 entries, 10 chunks); MTP
  head present, maker not stated. The header does not name orcarouter
  (`general.name` 'Staged_Tmpl'). Vendor figures (RTX 5070 Ti, custom builds;
  UNVERIFIED): 33.7 t/s at 196K q4_0, tool-call JSON 13/14, MTP acceptance 0.91;
  GPQA-D 75.25, WikiText-2 PPL 6.17 and XSTest over-refusal 0/250 are v2.0 only; no KL
  or refusal-rate figure for the base. Its embedded chat template is the froggeric
  v22.5 tool-use template (28,226 chars, md5 starting 5c928b42), not the stock one
  (md5 `519239a4...`); `serve.ps1` serves it with the patched
  `config/chat-templates/qwen3.8-27b.jinja` because the file sits under
  `models/qwen3.8-27b-uncensored`, so its own template is untested. Ladder results:
  `docs/ROADMAP.md`, Model test 2. The deprecated sibling repo
  `RentedNoodle/Qwen3.8-27B-GSQ-RCO-IQ3_XXS-Uncensored` is the frozen huihui-line v1.x.
- Queue item 8, surveyed 2026-11-08, not downloaded:
  `huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF` (Apache-2.0, not gated, main
  `1c69098e9c32db6dc06fc48f1d6cc75ad07da89e`), file
  `...-GSQ-RCO-IQ3_XXS-mtp.gguf`, 10,442,827,296 B, sha256
  `53fbcda56fae73e1bc2f3222f6939b4cf051fc52c26acc387b4c90f6da7d5c7d`. Card: ISTA's GGUF
  ablated in place, "only layers 22 to 52 (0-based) have been ablated", "crude,
  proof-of-concept", no metrics; header `general.finetune` 'abliterated'.
