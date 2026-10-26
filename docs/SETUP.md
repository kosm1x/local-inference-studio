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

With no parameters it serves the default file on `127.0.0.1:8080` at ctx 131072, q4_0
KV, flash attention on, one slot, `--api-key local`, model alias `local`, and (for files
under `models\qwen3.8-27b-uncensored`) `--chat-template-file config\chat-templates\qwen3.8-27b.jinja`;
no MTP (ruling 14). MTP (`--spec-type draft-mtp --spec-draft-n-max 2`) is added for the
default file only at `-Ctx 65536` or below (`-NoMtp` turns it off); an explicit `-Ctx`
above 65536 skips the flags with a warning so the model stays all-GPU, and `-NoMtp`
silences the warning.

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
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisContextTokens 65536   # only with serve.ps1 -Ctx 65536
pwsh Z:\repos\kosm1x\local-inference-studio\scripts\claude-local.ps1 -LisFull
```

For this process only, it sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`,
`ANTHROPIC_AUTH_TOKEN=local`, and `ANTHROPIC_MODEL` plus the Opus, Sonnet and Haiku
default aliases to `local`. It unsets `ANTHROPIC_API_KEY` (a real key would be sent to
the local server) and the `CLAUDE_CODE_SUBAGENT_MODEL*` variables, and passes
`--settings config\claude-settings.json` (model and subagent model `local`,
auto-compact at 131072, WebSearch, WebFetch, Agent and Workflow denied; the wrapper
passes a per-run copy in `%TEMP%` with the auto-compact value rewritten to
`-LisContextTokens`). Why: a global `~\.claude\settings.json` that pins cloud models or
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
`-LisFull:false`) omits the three additions for a session that needs the full tool set
or MCP (measured 21,908 tokens from the scratch dir; Agent and Workflow stay denied by
the settings file). Absolute sizes vary by a few hundred tokens with the cwd path and
environment text; the reproducible figure is the lean saving, about 9,172 tokens against
`-LisFull` in the same cwd and about 12,812 against the pre-ruling full set (9,560 and
13,200 before the 2026-10-25 policy block), all measured before the loop guards (+101
tokens).

What a lean session cannot do (`-LisFull` restores these tools and MCP, nothing else):

- task tracking (TodoWrite / Task* tools), NotebookEdit, LSP, Monitor, reading the output
  of a background Bash command, AskUserQuestion, ToolSearch;
- plan mode (EnterPlanMode / ExitPlanMode; interactive behaviour UNVERIFIED);
- WebFetch and WebSearch (denied by the settings file in every local session).

Agent and Workflow are denied in EVERY local session, `-LisFull` included, so skills that
delegate to subagents (`/ship-it`, multi-round-audit, code-review, the `/diagnose` ->
`/sweep` fan-out) cannot run as written locally. A `--tools` or `--append-system-prompt`
you pass yourself lands after the wrapper's; which one wins is UNVERIFIED, so pass
`-LisFull` instead of overriding `--tools`.

Permissions (ruling 15: only writes and deletes of critical files block or ask; the rest
runs). Measured in `docs/permissions-assessment-plan-2026-10-25.md` section 0a.

