# Setup from zero

This guide takes a Windows 11 PC with an NVIDIA GPU from nothing to Claude Code
running against a local `llama-server` with the default model (Orca
Qwen3.8-27B-Uncensored IQ3_XXS). It uses `Z:\repos\kosm1x\local-inference-studio` as
the repo path. If you clone somewhere else, replace that path everywhere.

Run every command in PowerShell 7 (`pwsh`) from the repo root unless a step says
otherwise. Items marked UNVERIFIED were not checked on the reference machine.

## 0. Prerequisites

- Windows 11 and an NVIDIA GPU in the 16 GB class with a current driver (reference
  machine: RTX 4070 Ti SUPER 16 GB, driver 617.42; smaller cards are UNVERIFIED).
- About 15 GB of disk for the default model and 1.3 GB for `bin\` (measured).
- PowerShell 7, Git, Node.js, the Claude Code CLI, and a Hugging Face account for the
  gated default model.

Not needed: LM Studio, Ollama, the CUDA toolkit, cmake or any compiler. llama.cpp comes
from a prebuilt release zip.

```powershell
winget install Microsoft.PowerShell      # only if `pwsh` is missing
npm install -g @anthropic-ai/claude-code
nvidia-smi; git --version; node --version; claude --version
```

Success: `nvidia-smi` lists your GPU and the rest print versions. No `nvidia-smi`:
install the NVIDIA driver. No `claude` after the npm install: open a new terminal.

## 1. Clone the repo

```powershell
git clone https://github.com/kosm1x/local-inference-studio.git Z:\repos\kosm1x\local-inference-studio
Set-Location Z:\repos\kosm1x\local-inference-studio
```

Success: the folder holds `scripts\`, `config\`, `bench\` and `docs\`.

## 2. Install llama.cpp (`scripts\install.ps1`)

It downloads `llama-b11868-bin-win-cuda-13.4-x64.zip` and
`cudart-llama-bin-win-cuda-13.4-x64.zip` from the ggml-org/llama.cpp GitHub release,
checks each SHA256 against the digest the GitHub API publishes, and extracts both into
`bin\`. It creates an empty `models\` and never downloads a model.

```powershell
pwsh scripts\install.ps1 -WhatIf         # preview only
pwsh scripts\install.ps1
bin\llama-server.exe --version
```

Success: two `SHA256 OK:` lines, then `Installed: ...\bin\llama-server.exe`. The
version check prints `version: 0.7.0-dev (build 11868, commit 78a8ae14b)`. `bin\` also
holds `cudart64_13.dll`, `cublas64_13.dll` and `cublasLt64_13.dll`.

If it fails: `Could not fetch ... for SHA256 digests` means the GitHub API was
unreachable or rate-limited; wait and re-run (`-SkipVerify` skips the check, not
recommended). `-LlamaRelease` and `-Cuda` pick another release; check its asset names.

## 3. NVIDIA setting: Prefer No Sysmem Fallback

When VRAM runs out, the Windows driver can silently spill into system RAM, and the
model runs much slower with no error. With the fallback off, llama-server fails loudly
with `cudaMalloc failed: out of memory` instead. In NVIDIA Control Panel, open Manage
3D settings, Program Settings, add `Z:\repos\kosm1x\local-inference-studio\bin\llama-server.exe`,
set "CUDA - Sysmem Fallback Policy" to "Prefer No Sysmem Fallback", and Apply.

Success: an oversized context fails in seconds with an out-of-memory error. The
reference machine failed that way, but the setting itself was never read back there,
and the menu labels may differ by driver version (both UNVERIFIED).

## 4. Get the default model

The default is `Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` from the gated Hugging Face repo
`orcarouter/Qwen3.8-27B-Uncensored-GGUF`, 11,637,692,000 bytes. No script downloads it.
Accept the terms on the model page at huggingface.co, create a read token (Settings,
Access Tokens), then install the `hf` CLI and log in; it prompts for the token. Never
paste the token into a file, a commit or a chat.

```powershell
uv tool install huggingface_hub          # or: pip install -U huggingface_hub
hf auth login
hf download orcarouter/Qwen3.8-27B-Uncensored-GGUF Qwen3.8-27B-Uncensored-IQ3_XXS.gguf --local-dir models\qwen3.8-27b-uncensored
(Get-Item models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf).Length
```

Success: the last line prints `11637692000` (the reference machine's file matches).
The `hf` CLI is not installed on the reference machine, so the first three lines are
UNVERIFIED. A 401 or 403 means the terms are not accepted or the token lacks read
access. A different byte count means a partial download; run `hf download` again.

Ungated fallback: Qwen3.6-35B-A3B. `llama-server -hf` downloads it on the first start
into `%USERPROFILE%\.cache\huggingface\hub` (13.2 GB, about 5 min on the reference
machine). As for any model other than the default file, `serve.ps1` then uses q8_0 KV
and adds no chat template.

```powershell
pwsh scripts\serve.ps1 -Model 'unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS'
```

## 5. First manual start (`scripts\serve.ps1`)

Skip this step if the server is already running (after step 7 it starts at every
logon). Check first; `ok` means go straight to step 8:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health -Headers @{Authorization='Bearer local'}
```

