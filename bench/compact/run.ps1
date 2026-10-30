#Requires -Version 7.0
<#
.SYNOPSIS
  Auto-compaction bench: one read-only `-p` session that grows past the compaction
  threshold, with every request and response captured on the wire by bench/compact/proxy.js.
.DESCRIPTION
  One case per call (the server has one slot). Steps:
  1. Refuses to start if logs/llama-server.log was written in the last 60 s, /slots shows
     a slot processing, or -ProxyPort is already listening.
  2. Scratch tree: `git archive HEAD` extracted to <OS temp>\lis-compact-<case>-<stamp>, so
     nothing the session does lands in this repo. -Pad N adds N generated 60 KB text files
     under docs\pad\ for a longer read list.
  3. The tree's copy of scripts\claude-local.ps1 sets ANTHROPIC_BASE_URL and
     CLAUDE_CODE_MAX_OUTPUT_TOKENS itself, which would override a plain process env, so
     the case's variables (and the proxy URL) are written into the tree's wrapper ($set
     entries) and the tree's config\claude-settings.json env block (CLI-level --settings),
     and set in the child's process env. The repo's own files are not changed.
  4. Starts proxy.js as a thread job (capture <OutDir>\compact-<case>-<stamp>.capture.jsonl),
     runs the session from the tree with the fixed prompt below, stops the job, deletes
     the tree (finally), copies the session transcript, and runs analyze.py.
  Outputs under -OutDir (gitignored): compact-<case>-<stamp>.capture.jsonl, .result.json
  (stdout), .stderr.txt, .debug.log, .proxy.log, .run.log, .transcript.jsonl, .analysis.txt
  and .json (run metadata).
  Schema in bench/compact/README.md. Never starts or stops the server.
  -DryRun prints the env, the tree steps and the exact command lines, and launches nothing.
.EXAMPLE
  pwsh bench/compact/run.ps1 -Case baseline -DryRun
.EXAMPLE
  pwsh bench/compact/run.ps1 -Case pct50-effort-low
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('baseline', 'pct50', 'effort-low', 'pct50-effort-low', 'nothink', 'out32k', 'effort-low-forced')]
    [string]$Case,
    [int]$ProxyPort = 8081,
    [string]$OutDir = (Join-Path $PSScriptRoot '..\results'),
    [int]$Pad = 0,
    [int]$MaxTurns = 60,
    [ValidateRange(1, 600)][int]$TimeoutMin = 120,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

# Case -> extra env. Variable names and definitions: bench/compact/README.md.
$cases = [ordered]@{
    'baseline'         = [ordered]@{}
    'pct50'            = [ordered]@{ CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = '50' }
    'effort-low'       = [ordered]@{ CLAUDE_CODE_EFFORT_LEVEL = 'low' }
    'pct50-effort-low' = [ordered]@{ CLAUDE_AUTOCOMPACT_PCT_OVERRIDE = '50'; CLAUDE_CODE_EFFORT_LEVEL = 'low' }
    'nothink'          = [ordered]@{ MAX_THINKING_TOKENS = '0' }
    'out32k'           = [ordered]@{ CLAUDE_CODE_MAX_OUTPUT_TOKENS = '32768' }
    'effort-low-forced' = [ordered]@{ CLAUDE_CODE_EFFORT_LEVEL = 'low'; CLAUDE_CODE_ALWAYS_ENABLE_EFFORT = '1' }
}
$prompt = 'Read every file under scripts/, bench/, docs/ and config/ one by one with the Read tool, whole files, largest first (use Glob to list them). After each file, state its line count in one sentence. Do not stop until you have read every file; then answer: how many files did you read and what is the total line count?'
$disallowed = 'Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Agent,Skill,Workflow'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$proxyJs = Join-Path $PSScriptRoot 'proxy.js'
$analyzePy = Join-Path $PSScriptRoot 'analyze.py'
$serverLog = Join-Path $repo 'logs\llama-server.log'
# The per-start key scripts/serve.ps1 writes; a server started before that uses 'local'.
$keyFile = Join-Path $repo 'logs\api-key'
$apiKey = if (Test-Path -LiteralPath $keyFile -PathType Leaf) { "$(Get-Content -LiteralPath $keyFile -TotalCount 1)".Trim() }
if (-not $apiKey) { $apiKey = 'local' }
$OutDir = [IO.Path]::GetFullPath($OutDir)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $OutDir "compact-$Case-$stamp"
$capture = "$base.capture.jsonl"
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tree = Join-Path $tempRoot "lis-compact-$Case-$stamp"
$treeWrapper = Join-Path $tree 'scripts\claude-local.ps1'
$treeSettings = Join-Path $tree 'config\claude-settings.json'
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
$pwshExe = (Get-Process -Id $PID).Path

