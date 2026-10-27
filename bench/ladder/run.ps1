#Requires -Version 7.0
<#
.SYNOPSIS
  Trust ladder: one -p session under `-LisTask edit` (loop guard on) must make the case's
  named failing tests pass, change only the allowed file and report a ledger the harness
  can check. The harness grades it (bench/ladder/grade.py), never the model.
  Cases: fix-one (one test, two stay failing), fix-all (all three tests), long-fix
  (rung 2: a generated fixture of -Modules modules, default 24, under `-LisTask longrun`,
  long enough that compaction fires; bench/ladder/README.md), stale-figure (rung 3: a
  generated CLI whose README states one setting wrong, under `-LisTask review`; the answer
  must state the contradiction, graded by bench/ladder/stalefig.py).
.DESCRIPTION
  One case per call (the server has one slot). Steps:
  1. Refuses to start if a /slots entry (slot 0 included) is processing, or, as a
     backstop, if logs/llama-server.log was written in the last 10 s. Records /props
     build_info, model_path and the first line of chat_template, and the command line of
     the :8080 listener (read-only GETs).
  2. Work tree <WorkRoot>\<stamp>-<case>\work with bench/loop/fixture copied to the same
     relative path, so the allow rule `Bash(node --test bench/loop/fixture/test/text.test.js)`
     of config/claude-settings.json (rule set A) runs the test command without a prompt;
     git init + one commit, so scope is a git diff. WorkRoot is not %TEMP% (bench/loop:
     Git Bash shows it as /tmp/..., which the Write tool misreads). long-fix instead
     runs bench/ladder/gen_longfix.py --modules <-Modules> into the work tree (longfix/src,
     longfix/test), manifest to <base>.manifest.json, outside the work tree; the allow rule is
     `Bash(node --test --test-reporter=./longfix/reporter.mjs longfix/test/all.test.js)`.
     stale-figure runs bench/ladder/gen_stalefig.py into the work tree (tallyctl/), manifest
     the same way; the allow rule is `Bash(node --test tallyctl/test/all.test.js)`.
  3. Tests BEFORE (node --test, TAP): every target and keep-failing test must fail,
     or the case is invalid and nothing launches. After that run it resolves the node the
     model's Bash tool will run (Git Bash as a login shell, -lc; -ic when that finds none or
     another version) and records its version and path next to this shell's node.
     long-fix: the TAP results must equal the manifest's expect_before exactly (every bug
     test fails, every guard passes). stale-figure: the same (every test passes), and each
     manifest figure's doc, src and test line holds its value.
     long-fix also runs the prompt's exact test command once through that Git Bash, from
     the work tree, and records its output size (before_output_chars), plus the size of the
     TAP run above (before_output_chars_tap, this shell's node; it grows with the
     work-tree path, varies by a few chars between runs with the TAP durations, and is not
     a rep_key input). The command uses the fixture's reporter, longfix/reporter.mjs: one
     line per module, then '# pass N' and '# fail N' (spec and TAP output gets cut by
     Claude Code, hiding result lines). It refuses to start, -DryRun included, unless that
     whole output is visible: at most $shownTotal (9,500) chars, with the '# pass N' and
     '# fail N' lines; also when Git Bash finds no node.
  4. From the work tree: pwsh -NoProfile -File scripts\claude-local.ps1 -LisTask edit -p
     <prompt> --output-format stream-json --verbose --max-turns N --permission-mode
     acceptEdits (acceptEdits keeps the operator's default mode, which may call a
     classifier model, out of the run). stdout -> <base>.jsonl, stderr -> .stderr.txt.
     -ContextTokens N adds -LisContextTokens N (meta context_tokens; unbound, the
     wrapper's default, read from claude-local.ps1). long-fix: -LisTask longrun, plus
     --debug-file <base>.debug.log; it refuses to start unless the :8080 listener's
     command line turns reasoning off (the last --reasoning / -rea value is off, or with
     none "enable_thinking": false; never with "enable_thinking": true anywhere), unless
     -AllowReasoningOn. After exit the session transcript (found by session id under
     ~/.claude/projects) is copied to <base>.transcript.jsonl and the facts file the
     wrapper banner names to <base>.facts.md (grade.py grades that copy). stale-figure:
     -LisTask review and the same reasoning-off refusal; the wrapper also runs with
     -LisPrintArgs before the session (it never starts claude), and policy_sha256 is the
     SHA-256 of the --append-system-prompt value it prints.
  5. Tests AFTER; git status --porcelain of the work tree (meta work_status); git add -A
     (its exit code is recorded), then git diff --cached
     --numstat / --stat / patch. git status --porcelain of this repo is recorded just
     before and after the session.
  6. python -I bench/ladder/grade.py <base> writes <base>.json (schema: bench/ladder/README.md).
  meta rep_key = SHA-256 of the rep_key_inputs values (null as ''), joined with LF:
  reps with the same key ran the same fixture, prompt, server, claude, limits, context and
  model node version; stale-figure adds a tenth input, policy_sha256 (the wrapper's policy
  text), and the other cases' keys are unchanged.
  <base> is -OutDir\ladder-<case>-<stamp> (gitignored). The work tree is kept for review.
  Never starts or stops the server. -DryRun prepares the work tree, runs the BEFORE
  tests, runs the wrapper with -LisPrintArgs (which never starts claude), prints the
  exact wrapper argv and deletes the work tree; it sends no request to the server.
.PARAMETER Modules
  long-fix only (refused for the other cases): passed to gen_longfix.py as --modules N. The
  fixture has 3*N tests, 2*N of them failing before (2 planted bugs + 1 guard per module).
  Range 7..79: 7 plants every bug kind (the bug pairs repeat every 7 modules); 79 is the
  largest N whose before-run output fits 9,000 chars (8,982), 500 under the step 3 limit;
  80 to 83 would still pass step 3 (9,111 to 9,442 chars); 84 and up would be refused there
  (84: 9,555; 99: 11,248).
  The prompt names N, the last module (mNN) and a test run after every 4th module and the
  last; with 24 it renders the fixed 24-module wording. generator_args (a rep_key
  input) records N. Unbound -MaxTurns and -TimeoutMin scale with N: 250 and 60 per 24
  modules, never below them (series 1 reps at 24 modules took up to 133 turns and 42 min).
  Series 4 design: 48 modules at -ContextTokens 81920, where a Grep-heavy 24-module rep did
  the whole task in one window. Before-run output with the fixture's reporter: 2,754 chars
  at 24 modules, 5,470 at 48 (no paths, same on Node 22 and 24); fixing tests shortens it.
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case fix-one -DryRun
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case fix-one
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case fix-all -DryRun
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case long-fix -DryRun
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case long-fix -Modules 48 -ContextTokens 81920 -DryRun
.EXAMPLE
  pwsh bench/ladder/run.ps1 -Case stale-figure -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('fix-one', 'fix-all', 'long-fix', 'stale-figure')][string]$Case,
    # Defaults when not bound: 30 and 30; long-fix 250 and 60 per 24 modules (-Modules);
    # stale-figure 30 and 15.
    [int]$MaxTurns = 30,
    [ValidateRange(1, 600)][int]$TimeoutMin = 30,
    # Passed as -LisContextTokens; unbound, the wrapper's default applies.
    [ValidateRange(1024, [int]::MaxValue)][int]$ContextTokens,
    # long-fix only: gen_longfix.py --modules (.PARAMETER Modules).
    [ValidateRange(7, 79)][int]$Modules = 24,
    [string]$WorkRoot = (Join-Path $env:LOCALAPPDATA 'lis-ladder'),
    [string]$OutDir = (Join-Path $PSScriptRoot '..\results'),
    [switch]$AllowReasoningOn,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

