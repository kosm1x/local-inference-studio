# Uploader rule (ruling 35, 2026-10-30)

Which uploader's GGUF this repo uses for each model, and why. Ruled GO by (35) in
[ROADMAP.md](ROADMAP.md) ("Rulings 2026-10-30"). A read-only study: nothing was
downloaded and no server was contacted. Figures come from the GGUF headers, the HF
download cache, `bench/summary-2026-10-24.md` and the Phase 3d loop results (read
locally); every other figure is marked UNVERIFIED.

## Rule

1. The publisher's own GGUF first: ggml-org for gpt-oss (native MXFP4); the finetune
   author for a finetune (orcarouter for Uncensored, ISTA DASLab for GSQ-RCO). Every
   requant adds an unknown.
2. Otherwise Unsloth UD, as P3 measured it: each Unsloth file benched 20/20 tool calls,
   names its imatrix and embeds a template that mentions tools.
3. Bartowski only when Unsloth has no file inside the size and KV budget, or when the
   Unsloth file fails the gate below while a same-quant Bartowski file passes it.

## Gate (any file, before agentic use)

- (a) the GGUF's embedded `tokenizer.chat_template` mentions tools;
- (b) `scripts/smoke.ps1` PASS (a `get_weather` tool_use with a non-empty city);
- (c) `bench/run.ps1` 20/20 tool calls;
- (d) under Claude Code: `/apply-template` renders a [system, user, system] request,
  or the loop fixture (`bench/loop/run.ps1`) passes 3/3.

A file that fails (d) with the patched template has a template problem, not an
uploader one.

## Per model (the nine local files)

Local files, each followed by the HF repo it came from.

1. `models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` (the default)
   <- orcarouter/Qwen3.8-27B-Uncensored-GGUF
2. `models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ2_XXS.gguf` <- same repo
3. Qwen3.6-35B-A3B UD-IQ3_XXS (HF hub cache, served with `-hf`)
   <- unsloth/Qwen3.6-35B-A3B-GGUF
4. `models/qwen3.8-27b/Qwen3.8-27B-UD-Q3_K_XL.gguf` <- unsloth/Qwen3.8-27B-GGUF
5. `models/gemma-4-26b-a4b/gemma-4-26B-A4B-it-UD-IQ4_XS.gguf`
   <- unsloth/gemma-4-26B-A4B-it-GGUF
6. `models/glm-4.7-flash/GLM-4.7-Flash-UD-Q3_K_XL.gguf` <- unsloth/GLM-4.7-Flash-GGUF
7. `models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf` <- ggml-org/gpt-oss-20b-GGUF
8. `models/qwen3.8-27b-gsq-rco/Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf`
   <- ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF
9. `models/saluki-27b/Underdog-Saluki-27B-1.0-IQ2-mix.gguf`
   <- ConwayResearch/Underdog-Saluki-27B-1.0 (header `quantized_by`: ISTA DASLab)

| # | Uploader | Quant | imatrix set (chunks) | Tmpl md5 | Tools | Loop |
|---|---|---|---|---|---|---|
| 1 | orcarouter | IQ3_XXS | local path, unpublished (312) | 519239a4 | 20/20 | 3/3 T |
| 2 | orcarouter | IQ2_XXS | same as 1 (312) | 519239a4 | 20/20 | 3/3 T |
| 3 | Unsloth | UD-IQ3_XXS | Unsloth txt (76) | a7f294a5 | 20/20 | 3/3 E |
| 4 | Unsloth | UD-Q3_K_XL | `imatrix_unsloth` (1251) | 2a79880b | 20/20 | - |
| 5 | Unsloth | UD-IQ4_XS | Unsloth txt (141) | 7e2ad1fb | 20/20 | - |
| 6 | Unsloth | UD-Q3_K_XL | Unsloth txt (85) | ba2430d0 | 20/20 | - |
| 7 | ggml-org | MXFP4 | none (native MXFP4) | 4d4366d7 | 20/20 | 3/3 E |
| 8 | ISTA DASLab | IQ3_XXS | calib_qwen3.8-27b.tokids (1000) | 519239a4 | 20/20 | 3/3 T |
| 9 | ConwayResearch | IQ2-mix | same as 8 (1000) | 519239a4 | 20/20 | 3/3 T |

