# Setup from zero

This guide takes a Windows 11 PC with an NVIDIA GPU from nothing to Claude Code
running against a local `llama-server` with the default model (RentedNoodle
Qwen3.8-27B OrcaRouter GSQ-RCO IQ3_XXS v2.1 since 2026-11-08; the fallback, the
default until then, is Orca Qwen3.8-27B-Uncensored IQ3_XXS). It uses
`Z:\repos\kosm1x\local-inference-studio` as the repo path. If you clone somewhere else,
replace that path everywhere.

Run every command in PowerShell 7 (`pwsh`) from the repo root unless a step says
otherwise. Items marked UNVERIFIED were not checked on the reference machine.

## 0. Prerequisites

- Windows 11 and an NVIDIA GPU in the 16 GB class with a current driver (reference
  machine: RTX 4070 Ti SUPER 16 GB, driver 617.42; smaller cards are UNVERIFIED).
- About 11 GB for the default model (10,382,717,184 B) and 12 GB more for the fallback
  (about 15 GB of disk measured with the fallback as the default), and 1.3 GB for
  `bin\` (measured).
- PowerShell 7, Git, Node.js, the Claude Code CLI, and a Hugging Face account for the
  gated fallback model only (the default's repo is ungated).

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
checks each SHA256 against both the digest pinned in the script (`$pinned`, taken with
`Get-FileHash` from the zips on the reference machine on 2026-10-30, which the security
audit of that day found equal to GitHub's) and the digest the GitHub API publishes (the
two must agree), and extracts both into `bin\`. Another `-LlamaRelease` or `-Cuda` has
no pin and stops until its digests are added to `$pinned`. It creates an empty
`models\` and never downloads a model.

```powershell
pwsh scripts\install.ps1 -WhatIf         # preview only
pwsh scripts\install.ps1
bin\llama-server.exe --version
```

Success: two `SHA256 OK (pinned + API):` lines, then
`Installed: ...\bin\llama-server.exe`. The version check prints
`version: 0.7.0-dev (build 11868, commit 78a8ae14b)`. `bin\` also holds
`cudart64_13.dll`, `cublas64_13.dll` and `cublasLt64_13.dll`.

If it fails: `Could not fetch ... for SHA256 digests` means the GitHub API was
unreachable or rate-limited; wait and re-run. `-SkipVerify` skips both checks, only
together with `-SkipVerifyAck` (without it the script throws before fetching anything),
and warns for each zip; not recommended. `-LlamaRelease` and `-Cuda` pick another
release; check its asset names and pin its digests first. Tests (pins, manifest, the
`-SkipVerifyAck` gate; no network): `python -I scripts/tests/install_verify_test.py`
(`--full` also hashes the default GGUF).

`$pinned` also holds the SHA256 of `llama-server.exe` and `llama-server-impl.dll` as
they are in the pinned llama zip, and the install writes the release tag to
`bin\llama-release.txt`; `serve.ps1` checks both binaries before each start (step 5).
To check a downloaded zip against its pin offline (the same check the install runs; no
network, no extract), one zip per run, since under `pwsh -File` a second path binds to
`-LlamaRelease`:

```powershell
pwsh scripts\install.ps1 -VerifyZip bin\.download\llama-b11868-bin-win-cuda-13.4-x64.zip
```

Success: `SHA256 OK (pinned): <name>`. A changed zip throws `SHA256 mismatch for <name>:
expected <pin> (pinned), got <hash>`; on 2026-11-04 a copy of the real llama zip with
one byte changed was refused this way, and both real zips passed. `-VerifyZip` checks
any file whose name has a pin for `-LlamaRelease`, so it also takes the cudart zip or a
loose `llama-server.exe`.

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

The default (since 2026-11-08 22:27, the Model test 2 ruling in `docs\ROADMAP.md`) is
`Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf` from the Hugging Face repo
`RentedNoodle/Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-Uncensored` (Apache-2.0, not
gated), 10,382,717,184 bytes. No script downloads it. Install the `hf` CLI; it needs
no login for this repo (UNVERIFIED).

```powershell
uv tool install huggingface_hub          # or: pip install -U huggingface_hub
hf download RentedNoodle/Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-Uncensored Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf --local-dir models\qwen3.8-27b-uncensored
(Get-Item models\qwen3.8-27b-uncensored\Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf).Length
```

Success: the last line prints `10382717184` (the reference machine's file matches).
The `hf` CLI is not installed on the reference machine, so the first two lines are
UNVERIFIED. A different byte count means a partial download; run `hf download` again.

The fallback (the default 2026-10-24 to 2026-11-08) is
`Qwen3.8-27B-Uncensored-IQ3_XXS.gguf` from the gated repo
`orcarouter/Qwen3.8-27B-Uncensored-GGUF`, 11,637,692,000 bytes. Accept the terms on the
model page at huggingface.co, create a read token (Settings, Access Tokens), then log
in with the `hf` CLI; it prompts for the token. Never paste the token into a file, a
commit or a chat.

```powershell
hf auth login
hf download orcarouter/Qwen3.8-27B-Uncensored-GGUF Qwen3.8-27B-Uncensored-IQ3_XXS.gguf --local-dir models\qwen3.8-27b-uncensored
(Get-Item models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf).Length
```

Success: `11637692000` (the reference machine's file matches; the first two lines are
UNVERIFIED). A 401 or 403 means the terms are not accepted or the token lacks read
access. Serve it as in step 9.

`models/manifest.json` (the one tracked file under `models\`) pins every GGUF this repo
uses: Hugging Face repo, the revision (commit) `hf download` fetched, byte size and
SHA256. On the reference machine each SHA256 was computed with `Get-FileHash` on
2026-10-30 (the default's on 2026-11-08) and equals the LFS etag `hf download` recorded in
`models\<dir>\.cache\huggingface\download\<file>.metadata`. To check the files you have
(no download; absent files are listed and skipped; a size or SHA256 mismatch throws):

```powershell
pwsh scripts\install.ps1 -VerifyModels
```

Hashing all five files took 193 s on the reference machine (2026-11-09, server running,
five OK). To fetch the
pinned revision rather than the repo's current one, add `--revision <revision>` to
`hf download` (UNVERIFIED: the `hf` CLI is not installed here). A `-hf` download by
`llama-server` is not covered by the manifest.

Ungated fallback: Qwen3.6-35B-A3B. `llama-server -hf` downloads it on the first start
into `%USERPROFILE%\.cache\huggingface\hub` (13.2 GB, about 5 min on the reference
machine). As for any model other than the default and fallback files, `serve.ps1` then
uses q8_0 KV and adds no chat template.

```powershell
pwsh scripts\serve.ps1 -Model 'unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS'
```

## 5. First manual start (`scripts\serve.ps1`)

Skip this step if the server is already running (after step 7 it starts at every
logon). Check first, from the repo root; `200` means go straight to step 8 (the key is
the first line of `logs\api-key`, which serve.ps1 writes at each start; a server started
before that uses `local`). The check uses `/slots` because `/health` answers 200 with
any key or none on b11868, so it proves only that the server is up:

```powershell
$key = "$(Get-Content logs\api-key -TotalCount 1 -ErrorAction Ignore)".Trim()
if (-not $key) { $key = 'local' }
(Invoke-WebRequest http://127.0.0.1:8080/slots -SkipHttpErrorCheck `
    -Headers @{Authorization="Bearer $key"}).StatusCode
```

With no parameters it serves the default file on `127.0.0.1:8080` at ctx 131072, q4_0
KV, flash attention on, one slot, `--api-key-file logs\api-key` (a new random key
written at each start; the scripts that call the server read that file and fall back to
`local` when it is absent), `--no-webui`, model alias `local`, server
thinking off (`--reasoning off`), and (for files under `models\qwen3.8-27b-uncensored`
and `models\qwen3.8-27b-gsq-rco`)
`--chat-template-file config\chat-templates\qwen3.8-27b.jinja`; no MTP (ruling 14; the
default's MTP head is present but UNVERIFIED here, so it never gets MTP).
Thinking off is the default by operator ruling of 2026-10-26: the compaction bench got
a real summary on every compaction request only with it off (3 of 3, against 2 of 4
with it on; one run each, n=1). `-Reasoning on` forces thinking on; `-Reasoning auto`
is the server's own default (detect from the template), which is what `serve.ps1` ran
before this flag. `--reasoning off` replaces the older form
`--chat-template-kwargs '{"enable_thinking": false}'`, which the server log calls
deprecated; on b11868 both render the same closed, empty think block for the assistant
turn (the `/apply-template` check at the end of this section). The effect on output is
measured only under the older form (one compaction run and ladder test 1).
MTP (`--spec-type draft-mtp --spec-draft-n-max 2`) is added for the fallback file only
(measured there, Phase 3e) at `-Ctx 65536` or below (`-NoMtp` turns it off); an
explicit `-Ctx` above 65536 skips the flags with a warning so the model stays all-GPU,
and `-NoMtp` silences the warning.

```powershell
pwsh scripts\serve.ps1
```

It prints the full `llama-server.exe` command line, then the server log. Ready is
`server_run_i: model loaded` followed by `listening on http://127.0.0.1:8080`. On the
reference machine that took about 4 s, with the file likely in the OS cache; a cold
load from disk is UNVERIFIED. Leave the window open and check from a second one, in the
repo root:

```powershell
$key = "$(Get-Content logs\api-key -TotalCount 1 -ErrorAction Ignore)".Trim()
if (-not $key) { $key = 'local' }
(Invoke-WebRequest http://127.0.0.1:8080/slots -SkipHttpErrorCheck `
    -Headers @{Authorization="Bearer $key"}).StatusCode
```

Success: `200` (`401` means the key is wrong). `Port 8080 is already in use` usually
means the task's own
server is up (`Get-NetTCPConnection -LocalPort 8080 -State Listen` shows a
`llama-server` PID); use it and go to step 8. Otherwise see Troubleshooting.
`Model file not found`: step 4 is not done. Stop with Ctrl+C or `pwsh scripts\stop.ps1`.

**Start checks.** Before it writes the key file, `serve.ps1` hashes
`bin\llama-server.exe` and `bin\llama-server-impl.dll` (the exe is a 9 KB loader for
the dll) against the pins next to the zip digests in `scripts\install.ps1`, for the
release in `bin\llama-release.txt` (written by `install.ps1`; without that file, the
pinned release the exe matches). A mismatch, or an exe that matches no pin while that
file is absent, refuses the start and prints both hashes, and so does a missing
`install.ps1` or a `$pinned` that does not read as a table of constants. A release
with no exe pin, or a pinned release with no pin for the dll, warns and starts, so an
upgrade is not blocked (add its hashes to `$pinned` after checking them). Other DLLs
(`llama.dll`, `llama-common.dll`, the ggml and CUDA DLLs) are not checked. Then it
hashes the model file against
`models\manifest.json` (`-ModelManifest` names another), at most once per boot: the
first start after a boot pays the hash, 20 s for the fallback 11.6 GB file on the
reference machine (cold; 8.9 s when the file was in the OS cache; 2026-11-04), and
writes `logs\model-verify.json` (boot time, path, size, mtime, SHA256). The checks run
once per `serve.ps1` run, before its restart loop, so a relaunch after a crash never
rehashes, and a later `serve.ps1` in the same boot (the watchdog's, or a manual
restart) takes the marker. A size or SHA256 mismatch refuses the start with both
values; a file not in the manifest, or an `-hf` model, warns and starts. A shutdown
with Windows Fast Startup may keep the boot time (UNVERIFIED); such a start takes the
marker while size and mtime match. When the boot time cannot be read, the file is
hashed and no marker is written. The marker saves time; it is not a seal: whoever can
replace the GGUF can also rewrite `logs\model-verify.json` (same user, same rights).
`-SkipModelVerify` skips the model hash in an emergency and logs `WARNING model hash
check skipped (-SkipModelVerify)`. A check that throws refuses the start with its
message, in `-LogFile` too. A `stop.ps1` while the checks run (the hash can take 20 s)
is honoured: `serve.ps1` logs `not starting: [stop.ps1] stop requested ...` and exits
0 without starting the server; a stop request from before the run is deleted, as
before. A `stop.ps1` after the checks, while the model loads (nothing listens on the
port yet), leaves the server running until it exits and then prevents the restart (as
before these checks). `-VerifyOnly` runs both checks and exits (0 = pass); `-PrintArgs`
prints the `llama-server.exe` command line and exits. Neither takes the port
mutex, checks the port, writes the key, deletes a stop request, rotates or appends to
`-LogFile` (their lines go to the console) or starts a server; `-VerifyOnly` writes
only `logs\` and `logs\model-verify.json` (when the hash runs and matches),
`-PrintArgs` nothing. Both are safe while the server runs:

```powershell
pwsh scripts\serve.ps1 -VerifyOnly
pwsh scripts\serve.ps1 -Web -PrintArgs
```

On 2026-11-04, with the server up, `-VerifyOnly` printed `llama-server binaries match
the b11868 pins (llama-server.exe, llama-server-impl.dll)` and `model sha256 matches
... (8.9 s)`, and a second run printed `model sha256 verified earlier this boot`. A
real start through these checks is UNVERIFIED until the next operator start.

`-Web` is the server half of a web session (`docs\web-access.md`; web access is ARMED
since 2026-11-05 through `claude-local.ps1 -LisWeb`, which does not start the server,
so `-Web` applies only to a server started with it): it passes `-lv 3` (info, the
server's default threshold), clears
`LLAMA_ARG_LOG_VERBOSITY` and refuses `-v`, `--verbose`, `--log-verbose` and any `-lv`,
`--verbosity` or `--log-verbosity` above 3 in `-ExtraArgs` or `-ExtraArgLine`: levels 4
(trace) and 5 (debug) may log request bodies (UNVERIFIED).

**Launching by hand.** The scripts need PowerShell 7 (`#Requires -Version 7.0`);
Windows PowerShell 5.1 refuses them with a `#requires` error. Start `pwsh` first and
only then paste the launch line: a paste that begins with `pwsh` followed by more lines
loses those lines to the shell switch (seen by the operator, not reproduced). Use
absolute paths: a relative `-LogFile` resolves against the current filesystem
location, a relative `-Model` or `-ChatTemplateFile` against the repo root. With
`-LogFile` the console shows nothing, because all llama-server output goes to the log:
look for `model loaded` in `logs\llama-server.log`. Thinking is off by default, so the
launch line needs no extra argument. From inside `pwsh`:

```powershell
& Z:\repos\kosm1x\local-inference-studio\scripts\serve.ps1 -LogFile Z:\repos\kosm1x\local-inference-studio\logs\llama-server.log
```

The same from another shell:

```powershell
pwsh -File Z:\repos\kosm1x\local-inference-studio\scripts\serve.ps1 -LogFile Z:\repos\kosm1x\local-inference-studio\logs\llama-server.log
```

