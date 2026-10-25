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
  -LisNoGuard leaves the hook out (rules only, set A; used by bench/perm/run.ps1).

  There is deliberately no param() block. A declared parameter binds claude's
  positional prompt (or any unmatched token such as --model) to itself and claims
  prefix matches (-m for -MaxContextTokens), and [CmdletBinding()] would drop $args
  and let common parameters (-Verbose, -Debug, -ProgressAction, ...) capture claude's
  -v/-d/-p. The script options, -LisContextTokens N, -LisFull and -LisNoGuard, are taken
  out of $args here. -LisContextTokens defaults to 131072, the default server ctx (ruling 14);
  keep it <= the server's -Ctx.
  A prompt that starts with `-` must be passed after a quoted `'--'` when calling in-process.
.EXAMPLE
  pwsh scripts/claude-local.ps1 -p "list the files in this repo"
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisContextTokens 32768 -p "list the files in this repo"
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisFull
#>
$ErrorActionPreference = 'Stop'

# -LisContextTokens N, -LisContextTokens:N (any case). In-process, PowerShell hands
# -LisContextTokens:N over as '-LisContextTokens:' followed by N, so an empty inline
# value takes the next token. -LisFull, -LisFull:true|false works the same way
# (in-process -LisFull:$false arrives as '-LisFull:' followed by a [bool]).
# All checks run before any env change.
$LisContextTokens = 131072
$LisFull = $false
$LisNoGuard = $false
$claudeArgs = [System.Collections.Generic.List[object]]::new()
$seen = $false
$seenFull = $false
for ($j = 0; $j -lt $args.Count; $j++) {
    $a = $args[$j]
    if ($a -is [string] -and $a -eq '-LisNoGuard') { $LisNoGuard = $true; continue }
    if ($a -is [string] -and $a -match '^-LisFull(:(.*))?$') {
        if ($seenFull) { throw "-LisFull was given more than once." }
        $seenFull = $true
        if (-not $Matches[1]) { $LisFull = $true; continue }
        $v = $Matches[2]
        if (-not $v) {
            if ($j + 1 -ge $args.Count) { throw "-LisFull: needs a value (true or false)." }
            $v = $args[++$j]
        }
        if ($v -is [bool]) { $LisFull = $v; continue }
        $b = $false
        if (-not [bool]::TryParse("$v".TrimStart('$'), [ref]$b)) { throw "-LisFull value '$v' is not true or false." }
        $LisFull = $b
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
$leanArgs = if ($LisFull) { @() } else {
    @('--tools', 'Bash,Read,Edit,Write,Glob,Grep,Skill', '--strict-mcp-config',
      '--mcp-config', $mcpConfig, '--append-system-prompt', $policy)
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
    if (-not $LisNoGuard) {
        $guard = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'hooks\lis-guard.py')).Path.Replace('\', '/')
        if (-not $cfg.hooks) { $cfg.hooks = [ordered]@{} }
        $cfg.hooks['PreToolUse'] = @($cfg.hooks['PreToolUse'] | Where-Object { $_ }) + @([ordered]@{
                matcher = 'Bash'
                hooks   = @([ordered]@{ type = 'command'; command = "python -I `"$guard`""; timeout = 10; onFailure = 'block' })
            })
    }
    $cfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $settings -Encoding utf8NoBOM
    if (-not $LisFull) { Set-Content -LiteralPath $mcpConfig -Value '{"mcpServers":{}}' -Encoding utf8NoBOM }
    foreach ($k in $set.Keys) { Set-Item "env:$k" $set[$k] }
    foreach ($k in $unset) { Remove-Item "env:$k" -ErrorAction Ignore }
    & claude --settings $settings @leanArgs @claudeArgs
    $code = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $settings, $mcpConfig -ErrorAction Ignore
    foreach ($k in $saved.Keys) {
        if ($null -eq $saved[$k]) { Remove-Item "env:$k" -ErrorAction Ignore }
        else { Set-Item "env:$k" $saved[$k] }
    }
}
exit $code