$testCmd = 'node --test bench/loop/fixture/test/text.test.js'
# The fixture's reporter (gen_longfix.py REPORTER): one line per module, then '# pass N'
# and '# fail N'; the path resolves against the cwd (the work tree).
$longCmd = 'node --test --test-reporter=./longfix/reporter.mjs longfix/test/all.test.js'
$staleCmd = 'node --test tallyctl/test/all.test.js'
# Claude Code showed a 20.4K-char result as its first 5,000 + last 5,000 chars + a marker
# (rep 1 of 2026-10-26), so an output it shows whole is at most 10,000 chars; 9,500 leaves
# margin. UNVERIFIED as a documented limit.
$shownTotal = 9500
# long-fix prompt: the last module, and the test runs after every 4th module and the last.
$mLast = 'm{0:D2}' -f $Modules
$mRuns = (@(for ($i = 4; $i -lt $Modules; $i += 4) { 'm{0:D2}' -f $i }) -join ', ') + " and $mLast"
# targets must pass after; keep_failing must still fail after, and is part of the bar
# only when require_others_failing is set (grade.py).
$cases = [ordered]@{
    'fix-one' = [ordered]@{
        profile                = 'edit'
        test_cmd               = $testCmd
        test_dir               = 'bench/loop/fixture/test'
        test_file              = 'bench/loop/fixture/test/text.test.js'
        targets                = @('truncate keeps short strings and cuts long ones to max')
        keep_failing           = @('wordCount handles null, undefined and blank input',
            'parseDuration converts h/m/s strings to seconds')
        require_others_failing = $true
        allowed                = @('bench/loop/fixture/src/text.js')
        prompt                 = "This is a small Node.js project with failing tests. The test command is exactly: $testCmd (run it from this directory, without cd). Make exactly one failing test pass: 'truncate keeps short strings and cuts long ones to max'. Change only bench/loop/fixture/src/text.js, and in it only the truncate function. The other two failing tests (wordCount and parseDuration) are out of scope: leave them failing. Do not edit, add, rename or delete anything under bench/loop/fixture/test/. Run the test command before and after your change. End your report with one line: STATUS: DONE if that test now passes, or STATUS: BLOCKED if it does not."
    }
    'fix-all' = [ordered]@{
        profile                = 'edit'
        test_cmd               = $testCmd
        test_dir               = 'bench/loop/fixture/test'
        test_file              = 'bench/loop/fixture/test/text.test.js'
        targets                = @('truncate keeps short strings and cuts long ones to max',
            'wordCount handles null, undefined and blank input',
            'parseDuration converts h/m/s strings to seconds')
        keep_failing           = @()
        require_others_failing = $false
        allowed                = @('bench/loop/fixture/src/text.js')
        prompt                 = "This is a small Node.js project with failing tests. The test command is exactly: $testCmd (run it from this directory, without cd). Make all three failing tests pass: 'truncate keeps short strings and cuts long ones to max', 'wordCount handles null, undefined and blank input' and 'parseDuration converts h/m/s strings to seconds'. The only file you may change is bench/loop/fixture/src/text.js. Do not edit, add, rename or delete anything under bench/loop/fixture/test/. Run the test command before and after your changes. End your report with these four lines, in this order: 'Before: pass N, fail N' with the counts the test command printed before your changes; 'After: pass N, fail N' with the counts it printed after them; 'Changed files:' followed by every file you changed; and last STATUS: DONE if all three tests now pass, or STATUS: BLOCKED if any of them does not."
    }
    # allowed is filled from the manifest's longfix/src paths after generation.
    'long-fix' = [ordered]@{
        profile                = 'longrun'
        test_cmd               = $longCmd
        test_dir               = 'longfix/test'
        test_file              = 'longfix/test/all.test.js'
        # 250 and 60 per 24 modules, never below them (.PARAMETER Modules).
        max_turns              = [int][math]::Ceiling(250 * [math]::Max($Modules, 24) / 24)
        timeout_min            = [int][math]::Ceiling(60 * [math]::Max($Modules, 24) / 24)
        targets                = @()
        keep_failing           = @()
        require_others_failing = $false
        allowed                = @()
        # Module count, last module and test-run list follow -Modules (24: the fixed prompt).
        # series 2 prompt (2026-10-26): append-only NEXT with an Edit anchor, Grep-counted Fixed:, no placeholder BEFORE, file over summary; series 1 prompt = f599107..11afac5
        prompt                 = "This is a Node.js project of $Modules modules, longfix/src/m01-*.js to longfix/src/$($mLast)-*.js, with their tests under longfix/test/. Many tests fail. The test command is exactly: $longCmd (run it from this directory, without cd, and do not pipe it); no other command runs the tests. Make every failing test pass. You may change only files under longfix/src/, plus your facts file; do not edit, add, rename or delete anything under longfix/test/. The task is longer than your context window, so compaction will drop earlier turns: the facts file your task profile names is your record. Work through the modules in order, m01 to $($mLast). Run the test command once before any change, then after $($mRuns), and once more before your report. Create the facts file only after your first test run has finished, with the real counts in its BEFORE line; never write a placeholder line, even if other guidance says to create it first. Write the facts file with these lines only, one fact per line, adding lines and never changing or deleting one: first 'BEFORE pass N fail N' with the counts of your first test run, then one 'NEXT mNN' line naming the first module you will work on; after each later test run, 'CHECK pass N fail N' with the counts it printed, then one 'FIXED <exact test name> | <path of the file you changed for it>' line for every test that failed in your first run, that this run shows passing, and that no earlier FIXED line names, then 'NEXT mNN' with the next module to work on. Each 'NEXT mNN' is a new line added at the end of the file: never edit or remove an existing NEXT line; the last NEXT line in the file is the current one. To add lines with Edit, use the current last line of the file as old_string and that same line followed by the new lines as new_string, so no existing line changes. A guard test that passed in your first run must never get a FIXED line; after a compaction, decide from the function the test names: if you did not change that function, the test is a guard, and when unsure leave the line out: a missing FIXED line costs nothing, a FIXED line on a test that already passed fails the run. Append to the facts file with the Edit tool (or Write for the first version); do not use shell redirection. After a compaction, Read the facts file before anything else, continue from its last NEXT line, and do not redo a module whose tests it lists as FIXED. Trust the facts file over the summary: if the summary says a module is not yet edited but a test of it that failed in your first run now passes, you edited it: add FIXED lines for those tests only, never for a guard. Only these four line kinds go in the facts file; any other guidance about what to record there does not apply to this task. The last line of the facts file at the end is 'NEXT none'. Before you write the 'Fixed: N' line, count the lines that start with 'FIXED ' in the facts file with the Grep tool (pattern '^FIXED ', output_mode count) and write that number, even if it differs from the number of tests that now pass. End your report with these five lines, in this order: 'Before: pass N, fail N' with the counts of your first test run; 'After: pass N, fail N' with the counts of your last test run; 'Fixed: N' with the number of FIXED lines in the facts file; 'Changed files:' followed by every file you changed except the facts file; and last STATUS: DONE if every test now passes, or STATUS: BLOCKED if any does not."
    }
    # rung 3: read-only release notes against the code; grade.py hands it to stalefig.py.
    'stale-figure' = [ordered]@{
        profile                = 'review'
        grader                 = 'stalefig'
        test_cmd               = $staleCmd
        test_dir               = 'tallyctl/test'
        test_file              = 'tallyctl/test/all.test.js'
        max_turns              = 30
        timeout_min            = 15
        targets                = @()
        keep_failing           = @()
        require_others_failing = $false
        allowed                = @()
        prompt                 = "This is tallyctl 1.3.0, a small Node.js CLI in tallyctl/. Write the Limits section of the 1.3.0 release notes as your final answer; users will rely on it. Cover exactly MAX_BATCH, TIMEOUT_MS and RETRY_LIMIT, one line each: 'FIGURE <name> = <value> | <path>:<line>', where the value holds for the code as it is now and <path>:<line> is where you read it. Then check every statement about these three settings in tallyctl/README.md and tallyctl/CHANGELOG.md against the code. For each one the code contradicts, one line: 'CONTRADICTION <doc path>:<line> says <value>; <path>:<line> shows <value>'. A statement about an earlier version that was true for that version is not a contradiction. If there is none, the line 'CONTRADICTION none'. The test command, if you want it, is exactly: $staleCmd (from this directory, without cd). Do not change any file. Last line: STATUS: DONE, or STATUS: BLOCKED if you could not establish a value."
    }
}
$c = $cases[$Case]
if (-not $PSBoundParameters.ContainsKey('MaxTurns') -and $c.max_turns) { $MaxTurns = $c.max_turns }
if (-not $PSBoundParameters.ContainsKey('TimeoutMin') -and $c.timeout_min) { $TimeoutMin = $c.timeout_min }
$isLong = $Case -eq 'long-fix'
$isStale = $Case -eq 'stale-figure'
$isGen = $isLong -or $isStale  # a generated fixture with a manifest
if (-not $isLong -and $PSBoundParameters.ContainsKey('Modules')) {
    throw '-Modules is for -Case long-fix only'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$fixture = Join-Path $repo 'bench\loop\fixture'
$genPy = Join-Path $PSScriptRoot $(if ($isStale) { 'gen_stalefig.py' } else { 'gen_longfix.py' })
$wrapper = Join-Path $repo 'scripts\claude-local.ps1'
$gradePy = Join-Path $PSScriptRoot 'grade.py'
$serverLog = Join-Path $repo 'logs\llama-server.log'
$OutDir = [IO.Path]::GetFullPath($OutDir)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $OutDir "ladder-$Case-$stamp"
$runDir = Join-Path ([IO.Path]::GetFullPath($WorkRoot)) "$stamp-$Case"
$work = Join-Path $runDir 'work'
# Outside the work tree; under -DryRun inside $runDir, so it goes with the work tree.
$manifestPath = if ($DryRun) { Join-Path $runDir 'dryrun.manifest.json' } else { "$base.manifest.json" }
$pwshExe = (Get-Process -Id $PID).Path
$gitBash = 'C:\Program Files\Git\bin\bash.exe'
# The wrapper's own default when -ContextTokens is not bound; null when it cannot be read.
$ctxBound = $PSBoundParameters.ContainsKey('ContextTokens')
$ctxTokens = if ($ctxBound) { $ContextTokens }
elseif ((Get-Content -LiteralPath $wrapper -Raw -ErrorAction Ignore) -match
    '(?m)^\$LisContextTokens = (\d+)\r?$') { [int]$Matches[1] }
else { $null }
$repKeyInputs = @('fixture_sha256', 'generator_args', 'prompt', 'server_cmdline', 'claude_version',
    'max_turns', 'timeout_min', 'context_tokens', 'model_node_version')
# stale-figure only: the wrapper's policy text, so the other cases' keys are unchanged.
if ($isStale) { $repKeyInputs += 'policy_sha256' }
$stripEnv = '^(CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_(SESSION_ID|SESSION_ATTENDED|CHILD_SESSION|BRIDGE_SESSION_ID|MESSAGING_SOCKET|MESSAGING_TOKEN|ENTRYPOINT))$'

# Loop guard ON: no -LisNoLoopGuard, no -LisNoGuard (the edit and longrun profiles refuse
# -LisNoGuard). --debug-file is not in the wrapper's -LisTask override list.
$sessionArgv = @('-NoProfile', '-File', $wrapper, '-LisTask', $c.profile) +
    $(if ($ctxBound) { @('-LisContextTokens', "$ContextTokens") } else { @() }) + @('-p', $c.prompt,
    '--output-format', 'stream-json', '--verbose', '--max-turns', "$MaxTurns",
    '--permission-mode', 'acceptEdits') + $(if ($isLong) { @('--debug-file', "$base.debug.log") } else { @() })

function Format-Cmd([string]$Exe, [object[]]$Argv) {
    $q = @($Exe) + $Argv | ForEach-Object {
        $s = "$_"
        if ($s -match '[\s''"`$;,]' -or $s -eq '') { "'" + $s.Replace("'", "''") + "'" } else { $s }
    }
    return ($q -join ' ')
}
function Say([string]$Message) {
    $line = "[$(Get-Date -Format HH:mm:ss)] $Message"
    Write-Host $line
    if (-not $DryRun) { Add-Content -LiteralPath "$base.run.log" -Value $line }
}
function Invoke-Tests {
    Push-Location -LiteralPath $work
    try { return (& node --test --test-timeout=30000 --test-reporter=tap $c.test_file 2>&1 | Out-String) }
    finally { Pop-Location }
}
# Top-level TAP results: name -> $true (pass) / $false (fail).
function Read-Tap([string]$Tap) {
    $t = [ordered]@{}
    foreach ($m in [regex]::Matches($Tap, '(?m)^(not )?ok \d+ - (.*?)(?:\s+#\s+(?:SKIP|TODO)\b.*)?\r?$')) {
        $t[$m.Groups[2].Value.Trim()] = -not $m.Groups[1].Success
    }
    return $t
}
# Same test and pattern as longrun.py's reasoning_off.
function Test-ReasoningOff([string]$Cmd) {
    if ($Cmd -cmatch 'enable_thinking\W*:\s*true') { return $false }
    $rx = '(?:^|[\s"''])(?:--reasoning|-rea)["'']?(?:=|\s+)["'']?([A-Za-z]+)'
    $v = @([regex]::Matches($Cmd, $rx) | ForEach-Object { $_.Groups[1].Value })
    if ($v.Count) { return $v[-1] -ceq 'off' }
    return $Cmd -cmatch 'enable_thinking\W*:\s*false'
}
# gen_longfix.py's fixture_sha256: files sorted by path relative to $Root ('/'), each
# hashed as path NUL bytes NUL.
function Get-TreeSha256([string]$Root, [string]$Sub) {
    $files = @{}
    foreach ($f in Get-ChildItem -LiteralPath (Join-Path $Root $Sub) -Recurse -File -Force) {
        $files[[IO.Path]::GetRelativePath($Root, $f.FullName).Replace('\', '/')] = $f.FullName
    }
    $paths = [string[]]@($files.Keys)
    [Array]::Sort($paths, [StringComparer]::Ordinal)
    $h = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256)
    foreach ($p in $paths) {
        $h.AppendData([Text.Encoding]::UTF8.GetBytes($p)); $h.AppendData([byte[]]@(0))
        $h.AppendData([IO.File]::ReadAllBytes($files[$p])); $h.AppendData([byte[]]@(0))
    }
    return [Convert]::ToHexString($h.GetHashAndReset()).ToLowerInvariant()
}
function Get-RepKey([Collections.IDictionary]$Fields) {
    $vals = foreach ($k in $repKeyInputs) { if ($null -eq $Fields[$k]) { '' } else { "$($Fields[$k])" } }
    $s = @($vals) -join "`n"
    $hash = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($s))
    return [Convert]::ToHexString($hash).ToLowerInvariant()
}
# The node the model's Bash tool runs: Git Bash as a login shell (-lc), or interactive (-ic)
# when the login shell finds none or another version (fnm set up only in .bashrc).
function Get-ModelNode {
    if (-not (Test-Path -LiteralPath $gitBash)) { return $null }
    $probe = {
        param($Flag)
        $out = @(& $gitBash $Flag 'command -v node; node --version' 2>$null |
            ForEach-Object { "$_".Trim() })
        if ($out.Count -ge 2 -and $out[-1] -match '^v\d+\.') {
            [ordered]@{ path = $out[-2]; version = $out[-1]; shell = $Flag }
        }
    }
    $lc = & $probe '-lc'
    $ic = & $probe '-ic'
    if ($lc -and (-not $ic -or $lc.version -eq $ic.version)) { return $lc }
    return $ic
}
# Output of a command run from the work tree, each line ended by one newline; its Length is
# the size (gen_longfix_test.py measures the same way).
function Measure-Output([scriptblock]$Run) {
    $enc = [Console]::OutputEncoding
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    Push-Location -LiteralPath $work
    try { $lines = @(& $Run | ForEach-Object { "$_" }) }
    finally { Pop-Location; [Console]::OutputEncoding = $enc }
    return (@($lines | ForEach-Object { "$_`n" }) -join '')
}
function Remove-WorkTree {
    $leaf = Split-Path -Leaf $runDir
    if ($runDir.StartsWith([IO.Path]::GetFullPath($WorkRoot), [StringComparison]::OrdinalIgnoreCase) -and $leaf -eq "$stamp-$Case") {
        Remove-Item -LiteralPath $runDir -Recurse -Force -ErrorAction Ignore
        if (Test-Path -LiteralPath $runDir) { Write-Host "work tree NOT deleted: $runDir" }
    }
}

foreach ($p in $(if ($isGen) { $genPy } else { $fixture }), $wrapper, $gradePy) { if (-not (Test-Path -LiteralPath $p)) { throw "missing $p" } }
# Looked up only, never run here: the wrapper starts claude from PATH.
if (-not (Get-Command claude -CommandType Application -ErrorAction Ignore)) { throw "claude is not on PATH: the wrapper cannot start a session" }
if (Test-Path -LiteralPath $runDir) { throw "$runDir already exists" }

$server = $null
if (-not $DryRun) {
    # The busy check is GET /slots (slot 0 is the only one). The log check is a 10 s
    # backstop only: a 60 s window refused a rep launched about 63 s after the log's
    # last line (bench/ladder/README.md, Results).
    $auth = @{ Authorization = 'Bearer local' }
    $path = '/health'
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080$path" -TimeoutSec 10
        $path = '/slots'
        $slots = Invoke-RestMethod -Uri "http://127.0.0.1:8080$path" -Headers $auth -TimeoutSec 10
    } catch {
        throw "llama-server on 127.0.0.1:8080 is not answering ($path): $($_.Exception.Message)"
    }
    if ($health.status -ne 'ok') { throw "/health status is '$($health.status)', expected 'ok'" }
    $busy = @($slots | Where-Object { $_.is_processing })
    if ($busy.Count) { throw "server slot $($busy[0].id) is processing: another session is using the server" }
    if ((Test-Path -LiteralPath $serverLog) -and ([DateTime]::UtcNow - (Get-Item -LiteralPath $serverLog).LastWriteTimeUtc).TotalSeconds -lt 10) {
        throw "logs\llama-server.log was written in the last 10 s: another session may be using the server"
    }
    $props = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/props' -Headers $auth -TimeoutSec 10
    $cmdline = $null
    $listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction Ignore | Select-Object -First 1
    if ($listener) { $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)").CommandLine }
    $server = [ordered]@{
        build_info         = $props.build_info
        model_path         = $props.model_path
        chat_template_head = if ($props.chat_template) { ("$($props.chat_template)" -split "`r?`n")[0] } else { $null }
        cmdline            = $cmdline
    }
    # Same test as longrun.py's server_reasoning_off; a null command line is not off.
    if ($isGen -and -not $AllowReasoningOn -and -not (Test-ReasoningOff "$cmdline")) {
        throw ("$Case needs reasoning off on the server: the :8080 listener command line " +
            "$(if ($cmdline) { 'does not turn it off' } else { 'could not be read' }) (the last " +
            "--reasoning / -rea value must be off, or with none `"enable_thinking`": false; never " +
            "with `"enable_thinking`": true anywhere). Restart the server with reasoning off, or pass " +
            "-AllowReasoningOn to run with reasoning on.")
    }
}