With no parameters it serves the default file on `127.0.0.1:8080` at ctx 65536, q4_0
KV, flash attention on, one slot, `--api-key local`, model alias `local`, and (for files
under `models\qwen3.8-27b-uncensored`) `--chat-template-file config\chat-templates\qwen3.8-27b.jinja`;
for the default file only, MTP (`--spec-type draft-mtp --spec-draft-n-max 2`; `-NoMtp`
turns it off; with `-Ctx` above 65536 the flags are skipped with a warning so the model
stays all-GPU, and `-NoMtp` silences the warning).

```powershell
pwsh scripts\serve.ps1
```

It prints the full `llama-server.exe` command line, then the server log. Ready is
`server_run_i: model loaded` followed by `listening on http://127.0.0.1:8080`. On the
reference machine that took about 4 s, with the file likely in the OS cache; a cold
load from disk is UNVERIFIED. Leave the window open and check from a second one:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health -Headers @{Authorization='Bearer local'}
```

Success: `status` is `ok`. `Port 8080 is already in use` usually means the task's own
server is up (`Get-NetTCPConnection -LocalPort 8080 -State Listen` shows a
`llama-server` PID); use it and go to step 8. Otherwise see Troubleshooting.
`Model file not found`: step 4 is not done. Stop with Ctrl+C or `pwsh scripts\stop.ps1`.

## 6. Smoke test (`scripts\smoke.ps1`)

It checks `/health`, sends one `/v1/messages` request with a `get_weather` tool, and
reports `/v1/messages/count_tokens`.

```powershell
pwsh scripts\smoke.ps1
```

Success: exit code 0, `stop_reason: tool_use`, and a last line like
`PASS: tool_use get_weather {"city":"Mexico City"}`. If FAIL shows only `[thinking]`
blocks, raise the budget with `-MaxTokens 8192`. `count_tokens: unavailable` does not fail.

## 7. Run at logon (Scheduled Task)

`scripts\register-task.ps1` registers `LocalInferenceStudio-llama-server` for the
current user, no elevation. At logon it runs `pwsh -NoProfile -NonInteractive
-WindowStyle Hidden -File scripts\serve.ps1 -LogFile logs\llama-server.log` from the
repo root, on battery too, with no time limit. Its restart settings only retry a launch
that fails: after a crash or `stop.ps1` the server stays down until the next logon or
`Start-ScheduledTask`. Stop the manual server from step 5 first:

```powershell
pwsh scripts\stop.ps1
pwsh scripts\register-task.ps1 -WhatIf   # preview only
pwsh scripts\register-task.ps1
Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server
Get-ScheduledTask -TaskName LocalInferenceStudio-llama-server | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName LocalInferenceStudio-llama-server
Get-Content logs\llama-server.log -Tail 5
```

Success: State `Running`, and `/health` returns `ok` 5 to 32 s later (reference
machine). The log is appended, renamed to `.1` past 50 MB, and each run ends with
`llama-server exited <code>`. Paths in the task are absolute: re-run
`register-task.ps1` after moving the repo. Remove the task with
`pwsh scripts\unregister-task.ps1` (a running server is left alone).

## 8. Run Claude Code against it (`scripts\claude-local.ps1`)

Change to the project you want to work in, then call the wrapper by its full path:

```powershell
Set-Location <your project>
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -p "list the files in this repo"
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisContextTokens 65536
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisFull
```

For this process only, it sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`,
`ANTHROPIC_AUTH_TOKEN=local`, and `ANTHROPIC_MODEL` plus the Opus, Sonnet and Haiku
default aliases to `local`. It unsets `ANTHROPIC_API_KEY` (a real key would be sent to
the local server) and the `CLAUDE_CODE_SUBAGENT_MODEL*` variables, and passes
`--settings config\claude-settings.json` (model and subagent model `local`,
auto-compact at 65536, WebSearch, WebFetch, Agent and Workflow denied; the wrapper
passes a per-run copy in `%TEMP%` with the auto-compact value rewritten to
`-LisContextTokens`). Why: a global `~\.claude\settings.json` that pins cloud models or
a subagent model would otherwise win, and those models do not exist locally. Your
environment is restored on exit.

