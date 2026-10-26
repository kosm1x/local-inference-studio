#Requires -Version 7.0
<#
.SYNOPSIS
  Agentic-loop bench: Claude Code (scripts/claude-local.ps1) fixes the bench/loop fixture
  -Reps times against the RUNNING server on 127.0.0.1:8080, one JSON result per call.
.DESCRIPTION
  Per repetition: copy bench/loop/fixture to a fresh <WorkRoot>/<stamp>-<Label>/r<N>/work
  (git init + one commit, as the P2 sandbox), hash every file, then run from that dir
    pwsh -NoProfile -File <Launcher> -LisNoLoopGuard [-LisContextTokens N]
      -p <bench/loop/prompt.txt> --output-format json --max-turns <MaxTurns>
      --permission-mode acceptEdits --allowedTools Bash(node:*) Bash(npm:*)
      --debug-file <r<N>/out/debug.log>
  with a -TimeoutMin limit (the process tree is killed when it is reached). Afterwards it
  runs the fixture's tests (node --test, TAP reporter), re-hashes the files and reads:
  the JSON result (stdout), stderr (unrecognized_model and other lines), the debug log
  (tool dispatch outcomes and error codes, [ERROR] lines) and the session transcript
  (~/.claude/projects/*/<session_id>.jsonl, copied to r<N>/out: tool_use counts and
  is_error tool results, classified as format errors or other). Peak VRAM is whole-GPU
  nvidia-smi memory.used sampled every 500 ms during the Claude Code run.
  PASS = all 3 tests pass, no file under test/ changed, added or removed, is_error false
  (a timeout or unparseable stdout is a FAIL).
  Writes -OutDir/<stamp>-loop-<Label>.json and the console to <stamp>-loop-<Label>.log.
  It does not start or stop the server. The work dirs are kept for inspection.
  WorkRoot defaults to %LOCALAPPDATA%\lis-loop, not %TEMP%: under %TEMP% Git Bash shows
  the cwd as /tmp/..., which the Write tool then reads as \tmp\... (P2 run B).
  Session-identity variables of a calling Claude Code session (CLAUDECODE, CLAUDE_PID,
  CLAUDE_CODE_SESSION_ID, ...) are removed from the child environment, so a run started
  by an agent matches one started from a plain terminal.
  -Launcher exists for a dry run with a stub script; the bench always uses the default.
.EXAMPLE
  pwsh bench/loop/run.ps1 -Label qwen3.6-35b-a3b
.EXAMPLE
  pwsh bench/loop/run.ps1 -Label gsq-rco-mtp-c65k -LisContextTokens 65536
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Label,
    [int]$Reps = 3,
    [int]$MaxTurns = 40,
    [int]$LisContextTokens = 0,
    [int]$TimeoutMin = 30,
    [string]$WorkRoot = (Join-Path $env:LOCALAPPDATA 'lis-loop'),
    [string]$OutDir = (Join-Path $PSScriptRoot '..\results'),
    [string]$Launcher = (Join-Path $PSScriptRoot '..\..\scripts\claude-local.ps1')
)
$ErrorActionPreference = 'Stop'

$fixture = Join-Path $PSScriptRoot 'fixture'
$prompt = ((Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'prompt.txt')) -replace '\s+', ' ').Trim()
$testRel = 'test/text.test.js'
$expectedTests = 3
$Launcher = [IO.Path]::GetFullPath($Launcher)
$OutDir = [IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $OutDir "$stamp-loop-$Label.log"
$outFile = Join-Path $OutDir "$stamp-loop-$Label.json"
$runRoot = Join-Path ([IO.Path]::GetFullPath($WorkRoot)) "$stamp-$Label"

function Say([string]$Message) {
    $line = "[$(Get-Date -Format HH:mm:ss)] $Message"
    Write-Host $line
    Add-Content -LiteralPath $logFile -Value $line
}
function Get-Median([double[]]$Values) {
    $s = @($Values | Sort-Object)
    if ($s.Count -eq 0) { return $null }
    if ($s.Count % 2) { return $s[[int][math]::Floor($s.Count / 2)] }
    return ($s[$s.Count / 2 - 1] + $s[$s.Count / 2]) / 2
}
# Relative path (forward slashes) -> sha256, every file except .git/.
function Get-Hashes([string]$Root) {
    $h = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
        Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' } | Sort-Object FullName | ForEach-Object {
            $h[[IO.Path]::GetRelativePath($Root, $_.FullName).Replace('\', '/')] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    return $h
}
function Get-Text($Content) {
    if ($Content -is [string]) { return $Content }
    return (@($Content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join ' ')
}
function Cut([string]$Text, [int]$Max) { if ($Text.Length -gt $Max) { $Text.Substring(0, $Max) } else { $Text } }

$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 10
if ($health.status -ne 'ok') { throw "/health status is '$($health.status)', expected 'ok'" }
$serverBuild = (Invoke-RestMethod -Uri 'http://127.0.0.1:8080/props' -Headers @{ Authorization = 'Bearer local' } -TimeoutSec 10).build_info
$flags = $null
$listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction Ignore | Select-Object -First 1
if ($listener) {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)").CommandLine
    $flags = ($cmd -replace '^\s*("[^"]*"|\S+)\s*', '')
}
$claudeVersion = ("$(& claude --version 2>&1)").Trim()
$nodeVersion = ("$(& node --version 2>&1)").Trim()
Say "loop $Label | server $serverBuild | $claudeVersion | node $nodeVersion | reps $Reps, max-turns $MaxTurns, lis-ctx $(if ($LisContextTokens) { $LisContextTokens } else { 'default' })"
Say "flags: $flags"

$pwshExe = (Get-Process -Id $PID).Path
$stripEnv = '^(CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_(SESSION_ID|SESSION_ATTENDED|CHILD_SESSION|BRIDGE_SESSION_ID|MESSAGING_SOCKET|MESSAGING_TOKEN|ENTRYPOINT))$'
$runs = @()
for ($r = 1; $r -le $Reps; $r++) {
    $repDir = Join-Path $runRoot "r$r"
    $work = Join-Path $repDir 'work'
    $out = Join-Path $repDir 'out'
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    Copy-Item -Recurse -LiteralPath $fixture -Destination $work
    & git -C $work init -q
    & git -C $work add -A
    & git -C $work -c user.name=loop -c user.email=loop@localhost -c commit.gpgsign=false commit -qm 'loop fixture'
    $before = Get-Hashes $work

    $debugFile = Join-Path $out 'debug.log'
    $psi = [Diagnostics.ProcessStartInfo]::new($pwshExe)
    $psi.WorkingDirectory = $work
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($k in @($psi.Environment.Keys)) { if ($k -match $stripEnv) { $null = $psi.Environment.Remove($k) } }
    # -LisNoLoopGuard: no loop-guard, so runs stay comparable with the 10-24 baselines.
    $argv = @('-NoProfile', '-File', $Launcher, '-LisNoLoopGuard')
    if ($LisContextTokens) { $argv += '-LisContextTokens', "$LisContextTokens" }
    $argv += '-p', $prompt, '--output-format', 'json', '--max-turns', "$MaxTurns", '--permission-mode', 'acceptEdits',
        '--allowedTools', 'Bash(node:*)', 'Bash(npm:*)', '--debug-file', $debugFile
    foreach ($a in $argv) { $psi.ArgumentList.Add($a) }

    $vramJob = Start-ThreadJob -ScriptBlock {
        while ($true) { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; Start-Sleep -Milliseconds 500 }
    }
    Say "r$r start in $work"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = [Diagnostics.Process]::Start($psi)
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $timedOut = -not $proc.WaitForExit($TimeoutMin * 60000)
    if ($timedOut) { $proc.Kill($true); $proc.WaitForExit() }
    $sw.Stop()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $proc.ExitCode
    Stop-Job $vramJob
    $vram = @(Receive-Job $vramJob | ForEach-Object { [int]"$_".Trim() })
    Remove-Job $vramJob -Force
    Set-Content -LiteralPath (Join-Path $out 'stdout.json') -Value $stdout
    Set-Content -LiteralPath (Join-Path $out 'stderr.txt') -Value $stderr

    # Tests afterwards, in place (a changed test file fails the run on its own).
    Push-Location -LiteralPath $work
    try { $tap = (& node --test --test-timeout=30000 --test-reporter=tap $testRel 2>&1 | Out-String) } finally { Pop-Location }
    Set-Content -LiteralPath (Join-Path $out 'tests-after.txt') -Value $tap
    $mPass = [regex]::Match($tap, '(?m)^# pass (\d+)')
    $mFail = [regex]::Match($tap, '(?m)^# fail (\d+)')
    $testsPass = if ($mPass.Success) { [int]$mPass.Groups[1].Value } else { 0 }
    $testsFail = if ($mFail.Success) { [int]$mFail.Groups[1].Value } else { $null }

    $after = Get-Hashes $work
    $changed = @($before.Keys | Where-Object { $after.Contains($_) -and $after[$_] -ne $before[$_] })
    $removed = @($before.Keys | Where-Object { -not $after.Contains($_) })
    $added = @($after.Keys | Where-Object { -not $before.Contains($_) })
    $testTouched = @($changed + $removed + $added | Where-Object { $_ -like 'test/*' })

    $res = $null
    $jsonLine = @($stdout -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
    if ($jsonLine) { try { $res = $jsonLine | ConvertFrom-Json -Depth 50 } catch { $res = $null } }

    $stderrLines = @($stderr -split "`r?`n" | Where-Object { $_.Trim() })
    $unrecognized = @($stderrLines | Where-Object { $_ -match 'unrecognized_model' }).Count
    $stderrOther = @($stderrLines | Where-Object {
            $_ -notmatch 'unrecognized_model' -and $_ -notmatch '^claude-local: ' -and
            $_ -notmatch 'claude\.ai connectors are disabled' })

    $dispatch = [ordered]@{}
    $errCodes = [ordered]@{}
    $debugErrors = @()
    if (Test-Path -LiteralPath $debugFile) {
        foreach ($line in [IO.File]::ReadLines($debugFile)) {
            $m = [regex]::Match($line, 'tool_dispatch_end tool=(\S+) .*?outcome=(\w+)')
            if ($m.Success) {
                $t = $m.Groups[1].Value
                if (-not $dispatch.Contains($t)) { $dispatch[$t] = [ordered]@{ calls = 0; errors = 0 } }
                $dispatch[$t].calls++
                if ($m.Groups[2].Value -ne 'ok') { $dispatch[$t].errors++ }
            }
            $m = [regex]::Match($line, 'tool error \(\d+ms\): code=(\S+)')
            if ($m.Success) { $errCodes[$m.Groups[1].Value] = 1 + [int]$errCodes[$m.Groups[1].Value] }
            if ($line -match '\[ERROR\]') { $debugErrors += Cut $line 300 }
        }
    }

    # Transcript of the main session (subagent transcripts are not read).
    $toolUse = [ordered]@{}
    $toolErrors = @()
    $transcript = $null
    if ($res -and $res.session_id) {
        $src = Get-ChildItem -LiteralPath (Join-Path $HOME '.claude\projects') -Recurse -File -Filter "$($res.session_id).jsonl" -ErrorAction Ignore | Select-Object -First 1
        if ($src) {
            $transcript = Join-Path $out 'transcript.jsonl'
            Copy-Item -LiteralPath $src.FullName -Destination $transcript
            foreach ($line in [IO.File]::ReadLines($transcript)) {
                $e = $null
                try { $e = $line | ConvertFrom-Json -Depth 50 } catch { continue }
                if (-not $e.message -or $e.message.content -is [string]) { continue }
                foreach ($b in @($e.message.content)) {
                    if ($e.type -eq 'assistant' -and $b.type -eq 'tool_use') { $toolUse[$b.name] = 1 + [int]$toolUse[$b.name] }
                    if ($e.type -eq 'user' -and $b.type -eq 'tool_result' -and $b.is_error) {
                        $text = (Get-Text $b.content) -replace '\s+', ' '
                        $toolErrors += [ordered]@{
                            format = [bool]($text -match 'InputValidationError|No such tool|Invalid tool|unexpected parameter|required parameter|is missing|Invalid input')
                            text   = Cut $text 200
                        }
                    }
                }
            }
        }
    }

    $u = if ($res) { $res.usage } else { $null }
    $isError = if ($res) { [bool]$res.is_error } else { $true }
    $pass = (-not $timedOut) -and $res -and (-not $isError) -and $testsPass -eq $expectedTests -and $testTouched.Count -eq 0
    $run = [ordered]@{
        rep                         = $r
        pass                        = [bool]$pass
        tests_pass                  = $testsPass
        tests_fail                  = $testsFail
        tests_expected              = $expectedTests
        test_files_touched          = $testTouched
        files_changed               = $changed
        files_added                 = $added
        files_removed               = $removed
        exit_code                   = $exitCode
        timed_out                   = $timedOut
        wall_s                      = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        num_turns                   = $res.num_turns
        duration_ms                 = $res.duration_ms
        duration_api_ms             = $res.duration_api_ms
        is_error                    = $isError
        subtype                     = $res.subtype
        terminal_reason             = $res.terminal_reason
        stop_reason                 = $res.stop_reason
        input_tokens                = $u.input_tokens
        cache_read_input_tokens     = $u.cache_read_input_tokens
        cache_creation_input_tokens = $u.cache_creation_input_tokens
        tokens_in_total             = if ($u) { [long]$u.input_tokens + [long]$u.cache_read_input_tokens + [long]$u.cache_creation_input_tokens } else { $null }
        output_tokens               = $u.output_tokens
        models                      = if ($res.modelUsage) { @($res.modelUsage.PSObject.Properties.Name) } else { @() }
        permission_denials          = @($res.permission_denials | ForEach-Object { $_.tool_name })
        tool_use                    = $toolUse
        tool_errors                 = $toolErrors.Count
        tool_format_errors          = @($toolErrors | Where-Object { $_.format }).Count
        tool_error_samples          = @($toolErrors | Select-Object -First 10)
        dispatch                    = $dispatch
        dispatch_error_codes        = $errCodes
        debug_error_lines           = $debugErrors.Count
        debug_error_samples         = @($debugErrors | Select-Object -First 5)
        stderr_unrecognized_model   = $unrecognized
        stderr_other                = @($stderrOther | Select-Object -First 20)
        vram_mb_peak                = if ($vram.Count) { [int]($vram | Measure-Object -Maximum).Maximum } else { $null }
        result_text                 = if ($res.result) { Cut $res.result 400 } else { $null }
        session_id                  = $res.session_id
        work_dir                    = $work
        transcript                  = $transcript
    }
    $runs += $run
    $apiS = if ($null -ne $run.duration_api_ms) { [math]::Round($run.duration_api_ms / 1000, 1) } else { '-' }
    Say ("r{0} {1}: tests {2}/{3} | test files touched {4} | is_error {5} | turns {6} | wall {7} s | api {8} s | in {9} out {10} | tool errors {11} (format {12}) | denials {13} | vram {14} MiB | exit {15}{16}" -f
        $r, $(if ($pass) { 'PASS' } else { 'FAIL' }), $testsPass, $expectedTests, $testTouched.Count, $isError, $run.num_turns, $run.wall_s,
        $apiS, $run.tokens_in_total, $run.output_tokens, $run.tool_errors, $run.tool_format_errors, $run.permission_denials.Count,
        $run.vram_mb_peak, $exitCode, $(if ($timedOut) { ' TIMEOUT' } else { '' }))
    foreach ($s in $run.tool_error_samples) { Say "   tool error$(if ($s.format) { ' [format]' }): $($s.text)" }
    if ($run.result_text) { Say "   result: $(Cut ($run.result_text -replace '\s+', ' ') 200)" }
}

$ok = @($runs | Where-Object { $null -ne $_.num_turns })
$result = [ordered]@{
    label                    = $Label
    date                     = (Get-Date -Format o)
    server_build             = $serverBuild
    flags                    = $flags
    claude_version           = $claudeVersion
    node_version             = $nodeVersion
    lis_context_tokens       = if ($LisContextTokens) { $LisContextTokens } else { 131072 }
    max_turns                = $MaxTurns
    timeout_min              = $TimeoutMin
    prompt                   = $prompt
    reps                     = $Reps
    runs_passed              = @($runs | Where-Object { $_.pass }).Count
    median_turns             = Get-Median ($ok | ForEach-Object { $_.num_turns })
    median_wall_s            = Get-Median ($runs | ForEach-Object { $_.wall_s })
    median_api_s             = Get-Median ($ok | ForEach-Object { $_.duration_api_ms / 1000 })
    median_tokens_in         = Get-Median ($ok | ForEach-Object { $_.tokens_in_total })
    median_tokens_out        = Get-Median ($ok | ForEach-Object { $_.output_tokens })
    tool_errors_total        = [int]($runs | ForEach-Object { $_.tool_errors } | Measure-Object -Sum).Sum
    tool_format_errors_total = [int]($runs | ForEach-Object { $_.tool_format_errors } | Measure-Object -Sum).Sum
    vram_mb_peak             = ($runs | ForEach-Object { $_.vram_mb_peak } | Where-Object { $_ } | Measure-Object -Maximum).Maximum
    runs                     = $runs
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $outFile -Encoding utf8
$medApi = if ($null -ne $result.median_api_s) { [math]::Round($result.median_api_s, 1) } else { '-' }
Say ("loop {0}: {1}/{2} PASS | median turns {3} | wall {4} s | api {5} s | in {6} out {7} | tool errors {8} (format {9}) | vram peak {10} MiB -> {11}" -f
    $Label, $result.runs_passed, $Reps, $result.median_turns, $result.median_wall_s, $medApi,
    $result.median_tokens_in, $result.median_tokens_out, $result.tool_errors_total, $result.tool_format_errors_total, $result.vram_mb_peak, $outFile)
