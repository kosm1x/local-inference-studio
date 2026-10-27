#Requires -Version 7.0
<#
.SYNOPSIS
  Run Claude Code against the local llama-server. Extra arguments go to `claude`.
.DESCRIPTION
  Sets the env block from docs/landscape-2026-10-24.md for this process only, runs
  `claude @args`, then restores the previous values so the calling shell is unchanged.

  IMPORTANT (this machine): ~/.claude/settings.json pins subagents to Opus via
  CLAUDE_CODE_SUBAGENT_MODEL=opus + CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1, and the main
  session to `model: fable`. Neither model exists locally.
  - The two SUBAGENT vars are unset for the child below. They are also defined in the
    settings.json `env` block, which Claude Code applies itself and which may win over
    the process env, so config/claude-settings.json is passed via --settings to set
    CLAUDE_CODE_SUBAGENT_MODEL=local and model=local at CLI precedence.
  - ANTHROPIC_MODEL must override `model: fable`.
  Both are VERIFIED (Phase 2 run 2026-10-24): all requests reached 127.0.0.1:8080
  with model `local`, including subagents; see docs/ROADMAP.md.
  The --settings file is a per-run copy of config/claude-settings.json in $env:TEMP
  (lis-settings-<pid>.json, deleted on exit) whose env.CLAUDE_CODE_AUTO_COMPACT_WINDOW
  is rewritten to -LisContextTokens, so the settings env and the process env agree.

  Lean set (ruling 13), added before the forwarded arguments:
  --tools Bash,Read,Edit,Write,Glob,Grep,Skill, --strict-mcp-config --mcp-config with a
  per-run empty {"mcpServers":{}} file ($env:TEMP\lis-mcp-<pid>.json, deleted on exit),
  and --append-system-prompt with the one-model policy (docs/context-audit-2026-10-24.md
  section 5) plus an evidence and machine-survey block. Hooks stay on. -LisFull omits
  all three for a session that needs the full tool set or MCP; Agent and Workflow stay
  denied by config/claude-settings.json.

  Permissions (ruling 15): the per-run settings carry rule set A from
  config/claude-settings.json plus a PreToolUse Bash hook, scripts/hooks/lis-guard.py
  (run as `python -I <repo path>`), added here so the committed JSON holds no absolute
  path. The hook denies critical writes, also inside interpreter and ssh payloads,
  and allows read-only commands and read-only scripts; see docs/SETUP.md step 8.
  A PostToolUse Write|Edit hook, scripts/verify-doc.py --hook, checks the figures in
  every .md the session writes inside the working directory and feeds them back.
  -LisNoGuard leaves both hooks out (rules only, set A; used by bench/perm/run.ps1).
  A PreToolUse hook on every tool, scripts/hooks/loop-guard.py, denies the 4th identical
  call within the last 12 counted calls (docs/SETUP.md step 8). -LisNoGuard drops it too;
  -LisNoLoopGuard drops only it (benches that measure raw loop behaviour).

  Task profiles (ROADMAP "Trust ladder"): -LisTask review|edit|longrun is chosen by the
  person launching the session and nothing in the session can change it. A profile sets
  --tools, appends a policy block that starts "Task profile: <name>" (so the transcript
  carries it), may add deny rules to the per-run settings, and prints to stderr, before
  launch and after exit, the verifier lines the person runs when the session ends.
  review: no Edit/Write (also denied by rule), the deliverable is the final answer.
  edit: the lean tool set, change only the named files, test before and after.
  longrun: as edit, plus a facts file in the working directory (lis-facts-<stamp>.md)
  that the model appends to so a compaction cannot lose verified figures.
  Without -LisTask no profile applies (loop-guard still registers unless -LisNoGuard or
  -LisNoLoopGuard); stderr shows "profile: none".
  -LisTask cannot be combined with -LisFull, with -LisNoGuard or with claude options that
  would override what it fixes (--tools, --settings, system-prompt options, permission
  bypass, --allowedTools, --mcp-config, --plugin-dir, --add-dir).
  -LisPrintArgs prints the claude argument list and the settings JSON to stdout and
  exits 0 without writing temp files, changing the environment or launching claude.

  There is deliberately no param() block. A declared parameter binds claude's
  positional prompt (or any unmatched token such as --model) to itself and claims
  prefix matches (-m for -MaxContextTokens), and [CmdletBinding()] would drop $args
  and let common parameters (-Verbose, -Debug, -ProgressAction, ...) capture claude's
  -v/-d/-p. The script options, -LisContextTokens N, -LisFull, -LisNoGuard,
  -LisNoLoopGuard, -LisTask NAME and -LisPrintArgs, are taken out of $args here.
  -LisContextTokens defaults to 131072, the default server ctx (ruling 14); keep it <=
  the server's -Ctx.
  A switch value (-LisFull:V, -LisNoGuard:V, ...) is true or false only; any other value
  is an error, and a word after a bare switch is a prompt.
  A prompt that starts with `-` must be passed after a quoted `'--'` when calling in-process.
  A claude argument that is exactly a Lis flag is consumed by the wrapper (e.g. the prompt
  in `-p -LisNoGuard`), so pass a prompt as one quoted string.