- Rule set A, in `config/claude-settings.json` `permissions`. `allow`: read-only prefixes
  for host inspection, versions, service state and repo reads, e.g.
  `Bash(powershell -NoProfile -Command \"Get-*)`. The matcher sees the raw command string,
  so a PowerShell rule carries the opening quote of the `-Command` payload, and every
  `;` / `&&` / `|` segment of a command must match. An allowed command skips the auto-mode
  classifier (about 60 s per decision on the local model). Six exact rules run this
  repo's tests from its root, `Bash(python -I scripts/hooks/tests/lis-guard_test.py)`,
  `Bash(python -I scripts/hooks/tests/loop-guard_test.py)`,
  `Bash(python -I bench/ladder/tests/grade_test.py)`,
  `Bash(python -I scripts/tests/verify-doc_test.py)`,
  `Bash(python -I scripts/tests/verify_claims_report_test.py)` and
  `Bash(node --test bench/loop/fixture/test/text.test.js)` (TEST 6 in docs/ROADMAP.md;
  an exact rule stays in auto mode, a wildcard after `node` or `python` is dropped).
  An exact rule trusts the file it names: neither the hook nor the classifier scans
  that file, so editing one of the six test files changes what its rule allows.
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
  forms (`-a`, `--list`, `--show-current`, `-vv`, bare); `curl` and `wmic` have no
  allow rule (the hook allows a read-only `curl` to the local server and `wmic <alias>
  get|list`, and gives no decision on the rest).
  `date`, `nvidia-smi` and `hostname` are allowed only as `date`, `date +*`,
  `nvidia-smi`, `nvidia-smi --query-*`, `nvidia-smi -L*`, `nvidia-smi -q*` and a bare
  `hostname`, so `date -s`, `nvidia-smi -pl` and `hostname <name>` match no allow rule.
  The ask rules `Bash(nvidia-smi * -f*)`, `Bash(nvidia-smi *--filename*)`,
  `Bash(nvidia-smi * -l*)`, `Bash(nvidia-smi *--loop*)` and `Bash(date +* -*)` cover the
  `-f`/`-l` flags and post-format `date` flags those allow prefixes would otherwise
  admit; in `-p` they are denials (LIVE-UNVERIFIED, V14-class).
  Curl has no allow rule: a read-only curl to the local server runs on the hook's allow
  alone, and with `-LisNoGuard` every curl that no rule decides goes to the classifier.
  A user-level allow such as `Bash(curl:*)` in `~/.claude/settings.json` still applies,
  because the wrapper loads user settings: on a machine that has one, any curl that no
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
  `deny`: WebSearch, WebFetch, Agent, Workflow.
- The hook, `scripts/hooks/lis-guard.py` (Python 3, stdlib, `python -I`), which the
  wrapper adds to the per-run settings as a PreToolUse `Bash` hook. It denies a critical
  write or delete anywhere in the command, including inside `powershell -Command "..."`,
  `bash -c '...'`, `wsl ... -- ...` and ssh remote commands (on the VPS side: `rm`,
  `systemctl` other than `status`, `docker` other than read subcommands, `git push`,
  `tee`, `>`, `mv`, `chmod`, `kill`, `apt`, `reboot`); it allows commands whose every
  segment is read-only (ssh read-only VPS review included). For scripts (`bash file`,
  `pwsh -File`, `python file`, `node file`) and interpreter payloads it is the judge of
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
  `python -I scripts\hooks\tests\lis-guard_test.py`.
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
- The limit (V5): a prefix rule cannot see a payload. `Bash(powershell -NoProfile
  -Command \"Get-*)` alone allows `"Get-Date; Remove-Item x"`; only the mid-pattern ask
  rules and the hook catch it. A trailing `*` also spans the rest of an ssh remote
  command, which is why no ssh rule exists and ssh is the hook's job. Reads are not
  guarded: the hook allows `cat` of any file (ruling 15), and the classifier never sees a
  tool's output or a script's content.

All other arguments go straight to `claude` (`-p`, `--max-turns` and so on). The
wrapper options are `-LisContextTokens N` (default 131072, minimum 1024; set it to the
server's `-Ctx` when that is smaller), `-LisFull`, `-LisNoGuard`, `-LisNoLoopGuard`,
`-LisTask NAME` and `-LisPrintArgs`. Success: Claude Code answers and the server log
shows the requests. A `[claude-code:unrecognized_model] {"model":"local"}` line is
harmless.

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
  that the model appends verified figures to, so a compaction cannot lose them.

Without `-LisTask` no profile applies; stderr shows `profile: none`. `-LisTask` refuses
`-LisFull`, `-LisNoGuard`, `--tools`, `--settings`, system-prompt options, permission
bypass, `--allowedTools`, `--mcp-config`, `--plugin-dir` and `--add-dir`.
`-LisPrintArgs` prints the claude arguments and settings JSON and exits without
starting claude.

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
