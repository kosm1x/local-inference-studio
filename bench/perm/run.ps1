#Requires -Version 7.0
<#
.SYNOPSIS
  Replay the permission corpus through scripts/claude-local.ps1 in -p auto mode.
.DESCRIPTION
  One `claude -p` run per Bash command from bench/perm/corpus.jsonl, prompt
  "Run exactly this command with the Bash tool and report its output verbatim: <cmd>".
  -Set A runs rules only (-LisNoGuard), -Set AH runs rules plus scripts/hooks/lis-guard.py
  (-LisNoLoopGuard, so loop-guard denials never mix into the permission counts).
  Per command it records the decision path (rule / hook / classified / denied / blocked),
  permission_denials, classifier requests (debug log stalls and server requests over
  30,000 n_tokens), permission decision ms from the debug log, and wall time.
  Results: bench/results/<stamp>-perm-<set>.json, console tee <stamp>-perm-<set>.log,
  one debug log per run <stamp>-perm-<set>-<n>.debug.log (all gitignored).
  The corpus carries <user> and <vps-host> placeholders; rows with <vps-host> are
  skipped unless $env:LIS_VPS_HOST is set. Never stops or restarts the server; waits
  for /slots to be idle before each run.
.EXAMPLE
  pwsh bench/perm/run.ps1 -Set AH -Sample 24
#>
param(
    [Parameter(Mandatory)][ValidateSet('A', 'AH')][string]$Set,
    [int]$Sample = 0,
    [int]$Seed = 15,
    [int]$MaxTurns = 3,
    [int]$TimeoutSec = 300
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$wrapper = Join-Path $repo 'scripts\claude-local.ps1'
$serverLog = Join-Path $repo 'logs\llama-server.log'
$stamp = Get-Date -Format 'yyyy-MM-ddTHHmmss'
$results = Join-Path $repo 'bench\results'
$base = Join-Path $results "$stamp-perm-$Set"
$cwd = Join-Path $env:TEMP 'lis-perm-cwd'
New-Item -ItemType Directory -Path $cwd -Force | Out-Null
Start-Transcript -LiteralPath "$base.log" | Out-Null

$rows = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'corpus.jsonl') | ForEach-Object { $_ | ConvertFrom-Json } |
        Where-Object { $_.tool -eq 'Bash' })
if ($Sample -gt 0) {
    # Stratified: shuffle each bucket with a fixed seed, then take round-robin across buckets.
    $rng = [System.Random]::new($Seed)
    $queues = [ordered]@{}
    foreach ($g in ($rows | Group-Object bucket | Sort-Object Name)) {
        $q = [System.Collections.Generic.List[object]]::new()
        foreach ($r in ($g.Group | Sort-Object { $rng.Next() })) { $q.Add($r) }
        $queues[$g.Name] = $q
    }
    $picked = [System.Collections.Generic.List[object]]::new()
    while ($picked.Count -lt $Sample -and ($queues.Values | Where-Object { $_.Count })) {
        foreach ($q in $queues.Values) {
            if ($q.Count -and $picked.Count -lt $Sample) { $picked.Add($q[0]); $q.RemoveAt(0) }
        }
    }
    $rows = @($picked)
}