$caseEnv = [ordered]@{ ANTHROPIC_BASE_URL = "http://127.0.0.1:$ProxyPort" }
foreach ($k in $cases[$Case].Keys) { $caseEnv[$k] = $cases[$Case][$k] }
# Every case variable is removed from the child env first, so baseline inherits none.
$caseVars = @($cases.Values | ForEach-Object { $_.Keys }) | Sort-Object -Unique
$stripEnv = '^(CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_(SESSION_ID|SESSION_ATTENDED|CHILD_SESSION|BRIDGE_SESSION_ID|MESSAGING_SOCKET|MESSAGING_TOKEN|ENTRYPOINT))$'

$proxyArgv = @($proxyJs, "$ProxyPort", $capture)
# -LisNoLoopGuard: the cases measure raw compaction and loop behaviour, as in the
# 2026-10-26 captures (loop-guard would deny their repeated calls).
# -LisContextTokens 131072: the contextWindow every recorded case ran at (the wrapper's
# default then; now 114688).
$sessionArgv = @('-NoProfile', '-File', $treeWrapper, '-LisNoLoopGuard', '-LisContextTokens', '131072',
    '-p', $prompt, '--max-turns', "$MaxTurns",
    '--output-format', 'json', '--permission-mode', 'auto', '--disallowedTools', $disallowed,
    '--debug-file', "$base.debug.log")
$wrapperLines = @($caseEnv.Keys | ForEach-Object { "`$set['$_'] = '$($caseEnv[$_])'" })
# The tree's wrapper would read the tree's own logs\api-key, which does not exist, so the
# same resolver lines run inside it against this repo's file (passed in as $repo); the key
# itself never lands in the tree, the dry-run output or the settings env.
$wrapperLines += @("`$repo = '$($repo.Replace("'", "''"))'", '$keyFile = Join-Path $repo ''logs\api-key''', '$apiKey = if (Test-Path -LiteralPath $keyFile -PathType Leaf) { "$(Get-Content -LiteralPath $keyFile -TotalCount 1)".Trim() }', 'if (-not $apiKey) { $apiKey = ''local'' }',
    "`$set['ANTHROPIC_AUTH_TOKEN'] = `$apiKey")

function Format-Cmd([string]$Exe, [object[]]$Argv) {
    $q = @($Exe) + $Argv | ForEach-Object {
        $s = "$_"
        if ($s -match '[\s''"`$;,]' -or $s -eq '') { "'" + $s.Replace("'", "''") + "'" } else { $s }
    }
    return ($q -join ' ')
}
function Say([string]$Message) {
    $line = "[$(Get-Date -Format HH:mm:ss)] $Message"
    Write-Host $line
    if (-not $DryRun) { Add-Content -LiteralPath "$base.run.log" -Value $line }
}
function New-PadText([int]$Seed) {
    $words = 'alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet',
    'kilo', 'lima', 'mike', 'november', 'oscar', 'papa', 'quebec', 'romeo', 'sierra', 'tango',
    'uniform', 'victor', 'whiskey', 'xray', 'yankee', 'zulu', 'window', 'context', 'summary', 'token'
    $rng = [Random]::new($Seed)
    $sb = [Text.StringBuilder]::new()
    $i = 0
    while ($sb.Length -lt 61440) {
        $i++
        $line = "pad $Seed line ${i}:" + (-join (1..12 | ForEach-Object { ' ' + $words[$rng.Next($words.Count)] }))
        [void]$sb.Append($line).Append("`n")
    }
    return $sb.ToString()
}

if ($DryRun) {
    Write-Host "case: $Case"
    Write-Host "child env (process; also written into the tree's wrapper and settings env):"
    foreach ($k in $caseEnv.Keys) { Write-Host "  $k=$($caseEnv[$k])" }
    Write-Host "child env removed first: $($caseVars -join ', ')"
    Write-Host "tree: $tree"
    Write-Host ('  ' + (Format-Cmd 'git' @('-C', $repo, 'archive', '--format=tar', '-o', "$tree.tar", 'HEAD')))
    Write-Host ('  ' + (Format-Cmd $tarExe @('-xf', "$tree.tar", '-C', $tree)))
    Write-Host "  insert before the `$unset line of $treeWrapper`:"
    foreach ($l in $wrapperLines) { Write-Host "    $l" }
    Write-Host "  set env in $treeSettings`: $(($caseEnv.Keys | ForEach-Object { "$_=$($caseEnv[$_])" }) -join ', ')"
    if ($Pad -gt 0) { Write-Host "  pad: $Pad x 60 KB files in $(Join-Path $tree 'docs\pad')" }
    Write-Host "proxy (thread job):"
    Write-Host ('  ' + (Format-Cmd 'node' $proxyArgv))
    Write-Host "session (cwd $tree, timeout $TimeoutMin min):"
    Write-Host ('  ' + (Format-Cmd $pwshExe $sessionArgv))
    Write-Host "analyze:"
    Write-Host ('  ' + (Format-Cmd 'python' @('-I', $analyzePy, $capture, '--result', "$base.result.json", '--transcript', "$base.transcript.jsonl")))
    Write-Host "cleanup: stop the proxy job, delete $tree"
    return
}

