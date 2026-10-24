# Local Inference Studio

The most potent possible local LLM inference on this Windows 11 workstation,
consumed by the Claude Code CLI harness. No LM Studio, no Ollama.

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
Claude Code CLI
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
(2026-10-24): Claude Code runs an edit-test-fix loop on the local server. Next: Phase 3.

## Quick start

```powershell
pwsh scripts/install.ps1        # llama.cpp b11868 CUDA 13.4 zip + cudart into bin/
pwsh scripts/serve.ps1          # llama-server; -hf downloads the model on first run
pwsh scripts/smoke.ps1          # /health, /v1/messages tool_use, /count_tokens
pwsh scripts/claude-local.ps1   # Claude Code pointed at the local server
```

`install.ps1` fetches binaries only. The model (default
`unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS`) is downloaded by `llama-server -hf`
on first run into its own cache.

## Run at logon

- Register: `pwsh scripts/register-task.ps1` (task `LocalInferenceStudio-llama-server`, current user, no elevation needed); start now with `Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server`.
- Unregister: `pwsh scripts/unregister-task.ps1` (leaves a running server alone).
- Stop: `pwsh scripts/stop.ps1`. A stop or a llama-server crash stays down until the next logon or `Start-ScheduledTask`: the task's restart settings only retry a launch that fails. It also runs on battery.
- Re-run `register-task.ps1` after moving the repo (paths are absolute).
- Log: `logs/llama-server.log` (appended, renamed to `.1` past 50 MB, ends each run with `llama-server exited <code>`; gitignored). From a shell, `serve.ps1 -LogFile <path>` does the same.
- Ollama is paused, not uninstalled: [docs/ollama-paused.md](docs/ollama-paused.md).

## Docs

- [docs/evaluation-2026-10-24.md](docs/evaluation-2026-10-24.md) — the two repos the operator asked about (both REFERENCE ONLY) and the orcarouter HF org
- [docs/landscape-2026-10-24.md](docs/landscape-2026-10-24.md) — Claude Code wiring, backends, model candidates, gotchas
- [docs/ROADMAP.md](docs/ROADMAP.md) — phases P0-P6
- [config/models.md](config/models.md) — tracked model candidates
- [config/claude-settings.json](config/claude-settings.json) — `--settings` overlay used by `claude-local.ps1` (model + subagent model = `local`, auto-compact window 131072)
- [bench/README.md](bench/README.md) — P3 bench result schema

## Rules

- No Ollama, no LM Studio.
- Prebuilt llama.cpp binaries only; no source builds on this machine.
- Binaries (`bin/`) and models (`models/`, `*.gguf`) live outside git.
- Scripts never pipe to a shell (`irm | iex`, `curl | bash`).
- Claims not checked on this machine are marked UNVERIFIED.

## License

MIT, see [LICENSE](LICENSE).
