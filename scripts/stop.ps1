#Requires -Version 7.0
<#
.SYNOPSIS
  Stop the process listening on -Port (the llama-server started by scripts/serve.ps1).
.DESCRIPTION
  Refuses unless the listener's process name is llama-server; -Force overrides that
  check. PID 0 and PID 4 (System) are never stopped. -WhatIf prints what it would stop.
  Before stopping (also when nothing is listening) it appends the marker
  "[stop.ps1] stop requested <timestamp>" (plus " (<-Reason>)" when given) to -LogFile
  (default logs/llama-server.log), so the log tells a stop from a crash, then writes the
  same line to logs/.stop-requested-<Port> under the repo root, so the scripts/serve.ps1
  on that port does not restart llama-server (serve.ps1 deletes that file when it starts).
  While serve.ps1 runs llama-server it holds the log open; then the append fails and
  serve.ps1 logs the marker from that file after llama-server exits. Control characters
  and line separators in -Reason (newlines, U+0085, U+2028, U+2029 included) become
  spaces, so the marker is one line. scripts/watchdog.ps1 passes -FromWatchdog -Reason
  "watchdog: ..."; without -FromWatchdog a -Reason that starts with "watchdog:" is
  refused (the watchdog does not pause on its own stop requests).
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [int]$Port = 8080,
    [switch]$Force,
    [string]$LogFile = (Join-Path $PSScriptRoot '..\logs\llama-server.log'),
    [string]$Reason = '',
    [switch]$FromWatchdog
)
$ErrorActionPreference = 'Stop'

$stopFile = Join-Path $PSScriptRoot "..\logs\.stop-requested-$Port"
$Reason = ($Reason -replace '[\x00-\x1F\x7F\x85\u2028\u2029]+', ' ').Trim()
if ($Reason -match '^watchdog:' -and -not $FromWatchdog) {
    throw "-Reason may not start with 'watchdog:': that prefix marks scripts/watchdog.ps1's own stop requests."
}
# Marker first, then the stop file: serve.ps1 logs after it sees the file, so the two
# never write the log at the same time.
function Write-StopRequest {
    $marker = "[stop.ps1] stop requested $(Get-Date -Format o)$(if ($Reason) { " ($Reason)" })"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stopFile) | Out-Null
    try { Add-Content -LiteralPath $LogFile -Value $marker }
    catch { Write-Host "Log in use (serve.ps1 holds it while llama-server runs); serve.ps1 logs the stop request." }
    Set-Content -LiteralPath $stopFile -Value $marker
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
if (-not $listener) {
    if ($PSCmdlet.ShouldProcess($stopFile, 'Write stop request')) { Write-StopRequest }
    Write-Host "Nothing is listening on port $Port."
    exit 0
}
$procId = [int]$listener.OwningProcess
if ($procId -in 0, 4) { throw "Port $Port is owned by PID $procId (system); refusing to stop it." }
$proc = Get-Process -Id $procId
if ($proc.ProcessName -ne 'llama-server' -and -not $Force) {
    throw "Port $Port is owned by PID $procId ($($proc.ProcessName)), not llama-server; refusing. Use -Force to stop it anyway."
}
if ($PSCmdlet.ShouldProcess("PID $procId ($($proc.ProcessName)) on port $Port", 'Stop-Process')) {
    Write-StopRequest
    Write-Host "Stopping PID $procId ($($proc.ProcessName)) on port $Port"
    Stop-Process -Id $procId -Force
    $proc.WaitForExit(30000) | Out-Null
}