No file changes uploader. Tools = P3 `bench/run.ps1` tool calls (0 wrong, none, bad
args or errors in each). Loop = Phase 3d `bench/loop/run.ps1` runs passed: T with the
patched template, E with the embedded one, "-" not run. Each Unsloth file names its
own `unsloth_calibration_<model>.txt`; file 4 has no dataset key, only the imatrix file
name. File 1's calibration set is a local path with no published dataset (UNVERIFIED).
Template md5 = first 8 hex digits of the md5 of the embedded `tokenizer.chat_template`;
every one mentions `tools` and `tool_call`. The 519239a4 template raises "System
message must be at the beginning." on Claude Code's second system message (HTTP 500,
Phase 3d), which `config/chat-templates/qwen3.8-27b.jinja` fixes; file 4's template is
untested under Claude Code. The HF cache etags (sha256) were read; the local files
were not re-hashed (match UNVERIFIED).

## The gap finding

The only record of the "tool-call gap" is `docs/landscape-2026-10-24.md:93-95`
(Phase 0): "Unsloth IQ3_XXS Qwen3.5-27B 5% vs Bartowski 100% tool-call success". It has
no URL, date, harness or llama.cpp build, and Qwen3.5-27B was never benched here.
`docs/evaluation-2026-10-24.md:108-110` repeats it in prose and the ROADMAP's P3 open
ruling cited it. No bench run in this repo backs it, and no source was found on the
web: the claim is untraceable and UNVERIFIED.

Likely cause (UNVERIFIED): the Unsloth Qwen3.5 chat template bug fixed in their Feb 27
re-upload ("tool-calling fixes"; a commenter's diff adds a mapping check on tool-call
arguments in the template, so the fault was the template, not the weights):
https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF/discussions/10. llama.cpp issues on
Qwen3.5 tool calls are parser or template faults, none uploader-specific (states read
2026-10-30): #20260 (parser fails when text precedes `<tool_call>`; CLOSED 2026-09-12),
#20837 (tool calls inside the thinking block; OPEN), #20182 (enable_thinking; CLOSED).

Here, P3 found no gap: every file above scored 20/20, Unsloth included; a 5% success
rate would show as about 1/20. No Bartowski file was ever downloaded or benched. The
one tool-call failure the repo recorded is the template one above.

## Effect

No model changes uploader. The default stays
`models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` (orcarouter); no
download is needed.

Bartowski alternative for the default, NOT proposed:
`bartowski/orcarouter_Qwen3.8-27B-Uncensored-GGUF` IQ3_XXS is 12,626,774,272 B (HF
API, UNVERIFIED here), +989 MB (about 943 MiB) over file 1. Against the 1,630 MiB left
free at 131072 / q4_0 that leaves about 690 MiB (estimate, UNVERIFIED, untested).
Whether it carries the MTP layer and which template it embeds are unread. Unsloth has
no build of this finetune. Taking it would need an operator ruling and a 12.6 GB
download.

## What would overturn the rule

- A traced primary source for the 5%/100% test that applies to a current
  (post-Feb-27) Unsloth file of a model this repo runs.
- A file here failing gate (b) or (c) on two runs with the patched template while
  the other uploader's same-size file passes: a same-day A/B on the same build, which
  this repo has not run.
- The loop fixture showing a difference attributable to the quant (KLD or a repeated
  tool-argument error), not to the template or the parser (#20837 is still open).
- For the default: the operator wanting a published calibration set; the candidate is
  then the Bartowski requant, after a fit check at 131072 / q4_0 and an MTP layer check.