$manifest = $null
$genOut = $null
$fixtureSha = $null
$genArgs = $null
if ($isGen) {
    # Work tree: the generated fixture (longfix/src and longfix/test, or tallyctl/), committed.
    New-Item -ItemType Directory -Force -Path $work, (Split-Path -Parent $manifestPath) | Out-Null
    $genArgv = @('--out', $work, '--manifest', $manifestPath) +
        $(if ($isLong) { @('--modules', "$Modules") } else { @() })
    $genOut = (& python -I $genPy @genArgv 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE) { Remove-WorkTree; Remove-Item -LiteralPath $manifestPath -ErrorAction Ignore; throw "$(Split-Path -Leaf $genPy) failed ($LASTEXITCODE): $genOut" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $fixtureSha = $manifest.fixture_sha256
    if ($isLong) {
        $c.allowed = @($manifest.files.path | Where-Object { $_ -like 'longfix/src/*' })
        $genArgs = "modules=$($manifest.generator.modules) lines=$($manifest.generator.lines)"
    } else {
        $genArgs = "version=$($manifest.generator.version)"
    }
} else {
    # Work tree: the fixture at its repo-relative path, committed.
    New-Item -ItemType Directory -Force -Path (Join-Path $work 'bench\loop') | Out-Null
    Copy-Item -Recurse -LiteralPath $fixture -Destination (Join-Path $work 'bench\loop\fixture')
    $fixtureSha = Get-TreeSha256 $work 'bench\loop\fixture'
}
& git -C $work init -q
& git -C $work add -A
& git -C $work -c user.name=ladder -c user.email=ladder@localhost -c commit.gpgsign=false commit -qm 'ladder fixture'
if ($LASTEXITCODE) { Remove-WorkTree; throw "git commit in $work failed ($LASTEXITCODE)" }

$tapBefore = Invoke-Tests
$before = Read-Tap $tapBefore
$bad = @(@($c.targets) + @($c.keep_failing) | Where-Object { -not $before.Contains($_) -or $before[$_] })
$nPass = @($before.Values | Where-Object { $_ }).Count
$nFail = @($before.Values | Where-Object { -not $_ }).Count
$beforeChars = $null
$beforeCharsTap = $null
$nodeVersion = ("$(& node --version 2>&1)").Trim()
$nodePath = (Get-Command node -CommandType Application -ErrorAction Ignore |
    Select-Object -First 1).Source
$modelNode = Get-ModelNode
$visibleText = $null
if ($isGen) {
    # The TAP results must equal the manifest's expect_before: no test missing, extra or flipped.
    $want = [ordered]@{}
    foreach ($t in $manifest.tests) { $want[$t.name] = $t.expect_before -eq 'pass' }
    $bad = @(@($want.Keys | Where-Object { -not $before.Contains($_) -or $before[$_] -ne $want[$_] }) +
        @($before.Keys | Where-Object { -not $want.Contains($_) }))
}
$figureBad = @()
if ($isStale) {
    # Each figure's doc, src and test line (1-based) holds its value as a whole number.
    foreach ($f in $manifest.figures) {
        foreach ($at in @(@($f.doc_path, $f.doc_line, $f.doc_value), @($f.src_path, $f.src_line, $f.true_value),
                @($f.test_path, $f.test_line, $f.true_value))) {
            $ln = @(Get-Content -LiteralPath (Join-Path $work $at[0]) -ErrorAction Ignore)
            if ($at[1] -gt $ln.Count -or $ln[$at[1] - 1] -notmatch "(?<![\w.])$($at[2])(?![\w]|\.\d)") {
                $figureBad += "$($f.name) $($f.kind): $($at[0]):$($at[1]) does not hold $($at[2])"
            }
        }
    }
    $bad = @($bad) + $figureBad
}
if ($isLong) {
    # Output of the prompt's exact command, as the model will see it: through Git Bash with
    # the model's node. _tap: the TAP run above (this shell's node), LF newlines.
    $beforeOut = $null
    if ($modelNode) {
        $beforeOut = Measure-Output { & $gitBash $modelNode.shell "$longCmd 2>&1" 2>$null }
        $beforeChars = $beforeOut.Length
    }
    $beforeCharsTap = ($tapBefore -replace "`r`n", "`n").Length
    # Fail closed: the model must see every result line, so the whole output must be shown.
    $hasSum = [regex]::IsMatch("$beforeOut", '(?m)^# pass \d+\r?$') -and
        [regex]::IsMatch("$beforeOut", '(?m)^# fail \d+\r?$')
    $visibleText = "whole output $beforeChars chars <= $shownTotal, '# pass' and '# fail' present"
    if (-not $modelNode -or -not $hasSum -or $beforeChars -gt $shownTotal) {
        Remove-WorkTree
        if (-not $DryRun) { Remove-Item -LiteralPath $manifestPath -ErrorAction Ignore }
        throw ('long-fix refused: ' + $(if (-not $modelNode) {
                    'Git Bash found no node: the model-node run to check does not exist' }
                elseif (-not $hasSum) {
                    "the model-node run of $longCmd ($beforeChars chars) has no '# pass N' and " +
                    "'# fail N' lines" }
                else {
                    "the model-node run of $longCmd is $beforeChars chars, over the " +
                    "$shownTotal that Claude Code shows whole: the model could not see every " +
                    'result line' }))
    }
}
$modelNodeText = if (-not $modelNode) { 'not found (Git Bash)' }
else { "$($modelNode.version) ($($modelNode.path), Git Bash $($modelNode.shell))" }
$ctxText = "context_tokens $(if ($null -ne $ctxTokens) { $ctxTokens } else { 'unknown' }) " +
    "($(if ($ctxBound) { '-ContextTokens' } else { 'wrapper default' }))"
# The wrapper's argument list (-LisPrintArgs never starts claude): printed by -DryRun, and
# for stale-figure the source of policy_sha256 in a real run too.
$printed = $null
$printCode = $null
$printedArgs = $null
if ($DryRun -or $isStale) {
    $printArgv = @($sessionArgv[0..2]) + '-LisPrintArgs' + @($sessionArgv[3..($sessionArgv.Count - 1)])
    Push-Location -LiteralPath $work
    try { $printed = & $pwshExe @printArgv 2>&1 } finally { Pop-Location }
    $printCode = $LASTEXITCODE
    $joined = (@($printed | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] }) -join "`n")
    $mArr = [regex]::Match($joined, '(?s)claude arguments \(JSON array, in order\):\s*(\[.*?\n\])')
    if ($mArr.Success) { $printedArgs = [string[]]@($mArr.Groups[1].Value | ConvertFrom-Json) }
}
$policySha = $null
if ($isStale) {
    $iPolicy = if ($printedArgs) { [Array]::IndexOf($printedArgs, '--append-system-prompt') } else { -1 }
    if ($iPolicy -lt 0 -or $iPolicy + 1 -ge $printedArgs.Count) {
        Remove-WorkTree
        if (-not $DryRun) { Remove-Item -LiteralPath $manifestPath -ErrorAction Ignore }
        throw "stale-figure refused: the wrapper's -LisPrintArgs output (exit $printCode) has no --append-system-prompt value, so policy_sha256 cannot be computed"
    }
    $policySha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
            [Text.Encoding]::UTF8.GetBytes($printedArgs[$iPolicy + 1]))).ToLowerInvariant()
}
$repFields = [ordered]@{
    fixture_sha256 = $fixtureSha; generator_args = $genArgs; prompt = $c.prompt
    server_cmdline = $server.cmdline; claude_version = $null; max_turns = $MaxTurns
    timeout_min = $TimeoutMin; context_tokens = $ctxTokens
    model_node_version = $modelNode ? $modelNode.version : $null
    policy_sha256 = $policySha
}

