#Requires -Version 7.0
<#
.SYNOPSIS
  Remove the logon task registered by scripts/register-task.ps1.
.DESCRIPTION
  Unregisters "LocalInferenceStudio-llama-server". A running llama-server is left
  alone; stop it with scripts/stop.ps1.
#>
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'

$taskName = 'LocalInferenceStudio-llama-server'
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction Ignore)) {
    Write-Host "Task $taskName is not registered."
    exit 0
}
if ($PSCmdlet.ShouldProcess($taskName, 'Unregister-ScheduledTask')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Unregistered $taskName."
}