Add `-Reasoning on` to either line for thinking on. `--reasoning` is placed before
`-ExtraArgs` and `-ExtraArgLine`, so a `--reasoning` or `--chat-template-kwargs` passed
there also reaches llama-server, after the default; which of two such flags the server
honours is UNVERIFIED, so use `-Reasoning` rather than passing the flag twice.
`pwsh -File` collapses `-ExtraArgs 'a','b'` into one string, so from `-File` use
`-ExtraArgLine`. `pwsh -File` reads an argument that starts with `-` and contains `:`
as `-name:value`, so a value that starts with `-` and contains `:` needs the colon
form (`-ExtraArgLine '-lv 4'` binds without it); write each argument in it without
spaces, since the line is split on whitespace. The older thinking-off form follows
both rules; the server calls it deprecated, and compaction run 9 and ladder test 1
(docs/ROADMAP.md) ran with it (server start 11:02 local, 2026-10-26). Under today's
default the line below adds the kwarg on top of `--reasoning off`. Adding `-Reasoning
auto` comes closer to run 9's settings but does not reproduce them: `serve.ps1` always
emits the flag, so it gives an explicit `--reasoning auto` where run 9's line had no
`--reasoning` flag; that `auto` is the server default rests on the b11868 `--help`
text alone (`default: 'auto' (detect from template)`); whether explicit `auto` plus
the kwarg behaves like run 9's line is UNVERIFIED; and the server command line, and
so a ladder `rep_key`, differs from run 9's. The ladder's long-fix preflight refuses a
line whose last `--reasoning` value is `auto`, and one whose last value is `off` with
an `"enable_thinking": true` beside it (`bench/ladder/README.md`, step 1).

```powershell
pwsh -File Z:\repos\kosm1x\local-inference-studio\scripts\serve.ps1 '-ExtraArgLine:--chat-template-kwargs {"enable_thinking":false}' -LogFile Z:\repos\kosm1x\local-inference-studio\logs\llama-server.log
```

**Checking thinking off.** Once `/health` returns `ok`, render a one-message prompt
through the server's chat template (from the repo root):

```powershell
$key = "$(Get-Content logs\api-key -TotalCount 1 -ErrorAction Ignore)".Trim()
if (-not $key) { $key = 'local' }
(Invoke-RestMethod -Method Post http://127.0.0.1:8080/apply-template `
    -Headers @{Authorization="Bearer $key"} -ContentType 'application/json' `
    -Body '{"messages":[{"role":"user","content":"hi"}]}').prompt
```

With thinking off the prompt ends with the assistant turn and a closed, empty think
block (seen 2026-10-26 on b11868 after the 12:22 local restart with `--reasoning off`,
the same as with the older kwarg):

```text
<|im_start|>assistant
<think>

</think>

```

With thinking on the assistant turn ends with an open `<think>` and a newline instead
(`config/chat-templates/qwen3.8-27b.jinja`, the `add_generation_prompt` block).

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
repo root, on battery too, with no time limit. Its restart settings retry a launch that
fails (3 times, 1 minute apart). After a llama-server crash serve.ps1 starts it again
(10, 30, 60, 120, then 300 s later, at most 5 times an hour); after `stop.ps1` the
server stays down until the next logon or `Start-ScheduledTask`. Once the process has
exited, `stop.ps1` also appends `[stop.ps1] stopped PID <pid> (llama-server) <time>` to
the log (`stop timed out PID <pid> <time>` after 30 s): the record that the stop
completed, next to the `stop requested` marker that serve.ps1 quotes after the exit
line. The log is held by serve.ps1's own pwsh (its `*>>` redirect; measured 2026-11-05:
with the wrapper stopped and its child still running, an append succeeds), so a stop
while serve.ps1 is gone gets both lines directly; under the scheduled task neither
append lands (live 2026-11-06 22:14:58: exit line, then the quoted `stop requested`
marker, no `stopped PID` line), and the exit line followed by `not restarting:
[stop.ps1] stop requested` is the completion record. Stop the manual server from
step 5 first:

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

Free VRAM: before each start and each restart serve.ps1 logs `serve.ps1: vram free: <N>
MiB` (nvidia-smi `memory.free`, one value per GPU), or `serve.ps1: vram free:
unavailable` when nvidia-smi is missing, fails or hangs past 10 s; the start goes on
either way. The default model fills nearly the whole card (14,301 to 14,736 of 16,376
MiB in use idle after load across two starts on 2026-11-08, nvidia-smi read in the
session; bench VRAM peak 14,465 MB the same night; the fallback left 858 MiB of
16,376 free with it loaded in the resilience audit of 2026-10-30; about 1 GB free with
the server idle on 2026-11-04, 688 MiB while a rep ran), so close other GPU apps
(games, video tools, browsers with GPU acceleration) before a start: a reload after a
crash can fail when another app took the memory meanwhile. A low figure on the line
before a failed start points there.

### 7a. Register the watchdog (operator)

`scripts\register-watchdog.ps1` registers `LocalInferenceStudio-watchdog` for the
current user, at logon plus 5 minutes. It runs `scripts\watchdog.ps1`, which polls
`/health` every 60 s and after 3 failed polls runs `stop.ps1` and starts the server task
again, at most 3 times an hour. It pauses while an operator's stop request
(`logs\.stop-requested-8080`, written by `stop.ps1`) exists. Log: `logs\watchdog.log`.
Combined bound: each watchdog restart is a new serve.ps1 with its own 1 + 5 starts, so a
crash-looping server is started about 18 times an hour at most (24 in the first hour,
counting the logon start), assuming the task's RestartCount does not fire on a non-zero
exit (UNVERIFIED). The task stores absolute paths: re-run the script after moving the
repo.

```powershell
pwsh -NoProfile -File "<repo>\scripts\register-watchdog.ps1" -WhatIf   # preview only
pwsh -NoProfile -File "<repo>\scripts\register-watchdog.ps1"
```

After a restart (by the watchdog or any other start), prove from the repo root that the
server takes the new key, refuses `local` and serves no web UI; expect `200 401 nonHTML`
(`/health` is no proof: it answers 200 with any key or none on b11868):

```powershell
$k = (Get-Content logs\api-key -TotalCount 1).Trim(); $u = 'http://127.0.0.1:8080'
$s = { param($t) (Invoke-WebRequest "$u/slots" -SkipHttpErrorCheck `
    -Headers @{Authorization="Bearer $t"}).StatusCode }
$h = if ((Invoke-WebRequest "$u/" -SkipHttpErrorCheck).Content -match '<html') {
    'HTML' } else { 'nonHTML' }
"$(& $s $k) $(& $s 'local') $h"
```

During a long run, poll the slot and the metrics from a second window, from the repo
root. serve.ps1 passes `--metrics` (Prometheus text format; the b11868 `--help` says
"enable prometheus compatible metrics endpoint (default: disabled)"), and both endpoints
need the per-start key. Expect `200` and `401` for the two status codes. Both are
UNVERIFIED until the first start with `--metrics`, as are the metric names (llama.cpp
prefixes them `llamacpp:`, for example `llamacpp:requests_processing` and
`llamacpp:requests_deferred` for queue depth):

```powershell
$k = (Get-Content logs\api-key -TotalCount 1).Trim(); $u = 'http://127.0.0.1:8080'
$a = @{Authorization="Bearer $k"}
Invoke-RestMethod "$u/slots" -Headers $a | ConvertTo-Json -Depth 4
$m = (Invoke-WebRequest "$u/metrics" -Headers $a).Content
$m -split "`n" | Select-String '^llamacpp:'
"$((Invoke-WebRequest "$u/metrics" -Headers $a -SkipHttpErrorCheck).StatusCode) " +
    "$((Invoke-WebRequest "$u/metrics" -SkipHttpErrorCheck).StatusCode)"
```

Repeat it every few minutes while the run goes.

## 8. Run Claude Code against it (`scripts\claude-local.ps1`)

Change to the project you want to work in, then call the wrapper by its full path:

```powershell
Set-Location <your project>
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -p "list the files in this repo"
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisContextTokens 65536   # only with serve.ps1 -Ctx 65536
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisFull
```

For this process only, it sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`,
`ANTHROPIC_AUTH_TOKEN` to the first line of `logs\api-key` (`local` when that file is
absent), and `ANTHROPIC_MODEL` plus the Opus, Sonnet and Haiku
default aliases to `local`. It unsets `ANTHROPIC_API_KEY` (a real key would be sent to
the local server) and the `CLAUDE_CODE_SUBAGENT_MODEL*` variables, and passes
`--settings config\claude-settings.json` (model and subagent model `local`,
auto-compact at 114688, WebSearch, WebFetch, Agent, Workflow, the PowerShell tool and
three Playwright MCP tools denied; the wrapper passes a per-run copy in `%TEMP%` with
the auto-compact value rewritten to `-LisContextTokens`). Why: a global
`~\.claude\settings.json` that pins cloud models or
a subagent model would otherwise win, and those models do not exist locally. Your
environment is restored on exit.

Lean set (ruling 13): before your arguments the wrapper adds
`--tools Bash,Read,Edit,Write,Glob,Grep,Skill` (7 tools),
`--strict-mcp-config --mcp-config <per-run empty {"mcpServers":{}} file in %TEMP%>` (no
MCP servers) and `--append-system-prompt` with a one-model policy (one local model, no
subagents, ignore cloud model-role rules, verify before destructive actions, keep
answers short; text in `docs/context-audit-2026-10-24.md` section 5, which still names
the 65,536 window of the time; the wrapper's copy names a 131,072-token window whatever
`-LisContextTokens` says), followed by an evidence and machine-survey block (numbers come
from tool output, read a script before citing it, no silenced stderr, single-quoted
PowerShell payloads in Bash, a survey checklist; was 152, +388 on the prompt) and the
TEST 6 loop guards (plain reads in parallel but at most one command per Bash batch that
executes, writes or changes state, one retry after a permission-check timeout, no
checks the task does not need, line ranges for files over 300 lines; 101 tokens, not in
the prompt figures below); 641 tokens in all, 540 before the loop guards; the text is
`$policy` in the wrapper. Hooks stay on.
Fresh-session prompt: about 12,735 tokens from a dir outside `Z:\repos` and about 13,163
from this repo (measured 12,347 and 12,775 before the 2026-10-25 policy block, plus 388;
was 25,578 and 26,224 to 32,988). `-LisFull` (also `-LisFull:true` /
`-LisFull:false`) omits the tool list and the policy for a session that needs the full
tool set (measured 21,908 tokens from the scratch dir; Agent and Workflow stay denied by
the settings file). Since 2026-11-04 it keeps `--strict-mcp-config` with the empty MCP
file (ledger S-B5 audit C2): without it, the `.mcp.json` above this repo and servers
enabled in user settings load with no flag. The 21,908 figure predates that change and
is not re-measured. The only MCP routes are `-LisWeb` (one server, lis-web, below)
and an explicit `--mcp-config` without `-LisFull` or `-LisWeb` (web path C). Absolute
sizes vary by a few hundred tokens with the cwd path and
environment text; the reproducible figure is the lean saving, about 9,172 tokens against
`-LisFull` in the same cwd and about 12,812 against the pre-ruling full set (9,560 and
13,200 before the 2026-10-25 policy block), all measured before the loop guards (+101
tokens).

What a lean session cannot do (`-LisFull` restores these tools, nothing else; no MCP):

- task tracking (TodoWrite / Task* tools), NotebookEdit, LSP, Monitor, reading the output
  of a background Bash command, AskUserQuestion, ToolSearch;
- plan mode (EnterPlanMode / ExitPlanMode; interactive behaviour UNVERIFIED);
- WebFetch and WebSearch (denied by the settings file in every local session). WebSearch
  is an Anthropic server-side tool that llama-server cannot serve. WebFetch fetches
  and converts the page in Claude Code, then runs the prompt over it in a separate
  model call; only the hostname goes to api.anthropic.com (the domain preflight).
  Where that extraction call goes (the configured local endpoint) is UNVERIFIED: the
  docs do not say. The deny stays; web sessions read pages through the lis-web
  MCP tools instead (`-LisWeb`, below; [web-access.md](web-access.md)).

Agent and Workflow are denied in EVERY local session, `-LisFull` included, so skills that
delegate to subagents (`/ship-it`, multi-round-audit, code-review, the `/diagnose` ->
`/sweep` fan-out) cannot run as written locally. A `--tools` or `--append-system-prompt`
you pass yourself lands after the wrapper's; which one wins is UNVERIFIED, so pass
`-LisFull` instead of overriding `--tools`.

The PowerShell tool is denied by name in every local session, `-LisFull` included
(ledger S-B5): lis-guard judges Bash commands only, so a PowerShell tool call had no
hook. A bare tool name in `deny` removes the tool from the model's context (Claude Code
permissions docs, read 2026-11-04; not observed in a local session). Run PowerShell
through Bash (`pwsh -NoProfile -Command '...'`), where lis-guard parses the payload.
Three Playwright MCP tools are denied the same way in every session (ledger W-5):
`mcp__playwright__browser_evaluate`, `mcp__playwright__browser_run_code_unsafe` and
`mcp__playwright__browser_file_upload` (page and Node code, file upload; web path C),
and the same three tool names on any server: `mcp__*__browser_evaluate`,
`mcp__*__browser_run_code_unsafe`, `mcp__*__browser_file_upload` (a plugin's server is
named `mcp__plugin_<plugin>_<server>__*`). The permissions docs (read 2026-11-04) say
deny rules accept glob patterns in the tool-name position that must match the full
tool name (`"mcp__*"` matches every MCP tool); that the `mcp__*__<tool>` form matches a
plugin server's tool is UNVERIFIED in a session, so both forms stay.

`-LisFull` refuses web access (ledger S-B5): with `-LisWeb`, any `--mcp-config` (web
path C loads Playwright that way, and the wrapper cannot tell which server reaches the
web) or an `--allowedTools`/`--allowed-tools` value naming WebFetch, WebSearch or an MCP
tool (`mcp__`), the wrapper throws before it prints or launches anything. A prompt is
not checked. A web run uses the lean set.

