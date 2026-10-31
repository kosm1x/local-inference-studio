#Requires -Version 7.0
<#
.SYNOPSIS
  Download a prebuilt llama.cpp Windows CUDA release into bin/, or verify the local
  GGUF files against models/manifest.json.
.DESCRIPTION
  Fetches the llama.cpp Windows x64 CUDA zip and its cudart companion zip from the
  ggml-org/llama.cpp GitHub release, checks each zip's SHA256 against BOTH the digest
  pinned in this script ($pinned) and the digest the GitHub release API publishes, and
  extracts both into -BinDir. Never builds from source. A failed API fetch, a missing
  pin or digest, or any mismatch stops the install. A release or CUDA version without a
  pin stops too: add its two digests to $pinned after checking them.

  -SkipVerify extracts without either check and requires -SkipVerifyAck as well; it
  prints a warning for each zip. Not recommended.

  Models are NOT downloaded here. `llama-server -hf <repo>:<quant>` (scripts/serve.ps1)
  fetches the GGUF on first run into its own cache, and docs/SETUP.md step 4 downloads
  the default file with `hf download`. -VerifyModels checks every file listed in
  models/manifest.json that is present under the repo (byte size, then SHA256), reports
  absent ones, throws on a mismatch, and does nothing else (no download, no extract).
  It reads paths relative to the repo root and ignores -ModelsDir.
.EXAMPLE
  pwsh scripts/install.ps1 -WhatIf
.EXAMPLE
  pwsh scripts/install.ps1 -VerifyModels
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$LlamaRelease = 'b11868',
    [string]$Cuda = '13.4',
    [string]$BinDir = (Join-Path $PSScriptRoot '..\bin'),
    [string]$ModelsDir = (Join-Path $PSScriptRoot '..\models'),
    [switch]$SkipVerify,
    [switch]$SkipVerifyAck,
    [switch]$VerifyModels
)
$ErrorActionPreference = 'Stop'

if ($SkipVerify -and -not $SkipVerifyAck) {
    throw '-SkipVerify installs binaries nobody checked (no pinned digest, no API digest). Add -SkipVerifyAck to confirm.'
}

if ($VerifyModels) {
    $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $manifest = Get-Content -LiteralPath (Join-Path $repoRoot 'models\manifest.json') -Raw | ConvertFrom-Json
    $bad = 0
    foreach ($e in $manifest.files) {
        $p = [IO.Path]::GetFullPath($e.path, $repoRoot)
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { Write-Host "absent: $($e.path)"; continue }
        $len = (Get-Item -LiteralPath $p).Length
        if ($len -ne [long]$e.size) { Write-Host "SIZE MISMATCH: $($e.path) is $len bytes, manifest $($e.size)"; $bad++; continue }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower()
        if ($hash -ne $e.sha256) { Write-Host "SHA256 MISMATCH: $($e.path) is $hash, manifest $($e.sha256)"; $bad++; continue }
        Write-Host "OK: $($e.path) ($len bytes, sha256 $hash)"
    }
    if ($bad) { throw "$bad model file(s) do not match models/manifest.json; delete and download them again." }
    return
}

# Asset names follow the release-page pattern at the time of writing. They can change
# between releases: verify them at
# https://github.com/ggml-org/llama.cpp/releases/tag/<release> before relying on this.
$base = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaRelease"
$assets = @(
    "llama-$LlamaRelease-bin-win-cuda-$Cuda-x64.zip",
    "cudart-llama-bin-win-cuda-$Cuda-x64.zip"
)
$downloadDir = Join-Path $BinDir '.download'

# Expected SHA256 per release asset, pinned in the repo so the GitHub API is not the
# only witness. Source: Get-FileHash of the two zips in bin\.download on the reference
# machine, 2026-10-30; the security audit of that day found both equal to the digests
# the GitHub API published for b11868.
$pinned = @{
    'b11868' = @{
        'llama-b11868-bin-win-cuda-13.4-x64.zip' = '6b39772ceb8668e8e53af792fe6847c2c7ed7ec459c650c7531425974be8cccf'
        'cudart-llama-bin-win-cuda-13.4-x64.zip' = '738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668'
    }
}

# llama.cpp releases publish no .sha256 sidecars; the GitHub API exposes each
# asset's digest ("sha256:<hex>") instead. Fetched once, before any download.
$release = $null
if (-not $SkipVerify) {
    foreach ($name in $assets) {
        if (-not ($pinned[$LlamaRelease] -and $pinned[$LlamaRelease][$name])) {
            throw "No pinned SHA256 for $name (release $LlamaRelease). Check the digest and add it to `$pinned in scripts/install.ps1."
        }
    }
    $api = "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$LlamaRelease"
    try {
        $release = Invoke-RestMethod -Uri $api
    } catch {
        throw "Could not fetch $api for SHA256 digests: $($_.Exception.Message)"
    }
    Write-Host "Release JSON fetched: $($release.tag_name), $(@($release.assets).Count) assets"
}

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

    if ($SkipVerify) {
        Write-Warning "-SkipVerify -SkipVerifyAck: $name is NOT verified (no pinned digest, no API digest). Do not run it on a machine you care about."
    } else {
        $digest = ($release.assets | Where-Object { $_.name -eq $name }).digest
        if ($digest -notlike 'sha256:*') { throw "No published SHA256 digest for $name in release $LlamaRelease." }
        $api256 = $digest.Substring(7).ToLower()
        $pin256 = $pinned[$LlamaRelease][$name]
        if ($api256 -ne $pin256) { throw "GitHub API digest for $name ($api256) differs from the pinned one ($pin256); not installing." }
        $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
        if ($actual -ne $pin256) { throw "SHA256 mismatch for ${name}: expected $pin256 (pinned and API), got $actual" }
        Write-Host "SHA256 OK (pinned + API): $name"
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
