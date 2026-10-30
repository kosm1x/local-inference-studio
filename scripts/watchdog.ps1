#Requires -Version 7.0
<#
.SYNOPSIS
  Restart a hung or dead llama-server: poll /health, then stop.ps1 + Start-ScheduledTask.
.DESCRIPTION
  Polls http://127.0.0.1:<Port>/health every -IntervalSec seconds (default 60), each with a
  -TimeoutSec timeout (default 10). A poll fails on a timeout, a refused connection, an
  HTTP error (503 while the model loads counts) or a status other than "ok". After
  -FailThreshold consecutive failures (default 3) it restarts the server, unless
  -MaxRestartsPerHour restarts (default 3) already ran in the last hour.
  A restart runs scripts/stop.ps1 -Port <Port> -FromWatchdog -Reason "watchdog: ..."
  (which also writes logs/.stop-requested-<Port>, so a serve.ps1 still running exits
  instead of restarting),
  waits up to 60 s for the scheduled task -TaskName to leave the Running state (the task
  ignores a second start while one runs), then runs -StartCommand with the task name
  (default: Start-ScheduledTask -TaskName <name>); the new serve.ps1 deletes the stop
  file. When the start command throws or the 60 s wait expires, the watchdog deletes the
  stop file if it wrote it itself (its marker carries "(watchdog: ") and logs "start
  failed, clearing own stop request", so a later serve.ps1 restart is not blocked.
  The failure count restarts at 0 after a restart, so the model has -FailThreshold polls
  to load. scripts/serve.ps1 restarts llama-server itself after a crash (up to 5 times an
  hour); this watchdog covers a server that hangs with its port open and a serve.ps1 that
  gave up or died.
  While logs/.stop-requested-<Port> exists and was written by an operator's stop.ps1 (no
  "(watchdog: " reason) it does not poll at all (paused), and resumes when the file is
  gone; its own stop request never pauses it. Logs to -LogFile (default logs/watchdog.log
  under the repo root): start, failed polls up to the threshold, the first ok poll after a
  failure, each restart, and pause, resume and budget refusals once per episode. An error
  inside a poll (a failed log write included) is logged, or written to stderr when the
  log cannot be written, and the next poll runs. -MaxPolls N stops after N polls (0 = run
  forever; tests).
  Register at logon with scripts/register-watchdog.ps1.
.EXAMPLE
  pwsh -NoProfile -File scripts/watchdog.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8080,
    [ValidateRange(0, 3600)][int]$IntervalSec = 60,
    [ValidateRange(1, 600)][int]$TimeoutSec = 10,
    [ValidateRange(1, 100)][int]$FailThreshold = 3,
    [ValidateRange(0, 100)][int]$MaxRestartsPerHour = 3,
    [string]$TaskName = 'LocalInferenceStudio-llama-server',
    [scriptblock]$StartCommand = { param($Name) Start-ScheduledTask -TaskName $Name },
    [string]$LogFile = (Join-Path $PSScriptRoot '..\logs\watchdog.log'),
    [ValidateRange(0, [int]::MaxValue)][int]$MaxPolls = 0
)
$ErrorActionPreference = 'Stop'

$stopFile = Join-Path $PSScriptRoot "..\logs\.stop-requested-$Port"
$stopScript = Join-Path $PSScriptRoot 'stop.ps1'
$url = "http://127.0.0.1:$Port/health"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null
function Write-WatchLog([string]$Line) { Add-Content -LiteralPath $LogFile -Value "[$(Get-Date -Format o)] $Line" }
# A stop request written by this watchdog's own Restart-Server (stop.ps1 -Reason "watchdog: ...").
function Test-OwnStopRequest {
    "$(Get-Content -LiteralPath $stopFile -TotalCount 1 -ErrorAction Ignore)" -match '^\[stop\.ps1\] stop requested \S+ \(watchdog: '
}

function Restart-Server([string]$Why) {
    try { & $stopScript -Port $Port -FromWatchdog -Reason "watchdog: $Why" *>&1 | ForEach-Object { Write-WatchLog "stop.ps1: $_" } }
    catch { Write-WatchLog "stop.ps1 failed: $($_.Exception.Message)" }
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Ignore
        if (-not $task -or $task.State -ne 'Running') { $ok = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ok) { Write-WatchLog "task $TaskName still running after 60 s" }
    try { & $StartCommand $TaskName *>&1 | ForEach-Object { Write-WatchLog "start: $_" }; Write-WatchLog "started task $TaskName" }
    catch { Write-WatchLog "start of task $TaskName failed: $($_.Exception.Message)"; $ok = $false }
    # Left in place, the watchdog's own stop request would block the next serve.ps1 restart.
    if (-not $ok -and (Test-OwnStopRequest)) {
        Remove-Item -LiteralPath $stopFile -Force -ErrorAction Ignore
        Write-WatchLog 'start failed, clearing own stop request'
    }
}

Write-WatchLog ("watchdog start: $url every $IntervalSec s, timeout $TimeoutSec s, restart after " +
    "$FailThreshold failures, at most $MaxRestartsPerHour restarts per hour")
$fails = 0
$restarts = @()
$state = 'polling'
for ($poll = 1; $MaxPolls -eq 0 -or $poll -le $MaxPolls; $poll++) {
    if ($poll -gt 1) { Start-Sleep -Seconds $IntervalSec }
    # A failed log write or any other error ends this poll, never the watchdog.
    try {
        # Stopped on purpose with stop.ps1: no polls until serve.ps1 starts again. A stop
        # request this watchdog wrote itself never pauses it.
        if ((Test-Path -LiteralPath $stopFile) -and -not (Test-OwnStopRequest)) {
            if ($state -ne 'paused') { Write-WatchLog "paused: $stopFile exists (stopped with stop.ps1)" }
            $state = 'paused'
            $fails = 0
            continue
        }
        if ($state -eq 'paused') { Write-WatchLog 'resumed: the stop request is gone'; $state = 'polling' }
        $err = $null
        try {
            $h = Invoke-RestMethod -Uri $url -TimeoutSec $TimeoutSec
            if ($h.status -ne 'ok') { $err = "status '$($h.status)'" }
        } catch { $err = $_.Exception.Message }
        if (-not $err) {
            if ($fails) { Write-WatchLog "health ok after $fails failed polls" }
            $fails = 0
            $state = 'polling'
            continue
        }
        $fails++
        if ($fails -le $FailThreshold) { Write-WatchLog "health failed ($fails of $FailThreshold): $err" }
        if ($fails -lt $FailThreshold) { continue }
        $now = Get-Date
        $restarts = @($restarts | Where-Object { ($now - $_).TotalHours -lt 1 })
        if ($restarts.Count -ge $MaxRestartsPerHour) {
            if ($state -ne 'budget') { Write-WatchLog "not restarting: $($restarts.Count) restarts in the last hour (-MaxRestartsPerHour $MaxRestartsPerHour)" }
            $state = 'budget'
            continue
        }
        $restarts += $now
        $fails = 0
        $state = 'polling'
        Write-WatchLog "restart $($restarts.Count) of $MaxRestartsPerHour this hour after $FailThreshold failed polls"
        Restart-Server "$FailThreshold failed health polls"
    } catch {
        $msg = "poll $poll failed: $($_.Exception.Message)"
        try { Write-WatchLog $msg } catch { [Console]::Error.WriteLine("watchdog: $msg") }
    }
}