Lean set (ruling 13): before your arguments the wrapper adds
`--tools Bash,Read,Edit,Write,Glob,Grep,Skill` (7 tools),
`--strict-mcp-config --mcp-config <per-run empty {"mcpServers":{}} file in %TEMP%>` (no
MCP servers) and `--append-system-prompt` with a one-model policy (one local model, no
subagents, ignore cloud model-role rules, verify before destructive actions, keep
answers short; text in `docs/context-audit-2026-10-24.md` section 5; it names a
65,536-token window whatever `-LisContextTokens` says). Hooks stay on.
Measured fresh-session prompt: 12,347 tokens from a dir outside `Z:\repos`, 12,775
from this repo (was 25,578 and 26,224 to 32,988). `-LisFull` (also `-LisFull:true` /
`-LisFull:false`) omits the three additions for a session that needs the full tool set
or MCP (measured 21,908 tokens from the scratch dir; Agent and Workflow stay denied by
the settings file).

All other arguments go straight to `claude` (`-p`, `--max-turns` and so on). The two
wrapper options are `-LisContextTokens N` (default 65536, minimum 1024; set it to the
server's `-Ctx` when that is smaller) and `-LisFull`. Success: Claude Code answers and the server log
shows the requests. A `[claude-code:unrecognized_model] {"model":"local"}` line is harmless.

fnm note: if your shell profile runs `fnm env --use-on-cd`, a Bash tool command like
`cd X && node ...` fails inside Claude Code when `X` has a `package.json` ("We can't
find the necessary environment variables to replace the Node version"). Drop
`--use-on-cd` for these sessions, or run `node` without the `cd`.

## 9. Switching models

`serve.ps1` parameters: `-Model`, `-Ctx`, `-Port`, `-NCpuMoe`, `-KvType`, `-Alias`,
`-ChatTemplateFile`, `-WithMmproj`, `-ExtraArgs`, `-ExtraArgLine`, `-LogFile`.

- `-Model` is a local `.gguf` path (relative to the repo root) or a Hugging Face
  `repo:quant`, which `llama-server -hf` downloads on first run.
- KV rule: q4_0 only for the default file, q8_0 for any other `-Model`, unless you pass
  `-KvType`.
- Template rule: the Qwen3.8-27B GGUFs (Saluki, GSQ-RCO, Orca) need
  `config\chat-templates\qwen3.8-27b.jinja`, or Claude Code gets HTTP 500 "System
  message must be at the beginning." Only files under `models\qwen3.8-27b-uncensored`
  get it on their own; pass it for the others.

```powershell
pwsh scripts\stop.ps1
pwsh scripts\serve.ps1 -Model models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf -KvType q4_0
pwsh scripts\serve.ps1 -Model models\qwen3.8-27b-gsq-rco\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf -Ctx 65536 -ChatTemplateFile config\chat-templates\qwen3.8-27b.jinja
pwsh -File scripts\serve.ps1 -Model models\saluki-27b\Underdog-Saluki-27B-1.0-IQ2-mix.gguf "-ExtraArgLine:--chat-template-file Z:/repos/kosm1x/local-inference-studio/config/chat-templates/qwen3.8-27b.jinja"
```

Download a file first (names and sizes in `config\models.md`). Under `pwsh -File`, a
value that starts with `-` and contains `:` must be the single token
`"-ExtraArgLine:<value>"`, and the path must have no spaces. With a smaller `-Ctx`, pass
the same number to `claude-local.ps1 -LisContextTokens`.

The Scheduled Task: `register-task.ps1` takes no parameters, and its action passes only
`-LogFile`, so the task always serves the `serve.ps1` defaults. To change what it
serves, edit the `param()` defaults in `scripts\serve.ps1`, or add parameters to the
`-Argument` string in `register-task.ps1` and re-run it. If you change the `-Model`
default, also update `$defaultModel` in `serve.ps1`, or the KV rule falls back to q8_0.

## 10. Benchmarks

Both measure the server already running on :8080; neither starts or stops one.

```powershell
pwsh bench\run.ps1 -Label orca-iq3xxs -Quant IQ3_XXS -Ctx 131072
pwsh bench\loop\run.ps1 -Label orca-iq3xxs
```

`bench\run.ps1` writes `bench\results\<stamp>-<Label>.json` (decode, 20K prefill, 20 tool
calls, peak VRAM). `bench\loop\run.ps1` has Claude Code fix a 3-test Node fixture 3 times
and writes `bench\results\<stamp>-loop-<Label>.json` plus a `.log`, with work dirs in
`%LOCALAPPDATA%\lis-loop`. Results are gitignored. Schema: `bench\README.md`.

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Port 8080 is already in use by PID ...` | The task or another server holds the port. `pwsh scripts\stop.ps1` (refuses unless the owner is llama-server; `-Force` overrides), or serve on `-Port 8081`. |
| `/health` unreachable or not `ok` | Not started or still loading. Check `logs\llama-server.log` for `listening on` or an error. The status returned while loading is UNVERIFIED here. |
| HTTP 500 "System message must be at the beginning." | A Qwen3.8-27B GGUF without the patched template. Restart with `-ChatTemplateFile config\chat-templates\qwen3.8-27b.jinja`. |
| `cudaMalloc failed: out of memory` | Context or KV too large for free VRAM. Lower `-Ctx`, use `-KvType q4_0`, or close GPU-heavy apps; the desktop already holds 1.3 to 2.4 GB. |
| Server runs but is very slow | Possibly sysmem fallback. Redo step 3 and check `nvidia-smi` memory. |
| `[claude-code:unrecognized_model]` on stderr | Harmless warning about the model name `local`. |
| Server gone after a crash or `stop.ps1` | The task does not restart it. `Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server`. |
| `llama-server.exe not found in ...\bin` | Run step 2. |

## 12. Uninstall or revert

```powershell
pwsh scripts\unregister-task.ps1
pwsh scripts\stop.ps1
Remove-Item -Recurse -Force bin, models
```

`bin\`, `models\` and `logs\*` are gitignored, so git does not track them. Models pulled
with `-hf` live in `%USERPROFILE%\.cache\huggingface\hub`; delete them there. Ollama is
paused, not removed, on the reference machine; to turn it back on see
`docs\ollama-paused.md`.
