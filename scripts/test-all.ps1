#Requires -Version 7.0
<#
.SYNOPSIS
  Run the repo's test suites sequentially and print one PASS/FAIL/SKIP line per suite.
.DESCRIPTION
  Each suite runs with the repo root as working directory, so the script works from any
  cwd. Pass/fail is the suite's process exit code. On FAIL the last 15 output lines are
  printed indented. Ends with "N passed, M failed, K skipped in Ts"; exit 1 if any
  suite failed, else 0.
  The default (fast) set is every python suite listed in CLAUDE.md except the property
  test and lisweb_test.py, plus node --test over web/test/*.test.mjs (SKIP when
  web/node_modules is absent; run npm ci --prefix web once).
  bench/loop/fixture/test/text.test.js is never run: 3 of its tests fail by design.
.PARAMETER Full
  Also run scripts/hooks/tests/lis-guard_property_test.py and scripts/tests/lisweb_test.py
  (the latter's container half needs Docker and the lis-web image).
.PARAMETER Only
  Run only suites whose path contains this substring (case-insensitive). Considers every
  suite, including the -Full ones.
.EXAMPLE
  pwsh -NoProfile -File scripts/test-all.ps1 -Only verify-doc
#>
[CmdletBinding()]
param(
    [switch]$Full,
    [string]$Only
)

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$nodeSuite = 'web/test/*.test.mjs'
$fullOnly = @('scripts/hooks/tests/lis-guard_property_test.py', 'scripts/tests/lisweb_test.py')
$all = @(
    'scripts/hooks/tests/lis-guard_test.py'
    'scripts/hooks/tests/lis-guard_property_test.py'
    'scripts/hooks/tests/loop-guard_test.py'
    'scripts/hooks/tests/repeat-guard_test.py'
    'scripts/hooks/tests/facts-inject_test.py'
    'bench/ladder/tests/grade_test.py'
    'bench/ladder/tests/gen_longfix_test.py'
    'bench/ladder/tests/longrun_test.py'
    'bench/ladder/tests/gen_stalefig_test.py'
    'bench/ladder/tests/stalefig_test.py'
    'bench/ladder/tests/gen_blocked_test.py'
    'bench/ladder/tests/blocked_test.py'
    'bench/ladder/tests/gen_bait_test.py'
    'bench/ladder/tests/bait_test.py'
    'scripts/tests/verify-doc_test.py'
    'scripts/tests/verify_claims_report_test.py'
    'scripts/tests/web-readout_test.py'
    'scripts/tests/resilience_test.py'
    'scripts/tests/claude_settings_test.py'
    'scripts/tests/install_verify_test.py'
    'scripts/tests/lisweb_test.py'
    $nodeSuite
)
$selected = if ($Only) {
    @($all | Where-Object { $_.IndexOf($Only, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
} else {
    @($all | Where-Object { $Full -or $_ -notin $fullOnly })
}
if ($selected.Count -eq 0) {
    Write-Host "no suite path contains '$Only'"
    exit 1
}

$passed = 0; $failed = 0; $skipped = 0
$total = [Diagnostics.Stopwatch]::StartNew()
Push-Location -LiteralPath $repo
try {
    foreach ($suite in $selected) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $files = @()
        if ($suite -eq $nodeSuite) {
            if (-not (Test-Path -LiteralPath 'web/node_modules' -PathType Container)) {
                $skipped++
                Write-Host ('SKIP  {0:N1}s  {1}  web/node_modules absent (npm ci --prefix web)' -f 0, $suite)
                continue
            }
            $files = @(Get-ChildItem -LiteralPath 'web/test' -Filter '*.test.mjs' -File -ErrorAction Ignore |
                Sort-Object Name | ForEach-Object { "web/test/$($_.Name)" })
        }
        # A missing python/node throws; that suite FAILs (127) and the loop goes on.
        $global:LASTEXITCODE = -1
        try {
            if ($suite -ne $nodeSuite) { $out = & python -I $suite 2>&1 }
            elseif ($files.Count -gt 0) { $out = & node --test @files 2>&1 }
            else { throw 'no web/test/*.test.mjs files found' }
            $code = $LASTEXITCODE
        } catch {
            $out = "$_" -replace '\s*\r?\n\s*', ' '; $code = 127
        }
        $sw.Stop()
        $lines = @($out | ForEach-Object { "$_" })
        $last = "$($lines | Where-Object { $_.Trim() } | Select-Object -Last 1)".Trim()
        if ($last.Length -gt 90) { $last = $last.Substring(0, 90) }
        $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
        Write-Host ('{0}  {1:N1}s  {2}  {3}' -f $status, $sw.Elapsed.TotalSeconds, $suite, $last)
        if ($code -eq 0) { $passed++; continue }
        $failed++
        $lines | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" }
    }
} finally {
    Pop-Location
}
$secs = $total.Elapsed.TotalSeconds
Write-Host ('{0} passed, {1} failed, {2} skipped in {3:N1}s' -f $passed, $failed, $skipped, $secs)
exit ([int]($failed -gt 0))
