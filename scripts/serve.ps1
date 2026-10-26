#Requires -Version 7.0
<#
.SYNOPSIS
  Run llama-server (Anthropic /v1/messages on 127.0.0.1) from bin/.
.DESCRIPTION
  Default command line (rulings 6 and 14 in docs/ROADMAP.md; ruling 14 of 2026-10-25
  reverted ruling 12's 65536 + MTP): the local orcarouter Qwen3.8-27B-Uncensored
  IQ3_XXS at -c 131072 with q4_0 KV,
  --chat-template-file config/chat-templates/qwen3.8-27b.jinja and no MTP,
  plus -fa on, -np 1,
  Qwen sampling, --host/--port, --reasoning-format auto, --reasoning off, --api-key local
  and --no-mmproj (the vision projector is skipped unless -WithMmproj).
  -Reasoning (off, on or auto; default off) is passed as --reasoning. The default is off
  because the 2026-10-26 compaction bench got a real summary on every compaction request
  only with server thinking off (3 of 3, against 2 of 4 with it on; n=1 run each).
  -Reasoning auto is the server's own default (detect from the template), which is what
  the script ran before this flag; with the default template that meant thinking on.
  -Reasoning on forces thinking on. The server log calls the older form
  --chat-template-kwargs '{"enable_thinking": false}' deprecated in favour of this
  flag. That --reasoning off has the same effect on this build is VERIFIED at the
  template level (2026-10-26: after the 12:22 restart /apply-template rendered an empty
  think block for the assistant turn); its effect on output quality is unmeasured
  (compaction run 9 used the kwarg form). --reasoning comes before -ExtraArgs and
  -ExtraArgLine, so a later '--reasoning', 'on' or the kwarg form there is also passed;
  which one llama-server honours (last wins?) is UNVERIFIED. -Model is a
  Hugging Face "repo:quant" (passed as -hf, downloaded on first run) or a local .gguf
  path (passed as -m; relative to the repo root; a missing file throws). -KvType
  defaults to q4_0 for the default model file only and to q8_0 for any other -Model
  (the KV the other rows were benched with); an explicit -KvType always wins.
  -ChatTemplateFile (relative to the repo root) is passed as --chat-template-file; it
  defaults to config/chat-templates/qwen3.8-27b.jinja when the model is under
  models/qwen3.8-27b-uncensored (that GGUF's embedded template rejects Claude Code's
  second system message with HTTP 500).
  MTP (--spec-type draft-mtp --spec-draft-n-max 2) is added for the default model file
  only, at -Ctx 65536 or below, unless -NoMtp; any other -Model runs without it. It fits
  all-GPU at 65536 with q4_0 KV (Phase 3e), so `-Ctx 65536` turns it on. The default
  (no -Ctx, 131072) skips it silently; an explicit -Ctx above 65536 skips it with a
  warning (pass -NoMtp to silence it), since MTP there is expected to push layers to CPU.
  -ExtraArgs (string[]) is passed through verbatim, one element per argument, so a
  value with spaces stays whole; use it from inside pwsh. `pwsh -File` hands
  -ExtraArgs 'a','b' over as the single string "a,b", so from `pwsh -File` use
  -ExtraArgLine, which is split on whitespace (no quoting; values with spaces need
  -ExtraArgs). -LogFile (relative to the current filesystem location) appends the
  command line and llama-server stdout/stderr to that file (its folder is created)
  instead of the console, renames a log over 50 MB to
  <name>.1 first (replacing an older .1), and appends "llama-server exited <code>" when
  llama-server exits; the logon task from scripts/register-task.ps1 uses
  logs/llama-server.log. Stop with scripts/stop.ps1.
.EXAMPLE
  pwsh scripts/serve.ps1 -Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS -NCpuMoe 8
.EXAMPLE
  pwsh scripts/serve.ps1 -ExtraArgLine '-lv 4'
.EXAMPLE
  pwsh scripts/serve.ps1 -Reasoning on
#>
[CmdletBinding()]
param(
    [string]$Model = 'models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf',
    [int]$Ctx = 131072,
    [int]$Port = 8080,
    [int]$NCpuMoe = 0,
    [string]$KvType = 'q4_0',
    [string]$Alias = 'local',
    [string]$ChatTemplateFile = '',
    [ValidateSet('off', 'on', 'auto')]
    [string]$Reasoning = 'off',
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
    '--reasoning', $Reasoning.ToLowerInvariant(),
    '--api-key', 'local',
    '--host', '127.0.0.1', '--port', "$Port"
)
if (-not $WithMmproj) { $cmdArgs += '--no-mmproj' }
if ($NCpuMoe -gt 0) { $cmdArgs += '--n-cpu-moe', "$NCpuMoe" }
if ($ChatTemplateFile) { $cmdArgs += '--chat-template-file', $ChatTemplateFile }
if ($Model -eq $defaultModel -and -not $NoMtp) {
    if ($Ctx -gt 65536) {
        if ($PSBoundParameters.ContainsKey('Ctx')) { Write-Warning 'MTP skipped: only measured to fit all-GPU up to -Ctx 65536 (Phase 3e); pass -NoMtp to silence' }
    } else {
        $cmdArgs += '--spec-type', 'draft-mtp', '--spec-draft-n-max', '2'
    }
}
$cmdArgs += $ExtraArgs
$cmdArgs += $ExtraArgLine -split '\s+' | Where-Object { $_ }

$cmdLine = "$exe $($cmdArgs -join ' ')"
if ($LogFile) {
    # Relative to the current filesystem location, not the process cwd (which
    # Set-Location does not change); $PWD can be a non-filesystem drive (HKCU:, Env:).
    $LogFile = [IO.Path]::GetFullPath($LogFile, (Get-Location -PSProvider FileSystem).ProviderPath)
    $logDir = Split-Path -Parent $LogFile
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