# Preflight: one case at a time, never next to another session.
foreach ($p in $proxyJs, $analyzePy) { if (-not (Test-Path -LiteralPath $p)) { throw "missing $p" } }
if ((Test-Path -LiteralPath $serverLog) -and ((Get-Date) - (Get-Item -LiteralPath $serverLog).LastWriteTime).TotalSeconds -lt 60) {
    throw "logs\llama-server.log was written in the last 60 s: another session may be using the server"
}
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 10
if ($health.status -ne 'ok') { throw "/health status is '$($health.status)', expected 'ok'" }
$busy = @(Invoke-RestMethod -Uri 'http://127.0.0.1:8080/slots' -Headers @{ Authorization = "Bearer $apiKey" } -TimeoutSec 10 |
        Where-Object { $_.is_processing })
if ($busy.Count) { throw "a server slot is processing: another session is using the server" }
if (Get-NetTCPConnection -LocalPort $ProxyPort -State Listen -ErrorAction Ignore) { throw "port $ProxyPort is already listening" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$claudeVersion = ("$(& claude --version 2>&1)").Trim()
Say "compact $Case | $claudeVersion | pad $Pad | max-turns $MaxTurns | env $(($caseEnv.Keys | ForEach-Object { "$_=$($caseEnv[$_])" }) -join ' ')"

$job = $null
$proc = $null
$timedOut = $false
$stdout = ''
$stderr = ''
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    # Scratch tree from HEAD (uncommitted changes are not in it).
    New-Item -ItemType Directory -Path $tree | Out-Null
    & git -C $repo archive --format=tar -o "$tree.tar" HEAD
    if ($LASTEXITCODE) { throw "git archive failed ($LASTEXITCODE)" }
    & $tarExe -xf "$tree.tar" -C $tree
    if ($LASTEXITCODE) { throw "tar failed ($LASTEXITCODE)" }
    Remove-Item -LiteralPath "$tree.tar"

    $w = Get-Content -LiteralPath $treeWrapper -Raw
    $anchor = [regex]::Match($w, '(?m)^\$unset = ')
    if (-not $anchor.Success) { throw "anchor `$unset not found in $treeWrapper" }
    $setDecl = [regex]::Match($w, '(?m)^\$set = \[ordered\]@\{')
    if (-not $setDecl.Success -or $setDecl.Index -gt $anchor.Index) {
        throw "`$set = [ordered]@{ not found before the `$unset anchor in $treeWrapper; the inserted `$set lines would not apply"
    }
    $nl = if ($w.Contains("`r`n")) { "`r`n" } else { "`n" }
    $w = $w.Insert($anchor.Index, (($wrapperLines | ForEach-Object { "$_$nl" }) -join ''))
    Set-Content -LiteralPath $treeWrapper -Value $w -NoNewline -Encoding utf8NoBOM
    $cfg = Get-Content -LiteralPath $treeSettings -Raw | ConvertFrom-Json -AsHashtable
    if (-not $cfg.env) { $cfg.env = [ordered]@{} }
    foreach ($k in $caseEnv.Keys) { $cfg.env[$k] = $caseEnv[$k] }
    $cfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $treeSettings -Encoding utf8NoBOM
    if ($Pad -gt 0) {
        $padDir = Join-Path $tree 'docs\pad'
        New-Item -ItemType Directory -Path $padDir | Out-Null
        for ($k = 1; $k -le $Pad; $k++) {
            Set-Content -LiteralPath (Join-Path $padDir "pad-$k.txt") -Value (New-PadText $k) -NoNewline -Encoding utf8NoBOM
        }
    }
    Say "tree $tree ready ($(@(Get-ChildItem -LiteralPath $tree -Recurse -File).Count) files)"

    $job = Start-ThreadJob -ScriptBlock { param($a) & node @a 2>&1 } -ArgumentList (, $proxyArgv)
    $deadline = (Get-Date).AddSeconds(10)
    while ($true) {
        try { if ((Invoke-RestMethod -Uri "http://127.0.0.1:$ProxyPort/health" -TimeoutSec 2).status -eq 'ok') { break } } catch { }
        if ((Get-Date) -gt $deadline) { throw "proxy did not answer on port $ProxyPort within 10 s" }
        Start-Sleep -Milliseconds 300
    }
    Say "proxy up on $ProxyPort -> $capture"

    $psi = [Diagnostics.ProcessStartInfo]::new($pwshExe)
    $psi.WorkingDirectory = $tree
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($k in @($psi.Environment.Keys)) {
        if ($k -match $stripEnv -or $caseVars -contains $k) { $null = $psi.Environment.Remove($k) }
    }
    foreach ($k in $caseEnv.Keys) { $psi.Environment[$k] = $caseEnv[$k] }
    foreach ($a in $sessionArgv) { $psi.ArgumentList.Add($a) }
    Say "session start: $(Format-Cmd $pwshExe $sessionArgv)"
    $proc = [Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Close()
    $so = $proc.StandardOutput.ReadToEndAsync()
    $se = $proc.StandardError.ReadToEndAsync()
    # 1 s polls instead of one long blocking wait, so Ctrl+C reaches the finally below.
    while (-not $proc.WaitForExit(1000)) {
        if ($sw.Elapsed.TotalMinutes -ge $TimeoutMin) { $timedOut = $true; break }
    }
    # Our own process object (the pwsh started above) and its tree, never a looked-up pid.
    if ($timedOut) { $proc.Kill($true); $proc.WaitForExit() }
    $stdout = $so.GetAwaiter().GetResult()
    $stderr = $se.GetAwaiter().GetResult()
} finally {
    # Interrupted or failed while the session ran: same kill, same own process object.
    # A killed wrapper skips its own finally, so its per-pid temp files are removed here.
    if ($proc -and ($timedOut -or -not $proc.HasExited)) {
        if (-not $proc.HasExited) { $proc.Kill($true); $proc.WaitForExit() }
        Remove-Item -LiteralPath (Join-Path $env:TEMP "lis-settings-$($proc.Id).json"), (Join-Path $env:TEMP "lis-mcp-$($proc.Id).json") -ErrorAction Ignore
    }
    if ($job) {
        Stop-Job $job
        Receive-Job $job -ErrorAction Ignore | Out-File -LiteralPath "$base.proxy.log" -Encoding utf8
        Remove-Job $job -Force
    }
    $leaf = Split-Path -Leaf $tree
    if ($tree.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and $leaf -like 'lis-compact-*') {
        Remove-Item -LiteralPath $tree, "$tree.tar" -Recurse -Force -ErrorAction Ignore
        if (Test-Path -LiteralPath $tree) { Write-Host "tree NOT deleted: $tree" }
    }
}
$sw.Stop()

Set-Content -LiteralPath "$base.result.json" -Value $stdout -Encoding utf8NoBOM
Set-Content -LiteralPath "$base.stderr.txt" -Value $stderr -Encoding utf8NoBOM
$res = $null
$jsonLine = @($stdout -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
if ($jsonLine) { try { $res = $jsonLine | ConvertFrom-Json -Depth 50 } catch { $res = $null } }
$transcript = $null
if ($res -and $res.session_id) {
    $src = Get-ChildItem -LiteralPath (Join-Path $HOME '.claude\projects') -Recurse -File -Filter "$($res.session_id).jsonl" -ErrorAction Ignore | Select-Object -First 1
    if ($src) { $transcript = "$base.transcript.jsonl"; Copy-Item -LiteralPath $src.FullName -Destination $transcript }
}
Say ("session end: exit {0} | timed out {1} | wall {2} s | transcript {3}" -f $proc.ExitCode, $timedOut,
    [math]::Round($sw.Elapsed.TotalSeconds, 1), $(if ($transcript) { 'copied' } else { 'not found' }))

$analyzeArgv = @('-I', $analyzePy, $capture, '--result', "$base.result.json")
if ($transcript) { $analyzeArgv += '--transcript', $transcript }
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
& python @analyzeArgv | Tee-Object -FilePath "$base.analysis.txt"

[ordered]@{
    kind           = 'compact'
    case           = $Case
    stamp          = $stamp
    env            = $caseEnv
    pad            = $Pad
    max_turns      = $MaxTurns
    claude_version = $claudeVersion
    prompt         = $prompt
    exit_code      = $proc.ExitCode
    timed_out      = $timedOut
    wall_s         = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    is_error       = if ($res) { [bool]$res.is_error } else { $null }
    num_turns      = $res.num_turns
    capture        = $capture
    transcript     = $transcript
    analysis       = "$base.analysis.txt"
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$base.json" -Encoding utf8NoBOM