**Web sessions (`-LisWeb`, built 2026-11-05).** Operator rulings 2026-11-05: web access
goes through web tools over a stdio MCP server, and web sessions run in a container
with no access to the user profile; ruling 2026-11-06: the tools are this repo's own,
the `lis-web` server in `web/` (plain ESM JavaScript, ported from Jarvis's web tools),
independent of the Jarvis checkout ([web-access.md](web-access.md) has the rulings,
the mounts, the proof and the residuals). On the host `-LisWeb` never starts
claude: it runs `docker run --rm --init` of the `lis-web:2.1.318` image
(`container/Dockerfile`, built by the operator with `pwsh -NoProfile -File
scripts\web-image.ps1`) with `--cap-drop ALL`, `no-new-privileges`, `--pids-limit 512`,
`--memory 6g`, user `lis` and these mounts only: this repo read-only at `/lis`; when
`<repo>\.env` exists, a zero-byte per-run file read-only over `/lis/.env`, so the repo
mount never shows it; a per-run `logs\web-<stamp>-<pid>\logs\` read-write at
`/lis/logs`; a fresh per-run home at `/home/lis`; the current directory read-write at
`/work`. Neither `<repo>\.env` nor `logs\api-key` is visible inside. It refuses a work
directory inside or above the user profile or this repo, and a missing image (naming
the build line). Mount sources must be real paths; junctions and subst drives are
refused. It runs docker under try/finally and force-removes
`lis-web-<stamp>` on exit, so killing the wrapper leaves no web-enabled container
running. Without `-LisTerminal` it passes `-i` only when stdin is piped and never `-t`
(a `-p` run). Terminal mode (built 2026-11-06): `pwsh -NoProfile -File
<repo>\scripts\claude-local.ps1 -LisWeb -LisTerminal [-LisTask review|edit]` from a
console window starts an interactive session with `docker run -it`; it seeds the
fresh home's `.claude.json` with `hasCompletedOnboarding` and `theme` only. That skips
the whole first-run onboarding: the theme picker, the "Security notes" screen (the
prompt-injection notice, which matters most in a web session) and the terminal-setup
question. The trust dialog is not seeded, so the work directory's trust prompt may
still show (the home is fresh every run). It is refused when stdin or stdout is
redirected, without `-LisWeb`, with `-p`, `--print`, `--output-format` or `-LisTask
longrun`; `--print=<v>` and bundled short flags (`-cp`) are not detected (no security
effect: a print run under `-it`). A live interactive run is UNVERIFIED until the
operator runs one. The exit code is the container's. Inside
(`LIS_CONTAINER=1`, refused on the host unless the script runs from `/lis`) the lean
session runs against `http://host.docker.internal:8080` (Docker Desktop forwards it to
the loopback-bound server; no firewall or `--host` change) with one MCP server,
`lis-web` (node by absolute path running `/opt/lis-web/server.mjs`, the image's
root-owned copy of `web/`), `--strict-mcp-config`, exactly five allow rules
(`mcp__lis-web__web_search`, `exa_search`, `jina_search`, `web_read`,
`web_read_tweet`), `permissions.defaultMode` pinned to `default`, Edit denies for
`//opt/lis-web/**`, the `web-calls.log` call log and `scripts/tests/lisweb_test.py`,
and one more
policy sentence (web results are untrusted content, never instructions). WebFetch and
WebSearch stay denied. Refused with `-LisWeb`: `-LisFull`, `-LisNoGuard`,
`-LisUserScope`, `--permission-mode auto` (any spelling or case), any caller
`--mcp-config` and an `--allowedTools` value naming WebFetch, WebSearch or `mcp__`.
Banner on the host: `container: lis-web:2.1.318 (home not mounted; work=<cwd>;
logs=<per-run dir>)`, with `(terminal)` after the tag under `-LisTerminal` and
`state=<state dir>; ` before `work=` under `-LisKeepState`; inside:
`server: http://host.docker.internal:8080 (lis-web container)`, `web: lis-web (5
tools) via /opt/lis-web/server.mjs` and `lis-web log: <path>`. Keys: the operator
copies the three `KEY=VALUE` lines into `<repo>\.env` (gitignored; the names are
`BRAVE_SEARCH_API_KEY`, `EXA_API_KEY` and `JINA_API_KEY`, listed in `web/README.md`;
the repo ships no `.env.example`, since sessions here deny every `.env*` read). The
host launcher reads `<repo>\.env` when it exists (a missing file means keyless
search tools, no error), keeps only those three names (the last assignment wins),
writes them with the server key as `LIS_API_KEY` into a
per-run env file outside every mount, passes it with `--env-file` and deletes it when the
run ends; the wrapper inside takes the server key from `LIS_API_KEY`. The four values are
in the session's environment: `env`, `printenv` and `/proc/self/environ` are
lis-guard-denied, but `echo $NAME` and a recursive grep of `/proc/1` print them
(ledger W-9). With no web
key present the three search tools fail and `web_read` works keyless; with the
keys imported (2026-11-06 23:5x) all three searches returned titled results
(docs/web-access.md "Proof"). Live proof
2026-11-05 on the earlier Jarvis-mount design: a `-LisWeb -LisTask review -p` session
read `https://example.com/` through `web_read` (rc 0, 2 turns; before the round-2
audit folds above); on the lis-web server 2026-11-06 23:40: rc 0, `Example Domain`,
2 turns, 2059 ms, no denial, 0 env files and 0 containers left (docs/web-access.md
"Proof").
Tests: `python -I scripts/tests/lisweb_test.py` and `node --test web/test/*.test.mjs`
(needs `npm ci --prefix web` once). Residuals: egress from
the container is open (ledger W-8); the keys share the session's environment (W-9).

Permissions (ruling 15: only writes and deletes of critical files block or ask; the rest
runs). Measured in `docs/permissions-assessment-plan-2026-10-25.md` section 0a.

