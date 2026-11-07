#Requires -Version 7.0
<#
.SYNOPSIS
  Build the lis-web container image that claude-local.ps1 -LisWeb runs sessions in.
.DESCRIPTION
  Operator-run (operator ruling 2026-11-05: web-enabled sessions run in a container with no
  access to the operator's home folder). Builds container/Dockerfile with this repo as the
  build context (`docker build -f container/Dockerfile -t lis-web:<version> .`, run from
  the repo root; .dockerignore keeps bin/, models/, logs/, bench/results/,
  web/node_modules/ and .env out of it; the image copies only web/, the lis-web MCP
  server, whose npm ci reads web/package-lock.json), and tags the image
  lis-web:<version>, the version being the claude-code version the Dockerfile pins
  (@anthropic-ai/claude-code@X.Y.Z). It changes nothing but Docker's image store: no file
  in this repo is written. The build pulls the base image by digest, PowerShell from
  Microsoft's apt repo and the npm packages (several minutes the first time). Prints the
  image id, the base image digest from the Dockerfile and the size, and exits non-zero
  when the build fails.
  -Check: only report whether the image exists (exit 0 when it does, 1 when not); builds
  nothing.
.EXAMPLE
  pwsh -NoProfile -File scripts/web-image.ps1
.EXAMPLE
  pwsh -NoProfile -File scripts/web-image.ps1 -Check
#>
param(
    [switch]$Check
)
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$dockerfile = Join-Path $repo 'container' 'Dockerfile'
$text = Get-Content -LiteralPath $dockerfile -Raw
if ($text -notmatch '@anthropic-ai/claude-code@(\d+\.\d+\.\d+)\b') {
    throw "$dockerfile pins no exact @anthropic-ai/claude-code@X.Y.Z version."
}
$image = "lis-web:$($Matches[1])"
if ($text -notmatch '(?m)^FROM (\S+@sha256:[0-9a-f]{64})\s*$') {
    throw "$dockerfile has no FROM line pinned by digest (image@sha256:...)."
}
$base = $Matches[1]
if (-not (Get-Command docker -CommandType Application -ErrorAction Ignore)) {
    throw 'docker is not on PATH: start Docker Desktop (Linux containers) and retry.'
}

# The image's id, size and creation time, or $null when the image does not exist.
function Get-LisImage([string]$Name) {
    $line = & docker image inspect --format '{{.Id}} {{.Size}} {{.Created}}' $Name 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $line) { return $null }
    $id, $size, $created = "$line".Split(' ', 3)
    $mb = [math]::Round([double]$size / 1MB)
    return [pscustomobject]@{ Id = $id; SizeMB = $mb; Created = $created }
}

if ($Check) {
    $img = Get-LisImage $image
    if ($img) {
        "web-image: $image exists: id $($img.Id), $($img.SizeMB) MB, created $($img.Created)"
        exit 0
    }
    $self = Join-Path $PSScriptRoot 'web-image.ps1'
    "web-image: $image is missing; build it: pwsh -NoProfile -File `"$self`""
    exit 1
}

foreach ($f in 'package.json', 'package-lock.json', 'server.mjs') {
    if (-not (Test-Path -LiteralPath (Join-Path $repo 'web' $f) -PathType Leaf)) {
        throw "$(Join-Path $repo 'web') has no $f (the lis-web MCP server the image copies in)."
    }
}
"web-image: building $image from $dockerfile (base $base, context $repo)"
# From the repo root, so the context is `.` and .dockerignore applies.
Push-Location -LiteralPath $repo
try { & docker build -f container/Dockerfile -t $image . }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "docker build failed (exit $LASTEXITCODE); $image is unchanged." }
$img = Get-LisImage $image
if (-not $img) { throw "docker build reported success but $image is not in the image store." }
"web-image: image $image"
"web-image: id $($img.Id)"
"web-image: base $base"
"web-image: size $($img.SizeMB) MB, created $($img.Created)"
exit 0
