#Requires -Version 7.0
<#
.SYNOPSIS
  Download a prebuilt llama.cpp Windows CUDA release into bin/.
.DESCRIPTION
  Fetches the llama.cpp Windows x64 CUDA zip and its cudart companion zip from the
  ggml-org/llama.cpp GitHub release, verifies SHA256 against the digest the GitHub
  release API publishes, and extracts both into -BinDir. Never builds from source.

  Models are NOT downloaded here. `llama-server -hf <repo>:<quant>` (scripts/serve.ps1)
  fetches the GGUF on first run into its own cache. -ModelsDir is only created, for
  GGUF files you place by hand and pass to serve.ps1 as a .gguf path.
.EXAMPLE
  pwsh scripts/install.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$LlamaRelease = 'b11868',
    [string]$Cuda = '13.4',
    [string]$BinDir = (Join-Path $PSScriptRoot '..\bin'),
    [string]$ModelsDir = (Join-Path $PSScriptRoot '..\models')
)
$ErrorActionPreference = 'Stop'

# Asset names follow the release-page pattern at the time of writing. They can change
# between releases: verify them at
# https://github.com/ggml-org/llama.cpp/releases/tag/<release> before relying on this.
$base = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaRelease"
$assets = @(
    "llama-$LlamaRelease-bin-win-cuda-$Cuda-x64.zip",
    "cudart-llama-bin-win-cuda-$Cuda-x64.zip"
)
$downloadDir = Join-Path $BinDir '.download'

foreach ($dir in $BinDir, $ModelsDir, $downloadDir) {
    if ($PSCmdlet.ShouldProcess($dir, 'Create directory')) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

foreach ($name in $assets) {
    $url = "$base/$name"
    $zip = Join-Path $downloadDir $name
    if (-not $PSCmdlet.ShouldProcess($url, "Download and extract into $BinDir")) { continue }

    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip

    # llama.cpp releases publish no .sha256 sidecars; the GitHub API exposes each
    # asset's digest ("sha256:<hex>") instead.
    $expected = $null
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$LlamaRelease"
        $digest = ($release.assets | Where-Object { $_.name -eq $name }).digest
        if ($digest -like 'sha256:*') { $expected = $digest.Substring(7) }
    } catch {}
    if (-not $expected) { Write-Warning "No published SHA256 digest for $name (or fetch failed); SHA256 not verified." }
    if ($expected) {
        $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash
        if ($actual -ne $expected) { throw "SHA256 mismatch for ${name}: expected $expected, got $actual" }
        Write-Host "SHA256 OK: $name"
    }

    Expand-Archive -Path $zip -DestinationPath $BinDir -Force
}

if ($WhatIfPreference) { return }

$server = Join-Path $BinDir 'llama-server.exe'
if (-not (Test-Path $server)) {
    throw "llama-server.exe not found in $BinDir after extraction; check the zip layout and asset names."
}
Write-Host "Installed: $server"
Write-Host 'Next: pwsh scripts/serve.ps1   (first run downloads the model via -hf)'
