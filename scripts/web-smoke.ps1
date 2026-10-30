#Requires -Version 7.0
<#
.SYNOPSIS
  Check that this machine reaches the web and print how a local session would use it.
.DESCRIPTION
  Read-only: never starts claude, never changes settings or installs anything
  (docs/web-access.md).
  1. Internet: TCP 443 to -HostName (Test-NetConnection) and a GET of -Url, which must
     return 200 with -Expect in the body.
  2. MCP servers declared by this repo, each with its command line:
     scripts/web-access.example.mcp.json (never auto-loaded) and a root .mcp.json, which
     must not exist (it would load automatically). For an npx package pinned as
     name@version whose integrity is recorded below, the integrity of that version in the
     local npx cache is compared with the record (a mismatch fails the run).
     Also: which browser executables exist, and llama-server /health (both info only).
  3. The session commands that prove fetch works, printed and not run.
  Web access is DISARMED (docs/web-access.md, Blockers): the commands in part 3 are for
  after the blockers are closed.
  PASS (exit 0) when part 1 passes, the example config parses, no root .mcp.json exists
  and no pinned integrity mismatches; FAIL (exit 1) otherwise.
#>
[CmdletBinding()]
param(
    [string]$HostName = 'example.com',
    [string]$Url = 'https://example.com/',
    [string]$Expect = 'Example Domain',
    [int]$Port = 8080
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$fail = 0
# npm's own integrity value for each pinned package (package-lock "integrity" field).
$pins = @{
    '@playwright/mcp@0.0.75' = 'sha512-oBjzVXfEGZ9Ev45tKKQULNDVdF83B82lg0uPejEK3xsp/zWmdNdNVnPi032fmd/o20ZZXs+LX7cr77qRNbV4VA=='
}

# 1. Internet
$tcp = Test-NetConnection -ComputerName $HostName -Port 443 -InformationLevel Quiet
Write-Host "internet: tcp ${HostName}:443 $(if ($tcp) { 'open' } else { 'FAILED' })"
if (-not $tcp) { $fail++ }
try {
    $r = Invoke-WebRequest -Uri $Url -TimeoutSec 15 -MaximumRedirection 0 -SkipHttpErrorCheck
    $found = "$($r.Content)".Contains($Expect)
    Write-Host ("internet: GET $Url -> $($r.StatusCode), $($r.RawContentLength) bytes, " +
        "'$Expect' $(if ($found) { 'found' } else { 'NOT found' })")
    if ($r.StatusCode -ne 200 -or -not $found) { $fail++ }
} catch {
    Write-Host "internet: GET $Url FAILED: $($_.Exception.Message)"
    $fail++
}

# 2. MCP servers declared by the repo
$cache = $env:npm_config_cache
if (-not $cache) {
    try { $cache = (& npm config get cache).Trim() } catch { Write-Host "mcp: npm config get cache failed: $($_.Exception.Message)" }
}
foreach ($rel in 'scripts/web-access.example.mcp.json', '.mcp.json') {
    $p = Join-Path $repo $rel
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Host "mcp: $rel not present"
        if ($rel -ne '.mcp.json') { $fail++ }
        continue
    }
    try { $cfg = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json -AsHashtable }
    catch { Write-Host "mcp: $rel FAILED to parse: $($_.Exception.Message)"; $fail++; continue }
    foreach ($name in $cfg.mcpServers.Keys) {
        $s = $cfg.mcpServers[$name]
        Write-Host "mcp: $rel declares '$name': $($s.command) $($s.args -join ' ')"
        if ($rel -eq '.mcp.json') { Write-Host 'mcp:   FAIL: a root .mcp.json loads automatically; web access is DISARMED'; $fail++ }
        foreach ($tok in $s.args) {
            if (-not $pins.ContainsKey("$tok")) { continue }
            $pkg, $ver = "$tok" -split '@(?=[^@]+$)'
            $hit = $null
            if ($cache -and (Test-Path -LiteralPath (Join-Path $cache '_npx'))) {
                foreach ($lock in Get-ChildItem -Path (Join-Path $cache '_npx\*\package-lock.json')) {
                    $e = (Get-Content -LiteralPath $lock.FullName -Raw | ConvertFrom-Json -AsHashtable).packages["node_modules/$pkg"]
                    if ($e -and $e.version -eq $ver) { $hit = $e; break }
                }
            }
            if (-not $hit) {
                Write-Host "mcp:   $tok not in the npx cache ($cache): the first session start downloads it"
            } elseif ($hit.integrity -eq $pins["$tok"]) {
                Write-Host "mcp:   $tok cached, integrity matches the record"
            } else {
                Write-Host "mcp:   $tok cached, integrity MISMATCH: $($hit.integrity)"
                $fail++
            }
        }
    }
}
Write-Host 'mcp: the lean wrapper passes --strict-mcp-config, so a session loads only the --mcp-config files given'
$browsers = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\ms-playwright")
foreach ($b in $browsers) { Write-Host "browser: $b $(if (Test-Path -LiteralPath $b) { 'present' } else { 'absent' })" }
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5 -Headers @{ Authorization = 'Bearer local' }
    Write-Host "llama-server: /health $($h | ConvertTo-Json -Compress)"
} catch {
    Write-Host "llama-server: /health unreachable on port ${Port}: $($_.Exception.Message)"
}

# 3. Proof commands (printed only)
$wrapper = Join-Path $repo 'scripts\claude-local.ps1'
$mcp = Join-Path $repo 'scripts\web-access.example.mcp.json'
$ask = "reply with only the text of the page's h1 heading."
Write-Host ''
Write-Host 'DISARMED: run these only after the blockers in docs/web-access.md are closed.'
Write-Host 'proof, browser path (UNVERIFIED; expect result "Example Domain"):'
Write-Host ("  pwsh -NoProfile -File `"$wrapper`" --mcp-config `"$mcp`" --allowedTools " +
    'mcp__playwright__browser_navigate mcp__playwright__browser_snapshot mcp__playwright__browser_close ' +
    "--max-turns 8 --output-format json --debug-file `"`$env:TEMP\lis-web-proof.log`" " +
    "-p `"Open $Url with the browser tools and $ask`"")
Write-Host 'proof, WebFetch path (needs the proposed -LisWeb switch; UNVERIFIED):'
Write-Host ("  pwsh -NoProfile -File `"$wrapper`" -LisWeb --allowedTools `"WebFetch(domain:$HostName)`" " +
    "--max-turns 4 --output-format json -p `"Use WebFetch on $Url and $ask`"")

Write-Host ''
if ($fail) { Write-Host "FAIL: $fail check(s) failed"; exit 1 }
Write-Host 'PASS'
exit 0