.EXAMPLE
  pwsh scripts/claude-local.ps1 -p "list the files in this repo"
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisContextTokens 32768 -p "list the files in this repo"
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisFull
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisTask review -LisPrintArgs
#>
$ErrorActionPreference = 'Stop'

# -LisContextTokens N, -LisContextTokens:N (any case). In-process, PowerShell hands
# -LisContextTokens:N over as '-LisContextTokens:' followed by N, so an empty inline
# value takes the next token. The switches -LisFull, -LisNoGuard, -LisNoLoopGuard and
# -LisPrintArgs take :true|false the same way (in-process -LisFull:$false arrives as
# '-LisFull:' followed by a [bool]). All checks run before any env change.
$LisContextTokens = 131072
$LisFull = $false
$LisNoGuard = $false
$LisNoLoopGuard = $false
$LisTask = $null
$LisPrintArgs = $false
$claudeArgs = [System.Collections.Generic.List[object]]::new()
$seen = $false
$seenSwitch = @{}
$switchRe = '(?s)^-(LisFull|LisNoGuard|LisNoLoopGuard|LisPrintArgs)(:(.*))?\z'
# pwsh -File passes -X:true|false as '-X' followed by a [bool] but -X:0 as '-X' followed
# by the string '0', the same as '-X 0'. Only the process command line keeps the colon,
# so when this script is the -File target ($MyInvocation.Line is empty) check it there.
if (-not $MyInvocation.Line) {
    foreach ($r in [Environment]::GetCommandLineArgs()) {
        if ($r -notmatch $switchRe -or -not $Matches[2]) { continue }
        $name, $v = $Matches[1], $Matches[3]
        if (-not $v) { throw "-${name}: needs its value in the same token (-${name}:true or -${name}:false) when run with pwsh -File." }
        if ($v -notmatch '^\$?(true|false)\z') { throw "-$name value '$v' is not true or false." }
    }
}
for ($j = 0; $j -lt $args.Count; $j++) {
    $a = $args[$j]
    if ($a -is [string] -and $a -match $switchRe) {
        $name = $Matches[1]
        if ($seenSwitch[$name]) { throw "-$name was given more than once." }
        $seenSwitch[$name] = $true
        if (-not $Matches[2]) {
            # No colon (pwsh -File passes -X:false as '-X' followed by a [bool]): only a
            # following [bool] is the value; a string after a bare switch is a prompt.
            $on = if ($args[$j + 1] -is [bool]) { $args[++$j] } else { $true }
            Set-Variable -Name $name -Value $on
            continue
        }
        # -X:V, or in-process '-X:' followed by V (a [bool], a string or a number).
        $v = $Matches[3]
        if (-not $v) {
            if ($j + 1 -ge $args.Count) { throw "-${name}: needs a value (true or false)." }
            $v = $args[++$j]
        }
        $on = $false
        if ($v -is [bool]) { $on = $v }
        elseif (-not [bool]::TryParse("$v".TrimStart('$'), [ref]$on)) { throw "-$name value '$v' is not true or false." }
        Set-Variable -Name $name -Value $on
        continue
    }
    # -LisTask NAME, -LisTask:NAME; the set check stands in for ValidateSet (no param()).
    if ($a -is [string] -and $a -match '^-LisTask(:(.*))?$') {
        if ($LisTask) { throw "-LisTask was given more than once." }
        $v = $Matches[2]
        if (-not $v) {
            if ($j + 1 -ge $args.Count) { throw "-LisTask needs a value (review, edit or longrun)." }
            $v = "$($args[++$j])"
        }
        if ($v -notin 'review', 'edit', 'longrun') { throw "-LisTask value '$v' is not review, edit or longrun." }
        $LisTask = $v.ToLower()
        continue
    }
    if ($a -isnot [string] -or $a -notmatch '^-LisContextTokens(:(.*))?$') { $claudeArgs.Add($a); continue }
    if ($seen) { throw "-LisContextTokens was given more than once." }
    $seen = $true
    $v = $Matches[2]
    if (-not $v) {
        if ($j + 1 -ge $args.Count) { throw "-LisContextTokens needs a value (an integer >= 1024)." }
        $v = "$($args[++$j])"
    }
    $n = 0
    if (-not [int]::TryParse($v, [ref]$n)) { throw "-LisContextTokens value '$v' is not an integer." }
    if ($n -lt 1024) { throw "-LisContextTokens value $n is below the minimum of 1024." }
    $LisContextTokens = $n
}
if ($LisTask) {
    if ($LisFull) { throw "-LisTask cannot be combined with -LisFull: the profile sets --tools and the policy." }
    if ($LisNoGuard) {
        throw ('-LisTask cannot be combined with -LisNoGuard: ' +
            'the profile fixes permissions, guard hooks included.')
    }
    $override = '^--(tools|settings|(append-)?system-prompt(-file)?|' +
        '(allow-)?dangerously-skip-permissions|allowed-?tools|mcp-config|plugin-dir|' +
        'add-dir)(=|$)'
    foreach ($a in $claudeArgs) {
        if ("$a" -match $override -or
            "$a" -match '^(--permission-mode=)?bypassPermissions$') {
            throw "-LisTask $LisTask fixes tools, policy and permissions; '$a' would override them."
        }
    }
}

