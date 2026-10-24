#Requires -Version 7.0
<#
.SYNOPSIS
  Stop the process listening on -Port (the llama-server started by scripts/serve.ps1).
#>
[CmdletBinding()]
param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
if (-not $listener) {
    Write-Host "Nothing is listening on port $Port."
    exit 0
}
$proc = Get-Process -Id $listener.OwningProcess
Write-Host "Stopping PID $($proc.Id) ($($proc.ProcessName)) on port $Port"
Stop-Process -Id $proc.Id -Force
$proc.WaitForExit(30000) | Out-Null
