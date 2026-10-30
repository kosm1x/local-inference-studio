#Requires -Version 7.0
<#
.SYNOPSIS
  Register the logon task that starts llama-server (scripts/serve.ps1) for the current user.
.DESCRIPTION
  Task "LocalInferenceStudio-llama-server": trigger at logon of the current user, action
  pwsh -NoProfile -NonInteractive -WindowStyle Hidden -File scripts/serve.ps1 with the
  serve.ps1 defaults plus -LogFile logs/llama-server.log, working directory = repo root.
  Runs only while the user is logged on (interactive token, no stored password), also on
  battery (it neither waits for AC power nor stops when the machine switches to battery),
  no execution time limit, a second start is ignored while one runs, and a missed start
  runs when available. RestartCount 3 / RestartInterval 1 minute only retry a launch that
  fails. Once llama-server is running, serve.ps1 itself restarts it after a non-zero exit
  (up to 5 times within an hour, with backoff); scripts/stop.ps1 or a sixth failure leaves
  it down until the next logon or Start-ScheduledTask. scripts/register-watchdog.ps1 adds a
  second logon task that restarts a server failing /health (scripts/watchdog.ps1). The
  command line below is unchanged by those. The task stores absolute paths, so re-run this script
  after moving the repo. An existing task with the same name is replaced. Start now:
  Start-ScheduledTask -TaskName LocalInferenceStudio-llama-server.
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
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($PSCmdlet.ShouldProcess("$taskName ($user, at logon): $pwshExe $($action.Arguments)", 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'Local Inference Studio: llama-server on 127.0.0.1:8080 (scripts/serve.ps1)' `
        -Force | Out-Null
    Write-Host "Registered $taskName. Log: $logFile"
}