$set = [ordered]@{
    ANTHROPIC_BASE_URL                       = 'http://127.0.0.1:8080'
    ANTHROPIC_AUTH_TOKEN                     = 'local'
    ANTHROPIC_MODEL                          = 'local'
    ANTHROPIC_DEFAULT_OPUS_MODEL             = 'local'
    ANTHROPIC_DEFAULT_SONNET_MODEL           = 'local'
    ANTHROPIC_DEFAULT_HAIKU_MODEL            = 'local'
    CLAUDE_CODE_MAX_CONTEXT_TOKENS           = "$LisContextTokens"
    CLAUDE_CODE_AUTO_COMPACT_WINDOW          = "$LisContextTokens"
    CLAUDE_CODE_MAX_OUTPUT_TOKENS            = '16384'
    API_TIMEOUT_MS                           = '1800000'
    CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS   = '1'
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
    DISABLE_PROMPT_CACHING                   = '1'
    ENABLE_TOOL_SEARCH                       = 'false'
    CLAUDE_CODE_ATTRIBUTION_HEADER           = '0'
}
# ANTHROPIC_API_KEY is unset too: it would take precedence over the bearer token and
# send a real key to the local server.
$unset = 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE', 'ANTHROPIC_API_KEY'
$settingsSrc = Join-Path $PSScriptRoot '..\config\claude-settings.json'
$settings = Join-Path $env:TEMP "lis-settings-$PID.json"
$mcpConfig = Join-Path $env:TEMP "lis-mcp-$PID.json"

