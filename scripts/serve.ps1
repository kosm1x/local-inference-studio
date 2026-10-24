#Requires -Version 7.0
<#
.SYNOPSIS
  Run llama-server (Anthropic /v1/messages on 127.0.0.1) from bin/.
.DESCRIPTION
  Default command line = "Suggested start" in docs/landscape-2026-10-24.md, plus
  --host/--port, --reasoning-format auto, --api-key local and --no-mmproj (the vision
  projector is skipped unless -WithMmproj). -Model is a Hugging Face "repo:quant"
  (passed as -hf, downloaded on first run) or a local .gguf path (passed as -m).
  -ExtraArgs given as one space-separated string is split on whitespace, so the same
  form works from `pwsh -File` and from inside pwsh. Stop with scripts/stop.ps1.
.EXAMPLE
  pwsh scripts/serve.ps1 -Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS -NCpuMoe 8
.EXAMPLE
  pwsh scripts/serve.ps1 -ExtraArgs '--spec-type draft-mtp --spec-draft-n-max 2'
#>
[CmdletBinding()]
param(
    [string]$Model = 'unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS',
    [int]$Ctx = 131072,
    [int]$Port = 8080,
    [int]$NCpuMoe = 0,
    [string]$KvType = 'q8_0',
    [string]$Alias = 'local',
    [switch]$WithMmproj,
    [string[]]$ExtraArgs = @()
)
$ErrorActionPreference = 'Stop'

$binDir = Join-Path $PSScriptRoot '..\bin'
$exe = Join-Path $binDir 'llama-server.exe'
if (-not (Test-Path $exe)) { throw "llama-server.exe not found in $binDir. Run scripts/install.ps1 first." }

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction Ignore
    Write-Host "Port $Port is already in use by PID $($listener.OwningProcess) ($($owner.ProcessName)). Stop it first: pwsh scripts/stop.ps1 -Port $Port"
    exit 1
}

$source = if ($Model -like '*.gguf') { '-m' } else { '-hf' }
# Numbers are passed as strings so the decimal separator never depends on the culture.
$cmdArgs = @(
    $source, $Model,
    '-c', "$Ctx",
    '-fa', 'on',
    '-ctk', $KvType, '-ctv', $KvType,
    '-np', '1',
    '--alias', $Alias,
    '--temp', '0.6', '--top-p', '0.95', '--top-k', '20',
    '--reasoning-format', 'auto',
    '--api-key', 'local',
    '--host', '127.0.0.1', '--port', "$Port"
)
if (-not $WithMmproj) { $cmdArgs += '--no-mmproj' }
if ($NCpuMoe -gt 0) { $cmdArgs += '--n-cpu-moe', "$NCpuMoe" }
# `pwsh -File` hands -ExtraArgs 'a','b' over as the single string "a,b", so pass one
# space-separated string instead; it is split here.
if ($ExtraArgs.Count -eq 1 -and $ExtraArgs[0] -match '\s') { $ExtraArgs = $ExtraArgs[0] -split '\s+' | Where-Object { $_ } }
$cmdArgs += $ExtraArgs

Write-Host "$exe $($cmdArgs -join ' ')"
& $exe @cmdArgs
exit $LASTEXITCODE
