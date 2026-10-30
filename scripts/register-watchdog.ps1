#Requires -Version 7.0
<#
.SYNOPSIS
  Register the logon task that runs scripts/watchdog.ps1 for the current user.
.DESCRIPTION
  Task "LocalInferenceStudio-watchdog": trigger at logon of the current user, delayed
  5 minutes so the server task has loaded the model; action pwsh -NoProfile
  -NonInteractive -WindowStyle Hidden -File scripts/watchdog.ps1 with its defaults
  (/health every 60 s, restart after 3 failures, at most 3 restarts per hour, log
  logs/watchdog.log), working directory = repo root. Same settings as the server task
  (scripts/register-task.ps1): interactive token, no stored password, on battery too, no
  execution time limit, a failed launch retried 3 times 1 minute apart, a second start is
  ignored while one runs. The task stores
  absolute paths, so re-run this script after moving the repo. An existing task with the
  same name is replaced. -WhatIf prints the task without registering it. Start now:
  Start-ScheduledTask -TaskName LocalInferenceStudio-watchdog. Remove:
  Unregister-ScheduledTask -TaskName LocalInferenceStudio-watchdog -Confirm:$false.
#>
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'

$taskName = 'LocalInferenceStudio-watchdog'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$watchdog = Join-Path $repoRoot 'scripts\watchdog.ps1'
$pwshExe = Join-Path $PSHOME 'pwsh.exe'
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute $pwshExe -WorkingDirectory $repoRoot `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$watchdog`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT5M'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($PSCmdlet.ShouldProcess("$taskName ($user, at logon + 5 min): $pwshExe $($action.Arguments)", 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'Local Inference Studio: llama-server health watchdog (scripts/watchdog.ps1)' `
        -Force | Out-Null
    Write-Host "Registered $taskName. Log: $(Join-Path $repoRoot 'logs\watchdog.log')"
}
