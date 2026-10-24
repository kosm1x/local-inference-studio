#Requires -Version 7.0
<#
.SYNOPSIS
  Stop the process listening on -Port (the llama-server started by scripts/serve.ps1).
.DESCRIPTION
  Refuses unless the listener's process name is llama-server; -Force overrides that
  check. PID 0 and PID 4 (System) are never stopped. -WhatIf prints what it would stop.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [int]$Port = 8080,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
if (-not $listener) {
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
    Write-Host "Stopping PID $procId ($($proc.ProcessName)) on port $Port"
    Stop-Process -Id $procId -Force
    $proc.WaitForExit(30000) | Out-Null
}
