#Requires -Version 7.0
<#
.SYNOPSIS
  Run llama-server (Anthropic /v1/messages on 127.0.0.1) from bin/.
.DESCRIPTION
  Default command line = "Suggested start" in docs/landscape-2026-10-24.md, plus
  --host/--port and --reasoning-format auto. -Model is a Hugging Face "repo:quant"
  (passed as -hf, downloaded on first run) or a local .gguf path (passed as -m).
.EXAMPLE
  pwsh scripts/serve.ps1 -Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS -NCpuMoe 8
.EXAMPLE
  pwsh scripts/serve.ps1 -ExtraArgs '--spec-type','draft-mtp','--spec-draft-n-max','2'
#>
[CmdletBinding()]
param(
    [string]$Model = 'unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS',
    [int]$Ctx = 131072,
    [int]$Port = 8080,
    [int]$NCpuMoe = 0,
    [string]$KvType = 'q8_0',
    [string]$Alias = 'local',
    [string[]]$ExtraArgs = @()
)
$ErrorActionPreference = 'Stop'

$binDir = Join-Path $PSScriptRoot '..\bin'
$exe = Join-Path $binDir 'llama-server.exe'
if (-not (Test-Path $exe)) { throw "llama-server.exe not found in $binDir. Run scripts/install.ps1 first." }

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
    '--host', '127.0.0.1', '--port', "$Port"
)
if ($NCpuMoe -gt 0) { $cmdArgs += '--n-cpu-moe', "$NCpuMoe" }
$cmdArgs += $ExtraArgs

Write-Host "$exe $($cmdArgs -join ' ')"
& $exe @cmdArgs
exit $LASTEXITCODE
