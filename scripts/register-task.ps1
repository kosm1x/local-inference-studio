#Requires -Version 7.0
<#
.SYNOPSIS
  Register the logon task that starts llama-server (scripts/serve.ps1) for the current user.
.DESCRIPTION
  Task "LocalInferenceStudio-llama-server": trigger at logon of the current user, action
  pwsh -NoProfile -NonInteractive -WindowStyle Hidden -File scripts/serve.ps1 with the
  serve.ps1 defaults plus -LogFile logs/llama-server.log, working directory = repo root.
  Runs only while the user is logged on (interactive token, no stored password), no
  execution time limit, up to 3 restarts 1 minute apart, a second start is ignored while
  one runs, and a missed start runs when available. An existing task with the same name
  is replaced. Start now: Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server.
  Remove: scripts/unregister-task.ps1.
#>
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'

$taskName = 'LocalInferenceStudio-llama-server'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serve = Join-Path $repoRoot 'scripts\serve.ps1'
$logFile = Join-Path $repoRoot 'logs\llama-server.log'
$pwshExe = Join-Path $PSHOME 'pwsh.exe'
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute $pwshExe -WorkingDirectory $repoRoot `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$serve`" -LogFile `"$logFile`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable

if ($PSCmdlet.ShouldProcess("$taskName ($user, at logon): $pwshExe $($action.Arguments)", 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'Local Inference Studio: llama-server on 127.0.0.1:8080 (scripts/serve.ps1)' `
        -Force | Out-Null
    Write-Host "Registered $taskName. Log: $logFile"
}