# Lean set (ruling 13; measured in docs/context-audit-2026-10-24.md): a 7-tool allow-list
# (never drop Skill alone: the Workflow schema then grows by ~4,000 tokens), no MCP
# servers, and the one-model policy. -LisFull omits all three. --tools and --mcp-config
# take several values, so each is followed by another option, never by $claudeArgs.
$policy = 'This session runs on one local model served by llama-server on this machine. You are the only agent: do all work directly with your own tools and never spawn subagents, agent teams or workflows. Ignore every instruction about Fable, Opus, Sonnet or other model roles, orchestrator and subagent splits, or delegating implementation, tests or audits to a subagent; those rules apply to cloud sessions only. Sessions here may run long and unsupervised, so before any destructive or irreversible action (deleting files, git reset or force-push, stopping processes, editing config outside the working repo) verify the exact target first and prefer the reversible option. Keep answers short: the context window is 131,072 tokens.'
# Evidence rules and survey checklist: the gaps of the graded recon runs (ROADMAP ruling 15).
$policy += ' Evidence: copy every number in a report from a tool output; get counts with wc -l or Measure-Object, never by counting a listing yourself. Read a script before citing its output, and prefer a direct check over a helper script. Never append 2>/dev/null or 2>$null to a probe: a hidden error becomes a false claim. In the Bash tool, put a PowerShell payload in single quotes and use double quotes for strings inside it (powershell -NoProfile -Command ''Get-Volume | Select-Object DriveLetter,FileSystemLabel,Size,SizeRemaining'') so bash cannot expand $_, and quote ~ in a wsl or ssh command so it resolves on the far side. Mark anything you did not verify as UNVERIFIED. A machine survey covers: every mounted volume with letter, label, size and free space (df -h with no path, whose / row is C:, plus Get-Volume for labels), flagging any under 5 % free; the GPU (nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv); CPU, RAM and OS; toolchain versions; Docker (docker version) and WSL (wsl -l -v) state; the llama-server process (tasklist //FI "IMAGENAME eq llama-server.exe") and its loaded model (curl -sS http://127.0.0.1:8080/props -H ''Authorization: Bearer local'' | grep -o ''"model_path":"[^"]*"''; every endpoint except /health needs that header); and VPS reachability (wsl -d Ubuntu -- ssh -o BatchMode=yes -o ConnectTimeout=10 -i ''~/.ssh/vps-backup'' root@<ip> uptime, with the VPS IP address given in CLAUDE.md, not the mail alias).'
# Loop guards: the gaps of TEST 6 rep 1 (ROADMAP, TEST 6).
$policy += ' Plain reads may run in parallel; per Bash batch run at most one command that executes a program, writes, or changes state. If a command is rejected because its permission check timed out, retry it once; if that also fails, mark the figure UNVERIFIED and move on. Do no checks the task does not need: no re-runs on other platforms, no side investigations. For a file over 300 lines, grep it or read a line range, not the whole file.'
# Task profiles (ROADMAP "Trust ladder"): the person launching picks one; the policy never
# lets the model widen it. A profile block names the profile so the transcript carries it.
$tools = 'Bash,Read,Edit,Write,Glob,Grep,Skill'
$factsFile = 'lis-facts-{0:yyyyMMdd-HHmmss}.md' -f (Get-Date)
$profiles = @{
    review  = @{ tools = 'Bash,Read,Glob,Grep,Skill'; deny = @('Edit', 'Write', 'NotebookEdit')
        policy = ' Task profile: review, set by the person who launched this session; you cannot change it. You have no Edit or Write tool; do not create, change or delete any file by other means either (no redirection, tee, sed -i, Set-Content or a script that writes). Give the deliverable as your final answer in Markdown: the person saves it and runs verify-doc and verify-claims on it, so every number must trace to a tool output in this session and every path must exist. If the task asks you to write a file, say that the review profile cannot and put the content in your answer. Never ask for more tools or permissions, and never work around a denial.' }
    edit    = @{ tools = $tools; deny = @()
        policy = ' Task profile: edit, set by the person who launched this session; you cannot change it. Change only the files the task names; if another file must change, stop and say which and why instead of editing it. Run the test command the task gives before and after editing and copy both results. Never edit, skip or delete a test to make it pass unless the task says so. End with a Markdown report: every file you changed, the test command, and its pass and fail counts from the output. The person checks that report with verify-doc and verify-claims and compares your file list with git diff. Never ask for more tools or permissions, and never work around a denial.' }
    longrun = @{ tools = $tools; deny = @()
        policy = ' Task profile: longrun, set by the person who launched this session; you cannot change it. Compaction will drop earlier turns. Keep a facts file, ' + $factsFile + ', in the working directory: create it first, then after each step append (never rewrite) each verified figure with the command that produced it, each file changed and the next step. After a compaction, read it before anything else, and take report figures from it, not from memory. The edit rules apply: change only the files the task names, run the task''s test before and after editing and copy both results, never edit or skip a test to pass it. Never ask for more tools or permissions, and never work around a denial.' }
}
if ($LisTask) { $tools = $profiles[$LisTask].tools; $policy += $profiles[$LisTask].policy }
$leanArgs = if ($LisFull) { @() } else {
    @('--tools', $tools, '--strict-mcp-config',
      '--mcp-config', $mcpConfig, '--append-system-prompt', $policy)
}