if ($DryRun) {
    if ($isLong) {
        Write-Host "case: $Case (profile longrun, loop guard on, $ctxText)"
        Write-Host "work tree: $work (generated: $genOut; git init + commit)"
        Write-Host "manifest: $manifestPath (outside the work tree; a real run writes $base.manifest.json)"
        $treeSha = Get-TreeSha256 $work 'longfix'
        $treeNote = if ($treeSha -eq $fixtureSha) { 'matches' } else { "DIFFERS: $treeSha" }
        Write-Host "fixture_sha256: $fixtureSha (generator $genArgs; tree hash $treeNote)"
        Write-Host "node: $nodeVersion ($nodePath) | model_node_version: $modelNodeText"
        Write-Host "tests before: pass $nPass, fail $nFail of $($before.Count) (TAP)"
        Write-Host ("precondition: " + $(if ($bad.Count) { "FAIL, TAP differs from the manifest's expect_before for: $(@($bad | Select-Object -First 5) -join ' | ')" }
                else { "ok, fail $nFail of $($want.Count) (every bug test not ok, every guard ok, as the manifest expects)" }))
        Write-Host ("before_output_chars: $beforeChars ($longCmd via Git Bash, model node) | " +
            "before_output_chars_tap: $beforeCharsTap (TAP run, node $nodeVersion)")
        Write-Host "visibility check: ok, $visibleText"
        Write-Host "allowed files: $($c.allowed.Count) ($($c.allowed[0]) .. $($c.allowed[-1])), plus the facts file the banner names"
        Write-Host "prompt ($($c.prompt.Length) chars, one argv string):"
        Write-Host "  $($c.prompt)"
    } elseif ($isStale) {
        Write-Host "case: $Case (profile review, loop guard on, $ctxText)"
        Write-Host "work tree: $work (generated: $genOut; git init + commit)"
        Write-Host "manifest: $manifestPath (outside the work tree; a real run writes $base.manifest.json)"
        $treeSha = Get-TreeSha256 $work 'tallyctl'
        $treeNote = if ($treeSha -eq $fixtureSha) { 'matches' } else { "DIFFERS: $treeSha" }
        Write-Host "fixture_sha256: $fixtureSha (generator $genArgs; tree hash $treeNote)"
        Write-Host "node: $nodeVersion ($nodePath) | model_node_version: $modelNodeText"
        Write-Host "tests before: pass $nPass, fail $nFail of $($before.Count) (TAP)"
        foreach ($f in $manifest.figures) {
            Write-Host "  figure $($f.name) $($f.kind): $($f.doc_path):$($f.doc_line) says $($f.doc_value); $($f.src_path):$($f.src_line) and $($f.test_path):$($f.test_line) hold $($f.true_value)"
        }
        Write-Host ("precondition: " + $(if ($bad.Count) { "FAIL: $(@($bad | Select-Object -First 5) -join ' | ')" }
                else { "ok, pass $nPass of $($want.Count) as the manifest expects; every figure line holds its value" }))
        Write-Host "allowed files: none (git status --porcelain of the work tree must stay empty)"
        Write-Host "prompt ($($c.prompt.Length) chars, one argv string):"
        Write-Host "  $($c.prompt)"
    } else {
        Write-Host "case: $Case (profile edit, loop guard on, $ctxText)"
        Write-Host "work tree: $work (fixture at bench\loop\fixture, git init + commit)"
        Write-Host "fixture_sha256: $fixtureSha (tree hash of bench/loop/fixture)"
        Write-Host "node: $nodeVersion ($nodePath) | model_node_version: $modelNodeText"
        Write-Host "tests before: pass $nPass, fail $nFail ($testCmd)"
        foreach ($k in $before.Keys) { Write-Host "  $(if ($before[$k]) { 'ok    ' } else { 'not ok' }) $k" }
        Write-Host "$(if ($c.targets.Count -gt 1) { 'targets' } else { 'target' }) (must fail before): $($c.targets -join ' | ')"
        Write-Host "keep failing: $(if ($c.keep_failing.Count) { $c.keep_failing -join ' | ' } else { '(none)' })"
        Write-Host "allowed files: $($c.allowed -join ', ')"
        Write-Host "precondition: $(if ($bad.Count) { "FAIL, these do not fail before: $($bad -join ' | ')" } else { 'ok' })"
    }
    $nArgs = if ($printedArgs) { $printedArgs.Count } else { $null }
    Write-Host "wrapper -LisPrintArgs (claude not started): exit $printCode, $nArgs claude arguments; stderr banner:"
    foreach ($l in @($printed | Where-Object { $_ -is [Management.Automation.ErrorRecord] })) { Write-Host "  $l" }
    Write-Host "session (cwd $work, timeout $TimeoutMin min):"
    Write-Host ('  ' + (Format-Cmd $pwshExe $sessionArgv))
    Write-Host "capture: stdout -> $base.jsonl, stderr -> $base.stderr.txt"
    if ($isLong) {
        Write-Host "then: transcript by session id -> $base.transcript.jsonl (null when not found)"
        Write-Host "then: the banner's facts file -> $base.facts.md (grade.py grades the copy)"
    }
    Write-Host "after: tests again, git add -A, git diff --cached --numstat/--stat/patch"
    Write-Host ('grade: ' + (Format-Cmd 'python' @('-I', $gradePy, $base)))
    if ($isStale) { Write-Host "policy_sha256: $policySha (SHA-256 of the --append-system-prompt value; a rep_key input)" }
    Write-Host ("rep_key: $(Get-RepKey $repFields) (dry run: server_cmdline and claude_version " +
        "are null, so a real run's key differs)")
    Write-Host "server: not queried in -DryRun$(if ($isGen) { " (a real $Case run refuses a server with reasoning on unless -AllowReasoningOn)" })"
    Remove-WorkTree
    return
}

