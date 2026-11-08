# Local Inference Studio

The most potent possible local LLM inference on this Windows 11 workstation,
consumed by the Claude Code CLI harness. No LM Studio, no Ollama.

Setup: see [docs/SETUP.md](docs/SETUP.md).

Backend of record: llama.cpp `llama-server` run natively on Windows. Since
PR #17570 (HF blog 2026-01-19) it serves the Anthropic Messages API itself
(`/v1/messages`, `/count_tokens`, tool_use/tool_result, thinking, streaming),
so Claude Code talks to it with no proxy.

## Hardware (probed 2026-10-24)

| Component | Value |
|---|---|
| OS | Windows 11 Pro 10.0.26200 |
| GPU | NVIDIA RTX 4070 Ti SUPER 16 GB (16376 MiB), driver 617.42 |
| CPU | AMD Ryzen 7 9800X3D |
| RAM | 64 GB DDR5 (61.6 GiB usable) |
| WSL2 | Ubuntu, GPU visible (`nvidia-smi` works inside WSL) |
| Tooling | Docker Desktop 29.2.1, uv 0.13.5, Python 3.13.15, Node 24.22.1, Claude Code 2.1.310 |
| Not installed | CUDA toolkit (nvcc), cmake, Rust/cargo, llama-server |

No build toolchain is present, so llama.cpp comes from the prebuilt Windows
release zips. It is never built from source here.

## Architecture

```
Claude Code CLI  (scripts/claude-local.ps1: lean set = 7 tools, no MCP,
   |              one-model policy appended; -LisFull for the full set)
   | ANTHROPIC_BASE_URL=http://127.0.0.1:8080   (all model tiers = "local")
   v
llama-server.exe  /v1/messages  (native Windows, CUDA build)
   |
   v
GGUF model: weights + KV cache on the RTX 4070 Ti SUPER
            (MoE experts optionally on CPU/RAM via --n-cpu-moe)
```

## Status

Phase 0 done (2026-10-24): evaluation of two reference repos, landscape
survey, and this scaffold. Phase 1 done (2026-10-24): llama.cpp b11868 CUDA 13.4
installed, Qwen3.6-35B-A3B UD-IQ3_XXS serves `/v1/messages` with tool_use
(`smoke.ps1` PASS); numbers in [docs/ROADMAP.md](docs/ROADMAP.md). Phase 2 done
(2026-10-24): Claude Code runs an edit-test-fix loop on the local server. Phase 3
(bench matrix and agentic-loop comparison) done 2026-10-24; the default model is
ruled (below).

## Default model (ruled 2026-11-08, Model test 1 (c); before it rulings 6 and 14)

| Model | Local file | Ctx | KV | Chat template | MTP | Decode tok/s | Loop (Phase 3d) |
|---|---|---|---|---|---|---|---|
| ISTA DASLab Qwen3.8-27B GSQ-RCO IQ3_XXS-mtp (10.44 GB), the default from 2026-11-08 | `models/qwen3.8-27b-gsq-rco/Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf` | 131072 | q4_0 (now the default; before the switch serve.ps1 gave it q8_0 unless `-KvType q4_0`) | `config/chat-templates/qwen3.8-27b.jinja`, REQUIRED (now applied automatically) | off at 131072; now added at `-Ctx 65536` or below (with q4_0 KV there: UNVERIFIED) | 49.03 (measured 2026-11-08, Model test 1; 83.7 with MTP at 65536 and q8_0 KV, config/models.md) | ran only with MTP on: 3/3, median 8 turns, 121.1 s wall (131072, q4_0, 64/66 layers); at this setup see Model test 1 in docs/ROADMAP.md |
| Orca Qwen3.8-27B-Uncensored IQ3_XXS (abliterated, 11.64 GB), the default until 2026-11-08 | `models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` | 131072 | q4_0 only with `-KvType q4_0` since the switch (without it q8_0, measured 58/66 layers on the GPU at 131072) | `config/chat-templates/qwen3.8-27b.jinja`, REQUIRED (still applied automatically) | off (ruling 14); since the switch never added | 45.3 (measured, Phase 3d; 81.6 with MTP at 65536, Phase 3e) | 3/3, 0 tool errors, median 8 turns, ~128 s wall (measured at 131072 without MTP, full tool set) |

The ISTA stock file became the default on 2026-11-08 (operator ruling (c) after Model
test 1, docs/ROADMAP.md): at n=3 it led the former default on blocked and on both
long-fix rungs and trailed it on stale-figure and bait by a report-format slip only
(text after `STATUS:`), at the same all-GPU fit (12,648 + 248 MiB for the process)
and 9 percent faster decode. Still owed on it: a whole-file-read fixture and the
`STATUS:` slip screen of the Uncensored file's short-case reps. The rest of this
section describes the former default.

