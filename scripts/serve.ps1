#Requires -Version 7.0
<#
.SYNOPSIS
  Run llama-server (Anthropic /v1/messages on 127.0.0.1) from bin/.
.DESCRIPTION
  Default command line (rulings 6 and 12 in docs/ROADMAP.md, 2026-10-24): the local
  orcarouter Qwen3.8-27B-Uncensored IQ3_XXS at -c 65536 with q4_0 KV,
  --chat-template-file config/chat-templates/qwen3.8-27b.jinja and MTP
  (--spec-type draft-mtp --spec-draft-n-max 2), plus -fa on, -np 1,
  Qwen sampling, --host/--port, --reasoning-format auto, --api-key local and
  --no-mmproj (the vision projector is skipped unless -WithMmproj). -Model is a
  Hugging Face "repo:quant" (passed as -hf, downloaded on first run) or a local .gguf
  path (passed as -m; relative to the repo root; a missing file throws). -KvType
  defaults to q4_0 for the default model file only and to q8_0 for any other -Model
  (the KV the other rows were benched with); an explicit -KvType always wins.
  -ChatTemplateFile (relative to the repo root) is passed as --chat-template-file; it
  defaults to config/chat-templates/qwen3.8-27b.jinja when the model is under
  models/qwen3.8-27b-uncensored (that GGUF's embedded template rejects Claude Code's
  second system message with HTTP 500).
  MTP (--spec-type draft-mtp --spec-draft-n-max 2) is added for the default model file
  only, unless -NoMtp; any other -Model runs without it. It fits all-GPU at 65536 with
  q4_0 KV (Phase 3e); at a larger -Ctx pass -NoMtp, or --fit moves layers to CPU.
  -ExtraArgs (string[]) is passed through verbatim, one element per argument, so a
  value with spaces stays whole; use it from inside pwsh. `pwsh -File` hands
  -ExtraArgs 'a','b' over as the single string "a,b", so from `pwsh -File` use
  -ExtraArgLine, which is split on whitespace (no quoting; values with spaces need
  -ExtraArgs). -LogFile appends the command line and llama-server stdout/stderr to
  that file (its folder is created) instead of the console, renames a log over 50 MB to
  <name>.1 first (replacing an older .1), and appends "llama-server exited <code>" when
  llama-server exits; the logon task from scripts/register-task.ps1 uses
  logs/llama-server.log. Stop with scripts/stop.ps1.
.EXAMPLE
  pwsh scripts/serve.ps1 -Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS -NCpuMoe 8
.EXAMPLE
  pwsh scripts/serve.ps1 -ExtraArgLine '-lv 4'
.EXAMPLE
  & scripts/serve.ps1 -ExtraArgs '--chat-template-kwargs', '{"enable_thinking": false}'
#>
[CmdletBinding()]
param(
    [string]$Model = 'models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf',
    [int]$Ctx = 65536,
    [int]$Port = 8080,
    [int]$NCpuMoe = 0,
    [string]$KvType = 'q4_0',
    [string]$Alias = 'local',
    [string]$ChatTemplateFile = '',
    [switch]$WithMmproj,
    [switch]$NoMtp,
    [string[]]$ExtraArgs = @(),
    [string]$ExtraArgLine = '',
    [string]$LogFile = ''
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

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$source = if ($Model -like '*.gguf') { '-m' } else { '-hf' }
if ($source -eq '-m') {
    # Normalise every local path (relative, absolute, forward slashes) before the tests below.
    $Model = [IO.Path]::GetFullPath($Model, $repoRoot)
    if (-not (Test-Path -LiteralPath $Model -PathType Leaf)) { throw "Model file not found: $Model" }
}
$defaultModel = [IO.Path]::GetFullPath('models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf', $repoRoot)
if (-not $PSBoundParameters.ContainsKey('KvType') -and $Model -ne $defaultModel) { $KvType = 'q8_0' }
if (-not $ChatTemplateFile -and $source -eq '-m' -and
    $Model.StartsWith([IO.Path]::GetFullPath('models\qwen3.8-27b-uncensored', $repoRoot) + '\', 'OrdinalIgnoreCase')) {
    $ChatTemplateFile = 'config\chat-templates\qwen3.8-27b.jinja'
}
if ($ChatTemplateFile) {
    $ChatTemplateFile = [IO.Path]::GetFullPath($ChatTemplateFile, $repoRoot)
    if (-not (Test-Path -LiteralPath $ChatTemplateFile -PathType Leaf)) { throw "Chat template not found: $ChatTemplateFile" }
}
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
if ($ChatTemplateFile) { $cmdArgs += '--chat-template-file', $ChatTemplateFile }
if ($Model -eq $defaultModel -and -not $NoMtp) { $cmdArgs += '--spec-type', 'draft-mtp', '--spec-draft-n-max', '2' }
$cmdArgs += $ExtraArgs
$cmdArgs += $ExtraArgLine -split '\s+' | Where-Object { $_ }

$cmdLine = "$exe $($cmdArgs -join ' ')"
if ($LogFile) {
    $logDir = Split-Path -Parent ([IO.Path]::GetFullPath($LogFile))
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    if ((Test-Path -LiteralPath $LogFile) -and (Get-Item -LiteralPath $LogFile).Length -gt 50MB) {
        Move-Item -LiteralPath $LogFile -Destination "$LogFile.1" -Force
    }
    Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $cmdLine"
    & $exe @cmdArgs *>> $LogFile
    Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] llama-server exited $LASTEXITCODE"
} else {
    Write-Host $cmdLine
    & $exe @cmdArgs
}
exit $LASTEXITCODE