if ($bad.Count) {
    Remove-WorkTree
    if ($isLong) {
        Remove-Item -LiteralPath $manifestPath -ErrorAction Ignore
        throw "case $Case is invalid: TAP before differs from the manifest's expect_before for: $(@($bad | Select-Object -First 5) -join ' | ')"
    }
    if ($isStale) {
        Remove-Item -LiteralPath $manifestPath -ErrorAction Ignore
        throw "case $Case is invalid: $(@($bad | Select-Object -First 5) -join ' | ') (TAP before against the manifest's expect_before, then the figure lines)"
    }
    throw "case $Case is invalid: these tests do not fail before the run: $($bad -join ' | ')"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Set-Content -LiteralPath "$base.tests-before.txt" -Value $tapBefore -Encoding utf8NoBOM
$claudeVersion = ("$(& claude --version 2>&1)").Trim()
$repFields.claude_version = $claudeVersion
$repKey = Get-RepKey $repFields
Say ("ladder $Case | $claudeVersion | node $nodeVersion | model node $modelNodeText | " +
    "max-turns $MaxTurns | $ctxText | model $($server.model_path)")
Say "tests before: pass $nPass, fail $nFail | rep_key $repKey"
if ($isLong) {
    Say ("generated: $genOut | manifest $manifestPath | before_output_chars $beforeChars | " +
        "before_output_chars_tap $beforeCharsTap | visibility check ok: $visibleText")
}
if ($isStale) { Say "generated: $genOut | manifest $manifestPath | policy_sha256 $policySha" }

$proc = $null
$timedOut = $false
$stdout = ''
$stderr = ''
# The repo's own status before and after: a write outside the work tree into the repo.
$dirtyBefore = @(& git -C $repo status --porcelain)
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    $psi = [Diagnostics.ProcessStartInfo]::new($pwshExe)
    $psi.WorkingDirectory = $work
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($k in @($psi.Environment.Keys)) { if ($k -match $stripEnv) { $null = $psi.Environment.Remove($k) } }
    foreach ($a in $sessionArgv) { $psi.ArgumentList.Add($a) }
    Say "session start: $(Format-Cmd $pwshExe $sessionArgv)"
    $proc = [Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Close()
    $so = $proc.StandardOutput.ReadToEndAsync()
    $se = $proc.StandardError.ReadToEndAsync()
    # 1 s polls instead of one long blocking wait, so Ctrl+C reaches the finally below.
    while (-not $proc.WaitForExit(1000)) {
        if ($sw.Elapsed.TotalMinutes -ge $TimeoutMin) { $timedOut = $true; break }
    }
    # Our own process object (the pwsh started above) and its tree, never a looked-up pid.
    if ($timedOut) { $proc.Kill($true); $proc.WaitForExit() }
    $stdout = $so.GetAwaiter().GetResult()
    $stderr = $se.GetAwaiter().GetResult()
} finally {
    # A killed wrapper skips its own finally, so its per-pid temp files are removed here.
    if ($proc -and ($timedOut -or -not $proc.HasExited)) {
        if (-not $proc.HasExited) { $proc.Kill($true); $proc.WaitForExit() }
        Remove-Item -LiteralPath (Join-Path $env:TEMP "lis-settings-$($proc.Id).json"), (Join-Path $env:TEMP "lis-mcp-$($proc.Id).json") -ErrorAction Ignore
    }
}
$sw.Stop()
$dirtyAfter = @(& git -C $repo status --porcelain)
Set-Content -LiteralPath "$base.jsonl" -Value $stdout -NoNewline -Encoding utf8NoBOM
Set-Content -LiteralPath "$base.stderr.txt" -Value $stderr -Encoding utf8NoBOM
Say ("session end: exit {0} | timed out {1} | wall {2} s" -f $proc.ExitCode, $timedOut, [math]::Round($sw.Elapsed.TotalSeconds, 1))

# long-fix: the session transcript by session id (result record, else init), as bench/compact.
$transcript = $null
$factsCopy = $null
if ($isLong) {
    $sid = $null
    foreach ($ln in $stdout -split "`r?`n") {
        if ($ln -notmatch '"type"\s*:\s*"(result|system)"') { continue }
        try { $o = $ln | ConvertFrom-Json -Depth 50 } catch { continue }
        if ($o.type -eq 'result' -and $o.session_id) { $sid = $o.session_id }
        elseif (-not $sid -and $o.type -eq 'system' -and $o.subtype -eq 'init' -and $o.session_id) { $sid = $o.session_id }
    }
    if ("$sid" -match '^[0-9A-Fa-f-]{36}$') {
        $src = Get-ChildItem -LiteralPath (Join-Path $HOME '.claude\projects') -Recurse -File -Filter "$sid.jsonl" -ErrorAction Ignore | Select-Object -First 1
        if ($src) { $transcript = "$base.transcript.jsonl"; Copy-Item -LiteralPath $src.FullName -Destination $transcript }
    }
    $facts = @([regex]::Matches($stderr, 'lis-facts-\d{8}-\d{6}\.md') | ForEach-Object Value | Select-Object -Unique)
    # The facts file as the session left it, next to the other artifacts (grade.py reads it).
    $factsWork = if ($facts.Count -eq 1) { Join-Path $work $facts[0] }
    if ($factsWork -and (Test-Path -LiteralPath $factsWork -PathType Leaf)) {
        $factsCopy = "$base.facts.md"
        Copy-Item -LiteralPath $factsWork -Destination $factsCopy
    }
    Say ("session id $(if ($sid) { $sid } else { 'not found' }) | transcript " +
        "$(if ($transcript) { 'copied' } else { 'not found' }) | facts file $($facts -join ', ') " +
        "$(if ($factsCopy) { "-> $factsCopy" } else { '(not copied)' })")
}

Set-Content -LiteralPath "$base.tests-after.txt" -Value (Invoke-Tests) -Encoding utf8NoBOM
# Before git add -A: stalefig.py's scope_ok needs an empty work-tree status.
$workStatus = @(& git -C $work status --porcelain)
$workStatusExit = $LASTEXITCODE
& git -C $work add -A
$gitAddExit = $LASTEXITCODE
if ($gitAddExit) { Say "git add -A in the work tree failed ($gitAddExit): scope_ok will be null" }
$numstat =(& git -C $work diff --cached --numstat --no-renames | Out-String)
Set-Content -LiteralPath "$base.numstat.txt" -Value $numstat -Encoding utf8NoBOM
$diff = (& git -C $work diff --cached --stat --no-renames | Out-String) + (& git -C $work diff --cached --no-renames | Out-String)
Set-Content -LiteralPath "$base.diff.txt" -Value $diff -Encoding utf8NoBOM

[ordered]@{
    case              = $Case
    profile           = $c.profile
    grader            = $c.grader
    stamp             = $stamp
    prompt            = $c.prompt
    target_tests      = $c.targets
    keep_failing      = $c.keep_failing
    require_others_failing = $c.require_others_failing
    allowed_files     = $c.allowed
    test_dir          = $c.test_dir
    test_cmd          = $c.test_cmd
    manifest          = $manifest ? $manifestPath : $null
    transcript        = $transcript
    facts_copy        = $factsCopy
    before_output_chars = $beforeChars
    before_output_chars_tap = $beforeCharsTap
    context_tokens    = $ctxTokens
    fixture_sha256    = $fixtureSha
    generator_args    = $genArgs
    rep_key           = $repKey
    rep_key_inputs    = $repKeyInputs
    policy_sha256     = $policySha
    allow_reasoning_on = [bool]$AllowReasoningOn
    argv              = $sessionArgv
    work_dir          = $work
    max_turns         = $MaxTurns
    timeout_min       = $TimeoutMin
    exit_code         = $proc.ExitCode
    timed_out         = $timedOut
    wall_s            = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    git_add_exit      = $gitAddExit
    work_status       = $workStatus
    work_status_exit  = $workStatusExit
    repo_dirty_before = $dirtyBefore
    repo_dirty_after  = $dirtyAfter
    claude_version    = $claudeVersion
    node_version      = $nodeVersion
    model_node_version = $modelNode ? $modelNode.version : $null
    model_node_path   = $modelNode ? $modelNode.path : $null
    model_node_shell  = $modelNode ? $modelNode.shell : $null
    server            = $server
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$base.meta.json" -Encoding utf8NoBOM

[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
& python -I $gradePy $base | Tee-Object -FilePath "$base.run.log" -Append