$out = [System.Collections.Generic.List[object]]::new()
$n = 0
foreach ($r in $rows) {
    $n++
    $cmd = $r.command.Replace('<user>', $env:USERNAME)
    if ($cmd.Contains('<vps-host>')) {
        if (-not $env:LIS_VPS_HOST) { $out.Add([pscustomobject][ordered]@{ n = $n; run = $r.run; idx = $r.idx; bucket = $r.bucket; path = 'skipped' }); continue }
        $cmd = $cmd.Replace('<vps-host>', $env:LIS_VPS_HOST)
    }
    $deadline = (Get-Date).AddMinutes(10)
    while (@(Invoke-RestMethod -Uri 'http://127.0.0.1:8080/slots' -Headers @{ Authorization = 'Bearer local' } |
                Where-Object { $_.is_processing }).Count) {
        if ((Get-Date) -gt $deadline) { throw 'server busy for 10 min; the operator may be using it' }
        Start-Sleep -Seconds 15
    }
    $debug = "$base-$n.debug.log"
    $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
    $psi.WorkingDirectory = $cwd
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.RedirectStandardInput = $true
    $wargs = @('-NoProfile', '-File', $wrapper)
    $wargs += if ($Set -eq 'A') { '-LisNoGuard' } else { '-LisNoLoopGuard' }
    $wargs += @('-p', "Run exactly this command with the Bash tool and report its output verbatim: $cmd",
        '--output-format', 'json', '--permission-mode', 'auto', '--max-turns', "$MaxTurns", '--debug-file', $debug)
    foreach ($a in $wargs) { $psi.ArgumentList.Add($a) }
    foreach ($k in 'CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID') { [void]$psi.Environment.Remove($k) }
    $before = (Get-Content -LiteralPath $serverLog).Count
    $t0 = Get-Date
    $p = [System.Diagnostics.Process]::Start($psi)
    $p.StandardInput.Close()
    $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
    $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) {
        # Stop only the claude.exe this run started: the direct child of our pwsh, by validated PID.
        $child = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($p.Id)" | Where-Object Name -eq 'claude.exe'
        foreach ($c in @($child)) {
            $cp = [int]$c.ProcessId
            if ($cp -gt 1) { Stop-Process -Id $cp -Force }
        }
        $p.WaitForExit(20000) | Out-Null
    }
    $wall = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $lines = Get-Content -LiteralPath $serverLog | Select-Object -Skip $before
    $ntok = @($lines | Select-String 'stop processing: n_tokens = (\d+)' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value })
    $dbg = if (Test-Path -LiteralPath $debug) { Get-Content -LiteralPath $debug } else { @() }
    $clsStart = @($dbg | Select-String 'classifier_request_started').Count
    $clsBad = @($dbg | Select-String 'classifier_request_finished .*outcome=(?!ok)').Count
    $hook = @($dbg | Select-String 'lis-guard\.py.*returned permissionDecision: (\w+)' | ForEach-Object { $_.Matches[0].Groups[1].Value })
    $decMs = @($dbg | Select-String 'tool_dispatch_start tool=Bash .*permissionDecisionMs=(\d+)' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value })
    $j = $null
    try { $j = $so.Result | ConvertFrom-Json } catch { }
    $denials = if ($j -and $j.permission_denials) { @($j.permission_denials).Count } else { 0 }
    $path = if ($hook -contains 'deny') { 'denied' }
    elseif ($hook -contains 'allow') { 'hook' }
    elseif ($clsBad) { 'blocked' }
    elseif ($clsStart) { 'classified' }
    elseif ($denials) { 'denied' }
    elseif ($decMs.Count) { 'rule' }
    else { 'no-tool-call' }
    $row = [pscustomobject][ordered]@{
        n = $n; run = $r.run; idx = $r.idx; bucket = $r.bucket; path = $path
        permission_denials = $denials; classifier_requests = $clsStart; classifier_failed = $clsBad
        server_requests_gt30k = @($ntok | Where-Object { $_ -gt 30000 }).Count; server_requests = $ntok.Count
        hook_decisions = ($hook -join ','); decision_ms = ($decMs -join ','); wall_s = $wall; timed_out = $timedOut
        subtype = $j.subtype; num_turns = $j.num_turns
    }
    $out.Add($row)
    "{0,2} {1,-3} {2,-10} cls={3} hook={4,-10} dec_ms={5,-12} denials={6} wall={7}s" -f $n, $r.bucket, $path, $clsStart, $row.hook_decisions, $row.decision_ms, $denials, $wall
}

$summary = [ordered]@{}
foreach ($g in ($out | Group-Object { $_.bucket } | Sort-Object Name)) {
    $summary[$g.Name] = [ordered]@{}
    foreach ($k in 'rule', 'hook', 'classified', 'denied', 'blocked', 'no-tool-call', 'skipped') {
        $summary[$g.Name][$k] = @($g.Group | Where-Object { $_.path -eq $k }).Count
    }
}
$doc = [ordered]@{
    kind = 'perm'; set = $Set; stamp = $stamp; sample = $Sample; seed = $Seed; max_turns = $MaxTurns
    runs = $out.Count; classifier_requests = ($out | Measure-Object classifier_requests -Sum).Sum
    wall_s = ($out | Measure-Object wall_s -Sum).Sum; by_bucket = $summary; rows = $out
}
$doc | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$base.json" -Encoding utf8NoBOM
$summary | ConvertTo-Json -Depth 4
"set=$Set runs=$($doc.runs) classifier_requests=$($doc.classifier_requests) wall_s=$($doc.wall_s)"
Stop-Transcript | Out-Null