# Verifier lines for the person (stderr, before launch and after exit), run from the
# session's working directory. The tests are this repo's (CLAUDE.md), from its root.
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$docChecks = @("python -I `"$repo\scripts\verify-doc.py`" <deliverable.md>",
    "pwsh `"$repo\scripts\verify-claims.ps1`" -Document <deliverable.md>")
$testChecks = @(if (Test-Path -LiteralPath 'scripts/hooks/tests/lis-guard_test.py') {
    @('python -I scripts/hooks/tests/lis-guard_test.py', 'python -I scripts/hooks/tests/loop-guard_test.py',
      'python -I scripts/tests/verify-doc_test.py',
      'python -I scripts/tests/verify_claims_report_test.py', 'python -I bench/ladder/tests/grade_test.py',
      'python -I bench/ladder/tests/gen_longfix_test.py', 'python -I bench/ladder/tests/longrun_test.py',
      'python -I bench/ladder/tests/gen_stalefig_test.py', 'python -I bench/ladder/tests/stalefig_test.py',
      'node --test bench/loop/fixture/test/text.test.js')
} else { '<the test command the task names>' })
$scope = 'git diff --stat; git status --porcelain   # expect only the files the task named'
$checks = switch ($LisTask) {
    'review' { $docChecks + 'git status --porcelain   # expect empty, or only the saved deliverable' }
    'edit' { $testChecks + $scope + $docChecks }
    'longrun' {
        $testChecks + ($scope + ", plus ?? $factsFile") + $docChecks +
        "(Get-Content -LiteralPath '$factsFile' | Measure-Object -Line).Lines   # expect > 0"
    }
}
function Write-LisBanner {
    $e = [Console]::Error
    if (-not $LisTask) { $e.WriteLine('claude-local: profile: none'); return }
    $guardState = if ($LisNoGuard) { 'off' } elseif ($LisNoLoopGuard) { 'on, loop-guard off' } else { 'on' }
    $e.WriteLine("claude-local: profile: $LisTask   tools: $tools   guard: $guardState")
    $denied = $profiles[$LisTask].deny
    $e.WriteLine('claude-local: rules added: ' + $(if ($denied) { 'deny ' + ($denied -join ', ') } else { 'none' }))
    $e.WriteLine('claude-local: verifier, run from this directory when the session ends (fill in <...>):')
    foreach ($c in $checks) { $e.WriteLine("  $c") }
}

# Unset with Remove-Item: [Environment]::SetEnvironmentVariable($k, $null) leaves the
# variable defined as "" in PowerShell 7.6 / .NET 10.
$saved = @{}
foreach ($k in @($set.Keys) + $unset) {
    $saved[$k] = if (Test-Path "env:$k") { (Get-Item "env:$k").Value } else { $null }
}
$code = 1
try {
    $cfg = Get-Content -LiteralPath $settingsSrc -Raw | ConvertFrom-Json -AsHashtable
    if (-not $cfg.env) { $cfg.env = [ordered]@{} }
    $cfg.env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = "$LisContextTokens"
    # Path rules written as Edit(~/...) become Edit(//c/Users/<name>/...), the form
    # verified on this machine; the committed JSON carries no user name.
    $h = $HOME.Replace('\', '/')
    $homeRule = '//' + $h.Substring(0, 1).ToLower() + $h.Substring(2)
    foreach ($kind in 'allow', 'ask', 'deny') {
        if ($cfg.permissions -and $cfg.permissions[$kind]) {
            $cfg.permissions[$kind] = @($cfg.permissions[$kind] | ForEach-Object { $_.Replace('Edit(~/', "Edit($homeRule/") })
        }
    }
    if ($LisTask -and $profiles[$LisTask].deny) {
        $cfg.permissions['deny'] = @($cfg.permissions['deny']) + $profiles[$LisTask].deny
    }
    if (-not $LisNoGuard) {
        $guard = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'hooks\lis-guard.py')).Path.Replace('\', '/')
        if (-not $cfg.hooks) { $cfg.hooks = [ordered]@{} }
        $cfg.hooks['PreToolUse'] = @($cfg.hooks['PreToolUse'] | Where-Object { $_ }) + @([ordered]@{
                matcher = 'Bash'
                hooks   = @([ordered]@{ type = 'command'; command = "python -I `"$guard`""; timeout = 10; onFailure = 'block' })
            })
        if (-not $LisNoLoopGuard) {
            # loop-guard: denies an identical tool call repeated 3+ times in the last 12
            # counted calls; no onFailure = 'block', so a guard error never blocks a call
            # (docs/SETUP.md step 8).
            $loop = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'hooks\loop-guard.py')).Path.Replace('\', '/')
            $cfg.hooks['PreToolUse'] = @($cfg.hooks['PreToolUse'] | Where-Object { $_ }) + @([ordered]@{
                    matcher = '*'
                    hooks   = @([ordered]@{ type = 'command'; command = "python -I `"$loop`""; timeout = 5 })
                })
        }
        # verify-doc: deterministic figure checks on every .md the session writes or edits,
        # fed back to the model as additionalContext (docs/SETUP.md step 8).
        $verify = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'verify-doc.py')).Path.Replace('\', '/')
        $cfg.hooks['PostToolUse'] = @($cfg.hooks['PostToolUse'] | Where-Object { $_ }) + @([ordered]@{
                matcher = 'Write|Edit'
                hooks   = @([ordered]@{ type = 'command'; command = "python -I `"$verify`" --hook"; timeout = 30 })
            })
    }
    $json = $cfg | ConvertTo-Json -Depth 10
    Write-LisBanner
    if ($LisPrintArgs) {
        # Nothing is written, no env changes, claude is not started.
        'claude arguments (JSON array, in order):'
        ConvertTo-Json -InputObject (@('--settings', $settings) + $leanArgs + @($claudeArgs))
        'settings JSON (the --settings file):'
        $json
        $code = 0
    } else {
        Set-Content -LiteralPath $settings -Value $json -Encoding utf8NoBOM
        if (-not $LisFull) { Set-Content -LiteralPath $mcpConfig -Value '{"mcpServers":{}}' -Encoding utf8NoBOM }
        foreach ($k in $set.Keys) { Set-Item "env:$k" $set[$k] }
        foreach ($k in $unset) { Remove-Item "env:$k" -ErrorAction Ignore }
        & claude --settings $settings @leanArgs @claudeArgs
        $code = $LASTEXITCODE
        if ($LisTask) { Write-LisBanner }
    }
} finally {
    Remove-Item -LiteralPath $settings, $mcpConfig -ErrorAction Ignore
    foreach ($k in $saved.Keys) {
        if ($null -eq $saved[$k]) { Remove-Item "env:$k" -ErrorAction Ignore }
        else { Set-Item "env:$k" $saved[$k] }
    }
}
exit $code