The former default was chosen for accuracy over speed (ruling 6: the only 131072 row
with 0 tool errors). At
131072 all 66 layers and the 2,304 MiB q4_0 KV sit on the GPU with 1,630 MiB left free
(measured, `-lv 4`). Ruling 12 traded context for MTP (65536, 1.80x bench decode);
ruling 14 reverted it after a real report-producing session auto-compacted at 39,098
tokens on the 65536 window and the model's summary rewrote the facts it had read; MTP is
not blamed, the 65536 window is (one rep per arm; cwd, tool set and interactivity also
differed between RUN 1 and RUN 2) (docs/ROADMAP.md, ruling 14). `serve.ps1` applies the template automatically for files
under `models/qwen3.8-27b-gsq-rco` and `models/qwen3.8-27b-uncensored`; MTP is added
for the default file only at `-Ctx`
65536 or below (`-NoMtp` turns it off); without the template Claude Code
gets HTTP 500 ("System message must be at the beginning."). `claude-local.ps1` sets
Claude Code's context window to 131072 to match, and (ruling 13) starts every session
with the lean set: `--tools Bash,Read,Edit,Write,Glob,Grep,Skill`, no MCP servers and a
one-model policy appended to the system prompt (plus evidence rules and a machine-survey
checklist since 2026-10-25; 540 tokens, +388; TEST 6 loop guards add 101), hooks on;
before the loop guards a fresh session's first prompt is about 12,735 tokens from a
dir outside `Z:\repos` (12,347 measured before the policy block, plus 388; was
25,578). `-LisFull` drops the tool list and the policy and keeps the empty MCP
config (no MCP server loads). Absolute sizes vary by a few hundred
tokens with the cwd path; the reproducible figure is the saving, about 9,172 tokens
against `-LisFull` in the same cwd (9,560 before the policy block) and about 12,812
against the pre-ruling full set (13,200 before), all measured before the loop guards
(+101 tokens). Quality and refusal removal of the abliterated build are UNVERIFIED.
Numbers: [config/models.md](config/models.md),
[bench/summary-2026-10-24.md](bench/summary-2026-10-24.md).

## Quick start

```powershell
pwsh scripts/install.ps1        # llama.cpp b11868 CUDA 13.4 zip + cudart into bin/
pwsh scripts/serve.ps1          # llama-server with the default model (local file, see above)
pwsh scripts/smoke.ps1          # /health, /v1/messages tool_use, /count_tokens
pwsh scripts/claude-local.ps1   # Claude Code pointed at the local server
```

`install.ps1` fetches binaries only. The default model is a local file from the
ungated `ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF` repo and is not downloaded by any script;
it must already be in `models/qwen3.8-27b-gsq-rco/`. `install.ps1` checks each zip
against a SHA256 pinned in the script; `serve.ps1` refuses to start when
`bin/llama-server.exe` or its dll differs from its pin, or the model file from its
`models/manifest.json` entry (hashed once per boot, about 20 s for the 11.6 GB former
default file; the 10.44 GB default's time is UNVERIFIED);
see docs/SETUP.md steps 2 and 5. `-Model` also takes a Hugging Face
`repo:quant`, which `llama-server -hf` downloads on first run into its own cache (the
previous default: `-Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS -KvType q8_0`).

## Run at logon

- Register: `pwsh scripts/register-task.ps1` (task `LocalInferenceStudio-llama-server`, current user, no elevation needed); start now with `Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server`.
- Unregister: `pwsh scripts/unregister-task.ps1` (leaves a running server alone).
- Stop: `pwsh scripts/stop.ps1`. A stop stays down until the next logon or `Start-ScheduledTask`; after a llama-server crash `serve.ps1` starts it again (at most 5 times an hour). The task also runs on battery.
- Watchdog: `pwsh scripts/register-watchdog.ps1` (task `LocalInferenceStudio-watchdog`, at logon + 5 min) runs `scripts/watchdog.ps1`: polls `/health` and restarts a hung or dead server, at most 3 times an hour; log `logs/watchdog.log` ([docs/SETUP.md](docs/SETUP.md) step 7a).
- Logoff: the task runs only while you are logged on (interactive token, no stored
  password), so a logoff stops the server; it starts again at the next logon.
- Free VRAM: each start and restart logs `serve.ps1: vram free: <N> MiB` (or
  `unavailable`); the default model fills nearly the whole card, so close other GPU
  apps before a start ([docs/SETUP.md](docs/SETUP.md) step 7).
- Re-run `register-task.ps1` after moving the repo (paths are absolute).
- Log: `logs/llama-server.log` (appended, renamed to `.1` past 50 MB, ends each run with `llama-server exited <code>`; gitignored). From a shell, `serve.ps1 -LogFile <path>` does the same.
- Ollama is paused, not uninstalled: [docs/ollama-paused.md](docs/ollama-paused.md).

## Docs

- [docs/audits/2026-10-30-ledger.md](docs/audits/2026-10-30-ledger.md) — every
  2026-10-30 audit finding with owner, fix, status and proof, plus the work batches
- [docs/audits/2026-10-30-resilience.md](docs/audits/2026-10-30-resilience.md) —
  resilience audit (FAIL for unsupervised multi-hour tasks)
- [docs/audits/2026-10-30-security.md](docs/audits/2026-10-30-security.md) — security
  audit (FAIL for enabling web fetch then; web access ARMED 2026-11-05 via `-LisWeb`)
- [docs/audits/2026-10-30-trustworthiness.md](docs/audits/2026-10-30-trustworthiness.md)
  — trustworthiness audit of the ladder artifacts (FAIL for unsupervised long tasks)
- [docs/audits/2026-10-30-web-access-prep.md](docs/audits/2026-10-30-web-access-prep.md)
  (web access prep report: DISARMED then; superseded by docs/web-access.md)
- [docs/evaluation-2026-10-24.md](docs/evaluation-2026-10-24.md) — the two repos the operator asked about (both REFERENCE ONLY) and the orcarouter HF org
- [docs/landscape-2026-10-24.md](docs/landscape-2026-10-24.md) — Claude Code wiring, backends, model candidates, gotchas
- [docs/ROADMAP.md](docs/ROADMAP.md) — phases P0-P6
- [docs/start-lines.md](docs/start-lines.md) - every launch line (server, host
  profiles, web container) with its use case, pros, cons and warnings
- [docs/uploader-rule.md](docs/uploader-rule.md) — GGUF uploader per model (ruling 35)
- [docs/web-access.md](docs/web-access.md) - web read/search for the local model,
  ARMED 2026-11-05: `-LisWeb` runs the session in the lis-web container with this
  repo's own web tools over MCP (`web/`, ruling 2026-11-06, proven live the same
  day); WebFetch and WebSearch stay denied; open egress is a residual