- Rule set A, in `config/claude-settings.json` `permissions`. `allow`: read-only prefixes
  for host inspection, versions, service state and repo reads, e.g. `Bash(nvidia-smi
  -L*)`. No settings rule allows a PowerShell `-Command` payload except the exact
  `$PSVersionTable` check: a prefix rule allowed `Get-Volume; & ./x.ps1` (audit A3,
  2026-10-30), so the 24 survey prefixes were dropped and the hook allows the survey's
  `Get-Volume` and `Get-CimInstance` reads by parsing the payload. No settings rule
  allows `git -C <path> ...` or `git branch --show-current` either (ledger S-B8): the
  hook allows their read-only forms by parsing them. The matcher sees the
  raw command string, and every `;` / `&&` / `|` segment of a command must match. An
  allowed command skips the auto-mode classifier (about 60 s per decision on the local
  model). Sixteen exact rules run tests: thirteen run this repo's tests from its root,
  `Bash(python -I scripts/hooks/tests/lis-guard_test.py)`,
  `Bash(python -I scripts/hooks/tests/lis-guard_property_test.py)` (exact: its `--hook`
  option runs any Python file),
  `Bash(python -I scripts/hooks/tests/loop-guard_test.py)`,
  `Bash(python -I scripts/hooks/tests/facts-inject_test.py)`,
  `Bash(python -I bench/ladder/tests/grade_test.py)`,
  `Bash(python -I bench/ladder/tests/gen_longfix_test.py)`,
  `Bash(python -I bench/ladder/tests/longrun_test.py)`,
  `Bash(python -I scripts/tests/verify-doc_test.py)`,
  `Bash(python -I scripts/tests/verify_claims_report_test.py)`,
  `Bash(python -I scripts/tests/claude_settings_test.py)`,
  `Bash(python -I scripts/tests/install_verify_test.py)`,
  `Bash(python -I scripts/tests/resilience_test.py)` and
  `Bash(node --test bench/loop/fixture/test/text.test.js)` (TEST 6 in docs/ROADMAP.md),
  and three run a generated fixture's tests from a `bench/ladder` work tree
  (`bench/ladder/README.md`): `Bash(node --test longfix/test/all.test.js)`, the
  long-fix series 1 to 3 command, kept for that key, one exact rule for the current
  long-fix test command (`$longCmd` in `bench/ladder/run.ps1`), and
  `Bash(node --test tallyctl/test/all.test.js)` for the rung 3 stale-figure fixture;
  their paths are relative, so the rules match in any cwd that holds such a file. An
  exact rule stays in auto mode; a wildcard after `node` or `python` is dropped. An
  exact rule trusts the file it names: neither the hook nor the classifier scans that
  file, so editing one of the thirteen test files or `longfix/reporter.mjs` (the long-fix
  rule also trusts and executes the reporter) changes what its rule allows.
  `ask`: `Edit(...)` rules for the critical paths
  (`~/.claude`, `~/.ssh`, `.curlrc`/`_curlrc`, Windows, Program Files,
  ProgramData, `.env*`, `*.pem`, `*.key`, `token`, `.git` internals; `Edit` also governs
  Write; the wrapper rewrites `Edit(~/...)` to the `//c/Users/<name>/...` form at run
  time; UNVERIFIED: a user name containing a space is not quoted in that rewrite, so such
  a path may not match and was not tested on this machine) and Bash shapes for history
  rewrite (`git push --force`, `reset --hard`, `clean`, `rebase`, `branch -D`), disks,
  registry, services, scheduled tasks, `wsl --unregister|--import` and Docker deletes,
  plus `Bash(powershell *Remove-Item*)`-style rules (with `powershell.exe`/`pwsh.exe`
  variants) that see inside a payload. `git branch` is allowed only by its read-only
  forms (`--list*`, and exactly `-a`, `-vv` and bare; `--show-current` through the
  hook, ledger S-B8): `git branch -a*` and `-vv*` approved ref writes the hook leaves
  undecided (`git branch -a -m keepme renamed` renamed the branch in a scratch repo,
  audit 2026-11-05; `-vv -M`, `-a -c`, `--set-upstream-to=`, `--edit-description`
  too). `--list*` stays: git rejects `--list -m` and `--list -c`. `curl` and `wmic`
  have no allow rule (the hook allows a read-only `curl` to the local server and
  `wmic <alias> get|list`, and gives no decision on the rest).
  `date`, `nvidia-smi` and `hostname` are allowed only as `date`, `date +*`,
  `nvidia-smi`, `nvidia-smi --query-*`, `nvidia-smi -L*`, `nvidia-smi -q*` and a bare
  `hostname`, so `date -s`, `nvidia-smi -pl` and `hostname <name>` match no allow rule.
  The ask rules `Bash(nvidia-smi * -f*)`, `Bash(nvidia-smi *--filename*)`,
  `Bash(nvidia-smi * -l*)`, `Bash(nvidia-smi *--loop*)` and `Bash(date +* -*)` cover the
  `-f`/`-l` flags and post-format `date` flags those allow prefixes would otherwise
  admit; in `-p` they are denials (LIVE-UNVERIFIED, V14-class).
  Curl has no allow rule: a read-only curl to the local server runs on the hook's allow
  alone, and with `-LisNoGuard` every curl that no rule decides goes to the classifier.
  A user-level allow such as `Bash(curl:*)` in `~/.claude/settings.json` still applies
  when user settings load (`-LisFull` or `-LisUserScope`; off by default since ledger
  S-O3, below): on a machine that has one, any curl that no
  ask rule matches runs with or without the hook (VERIFIED 2026-10-25: with the hook on,
  `curl -sS .../health -so out.txt` ran through that rule). Curl file-writing and config
  flags ask: `Bash(curl * -o*)`, `* -O*`, `*--output*`, `*--remote-name*`, `* -D*`,
  `*--dump-header*`, `*--cookie-jar*`, `*--trace*`, `*%output*`, `*--stderr*`,
  `*--libcurl*`, `* -K*`, `*--config*`, `*--etag-save*`, `*--hsts*`, `*--alt-svc*`,
  `*@*` (a second URL with `user@`, `-d @file`, `-F f=@file`, `-w @-`), `* -T*`,
  `*--upload-file*`, `* -c*` (also `-cj`), `* -w*`, `*--write-out*`, `* -X*`, `* -d*`,
  `*--data*`, `*--json*`; `curl -sS .../health -o /dev/null` is a `-p` denial. Rules
  match per pipeline segment and case-sensitively (VERIFIED live 2026-10-25: `-d '...'`
  does not trip `-D*`), and the policy command `curl -sS .../props ... | grep -o ...`
  runs with no denial and no classifier call on the hook's allow. An ask rule wins over
  a hook allow (VERIFIED: `curl -sS .../health -X GET` is a `-p` denial although
  lis-guard allows it), so `-X GET` asks, and `--trace*` asks for the harmless
  `--trace-time`. No `-w`/`--write-out` is auto-allowed. The hook denies a curl file
  argument (`-o`, `-c`, `-D`, `-K`, `-T`, `-b`, `-E`, bundled or long form) or `-w`
  value holding `? * [ { } $ #` or a backtick, critical target or not, because the shell
  (or curl, which replaces `#N` in an output name with a URL-glob match) rewrites it
  after the hook reads it; that deny beats a user-level allow and covers every `-w
  '%{...}'` format (VERIFIED live 2026-10-25: `-so <dir>/.cl?ude/x` denied, nothing
  written). With `-O`/`--remote-name[-all]` or `-J`/`--remote-header-name` (bundled
  `-sSO`, `-OJ` included) it denies a URL holding `{` or `[` and a URL whose last path
  segment is a critical name (`.env`, `.curlrc`, `token`, `*.pem`; VERIFIED live: `-sSO
  .../.env` denied, no file); any other `-O` gets no decision, so a bundled `-sO` to a
  plain name runs under a user-level `Bash(curl:*)`, the ruling-15 non-critical residual
  (UNVERIFIED live for `-sO`; the `-so` case above is VERIFIED). Any shell expansion in a
  Bash segment gets no hook allow, and the rules or the classifier decide (critical denies
  still fire first). That covers a `$` or backtick anywhere, quoted or not and assignments
  included, plus an unquoted `{`, `}`, `*`, `?`, `[`, `]`, and an unquoted `~` at word
  start or after `=` or `:` (single-quoted or backslash-escaped characters are literal;
  inside double quotes only `$` and backtick expand). The shell rewrites such a segment
  after the hook reads it: `curl URL/$(printf 'a %so F' -)` word-splits into `-o F`,
  `find D "$(printf -- -delete)"` and `find D -{delete,delete}` pass a flag, `find X *`
  passes any file named `-delete`, `X=${Y@P}` runs a command, and `` echo "`touch F`" ``
  runs one inside double quotes (VERIFIED live 2026-10-25 for the `curl`, both `find` and
  the backtick shapes: hook no decision, Claude Code did not rule-allow them even under a
  user-level `Bash(find:*)`, the classifier timed out and denied, nothing written or
  deleted). Quote a glob or a `~` path (`'*.md'`, `'~/.ssh/vps-backup'`) to keep a hook
  allow. A `powershell`/`pwsh` payload may hold `$_` only
  where bash leaves it alone, in single quotes or as `\$`: in a double-quoted payload bash
  substitutes its own `$_` (the last argument of the previous command), so `echo 'Name;
  ri -r -fo DIR'; powershell -NoProfile -Command "Get-Date | Select-Object $_"` deletes
  DIR (VERIFIED under bash on a scratch dir; HEAD allowed it). `[[`, `[` and `test` are
  not read-only verbs: `[[ Z -eq 1 ]]` and `[ -v 'a[Z]' ]` evaluate `Z` as arithmetic,
  which can run a `$(...)` held in it.
  `deny`: WebSearch, WebFetch, Agent, Workflow; Bash `git push` (any form, `git -C * push`
  and `git -c * push` included), `gh` and `gh.exe` whole, `docker.exe` and
  `docker-compose` whole, `ssh`, `scp`, `sftp` (with `.exe`), and curl upload flags
  (`-d`, `--data*`, `-F`, `--form*`, `-T`, `--upload-file`, `--json`). `docker` and
  `wsl` are denied by form, not whole, so the survey's read-only checks keep running:
  `docker run|exec|cp|push|login|build|buildx|compose|save|load|import|export|commit|
  volume|network|system|container|image|create|start`, `docker context use|create|import`
  and a global option first (`-H`, `--host`, `-c`, `--context`, `--config`); `wsl` (and
  `wsl.exe`) with `-d`, `--distribution`, `-e`, `--exec`, `-u`, `--user`, `-- `,
  `--import`, `--export`, `--install`, `--unregister`, `--mount`, `--cd`, `~`,
  `--shell-type`, `bash` or `sh`. Left open, for the hook and the classifier: `wsl
  <command>` on the default distro (the hook reads that payload) and the other `docker`
  subcommands. `Read` of credential stores, in both the
  `~/` and `//c/Users/*/` forms: `.claude/.credentials.json`, `.claude.json` (and its
  `.claude.json.*` backups), `.claude/backups/**`, `.claude/settings*.json`, session
  transcripts `.claude/projects/**/*.jsonl`, `.cache/huggingface/**`, `.git-credentials`,
  `.config/gh/**`, `AppData/Roaming/GitHub CLI/**`, `.ssh/**`, `.aws/**`,
  `.docker/config.json`, plus `**/.env*` anywhere and, at any depth (audit A2: another
  profile, a copied home, a WSL distro), `**/.ssh/**`, `**/.aws/**`, `**/.netrc`,
  `**/_netrc`, `**/.git-credentials`, `**/.docker/config.json`, `**/.config/gh/**`,
  `**/.claude/settings*.json`, `//wsl.localhost/**/.ssh/**` and `//wsl$/**/.ssh/**`;
  and `Edit` (which governs Write) of
  the guards, both anchored (`//**/local-inference-studio/...`) and relative to the cwd:
  `scripts/hooks/**`, `scripts/verify-doc.py`, `serve.ps1`, `stop.ps1`,
  `claude-local.ps1`, `register-task.ps1`, `watchdog.ps1`, `register-watchdog.ps1`,
  `bench/ladder/run.ps1`, `config/claude-settings.json`,
  `config/chat-templates/**`, `scripts/tests/claude_settings_test.py`,
  `scripts/tests/install_verify_test.py`, `scripts/tests/resilience_test.py`, and
  (anchored only, since the wrapper runs in any project)
  `config/**`, `bin/**`, `.gitignore`, `.gitattributes`. The rest of `~/.claude` stays
  readable on purpose: skills, plugin files and memory are read with the Read tool.
  2026-10-30 (security audit B1, B3): the allow rules for `gh auth status`,
  `gh --version` and `wsl -d Ubuntu -- echo|uname` were removed, since the denies above
  shadow them and a deny always wins over an allow, so no read-only `gh` form can be
  carved out of `Bash(gh:*)`. The allows for `wsl --list`/`-l`/`--status` and
  `docker version|--version|context ls|ps|info` stay, so the survey's `docker version`
  and `wsl -l -v` run as before. Its remote-host check (`wsl -d Ubuntu -- ssh ...`) and
  any `gh` check now show as denied tool calls in a local session (the hook denies them
  too). The survey policy text cannot change to match without changing
  `policy_sha256`, which feeds the stale-figure key, so that waits for an operator
  ruling that breaks the key. Evidence for precedence: a tool-level `--settings` deny
  wins over a user allow (VERIFIED, docs/ROADMAP.md, "Overlay: deny WebSearch and
  WebFetch"); a content-scoped `Read(...)`, `Bash(...)` or `Edit(...)` deny winning
  over a user-level allow is documented ("deny, then ask, then allow") but UNVERIFIED
  live, as are `~` expansion in `Read` rules on Windows, the `//c/Users/*/` and `//**/`
  wildcard forms, cwd-relative `Edit` rules in flag settings and the `.exe` variants.
  Tests (no session, no network):
  `python -I scripts/tests/claude_settings_test.py`. It and
  `scripts/tests/install_verify_test.py` quote credential paths and `git push`, and
  `scripts/tests/resilience_test.py` quotes a `Remove-Item` payload (operator ruling,
  2026-10-30), so the hook exempts all three from its content scan (as it does its own
  two test files, `lis-guard_test.py` and `lis-guard_property_test.py`, the hook file
  itself, which quotes every shape, and `bench/ladder/run.ps1`,
  whose `-DryRun` deletes its own work tree under `-WorkRoot` (audit A4); a copy
  elsewhere is scanned) and denies shell writes to them, also after a
  `cd` (`cd scripts/tests && echo x > <name>`), through `''` splices, `/./` or `//`,
  `{a,b}` braces and globs that can match the name (`scripts/tests/claude*.py`); each
  has an exact allow rule above.
- The hook, `scripts/hooks/lis-guard.py` (Python 3, stdlib, `python -I`), which the
  wrapper adds to the per-run settings as a PreToolUse `Bash` hook. It denies a critical
  write or delete anywhere in the command, including inside `powershell -Command "..."`,
  `bash -c '...'`, `wsl ... -- ...` and ssh remote commands (on the remote host: `rm`,
  `systemctl` other than `status`, `docker` other than read subcommands, `git push`,
  `tee`, `>`, `mv`, `chmod`, `kill`, `apt`, `reboot`). Since 2026-10-30 (security audit
  B1, B3, B4 and fold 3) it denies every executable the `Bash` deny rules above deny,
  whatever its spelling (quoted, a full path such as `C:/Windows/System32/wsl.exe` or
  `/usr/bin/ssh`, upper case, a leading `\`, an env prefix such as
  `MSYS_NO_PATHCONV=1`): `ssh`, `scp`, `sftp`, `gh` (`gh auth status` included),
  `docker-compose`, `docker.exe`, the denied `docker` subcommands and global options,
  `wsl` with a distro, user, exec, cwd or shell option or a `bash`/`sh` payload
  (`wsl -d Ubuntu -- uname -a` included), `git push` and `git credential`. It also
  denies anywhere in the command: `docker push`, `gh` writes, uploads
  (curl or wget sending data or a file to a non-loopback host, `scp`, `sftp`, `nc`,
  `socat`, `ftp`, remote `rsync`, `Invoke-WebRequest`/`Invoke-RestMethod` with a body,
  `Send-MailMessage`), broadcast or computed kills (`kill -1`, `kill 0`, a process group,
  a `$`/backtick target, `pkill`, `killall`, `taskkill /IM` or `/T`, `Stop-Process
  -Name`, `wmic process delete`), a word naming a credential store in any context (the
  `Read` deny paths above: any file under `.ssh/` or `.aws/`, `.env*` by
  basename, `.claude/settings*.json`, `.claude/backups`, `.claude/projects` transcripts,
  `.docker/config.json`, `.git-credentials`, `.config/gh`, `GitHub CLI` (also
  `GitHub\ CLI`), the Hugging Face token; plus `.netrc`/`_netrc`,
  `.config/git/credentials`, `.npmrc`, `.pypirc`, `.vault-token`, files under `.kube/`
  or `.gnupg/`, `ssh_host_*_key`, `Microsoft/Credentials`, `.local/share/keyrings`,
  shell and REPL history files, `.claude/history.jsonl`, `/proc/<pid>/environ`, files
  under `.azure/` or `.config/gcloud`, `.pgpass`, `.cargo/credentials`,
  `.terraform.d/credentials`, `rclone.conf`, browser `Login Data` and `Cookies` under
  `User Data`,
  `gh auth token` and the token variable names `HF_TOKEN`,
  `HUGGING_FACE_HUB_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `OPENAI_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`,
  `BRAVE_API_KEY`, `TAVILY_API_KEY`), also when spliced (`pu''sh`,
  `"$HOME/.claude/.cred"entials.json`, `'git pu'+'sh'`), brace-expanded
  (`~/.claude/{.credentials,x}.json`), escaped (`.s\sh`), ANSI-C quoted
  (`~/$'\x2essh'`, `$'\056ssh'`, `\uHHHH`) or globbed (`.cred*.json`,
  `.credentials.jso?`, `.ss?/id_*`, `.s*`, any glob inside a credential directory). It
  denies a credential directory (`.ssh`, `.aws`, `.docker`, `.gnupg`, `.kube`,
  `.config/gh`, `.config/git`, `.claude` and its `projects`, `backups`, settings and
  credentials, `.cache/huggingface`, `GitHub CLI`, `Microsoft/Credentials`,
  `ProgramData/ssh`) named as a whole word by any command (`ls -la ~/.ssh`, `find
  ~/.ssh`, `Get-ChildItem` in a PowerShell payload), a `cd`/`pushd`/`Set-Location`
  into one, with the later segments judged under the `cd` target (`cd ~/.ssh && cat
  x`), and a recursive search or archive (`grep -r`, `rg`, `find`, `tree`, `du`, `tar`,
  `zip`, `ls -R`, `Get-ChildItem -Recurse` and the like) of a home directory or its
  `.config`, `.cache`, `.local` or `AppData`. It denies whole-environment dumps (`env`
  and `printenv` with no name, bare `set`, `export -p`, `declare -p|-x`, `compgen -v`,
  the PowerShell `env:` drive, `GetEnvironmentVariables`, and in code
  `print(os.environ)`, `os.environ.items()`, `console.log(process.env)`,
  `JSON.stringify(process.env)`), a `$(...)` or backtick in any argument of a network
  command (`curl`, `wget`, `nc`, `socat`, `git fetch|pull|clone|push|remote`), `pscp`,
  `plink`, `telnet`, `tftp`, `bitsadmin`, `Start-BitsTransfer`, `git config` or `git -c`
  setting an `alias.` or `credential.` key, `git-credential-*`, `git send-email`,
  `python -m http.server` not bound to loopback, and `iex` of `[char]` arithmetic. In a
  PowerShell payload or `.ps1` line it denies `Start-Process`, `Invoke-Expression`/`iex`,
  `Invoke-Command`, `Invoke-CimMethod`, `Invoke-WmiMethod`,
  `New-`/`Set-`/`Remove-CimInstance`, `Remove-WmiObject`, `Stop-Computer`,
  `Restart-Computer`, `Set-Volume`, `Format-Volume`,
  `Clear-Disk` and a command reached through `Get-Command` (`& (gcm git) push`). It
  denies `find ... -exec|-execdir|-ok` on files named like keys or tokens (`-name
  '*.pem'`), a `mklink` or `New-Item -ItemType SymbolicLink|Junction` onto a credential
  directory, and a recursive search of `C:/Users` (every home). A line holding more
  than 500 splices, braces, backslash escapes, ANSI-C strings or `cd`/`pushd` is denied
  as "obfuscation over cap", which bounds the decision time. Also denied (audit A4): a
  `$(...)` or backtick in an argument of a read verb (`cat`, `head`, `tail`, `less`,
  `more`, `type`, `Get-Content`, `grep`, `rg`, `find` and the like; `cat $(printf
  .ssh)/x`, and also the harmless `grep "$(date +%F)" log`), `git log|show|diff
  --output` (a file write), npm's global `etc/npmrc`, and `systeminfo`, `tasklist`,
  `wmic`, `sc`, `schtasks` and similar tools given `/S <host>`, `/U`, `/P`,
  `/node:` or `\\host` (also as `-S`, `-U`, `-P`; `git --outp=x` and other prefixes of
  `--output` count). Audit A5 adds the Environment provider by name (`Get-ChildItem
  Environment::`, `-PSProvider Environment`, `-Path:env:`) as an environment dump, a
  PowerShell read whose path is built from pieces (`Get-Content ('~/.s{0}h/x' -f 's')`,
  `-replace`, `-join`, `[char]`, `.Replace()`, `+`, a string index; also the harmless
  `Get-ChildItem ('mod' + 'els')`) as a credential read, a glob under `.config` with
  fewer than three literal characters or one that can match `gh`, `git` or `gcloud`
  (`~/.config/g*/hosts.yml`), and a glob path ending in a credential name (`*/hosts.yml`).
  A script line over 32 KB is denied as "obfuscation over cap" without being parsed. In
  a PowerShell payload, `&` on a plain program name is judged
  as that program (`& git status` gets no decision, `& git push` and `& curl -T`
  deny); `&` on a variable or expression and script text built at run time
  (`[scriptblock]::Create((gc x))`) deny. Also
  a `$(...)` or backtick substitution as the command word (`$(echo git) push`), a base64
  decode piped to a shell, and a write to its own guard files (`scripts/hooks`,
  `verify-doc.py`, `serve.ps1`, `stop.ps1`, `claude-local.ps1`, `register-task.ps1`,
  `watchdog.ps1`, `register-watchdog.ps1`, `bench/ladder/run.ps1`,
  `config/claude-settings.json`, `config/automode-web.json`, `scripts/statusline.mjs`,
  the three exempt tests in `scripts/tests`, `llama-server.exe`), including by `>`,
  `>>`, `>|`,
  `sed -i`/`--in-place`, `perl -i`/`-pi`, `git
  checkout|restore|switch|reset|apply` naming one, `patch`, a `git apply`/`patch` diff
  file whose headers name one, `tee`, `Set-Content`/`Out-File`/`Add-Content` and
  `Copy-Item`/`Move-Item`, after a `cd` (`cd config; echo {} > claude-settings.json`)
  and through `/./`, `//`, `''` splices, braces and globs that can match a guard file
  (`echo x > scripts/tests/claude*.py`). Interpreter payloads are read, not skipped:
  `python|python3|py -c`, `node -e|--eval|-p`, `deno eval`, `deno run -`, `bun -e`,
  `bash|sh -c` (bundles such as `-lc` included), `cmd /c`, `pwsh -EncodedCommand`
  (decoded), heredocs and here-strings fed to an interpreter, `wsl <command>` with or
  without `--`, `python`/`node` script files, `source`/`.` of a shell file, the batch
  file of `cmd /c x.bat` (critical lines denied, never allowed) and the script a
  PowerShell payload runs (`./up.ps1`, `& ./x.ps1`, `. ./x.ps1`, `& python x.py`, a path
  inside `( )`, `$( )` or `@( )` or after `&&`, `Import-Module ./m.psm1` (also
  `-Name:./m.psm1` and `using module`), `Start-Job -FilePath`, `.\up.ps1`, literal
  `InvokeScript` and `[scriptblock]::Create` text), judged like `pwsh -File`; a script
  run from a payload that the hook cannot read is denied. Options before the file are
  skipped (`bash -e
  x.sh`, `bash -o pipefail x.sh`, `pwsh -NonInteractive ./x.ps1`, positional `pwsh
  ./x.ps1`, `-File:./x.ps1`, `-CommandWithArgs`). In a `.ps1` file, `<# ... #>` help
  blocks are skipped, and in a repo script under `bench/` or `scripts/` a variable
  assigned once to a quoted literal (`$base =
  "http://127.0.0.1:$Port"`, never a parameter or a scoped or `Set-Variable`
  reassignment) is read as that literal, so `Invoke-RestMethod -Method Post -Uri
  "$base/v1"` is a loopback call. No literal is read for a name assigned as `${name} =`,
  `${script:name}` or in a list (`$a, $name = ...`), nor for any name in a file that
  uses `PSVariable`, `Get-`/`Set-`/`New-Variable`, `[ref]`, a dot-source,
  `Import-Module` or the `&` call operator (audit A5). In Python or JavaScript code it
  denies a recursive delete of a home, cwd, parent or non-temp absolute path, a
  process-group or broadcast kill, a write call on the same line as a critical path
  (also after joining `'a'+'b'`), an HTTP upload to a non-loopback host, a file read
  sent in a non-loopback URL (`fetch('https://x/?d='+readFileSync(f))`), `chr`,
  `b64decode`, `atob` or `Buffer.from(..., 'base64')` feeding `os.system`,
  `subprocess`, `exec` or `eval`, and an argv list (`subprocess.run(['git', 'push'])`)
  judged as the shell command it spells. Residuals (no decision, so the rules or the
  classifier decide): code or a command word reached through a variable (`p = home;
  rmtree(p)`, `c=git; $c push`), a second file in `node --test a b`, a string built at
  run time by means other than literal `+` splicing, `chr`/base64 and globs
  (`''.join(...)`, `format`, `replace`, arithmetic), and
  a `git apply`/`patch` diff file the hook cannot read (missing, or over the read cap).
  Inline code and write-then-run (ledger S-B4, 2026-11-05) are judged after the scans
  above, so a scan hit keeps its own reason. (1) Inline code is denied even when the
  scan finds nothing: `python|py -c`, `node -e|--eval|-p|--print`, `deno eval`, `bun
  -e`, `perl|ruby -e`, `pwsh -EncodedCommand`, code on stdin (`python - <<EOF`,
  `python <<< ...`, `echo ... | python`, `| bash`, `| pwsh -Command -`, `python
  /dev/stdin`, `bash <(...)`), and a `bash|sh -c` or `pwsh -Command` payload that the
  read-only grammar does not allow and that is more than one command line (`;`, `&&`,
  `||` or a newline between statements, a heredoc, `$( )` or a backtick, a PowerShell
  `{ }` block or `@( )`). A one-line payload (`bash -c 'npm test'`, `pwsh -Command "&
  git status"`, a pipeline) is judged as its commands. The reason asks for the code in
  a file under the working directory for review, or the task's existing test command.
  (2) A run of a file written in this session is denied, naming the file: the file of a
  script run (`python x.py`, `node x.js`, `bash|sh|zsh|dash|ksh x.sh`, `source x.sh`,
  `pwsh -File`, `./x.ps1` in a payload), an interpreter's `<` file, a `node -r`,
  `--import`, `--loader` or `--test-reporter` module, the file of `perl`, `ruby`,
  `deno run`, `bun`, `tsx`, `php`, `Rscript` or `lua`, and a command word that is a
  path (`./x.sh`, `.\x.ps1`); a relative path is read under the cwd as `cd`, `pushd`
  and `Set-Location` move it (a `cd` inside `( )`, `$( )`, backticks or a `-c` or
  `-Command` payload applies inside it only; one in `{ }`, an `if` body or at the top
  applies to the later segments, as the shell runs them). "Written in this session" is
  any of: its `st_birthtime` (`st_ctime` where there is none) or its `st_mtime` is
  later than env
  `LIS_SESSION_START`; an earlier segment of the same command writes it, whatever its
  times (the destination of `cp`, `mv`, `ln`, `install`, `copy`, `move`, `Copy-Item` or
  `Move-Item`, a `>` or `>>` redirect such as `cat > f.py <<EOF`, or the file of `tee`,
  `Tee-Object`, `Out-File`, `Set-Content` or `Add-Content`); or it does not exist when
  the command is judged (a path with a separator or an extension: the same command
  would have to create it). A command that runs more than 64 files is denied with a
  reason naming RUN_TARGET_CAP. `LIS_SESSION_START` is an ISO 8601 UTC time that
  scripts/claude-local.ps1 sets for claude and its hooks (`2026-11-05T03:12:45Z`; up to
  9 fraction digits, `Z` or `+00:00`). Unset or malformed, rule (2) is off: it never
  decides on a guess, and a call nothing else decides gets a stderr note that it was
  not judged. A file created, edited or modified (mtime) after the start counts:
  Claude Code's Edit tool rewrites a file through a temp file and a rename, which gives
  it a new birthtime (verified 2026-11-05 on NTFS and ReFS); an in-place write moves
  the mtime; NTFS tunneling (a name deleted or renamed away and reused within 15 s
  keeps the old birthtime, seen on this machine's temp volume) still moves the mtime.
  By design, code the session writes or edits runs only through the task's existing
  test command. Both rules read groups and compound commands (`( )`, `{ }`, `if`,
  `while`, `until` and `for` bodies, `!`, backticks) the way they read `$( )`, and
  `bash -c -- '...'` takes the word after `--`. The fixtures bench/ladder/run.ps1
  generates before the launch are older than the start: their four test commands and
  `node --test bench/loop/fixture/test/text.test.js` get no decision (lis-guard_test.py
  generates the fixtures and checks). Residuals of S-B4 (no decision): a module that a
  pre-existing file imports (`python -m x`, a session-written module under an old
  test), `node --test` of a directory or with no file, wrappers the hook does not
  unwrap (`uv run`, `npx`, `xargs`, `env -S`), npm scripts, a multi-command `cmd /c`
  payload, `pwsh -wd`, and a `cd` it cannot follow (`$VAR`, `cd -`); a `git checkout`
  or `pull` that rewrites a file during the session gives it new times (denied), and
  so does a copied tree (`cp -r fixture work && node --test work/...`: the copies are
  session-written). A `node x` target is judged as the file node loads (`x.js`,
  `x.mjs`, `x.cjs`, `x.json`, `x/index.js`).
  The residual class of S-B4 (audit 2026-11-05, W1), documented as a class rather than
  chased one shape at a time: a run the text does not name as a file path (a glob,
  brace, `$PWD` or `$(pwd)` path, an NTFS stream such as `python new.py::$DATA`, a `0<`
  or other fd redirect, an extension-less target such as `cmd /c new` or `python
  tdir`, a Git Bash root path such as `/tmp/x.py`), code injected through the
  environment (`NODE_OPTIONS=--require=...`, `PYTHONPATH=. python -m x`), `exec -a`,
  `builtin`, `node --import=data:...`, awk
  `system()` or sed `e`, `find -exec`, a writer outside the
  list above rewriting an existing file in the same command (`sed -i`, `curl -o`), and
  file times set back (`touch -d`). The governing fact: lis-guard is a text classifier
  and one layer. Since S-O3 a lean `-p` session treats a call that no hook or rule
  decides as a deny (the user `autoMode` rules no longer load; an interactive session
  prompts, and a caller's `--permission-mode auto` still runs the classifier), so these
  shapes are refused there; a `-LisUserScope` rep loads the user's allow rules, which
  can run them.
  A git global option that runs code (ledger S-B8, 2026-11-05) is denied right after
  the scans, so the `git -c alias.`/`credential.` scan keeps its own reason: `-c <k=v>`
  (also glued `-c<k=v>`), `--config-env[=...]` or `--exec-path[=...]` before the
  subcommand, at every level the walker reads (`&&`, `;`, `|`, `$( )`, backticks, `( )`,
  `bash -c`, `pwsh -Command`, `wsl`, `timeout`, code literals and argv lists). The
  reason reads `lis-guard: git global option <opt> can run code (pager, fsmonitor,
  alias, exec path); run git without it`. The settings rules `Bash(git -C * status*)`,
  `log*` and `branch --show-current*` matched any option at the `*` (Claude Code 2.1.318
  warns about it in the debug log), so they are removed, with
  `Bash(git branch --show-current*)`: its trailing `*` approved options after the
  subcommand, which the hook leaves undecided (`git branch --show-current
  --exec-path=x`). The hook allows `git -C <path> status|log|branch --show-current|
  diff|show|rev-parse` and `git branch --show-current` by parsing them, and a shape it
  cannot decide now meets no rule: denied in a lean `-p` session, approved in a
  `-LisUserScope` ladder rep by the user-scope `Bash(git:*)` rule (ruling 19's
  tradeoff). In a scratch repo (audit, 2026-11-05)
  `git -c core.fsmonitor='touch x; false' status` ran its command, while
  `-c core.pager=` ran nothing: git starts a pager only when stdout is a terminal, so
  the pager path is UNVERIFIED here. `--exec-path=<dir>` runs a helper planted there.
  A word up to the subcommand that the shell expands (`{-c,k=v}`, `$'-c'`, `${X:--c}`,
  `-[c]`, a `$X` that word-splits, in a `wsl` payload too) is denied as well, since
  the shell turns it into `-c` after the hook reads it (the audit's brace and `$'-c'`
  forms ran their fsmonitor command under Git Bash). That reason reads `lis-guard: git
  global option <word> may expand to one that can run code (pager, fsmonitor, alias,
  exec path); run git without the expansion`. A double-quoted `-C "$d"` is denied too,
  an accepted over-deny (it cannot word-split). A quoted literal is not an expansion:
  `git -C . log --grep='-c core.pager'` stays allowed. A quoted bracket or glob before
  the subcommand is denied when the same segment expands elsewhere: `git -C '[x]' log
  -1 $REF` denies, `git -C '[x]' log -1` is allowed.
  A backslash-newline (one not itself escaped) is a line continuation bash removes
  before it splits words: the audit's `git -C . -\<newline>c core.fsmonitor=x status`
  and `--exec-\<newline>path=` forms got no decision and bash ran them. The hook
  judges a command holding one twice, as written and joined (single quotes keep it:
  `echo 'a\<newline>b'` prints the backslash and the line break, measured; a pwsh
  payload in single quotes keeps it too, UNVERIFIED), and denies when either view
  denies, allows only when both allow; `r\<newline>m -rf x`
  and `cat .e\<newline>nv` are denied the same way. UNVERIFIED: how 2.1.318's allow
  rules match a command split across lines.
  Harmless keys (`-c core.quotepath=off`) and the bare `--exec-path` are denied too,
  an accepted over-deny. `-C`, `--git-dir` and `--work-tree` alone are unchanged.
  An env prefix (`GIT_PAGER=`, `GIT_EXEC_PATH=`, `GIT_CONFIG_PARAMETERS=`,
  `HOME=/tmp/h git -C . log -1`) or an earlier `export GIT_PAGER=x; git -C . log -1`
  gets no decision from the hook and stays in the env-prefix residual class; no repo
  rule approves it now, and whether the user-scope `Bash(git:*)` of a `-LisUserScope`
  rep matches an env-prefixed command is UNVERIFIED. `git -C . log -1 $REF` with
  `REF=--output=<path>` gets no decision either (it predates S-B8: the expansion comes
  after the subcommand); with the allow rules gone no repo rule approves it.
  `git log -1 --outpu[t]=/tmp/o` gets no decision and writes only if a path literally
  named `--output=/tmp/o` exists under the working directory (contrived); every other
  obfuscation of `--output` is denied (`$(echo --output=..)`, a brace, `$'..\x75..'`,
  `--outp''ut=`, `--outp"u"t=`, `--outp\ut=`, a backslash-newline split).
  Live 2026-11-05 (lean `-p` session in a throwaway repo, 2.1.318): a command
  substitution and a redirection under the trailing-`*` rule `Bash(git log*)` were
  both denied by Claude Code with the hook silent (the debug log shows the hooks
  finish with no decision, then `Bash tool permission denied`): the three commands
  `git log -1 $(echo --format=%h)`, the same split by a backslash-newline, and
  `git log -1 > out.txt` are verbatim in the session's `permission_denials`; no file
  was written (`bench/results/trailstar-20261105/`). The reason text is the model's
  own report: "A nested command in this command can't be checked before it runs"
  and "Output redirection to '<path>' needs approval", which match the harness's
  check messages; the log does not show whether such a check or a rule non-match
  denied them. A lean session denies what no rule allows.
  Residuals the hook allows or leaves open: a recursive search of the repo or another
  non-home directory (`grep -rn KEY .`), `git grep`, `git config --list`, `git remote
  -v` (a token embedded in a remote URL shows), `/proc/self/cmdline`, using an alias
  that already exists (`git p`), `git remote add`, `git bundle create`, `deno run -A`,
  a plain `curl https://host` that sends no data, a path fed through `xargs` or a `while
  read` loop, a pre-existing script fed on stdin (`bash < x.sh`, not content-scanned;
  process substitution is denied, S-B4), `./up` without its extension in a PowerShell
  payload,
  `~/.wslconfig`, and `git config --get remote.origin.url`.
  Credential files outside the named list get no decision or a read-only allow
  (`~/.m2/settings.xml`, `~/.gitconfig`, `~/.config/hub`, `~/.yarnrc.yml`, editor state
  stores; `~/.azure`, gcloud, `.pgpass`, cargo/terraform tokens and browser cookie and
  login stores were in this group until they were named on 2026-10-30): the hook names
  known stores, it does not find every secret. The hook is defense in depth,
  not a boundary: a session that must not read the operator's credentials runs under a
  separate Windows user that cannot read them (ruling S-B1i); these residuals stay
  documented rather than chased with more patterns.
  Residuals of the ASCII-only allow path (ruling 45, 2026-10-30), each no decision and
  never an allow (the property test checks both): R3, a splice the hook cannot resolve
  to a known verb (`pu''sh`) or a string built at run time; R4, an input past the
  hook's limits (over 32 KB, over 500 `cd` statements, a `cd` rewrite past its size
  bound, a script over 200 KB).
  Over-matches kept on the safe side (deny): a loopback URL whose path names a
  credential file (`curl http://127.0.0.1:8080/.env`) and any `.env*` basename, such
  as `cat .environment`.
  It allows commands whose every segment is read-only (ssh, `gh` and `wsl -d` are no
  longer among them), and only pure-ASCII ones (ruling 45, 2026-10-30): a command, or a
  script the allow path reads, with a byte over 0x7F or a NUL is denied or gets no
  decision, never allowed (`Get-Process` with `-Name` spelled with an en dash gets no
  decision). Nor does it allow a command, nor a script it reads, naming `id_rsa`,
  `.ssh/` or `.ssh\`, `.aws/` or `.aws\`, `credentials`, `api-key`, `hf_`, `.env`, `-ec`,
  `-EncodedCommand`, `Invoke-Expression` or `iex` (also behind a `''`, `""` or
  backslash-newline splice), a script outside the repo (by its path, a `..` path or a
  junction), or a script run after a cwd move (the shell would run another file than the
  one the hook read). A path starting with `//` or `\\` is never allowed, and the hook
  never opens or resolves one (audit A13: `cat //host/share/x` sends SMB traffic and an
  NTLM hash to that host, and a lookup of an unknown host takes about 3 s); this covers
  `\\?\` and `\\.\`, a value after `-f`, `--x=` or `@`, a script, `-wd` or patch file,
  and a UNC cwd. A `//Switch` to pwsh or tasklist stays allowed (Git Bash passes it as
  `/Switch`). A PowerShell payload is read-only only on
  a fixed allowlist
  (audits A5 to A7: the blocklist before it allowed `Environment::` and `-f` splices; a
  list of cmdlet names alone let `-Comp host` and `'HKCU:\Envi*'` through; a list of
  secret property names let `Select-Object $_` and the object-typed `Parent` through).
  Every `;` statement is a pipeline that starts with one producer and continues only
  with consumers; a producer after a `|` gets no decision, as it would take its path or
  name from the pipeline (`Get-PSDrive | Select-Object -ExpandProperty Root |
  Get-ChildItem`). Each cmdlet takes only these parameters (P = the first positional
  argument):

  | Producer | Parameters and value classes |
  |---|---|
  | `Get-CimInstance` | P or `-ClassName` class (required); `-ErrorAction` |
  | `Get-Volume` | P or `-DriveLetter` word |
  | `Get-PSDrive` | P or `-Name` word; `-PSProvider FileSystem` |
  | `Get-Process` | P or `-Name` word; `-Id` int; `-ErrorAction` |
  | `Get-Service` | P or `-Name` word; `-ErrorAction` |
  | `Get-Date` | `-Format` word |
  | `Get-ComputerInfo` | P or `-Property` property list (required) |
  | `Get-Command` | P or `-Name` name: letters, digits, `_`, `-`, optional `.exe` |
  | `Test-Path` | P, `-Path` or `-LiteralPath` repo path; `-PathType` word |
  | `Get-Item` | P, `-Path` or `-LiteralPath` repo path; `-Force -ErrorAction` |
  | `Get-ChildItem` | P, `-Path` or `-LiteralPath` repo path; `-Recurse -Force -File` |
  | | `-Directory -Name`; `-Filter -Include -Exclude` glob; `-Depth` 1-3 |
  | | `-ErrorAction` |
  | `Write-Output` | words: letters, digits, spaces, `. , ! -` (also a consumer) |

  | Consumer | Parameters and value classes |
  |---|---|
  | `Select-Object` | P or `-Property` props; `-ExpandProperty` one property |
  | | `-First -Last -Skip` int; `-Unique` |
  | `Format-Table` | P or `-Property` props; `-AutoSize -Wrap -HideTableHeaders` |
  | `Format-List` | P or `-Property` props |
  | `Sort-Object` | P or `-Property` props; `-Descending -Unique` |
  | `Where-Object` | P or `-FilterScript`: `{ $_.X -eq 'y' }` (`-eq -ne -gt -lt` |
  | | `-like -match`, a quoted or numeric literal) |
  | `Measure-Object` | P or `-Property` props; `-Sum -Average -Maximum -Minimum` |
  | `ConvertTo-Json` | `-Depth` 1-3; `-Compress` |

  Every property a payload names (in a props list, `-ExpandProperty`, a Where-Object
  `$_.X`, a calculated property's `$_.Y`, or `(pipeline).X`) must be on its producer's
  list of scalar properties; `$_` alone, `*`, any other `$` and any other name get no
  decision:

  | Producer | Properties |
  |---|---|
  | `Get-Process` | Name, Id, CPU, WS, PM, NPM, VM, Handles, Path, StartTime, |
  | | ProcessName, Responding, PriorityClass, WorkingSet64 |
  | `Get-Service` | Name, DisplayName, Status, StartType |
  | `Get-Volume` | DriveLetter, FileSystemLabel, Size, SizeRemaining, HealthStatus, |
  | | DriveType |
  | `Get-PSDrive` | Name, Root, Used, Free |
  | `Get-Item`, `Get-ChildItem` | Name, FullName, Length, LastWriteTime, Extension, |
  | | Mode, PSIsContainer |
  | `Get-Date` | Year, Month, Day, DateTime, Ticks |
  | `Get-Command` | Source, Path, Name, Version, CommandType |
  | `Get-ComputerInfo` | OsName, OsVersion, OsArchitecture, CsNumberOfLogicalProcessors, |
  | | CsTotalPhysicalMemory, OsTotalVisibleMemorySize, OsFreePhysicalMemory, |
  | | WindowsVersion |
  | `Win32_OperatingSystem` | Caption, Version, BuildNumber, OSArchitecture, |
  | | TotalVisibleMemorySize, FreePhysicalMemory, LastBootUpTime, InstallDate |
  | `Win32_ComputerSystem` | Model, Manufacturer, TotalPhysicalMemory, |
  | | NumberOfLogicalProcessors, NumberOfProcessors |
  | `Win32_Processor` | Name, NumberOfCores, NumberOfLogicalProcessors, |
  | | NumberOfEnabledLogicalProcessors, MaxClockSpeed, L2CacheSize, L3CacheSize |
  | `Win32_VideoController` | Name, AdapterRAM, DriverVersion, VideoProcessor |
  | `Win32_PhysicalMemory` | Capacity, Speed, Manufacturer, PartNumber |
  | `Win32_LogicalDisk` | DeviceID, Size, FreeSpace, FileSystem, DriveType |
  | `Win32_DiskDrive` | Model, Size, MediaType, InterfaceType |
  | `Win32_BIOS` | Manufacturer, Name, SMBIOSBIOSVersion, ReleaseDate |
  | `Test-Path`, `Write-Output` | none |

  After `Measure-Object`, `(pipeline).X` may read Count, Sum, Average, Maximum or
  Minimum. No object-typed property (Parent, Modules, DependentServices, Provider,
  CimSession) and no identity (UserName, RegisteredUser, SerialNumber, Domain,
  ProcessorId) is on any list. `ConvertTo-Json` follows only a listed selection (a
  `Select-Object` props list or `-ExpandProperty`, or `Get-ComputerInfo -Property`).
  `Format-Table` or `Format-List` with no props list, and a bare `Get-CimInstance`, get
  no decision unless a listed selection or `Measure-Object` came first; the exceptions
  are `Get-PSDrive`, `Get-Date`, `Get-Item`, `Get-ChildItem`, `Test-Path` and
  `Write-Output`, whose default views hold nothing more.

  A class is one of `Win32_OperatingSystem`, `Win32_ComputerSystem`,
  `Win32_Processor`, `Win32_VideoController`, `Win32_PhysicalMemory`,
  `Win32_LogicalDisk`, `Win32_DiskDrive` and `Win32_BIOS`; `Win32_Process` (command
  lines), `Win32_Service` (binary paths), `Win32_Product` and every `CIM_*` base class
  are out, as are `-Query`, `-Namespace` and `-Filter`. Props are a comma list of
  names from the producer's list or `@{n='X';e={[math]::Round($_.Y/1MB)}}` calculated
  properties (`1KB`, `1MB` or `1GB`, optional digits, or plain `e={$_.Y}`). A word is
  letters, digits, `.` and `-`; a glob adds `*` and `?`; an int is up to six digits;
  `-ErrorAction` takes SilentlyContinue, Stop, Continue or Ignore. A repo path is
  relative, with no `..`, drive, `~` or `:`, at most 64 parts, and no part of it, nor
  anything a wildcard in it matches, is a symlink or junction (`bench/results/latest` is
  one); a wildcard with more than 4096 matches is treated as a link. `Get-ChildItem
  -Name` with `-Recurse` or `-Depth` gets no decision (it lists through links). The
  path cmdlets, in a `-Command` payload or in a script the command runs (`pwsh -File`,
  `bash`, `sh`, `source`, `.`), are allowed only when the cwd is inside the repo, the
  script file is inside the repo (not drive-relative like `C:x.ps1`), and nothing
  anywhere in the command (any segment, a nested `bash -c` or `-Command`, a heredoc
  body) runs `cd`, `pushd`, `popd`, `chdir`, `Set-Location`, `sl`, `Push-Location` or
  `Pop-Location`, or starts PowerShell with a `-WorkingDirectory` (`-wd`, `-w`, any
  prefix, `-wd:` or `-wd=` too) other than the cwd; a `cd` inside a script covers its
  later lines. PowerShell options are read in every spelling pwsh takes: `-x`, `--x`,
  `/x`, and `//x` (Git Bash passes `/x` on), with the dash also an en dash (U+2013),
  em dash (U+2014) or horizontal bar (U+2015), single or doubled; so `--wd`, `/wd`,
  `--File` and `/c` count like `-wd`, `-File` and `-c`, and a command that names pwsh
  is read with those three dashes as `-`. A script run through pwsh needs `-NoProfile`
  and no `-SettingsFile` or `-ConfigurationFile`; one run through `bash` or `sh` takes no
  `-l`, `-i`, `--login`, `--rcfile` or `--init-file` (a profile can `cd`). Over 500
  `cd` statements (`cd`, `pushd`, `popd`, `chdir`, `sl`, `Set-Location`,
  `Push-Location`, `Pop-Location`) get no decision, past the hook's limit (R4); one line
  with over 500 obfuscation forms, or a `cd` prefix past 64 parts, is denied as
  obfuscation over the cap; arguments after a `cd` that read as more than twice the
  command's length plus 4096 get no decision. Parameter names match exactly
  (`-Comp`, `-cn` and `-Cred` are not names in the tables); any other parameter, or a
  value outside its class, gets no decision.
  A quoted value is judged like the same value unquoted (`'HKCU:\Envi*'` is out as
  `HKCU:\Envi*` is), and `\\` or `//` in any value is out. The only other statement
  forms are `(pipeline).Prop`, `[math]::Round((pipeline).Prop/1GB,1)` (`1KB`, `1MB`
  or `1GB`, optional digits) and the three exact forms `$PSVersionTable`,
  `$PSVersionTable.PSVersion` and `$PSVersionTable.PSVersion.ToString()`. A provider
  drive (`HKLM:`, `Variable:`), an alias, `Get-Content` and any other cmdlet get no
  decision.
  For scripts (`bash file`, `pwsh -File`, `python file`, `node file`) and interpreter
  payloads it is the judge of
  record (operator ruling, 2026-10-25): a critical write on any line is denied quoting
  that line, a file whose every line is read-only is allowed, and a file it cannot read
  or parse gets no decision. "No decision" does not mean "straight to the classifier":
  the call falls back to Claude Code's own permission rules (deny > ask > allow), and
  only a call no rule decides reaches the classifier. Its denials say "not retryable; report it to the operator",
  which stops the retry loop. The read-only grammar is a per-verb allow-list of argument
  shapes (a verb runs only with options from its own safe set; an unknown option gives no
  decision), so a write/exec option on an otherwise read-only verb (`uniq <out>`,
  `sort -o`, `find -fprint`, `nvidia-smi -f`, `wmic ... delete`, `curl -o`,
  `ssh -o ProxyCommand`) is never allowed. `find`, `tree` and `rg` were deny-lists until
  2026-10-25 and are now allow-lists too: `find` takes paths then only `-name -iname
  -path -ipath -type -maxdepth -mindepth -mtime -newer -size -regex -iregex` (each with
  its value), `-empty -print -print0 -prune -not -o -a -readable ! ( )`; `tree` only `-a
  -d -L -I -P -f -i -h -s -D --noreport --dirsfirst`; `rg` only `-n -i -l -c -w -F -e -g
  -t -T --glob --type -m --max-count -A -B -C -S --no-heading --color -o --json --hidden
  -u` (no bundles such as `-in`); `file` only `-b -i -L -h -z -s -k --mime --mime-type
  --brief` (`-C`, `-m`, `--compile` get no decision). Env prefixes are an allow-list too: a leading or
  standalone `NAME=VALUE` keeps a hook allow only for `MSYS_NO_PATHCONV`,
  `MSYS2_ARG_CONV_EXCL`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`, `TERM`, `COLUMNS`, `LINES`,
  `NO_COLOR`, `FORCE_COLOR`, `CLICOLOR`, `GIT_TERMINAL_PROMPT`, `GIT_OPTIONAL_LOCKS`,
  `PYTHONIOENCODING`, `PYTHONUTF8`, `PYTHONDONTWRITEBYTECODE`, `DOCKER_CLI_HINTS` and
  `WSL_UTF8` (exact case, no newline in the value). Any other name gives no decision, so
  the rules or the classifier decide: `GIT_EXTERNAL_DIFF`, `GIT_CONFIG_*`, `GIT_PAGER`,
  `PAGER`, `GIT_DIR`, `RIPGREP_CONFIG_PATH` and the like make a read-only verb run a
  program (VERIFIED live 2026-10-25: `GIT_EXTERNAL_DIFF=<script> git diff --ext-diff`
  got no hook decision, the classifier timed out and denied, the script did not run).
  `WSLENV` is left out because it forwards variables into WSL. The wrapper registers the hook with
  `timeout: 10` and `onFailure: block` (Claude Code 2.1.295+, so a hook crash or timeout
  blocks the call rather than letting it through), and inputs over 32 KB get no decision.
  `-LisNoGuard` leaves the hook out. Tests:
  `python -I scripts\hooks\tests\lis-guard_test.py` and the property test
  `python -I scripts\hooks\tests\lis-guard_property_test.py` (22,000 generated
  cases checked against the allow grammar, 1,000 of them UNC paths on random hosts;
  `--seed N`, ruling 45).
- PostToolUse hook (matcher `Write|Edit`, added with lis-guard, dropped by `-LisNoGuard`):
  `scripts/verify-doc.py --hook` checks every `.md` written or edited inside the working
  directory and hands its findings to the model as `additionalContext`, never blocking.
  FAIL: a labelled split of 3+ parts (or of 2 complementary parts such as
  tested/untested or pass/fail) that does not sum to its total, an unscoped
  "N PowerShell scripts"-style count against the repo, "`path` (N lines)" or a Lines
  cell against the file; a missing backticked path is INFO only.
  Remainders later in the sentence (N skipped, other, others, remaining, rest, left,
  pending, excluded or ignored) that close the gap exactly pass the split; the list is
  closed, not semantic, so a word used in another sense ("3 rest days") still counts.
  A file count followed within 40 chars by "at" or "as of" and a commit is INFO; an
  unrelated "fixed at `<sha>`" that close also downgrades it, and INFO still shows it.
  By hand:
  `python -I scripts/verify-doc.py <file.md>`.
  Text in double quotes is treated as a quotation and not checked for sums or file counts.
  Line counts are read only for files inside the working directory and under 8 MB; the
  reply is capped near 9,000 characters with FAIL lines first.
- PreToolUse hook `scripts/hooks/loop-guard.py` (Python 3, stdlib, `python -I`; matcher
  `*`, added with lis-guard, dropped by `-LisNoGuard` or `-LisNoLoopGuard`). It denies a
  tool call identical (tool name and canonical input) to 3 or more of the session's last
  12 counted calls, so the first and second repeat always run. Write, Edit, MultiEdit and
  NotebookEdit are never counted; a new Write/Edit/MultiEdit/NotebookEdit clears the
  window, so a re-read or a re-run test after an edit passes; edits made through Bash or
  PowerShell (sed -i, scripts, git) do not. Bash and PowerShell commands with a wait
  word at command position (`sleep`, `until`, `timeout`, `Start-Sleep`, `Wait-Process`,
  `Wait-Job`, `Wait-Event`) are polls and are not counted, nor are `BashOutput` and
  `TaskOutput` calls (tool names UNVERIFIED on 2.1.310). A quoted wait word also exempts
  a command, so `grep -rn 'timeout' src/` is never counted (a miss in the safe direction).
  The deny reason tells the model to use the earlier result, change approach or report
  what blocks it, and to say so when the tool it wants is not in its tool set; after 2
  denials of the same call it says to stop and answer. It stays a deny, never an ask: in
  `-p` an ask is a hard denial whose reason the model does not see. State lives in
  `%TEMP%\lis-loop-guard\<session_id>.json` (atomic write, pruned after 24 h). Bad
  input, input over 1 MB or a missing session_id give no decision; corrupt state is
  discarded (the window restarts); a lock left by a crashed hook means no decision for
  about 10 s, until it is broken as stale. The hook is registered without
  `onFailure: block`, so its failure never blocks a call.
  Why: one identical call repeated on the 27B model is the loop seen in 5 of the 8
  bench/compact runs (2026-10-26), 4 of which it held until `--max-turns`; replayed
  through the hook, the first deny fires at call 8 to 63, and 28 to 55 of 61 turns would
  have been saved had the model then answered (not verified live). bench/compact/run.ps1
  passes `-LisNoLoopGuard` so its cases stay comparable with those captures, and
  bench/loop/run.ps1 so its runs stay comparable with the 2026-10-24 baselines. Tests:
  `python -I scripts/hooks/tests/loop-guard_test.py`; replay of the effort-low-forced
  capture: `python -I scripts/hooks/tests/loop-guard_replay.py` (prints SKIP when the
  gitignored capture is absent, as in a fresh clone).
- SessionStart hook `scripts/hooks/facts-inject.py` (Python 3, stdlib, `python -I`;
  matchers `compact` and `startup`, added for `-LisTask longrun` only; ledger T-9 and
  R-W2). After each compaction, and at the start of a session the wrapper relaunched
  (`LIS_RELAUNCH` set; any other startup gets no output), it prints the facts file the
  profile names (`LIS_FACTS_FILE`, looked up in the stdin `cwd`, then in the hook's
  cwd) as `additionalContext`: a header line, then
  the content; over 9,000 UTF-16 units only its last whole lines, said in the header
  (Claude Code moves a string over 10,000 characters to a file and shows a 2,000
  character preview). Every run appends one line to `LIS_FACTS_INJECT_LOG`
  (`%TEMP%\lis-facts-inject-<stamp>.log`, created empty at launch, path in the banner):
  `injected=yes` with the file's lines and bytes, or `injected=no` with a reason (input,
  not-relaunch, unset, missing, empty, oversize or error) and no output. It always
  exits 0.
  lis-guard denies a Bash command that names the log literally (`lis-facts-inject` or
  `LIS_FACTS_INJECT_LOG`, a read included) and the per-run settings deny Edit (Write
  included) of `lis-facts-inject-*`; a globbed or computed name still reaches it, so
  the grader's `facts_injected_*` fields are forgeable and report-only (the transcript
  check decides `facts_read_after_boundary_any`). Tests:
  `python -I scripts/hooks/tests/facts-inject_test.py`.
- Hook copies (ledger S-B3): every hook script a run registers (`lis-guard.py`,
  `loop-guard.py`, `verify-doc.py`, `facts-inject.py`) runs from a copy in
  `%TEMP%\lis-hooks-<stamp>-<pid>\`, made at launch, byte-identical to the repo file,
  marked read-only and kept after exit for forensics (the banner names it:
  `claude-local: hook copies: <dir>`). An edit of the repo files mid-session changes no
  hook of that session. lis-guard runs as `lis-guard.py --hooks-dir
  <repo>/scripts/hooks`, so its exempt files and repo root still name the repo;
  verify-doc runs with `--script <repo>/scripts/verify-doc.py`, so its "+N more; run:"
  hint names the repo file. The per-run settings deny Edit of the directory, by its
  path and as `//**/lis-hooks-*/**` (Claude Code applies an Edit rule to every
  file-editing tool, Write included; a `Write(path)` rule is not matched by its file
  permission checks, warned at startup by 2.1.318, so the launcher emits none; a live
  lean `-p` session on 2026-11-05 was refused a Write into a hook copy directory and
  of `models/manifest.json`, and neither file was written; that session still carried
  the inert Write rules, so the inference rests on 2.1.318's warning plus that denial,
  and the next live session on this launcher, which emits none, re-proves it).
  lis-guard denies any Bash
  command that names `lis-hooks-`, `lis-settings-` or `lis-mcp-` (a read included): in
  Git Bash `chmod +w` clears the read-only flag, and an emptied hook exits 0, which
  fails open.
  A glob path whose last two parts can match `lis-hooks-<x>/<hook>`, or whose last part
  can match `lis-settings-<x>.json` or `lis-mcp-<x>.json`, counts as that file for the
  write checks (`cp /dev/null $TEMP/*/lis-guard.py`, a `glob.glob('.../lis-h*/*.py')`
  in Python code that writes, `$env:TEMP\lis-h*\lis-guard.py` in a pwsh payload). `<x>`
  is the stamp or pid, digits and dashes only, so `ls src/*.test.js` is not a per-run
  file; a part needs 3 letters besides `.py`/`.json`, so `ls */*.py` stays undecided.
  A pwsh write cmdlet fed by a pipe from a segment that names a critical path is a write
  to it (`Get-ChildItem <path> | Clear-Content`) when it names no path of its own and is
  not Out-File, Tee-Object or Copy-Item. The name must stand alone
  (`lis_settings_test.py` and `chrysalis-mcp-server` are not it). Residual: a computed
  name (built in a payload or a variable), a glob with fewer letters (`$TEMP/*/*.py`)
  or a pwsh pipe through a filter, ForEach-Object or a variable (`... | Where-Object
  Name -eq lis-guard.py | Clear-Content`) still reaches a copy, the same residual as
  the facts-inject log. Deleting the
  facts-inject copy suppresses the injection silently (no log line, nothing injected);
  `longrun.py`'s `facts_injected_*` fields show the gap on a graded rep. `-LisNoGuard`
  without longrun registers no hook and makes no copy; `-LisPrintArgs` shows the copy
  paths but writes nothing. The hooks' tests import the repo files. Remove old
  directories by hand when `%TEMP%` fills. The per-run settings also deny Edit (Write
  included) of the two pin sources `serve.ps1` trusts, `scripts/install.ps1` (zip, exe
  and dll digests) and `models/manifest.json` (GGUF digests), by absolute path in every
  profile.
- Verifier pass (verify-claims), by hand, not a hook: `pwsh scripts/verify-claims.ps1
  -Document <file.md> [-Root <repo>] [-Batch 1] [-MaxTurns 8] [-MaxClaims 0]
  [-OutDir <dir>] [-DryRun]` (Root defaults to the current directory, OutDir to this
  repo's gitignored `logs/verify`, MaxClaims 0 to every claim; `-DryRun` prints the
  claim count and the first 3 claims and starts no session). Steps: verify-doc runs on
  the document and each FAIL line is decided false by the harness (deterministic-false),
  never sent to a model; `scripts/verify_claims_extract.py` splits the rest into
  candidate claims (a sentence or table row holding a backticked path or identifier, a
  number or a quoted string; a table row goes out prefixed with its header row),
  skipping every claim that spans a FAIL line and every claim under a heading that names
  a plan, next steps, a proposal, a recommendation or a suggestion, until the next
  heading of the same or a higher level (counted as `plan-section claims skipped`).
  That skip was added after the proof runs below and no run has used it yet
  (UNVERIFIED effect); on the two proof documents the script (with the FAIL-line skip)
  now extracts 37 and 34 claims, 8 and 20 skipped as plan claims (the bare extractor
  gives 38 and 35; rep 2 also loses one claim to the no-split after `e.g.`). Each batch
  of `-Batch` claims goes, as JSON data, to ONE short `-p` session through the wrapper in
  Root with only Read, Grep and Glob (`--allowedTools`; Bash, Write, Edit, Skill and the
  rest in `--disallowedTools`) and a fixed prompt asking for a JSON array of id, verdict
  (true, false or unverifiable) and evidence; a batch whose command line, counted with
  its `"` and `\` escaping plus 4,000 characters of room for the wrapper, would pass
  32,000 characters stops the run (lower `-Batch`). A claim left unanswered, or a reply
  that does not parse (the whole reply, else the last `[{...}]` in it that decodes and
  holds a `verdict` key), is verifier-failed. `scripts/verify_claims_report.py` then
  checks the evidence without
  trusting it: evidence-backed means it names a relative path that exists under Root
  (absolute and `..` paths are never touched); evidence-confirmed means a true or false
  verdict cites `path:line` and quotes a span of 12+ characters that the harness finds
  in that file within 3 lines of the cited line. It prints the honest count:

  ```
  verify-claims v2: <doc>
  claims extracted: N   sent to the verifier: S in <sessions> sessions (batch B)
  plan-section claims skipped: P
  verdicts: true T   false F   unverifiable U   verifier-failed V   deterministic-false D
  evidence-backed: E of (T+F)   evidence-confirmed by the harness: C of E
  deterministic findings also judged false by the verifier: X of D'
  wall: <seconds> s   turns: <sum>   peak prompt tokens: <max>
  false claims (deterministic first):
    line L: <claim> -- <evidence>
  verifier-failed claims: <ids and lines>
  ```

  P is `not recorded` for a ledger written before the skip existed.
  D' counts the FAIL lines inside a claim that was sent anyway (normally 0, since those
  claims are skipped). Peak prompt tokens is the largest `n_tokens` the server log shows
  for one request during a session (the envelope's `usage` is a sum over the session),
  else that sum. Exit 1 when F + D > 0 or V > 0, else 0. Everything (ledger, per-session
  envelopes, counts) goes to `<OutDir>/<docname>.<yyyyMMdd-HHmmss>.verify.json`. The run
  stops, still writing the ledger, when `logs/llama-server.log` shows no activity for
  10 min while a session is pending (no such stop when that log is absent). The temp
  run file is deleted when the report exits 0 or 1, else kept and its path printed
  (`run data kept: <path>`). Why per claim: v1 inlined the whole document in
  one session and asked it to extract, check and report every claim; three runs took
  32 to 59 turns and over an hour each and ended at "Prompt is too long" (about 110K
  tokens) with no ledger. Now the harness keeps the books and each session answers a
  few claims. Cost: one short session per batch on the one server slot
  (`-Batch` claims each). Measured on two 142- and 166-line audit documents: one claim
  per session averaged 69 s (12 claims, 828 s; largest request 25,736 tokens);
  `-Batch 4` took 1,966 s and 2,737 s for 45 and 55 claims (largest request 40,730
  tokens) but a session that runs out of its 8 turns fails its whole batch: 12 of 45
  and 23 of 55 claims came back verifier-failed. A session whose reply holds no
  `[{"id"` prints `session <n>: result unparsed or partial, <count> claims
  verifier-failed` as it ends (a heuristic; the honest count is authoritative).
  Resume: `pwsh scripts/verify-claims.ps1 -Resume <ledger.json> [-Root <repo>]
  [-Batch 1] [-MaxTurns 12] [-MaxClaims 0] [-OutDir <dir>] [-DryRun]` keeps every
  decided verdict and the deterministic findings of that ledger, sends only its
  verifier-failed claims again (Document, and Root unless given, come from the ledger;
  MaxTurns defaults to 12) and writes a new ledger, never the old one. Its honest count
  names this run's sessions in the head and adds `resumed from: <ledger>` and
  `retried: R   recovered: K   still failed: V` after the verdicts line; the JSON gains
  `resumed_from`, `retried` and `recovered` (claim ids). Resuming those two ledgers
  (one claim per session, 12 turns) recovered 11 of 12 and 18 of 23 claims in 1,248 s
  and 5,272 s (largest request 93,056 tokens); 6 of those 29 verdicts were wrong (5
  false on a plan item or a Lines cell, 1 true on an off-by-one count), and 2 of the 6
  still failed had answered but put a `[` in the prose before the array (both reply
  shapes parse since the last-array scan; tested, not re-run).
  Limits: the verifier is the same local model family as the author and can share its
  mistake; true means not contradicted, not proven; evidence-confirmed means the
  harness found the quoted text near the cited line; it does not prove the verdict (2
  of the 6 wrong verdicts were evidence-confirmed). Tests:
  `python -I scripts/tests/verify_claims_report_test.py`.
- What asks: the `ask` rules above. Interactively you get a prompt. In `-p` mode an ask
  is a hard denial with no classifier, and the model retries the same call until
  `--max-turns`.
- The limit (V5): a prefix rule cannot see a payload. A rule like `Bash(powershell
  -NoProfile -Command 'Get-Volume*)` alone would allow `'Get-Volume; Remove-Item x'`,
  which is why the per-run settings carry no such rule; the hook parses the payload
  instead.
  A trailing `*` also spans the rest of an ssh remote command, so no read-only ssh form
  can be carved out: `ssh`, `scp` and `sftp` are denied whole, by a deny rule and by the
  hook. Reads are guarded
  only for credential stores: the hook allows `cat` of any other file (ruling 15) and
  denies any command naming a credential path (`cat ~/.ssh/id_ed25519` is denied since
  2026-10-30), the `Read` denies cover the Read tool, and the classifier never sees a
  tool's output or a script's content.

All other arguments go straight to `claude` (`-p`, `--max-turns` and so on). The
wrapper options are `-LisContextTokens N` (default 114688, minimum 1024; set it to the
server's `-Ctx` when that is smaller), `-LisFull` (refused with web access, above),
`-LisNoGuard`, `-LisNoLoopGuard`, `-LisUserScope` (user scope on, below),
`-LisTask NAME`, `-LisRelaunchMax N` (longrun, below), `-LisStartServer`,
`-LisKeepState` and `-LisPrintArgs`. `-LisStartServer` (host only, skipped by
`-LisPrintArgs`): when
`/health` is not ok, it starts the `LocalInferenceStudio-llama-server` task (unless it
is already running) and waits up to 180 s for `/health`, before the key is read
(proven 2026-11-09 01:10 against a stopped server: task started, `/health` ok in
about 10 s, the session answered in 21 s wall; run folder
`logs\web-20261109-011012-49848`). `-LisKeepState` (host only, with `-LisWeb`, built
2026-11-09, ledger W-18): web sessions keep their transcripts and prompt history
across runs in `<repo>\logs\web-state\<key>\` (one per work directory: the leaf name
plus 8 hex digits of the path's SHA-1), mounted at `/home/lis/.claude/projects` and
`/home/lis/.claude/history.jsonl`, so `--continue`, `--resume` and `/resume` find
the earlier runs (proven 2026-11-09 19:27 with two `-p` runs; the prompt-history
write is UNVERIFIED until an interactive run); the policy files stay fresh
per run (docs/web-access.md). Success:
Claude Code answers and the server log shows the requests. A
`[claude-code:unrecognized_model] {"model":"local"}` line is harmless.

Task profiles (trust ladder): `-LisTask review|edit|longrun`. You pick the profile when
you launch; nothing in the session can change it, and every test record states it.
Results are never compared across profiles. A profile sets the tools, appends a policy
block that names it (so the transcript carries "Task profile: <name>"), may add deny
rules, and prints to stderr, before launch and after exit, the checks to run when the
session ends:

- review: Bash, Read, Glob, Grep, Skill; Edit, Write and NotebookEdit also denied. The
  report is the final answer; save it and run verify-doc.py and verify-claims.ps1 on
  it; `git status --porcelain` must show nothing else.
- edit: the lean set; change only the files the task names, test before and after.
  Checks: the repo tests (CLAUDE.md), `git diff --stat` against the named files, then
  verify-doc and verify-claims on the report.
- longrun: as edit, plus a facts file `lis-facts-<stamp>.md` in the working directory
  that the model appends verified figures to, so a compaction cannot lose them. It also
  registers the facts-inject hook (step 8) and denies Edit (Write included) of
  `lis-facts-inject-*`.
  Session supervisor (ledger R-W2, T-5; a session decision of 2026-11-04 that the
  operator can overturn, not a ruling): with `-p <prompt>`, a claude exit with rc != 0
  relaunches one fresh `-p` session, never `--continue` or `--resume` (an autocompact
  thrash is what killed the first one, and Claude Code says to start fresh).
  `-LisRelaunchMax N` (0 to 3) bounds it: default 1 under longrun, 0 otherwise, and N >
  0 needs longrun. The relaunch keeps the arguments, settings and env, sets
  `LIS_RELAUNCH=<n>` and `LIS_RELAUNCH_RC=<rc>`, and puts one line before the prompt
  ("Relaunch <n> after the previous session exited (rc <rc>). The facts file <name> in
  the working directory holds the progress so far: run the test command first and append
  a CHECK line before any edit, then continue from its last NEXT line."). stderr gets
  `claude-local: relaunch n=<n> rc=<rc> reason=thrash|exit` (thrash when the `result`
  field of the dead session's last stream-json result record on stdout, or its last 50
  stderr lines, hold "Autocompact is thrashing"; another stdout line quoting it, such as
  a tool result, does not count), and the wrapper exits with the last session's rc
  (live 2026-11-05: a scratch session whose CLAUDE.md overflowed the context exited
  rc 1 on the 400, stderr `relaunch n=1 rc=1 reason=exit`, the second session got its
  own debug file and the facts-inject hook's relaunch start, the wrapper exited 1; the
  relaunch repeats the same request, so a deterministic cause such as an oversized
  working directory kills it too and the wrapper stops; it helps with one-off exits
  such as an autocompact thrash). A
  result record is a stdout line that starts with `{`, contains `"type":"result"` and
  parses with type `result` (Claude Code writes that key late in the line, after
  `duration_api_ms` and the rest); a line that does not parse is checked by substring
  for the subtype and the message instead. A session whose last result record has
  subtype `error_max_turns` is not relaunched (a relaunch would double the turn budget);
  stderr gets `claude-local: relaunch skipped rc=<rc> reason=max_turns`. A `--debug-file
  <path>` argument becomes `<path minus extension>.<session><extension>` for the
  relaunch (`<base>.debug.log` -> `<base>.debug.2.log`); the `--debug-file=<path>` form
  is not rewritten, and both sessions then write that one file. rc 0 never relaunches,
  and rc -1 (a claude killed by .NET Process.Kill) never relaunches; a kill that sets
  another code (taskkill /F gives 1, UNVERIFIED) does; the wrapper has no timeout of its
  own, and `bench/ladder/run.ps1`'s timeout kills the wrapper's whole tree. While the
  supervisor is armed, claude's stdout and stderr pass through the wrapper line by line
  as UTF-8 with LF line ends; otherwise they go straight to the console. The banner says
  `relaunch: max N` or why it is off. The relaunch exists only under `-LisTask longrun`
  with a `-p` prompt (it resumes from the longrun facts file); an interactive session
  or another profile gets none, so launch an unattended task that way.
  `LIS_CLAUDE_EXE` is a test-only override
  (`scripts/tests/resilience_test.py`): an executable under `%TEMP%` that runs instead
  of claude, with no server preflight; any other path is refused, and
  `bench/ladder/run.ps1` strips the variable from a rep.

Without `-LisTask` no profile applies; stderr shows `profile: none`. `-LisTask` refuses
`-LisFull`, `-LisNoGuard`, `--tools`, `--settings`, system-prompt options, permission
bypass, `--allowedTools`, `--mcp-config`, `--plugin-dir` and `--add-dir`.
In every profile, with or without `-LisTask`, the wrapper refuses `--settings`,
`--setting-sources`, `--plugin-dir`, `--dangerously-skip-permissions`,
`--allow-dangerously-skip-permissions` and `--permission-mode bypassPermissions`
(ledger S-B5 audit W2): the launcher owns the settings and the hooks, and
`--settings '{"disableAllHooks":true}'` reached claude before. A prompt is not checked.
`-LisPrintArgs` prints the claude arguments and settings JSON and exits without
starting claude.

User scope (ledger S-O3; a session decision of 2026-11-05 that the operator can
overturn, not a ruling): every mode except `-LisFull` passes `--setting-sources
project,local`, so `~\.claude\settings.json` does not load in a local session. Its allow
rules ran commands that no launcher rule allows: the debug log of every ladder run up to
2026-11-04 shows 97 rules loaded to `userSettings`, `Bash(rm:*)`, `Bash(mv:*)`,
`Bash(kill:*)`, `Bash(pkill:*)`, `Bash(sed:*)` and `Bash(find:*)` among them. Its four
deny rules (`.env`, `~/.ssh`, `~/.aws` reads) are also in the per-run settings. Gone
with them: the operator's global hooks, env, model, enabled plugins,
`permissions.defaultMode` (auto) and `autoMode` rules. The working directory's project
and local settings and the per-run `--settings` file still load. Consequences:

- The user `autoMode` rules no longer load. Without `--permission-mode auto` a lean `-p`
  session denies what no launcher rule or hook allows (an interactive session prompts).
  A caller's `--permission-mode auto` is still accepted (`bench/perm` and
  `bench/compact` pass it) and the classifier still runs then: the S-B2 ruling is open.
- `-LisNoGuard` sessions lose the user hooks' kill protection (the operator's
  kill-guard; lis-guard denies the same kill shapes, but `-LisNoGuard` turns it off).
- Bench inputs change against earlier runs where the bench does not pass
  `-LisUserScope` (left so: the lean default is the point): `bench/perm` (its 48 runs of
  2026-10-25 loaded 98 user allow rules and the user `autoMode` rules),
  `bench/loop/run.ps1` (`-LisNoLoopGuard`, no `-LisTask`) and `bench/compact/run.ps1`
  (`--permission-mode auto`).
- Every mode's per-run settings deny Edit (Write included) of
  `**/.claude/settings*.json` (S-O3 audit W4): whether a mid-session change to a
  work-tree settings file reloads is UNVERIFIED, and the deny is cheap.

S-O3 relies on the installed Claude Code build: its changelog, as the S-O3 audit read
it, says "Fixed a settings file excluded with --setting-sources still supplying some
settings, such as auto mode rules".

Flag grammar, CLI reference (read 2026-11-05): "Comma-separated list of setting sources
to load (`user`, `project`, `local`)". The user-scope `CLAUDE.md` and `rules\` files
still load under the flag (verified 2026-11-05: the global CLAUDE.md heading appears in
2 records, 3 occurrences, of the live-proof transcript; ROADMAP, Finding 2026-11-04).
`-LisFull` keeps user scope;
`-LisUserScope` (also `:true`/`:false`) opts it back in for one run, with or without
`-LisTask`. The banner prints `user scope: off (S-O3)`, `user scope: on (-LisUserScope)`
or `user scope: on (-LisFull)`. Ladder reps pass `-LisUserScope`
(`bench/ladder/run.ps1`, ruling (19)), so a rep loads the user scope as every earlier rep
did under the same `rep_key` inputs; `-DryRun` shows it in the session line and the
banner. Live proof (ran 2026-11-05, a lean `-p` session from a scratch directory,
artefacts in `bench/results/so3-proof-20261105/`, gitignored): on its debug log
`grep -c "destination 'userSettings'" <base>.debug.log` prints 0 (2 before: the allow
and the deny line) and `grep -c "destination 'flagSettings'" <base>.debug.log` prints 3.

`LIS_SESSION_START` is the wrapper run's start in ISO 8601 UTC, round-trip format with
7 fraction digits (`2026-11-05T07:37:44.1234567Z`; not truncated to the second, so a file
born in the launch second before the start does not count as session-written), set in
every mode in claude's environment (so the hooks inherit
it) and in the per-run settings `env` (`-LisPrintArgs` shows it); a relaunch keeps the
first value. It is for the hooks (ledger S-B4).

fnm note: if your shell profile runs `fnm env --use-on-cd`, a Bash tool command like
`cd X && node ...` fails inside Claude Code when `X` has a `package.json` ("We can't
find the necessary environment variables to replace the Node version"). Drop
`--use-on-cd` for these sessions, or run `node` without the `cd`.

## 9. Switching models

`serve.ps1` parameters: `-Model`, `-Ctx`, `-Port`, `-NCpuMoe`, `-KvType`, `-Alias`,
`-ChatTemplateFile`, `-WithMmproj`, `-ExtraArgs`, `-ExtraArgLine`, `-LogFile`.

- `-Model` is a local `.gguf` path (relative to the repo root) or a Hugging Face
  `repo:quant`, which `llama-server -hf` downloads on first run.
- KV rule: q4_0 only for the default and fallback files, q8_0 for any other `-Model`,
  unless you pass `-KvType`. MTP rule: only the fallback gets MTP, at `-Ctx 65536` or
  below.
- Template rule: the Saluki, ISTA GSQ-RCO and Orca Uncensored GGUFs need
  `config\chat-templates\qwen3.8-27b.jinja`, or Claude Code gets HTTP 500 "System
  message must be at the beginning."; the default gets it too, and its own embedded
  template is untested. Only files under
  `models\qwen3.8-27b-uncensored` and `models\qwen3.8-27b-gsq-rco` get it on their own;
  pass it for the others.

The fallback (the default until 2026-11-08), from a console with the server log on;
q4_0 KV by rule, no `-KvType` needed, and `-Ctx 65536` adds MTP for it:

```powershell
pwsh -NoProfile -File Z:\repos\kosm1x\local-inference-studio\scripts\stop.ps1
pwsh -NoProfile -File Z:\repos\kosm1x\local-inference-studio\scripts\serve.ps1 -Model models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf -LogFile logs\llama-server.log
```

The scheduled task's arguments stay as they are (no `-Model`), so the task, the
watchdog's restarts and the next logon start the default again. Other models:

```powershell
pwsh scripts\stop.ps1
pwsh scripts\serve.ps1 -Model models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf -KvType q4_0
pwsh scripts\serve.ps1 -Model models\qwen3.8-27b-gsq-rco\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf -Ctx 65536
```

The GSQ-RCO line above runs that file at 65536 with q8_0 KV and no MTP (the setup
config\models.md measured); the same `-Model` with `-KvType q4_0` and no `-Ctx` is the
Model test 1 setup (131072, q4_0, no MTP). For a Qwen3.8-27B file outside those two
folders, run `pwsh -File scripts\serve.ps1 -Model` with that file's path, followed by
this single token:

```powershell
"-ExtraArgLine:--chat-template-file Z:/repos/kosm1x/local-inference-studio/config/chat-templates/qwen3.8-27b.jinja"
```

Download a file first (names and sizes in `config\models.md`). Under `pwsh -File`, a
value that starts with `-` and contains `:` must be the single token
`"-ExtraArgLine:<value>"`, and the path must have no spaces. With a smaller `-Ctx`, pass
the same number to `claude-local.ps1 -LisContextTokens`.

The Scheduled Task: `register-task.ps1` takes no parameters, and its action passes only
`-LogFile`, so the task always serves the `serve.ps1` defaults. To change what it
serves, edit the `param()` defaults in `scripts\serve.ps1`, or add parameters to the
`-Argument` string in `register-task.ps1` and re-run it. If you change the `-Model`
default, also update `$defaultModel` in `serve.ps1`, or the KV rule falls back to q8_0,
and the `default` flag in `models\manifest.json` (`install_verify_test.py` checks that
it names the `-Model` default).

## 10. Benchmarks

Both measure the server already running on :8080; neither starts or stops one.

```powershell
pwsh bench\run.ps1 -Label qwen3.8-27b-orcarouter-gsq-rco -Quant IQ3_XXS-v2.1 -Ctx 131072
pwsh bench\loop\run.ps1 -Label qwen3.8-27b-orcarouter-gsq-rco -LisContextTokens 131072
```

Both lines ran on the default on 2026-11-08 (results under `bench\results\`, stamps
234151 and 234232): decode 48.6 tok/s, 20K prefill 11.8 s, tools 20 of 20, VRAM peak
14,465 MB in about 70 s; the loop passed 3 of 3 with 0 tool errors, median 8 turns and
39.5 s, in about 2.5 min. The loop's `-LisContextTokens` matches the server's `-Ctx`
(the wrapper's own default is 114688, a margin below it).

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