- [web/README.md](web/README.md) - the `lis-web` stdio MCP server (five tools: Brave,
  Exa and Jina search, the Jina reader, fxtwitter), its keys from `<repo>\.env` and
  its tests (`node --test web/test/*.test.mjs`)
- [config/models.md](config/models.md) — tracked model candidates
- [config/claude-settings.json](config/claude-settings.json) — `--settings` overlay used
  by `claude-local.ps1` (model + subagent model = `local`, auto-compact window 131072,
  WebSearch, WebFetch, Agent, Workflow, the PowerShell tool and three Playwright MCP
  tools denied, rule set A: read-only allow and critical-write ask rules, ruling 15);
  the wrapper adds the `scripts/hooks/lis-guard.py` payload hook, run from a read-only
  per-run copy like the other hooks (docs/SETUP.md step 8)
  and the `scripts/verify-doc.py` PostToolUse hook, which checks the sums, file counts,
  line counts and paths in every `.md` a session writes and reports them to the model
- [scripts/verify-claims.ps1](scripts/verify-claims.ps1) — verifier pass, run by hand
  after a task: short fresh read-only local sessions check a document's claims (one
  claim per session by default) against the repo and the harness prints an honest
  count (docs/SETUP.md step 8)
- [scripts/claude-local.ps1](scripts/claude-local.ps1) task profiles
  (`-LisTask review|edit|longrun`) set the tools, policy, rules and the checks you run
  at the end; `-LisPrintArgs` prints the claude arguments and settings JSON without
  launching (docs/SETUP.md step 8)
- [scripts/web-image.ps1](scripts/web-image.ps1) - builds the `lis-web:2.1.318` image
  from `container/Dockerfile` (context: this repo, `.dockerignore` applied; it copies
  in only `web/`) that `claude-local.ps1 -LisWeb` runs web sessions in (operator-run;
  docs/web-access.md)
- [scripts/hooks/loop-guard.py](scripts/hooks/loop-guard.py) - PreToolUse hook on every
  tool that denies a call identical to 3 or more of the session's last 12 counted calls,
  the loop seen in 5 of the 8 bench/compact runs (2026-10-26), 4 of which it held until
  `--max-turns` (`-LisNoLoopGuard` drops it; docs/SETUP.md step 8)
- [bench/README.md](bench/README.md) — P3 bench result schema

## Rules

- No Ollama, no LM Studio.
- Prebuilt llama.cpp binaries only; no source builds on this machine.
- Binaries (`bin/`) and models (`models/`, `*.gguf`) live outside git.
- Scripts never pipe to a shell (`irm | iex`, `curl | bash`).
- Claims not checked on this machine are marked UNVERIFIED.
- Tests: the commands listed in [CLAUDE.md](CLAUDE.md), run from the repo root, among
  them `python -I scripts/hooks/tests/lis-guard_property_test.py`,
  `python -I scripts/tests/resilience_test.py`,
  `python -I scripts/tests/claude_settings_test.py` and
  `python -I scripts/tests/install_verify_test.py`.

## License

MIT, see [LICENSE](LICENSE).
