#Requires -Version 7.0
<#
.SYNOPSIS
  Run llama-server (Anthropic /v1/messages on 127.0.0.1) from bin/.
.DESCRIPTION
  Default command line (Model test 2 ruling of 2026-11-08 22:27 in docs/ROADMAP.md, on
  top of rulings 6 and 14; ruling 14 of 2026-10-25 reverted ruling 12's 65536 + MTP):
  the local RentedNoodle Qwen3.8-27B-OrcaRouter-GSQ-RCO IQ3_XXS v2.1 file (the default
  until then, the orcarouter Qwen3.8-27B-Uncensored IQ3_XXS, is the fallback) at
  -c 131072 with q4_0 KV,
  --chat-template-file config/chat-templates/qwen3.8-27b.jinja and no MTP,
  plus -fa on, -np 1,
  Qwen sampling, --host/--port, --reasoning-format auto, --reasoning off, --api-key-file
  logs/api-key, --no-webui, --metrics and --no-mmproj (the vision projector is skipped
  unless -WithMmproj).
  --metrics serves the Prometheus /metrics endpoint (KV fill, queue depth); like /slots it
  needs the per-start key (UNVERIFIED until the next start). Before each start of
  llama-server (the first and every restart) the script logs "serve.ps1: vram free: <N>
  MiB" from nvidia-smi --query-gpu=memory.free (one value per GPU, comma-separated), or
  "serve.ps1: vram free: unavailable" when nvidia-smi is missing, fails, prints no number
  or takes over 10 s; the start goes on either way.
  API key: each start of this script writes a new random key (32 random bytes as 64 hex
  characters) to logs/api-key under the repo root (gitignored; the file is recreated with
  an ACL that grants only the current user) and passes the file with --api-key-file, so
  the key is in neither the command line nor the log. Eight scripts read that file and
  fall back to the old fixed key `local` when it is missing: scripts/claude-local.ps1,
  scripts/smoke.ps1, scripts/web-smoke.ps1, bench/run.ps1 and bench/ladder, loop, perm
  and compact run.ps1. -ExtraArgs / -ExtraArgLine may not carry --host, --port,
  --api-key, --api-key-file, --connect, --connect-code, --tools, --agent, --reuse-port,
  --webui, --ui, --mcp-servers-config, --mcp-servers-json, --ui-mcp-proxy,
  --webui-mcp-proxy, --path, -ag, --media-path, --hf-token, -hft, --slot-save-path,
  --log-prompts-dir, --props, --models-dir or --models-preset, alone or as --flag=value
  (the script throws): the loopback bind, the key, the disabled web UI, tools and MCP and
  the server's file paths are fixed here. llama-server also reads flags from LLAMA_ARG_*
  variables, so before the launch the script removes LLAMA_ARG_AGENT, _TOOLS, _CONNECT,
  _CONNECT_CODE, _MCP_SERVERS_CONFIG, _MCP_SERVERS_JSON, _UI_MCP_PROXY, _STATIC_PATH,
  _REUSE_PORT, _HOST, _PORT, _ENDPOINT_PROPS and LLAMA_API_KEY from its environment and
  logs "serve.ps1: cleared N llama-server env overrides (<names>)" when it removed any.
  The flag and variable names are verified against the bundled build's --help; that a
  command-line flag wins over its variable is UNVERIFIED. The environment forms of the
  file-path and token flags (HF_TOKEN, LLAMA_ARG_SLOT_SAVE_PATH and the like) are not
  cleared.
  --cors-origins is left alone: llama-server defaults it to `*`, and the random key is
  the mitigation (the effect of narrowing it is UNVERIFIED).
  One serve.ps1 per port: the script holds the named mutex
  Global\LocalInferenceStudio-serve-<port> until it ends (released also when it runs
  in-process with &), and a second instance on the same port exits 1 with "another
  serve.ps1 holds port <port>".
  Restarts: when llama-server exits with a non-zero code (a crash, a driver reset, a
  kill), the script starts it again after 10, 30, 60, 120, then 300 s (-RestartDelaySec;
  the last value repeats), at most -MaxRestarts times (default 5) within
  -RestartWindowMin minutes (default 60); the next failure gives up and the script exits
  with llama-server's code. Exit code 0 is a clean exit and is not restarted.
  scripts/stop.ps1 writes logs/.stop-requested-<port> before it stops the server; this
  script deletes that file when it starts and never restarts while it exists (also during the
  backoff wait, checked every second). Each restart, stop and give-up writes one
  "serve.ps1: ..." line to the log (or the console without -LogFile); the stop line
  carries stop.ps1's "[stop.ps1] stop requested <timestamp>" marker from that file.
  -MaxRestarts 0 runs llama-server once, as before. Combined bound: with
  scripts/watchdog.ps1 (at most 3 restarts an hour, each a new serve.ps1 with its own
  1 + 5 starts) a crash-looping server is started about 18 times an hour at most (24 in
  the first hour, counting the logon start), assuming the task's RestartCount does not
  fire on a non-zero exit (UNVERIFIED).
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
  defaults to q4_0 for the default and the fallback model files only and to q8_0 for
  any other -Model (the KV the other rows were benched with); an explicit -KvType always
  wins. Both files were measured at 131072 with q4_0 KV: the fallback all-GPU (Phase
  3d), the default whole-card only (14,736 of 16,376 MiB, Model test 2; its layer split
  is UNVERIFIED).
  -ChatTemplateFile (relative to the repo root) is passed as --chat-template-file; it
  defaults to config/chat-templates/qwen3.8-27b.jinja when the model is under
  models/qwen3.8-27b-gsq-rco or models/qwen3.8-27b-uncensored (the orcarouter and ISTA
  GGUFs embed the stock template, which rejects Claude Code's second system message with
  HTTP 500; the default embeds another one, untested).
  MTP (--spec-type draft-mtp --spec-draft-n-max 2) is added for the fallback model file
  only, at -Ctx 65536 or below, unless -NoMtp; the default and any other -Model run
  without it at every -Ctx (the default's MTP head is present but UNVERIFIED here). The
  fallback fits all-GPU at 65536 with q4_0 KV and MTP (Phase 3e), so `-Ctx 65536` turns
  it on there. The fallback at the default -Ctx (131072) skips it silently; an explicit
  -Ctx above 65536 skips it with a warning (pass -NoMtp to silence it), since MTP there
  is expected to push layers to CPU. The fallback starts with scripts/stop.ps1, then
  `serve.ps1 -Model models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf -LogFile logs\llama-server.log`.
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
  Supply-chain checks (security audit S-O1, S-O2) run once per serve.ps1 run, before
  the key file is written and outside the restart loop. llama-server.exe and
  llama-server-impl.dll (the exe is a 9 KB loader for that dll) are hashed and compared
  with the pins next to the zip digests in scripts/install.ps1 ($pinned, read as data),
  for the release named in bin\llama-release.txt (install.ps1 writes it) or, without
  that file, the pinned release the exe matches. A mismatch, or an exe that matches no
  pinned release while that file is absent, refuses the start and prints both hashes,
  and so does a missing install.ps1 or a $pinned table that cannot be read. A release
  with no exe pin in install.ps1, or a pinned release with no pin for the dll, warns
  and goes on, so an upgrade is not blocked. Other DLLs (llama.dll, llama-common.dll,
  ggml, CUDA) are not checked. A local -Model listed in models/manifest.json
  (-ModelManifest, relative to the repo root) is hashed at most once per boot: when
  logs/model-verify.json holds the same boot time (Win32_OperatingSystem
  LastBootUpTime), path, size, mtime and manifest sha256, it is not hashed; otherwise a
  size or sha256 mismatch refuses the start with both values and a match writes that
  marker (none when the boot time cannot be read, so the next run hashes again).
  Hashing the fallback 11.6 GB file took 20 s cold and 8.9 s from the OS file cache on
  the reference machine (2026-11-04); restarts in the loop never rehash, and a later
  serve.ps1 in the same boot (the watchdog's) takes the marker. A file not in the
  manifest, or an -hf model, warns and goes on. -SkipModelVerify skips the model hash
  and logs that it did. A check that throws refuses the start with its message. A stop
  request written while the checks run is honoured: serve.ps1 logs it and exits 0
  without starting llama-server (one from before this run is deleted, as above).
  -VerifyOnly runs both checks and exits (0 = pass); -PrintArgs prints the llama-server
  command line and exits without the checks. Neither takes the port mutex, checks the
  port, writes the key file, deletes a stop request, rotates or appends to -LogFile
  (their lines go to the console) or starts anything. -VerifyOnly creates logs\ and
  writes logs/model-verify.json when the model hash runs and matches; -PrintArgs
  writes nothing.
  -Web is the server half of a web session (docs/web-access.md; the session half is
  `claude-local.ps1 -LisWeb`, which runs in the lis-web container and does not start the
  server): it
  passes -lv 3 (info, llama-server's default threshold), clears LLAMA_ARG_LOG_VERBOSITY
  and refuses -v, --verbose, --log-verbose and any -lv, --verbosity or --log-verbosity
  above 3 in -ExtraArgs or -ExtraArgLine (security audit S-L1: levels 4 and 5 may log
  request bodies, UNVERIFIED).
.EXAMPLE
  pwsh scripts/serve.ps1 -Model unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS -NCpuMoe 8
.EXAMPLE
  pwsh scripts/serve.ps1 -ExtraArgLine '-lv 4'
.EXAMPLE
  pwsh scripts/serve.ps1 -Reasoning on
.EXAMPLE
  pwsh scripts/serve.ps1 -VerifyOnly
.EXAMPLE
  pwsh scripts/serve.ps1 -Web -PrintArgs
#>
[CmdletBinding()]
param(
    [string]$Model = 'models\qwen3.8-27b-uncensored\Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf',
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
    [switch]$Web,
    [switch]$VerifyOnly,
    [switch]$PrintArgs,
    [switch]$SkipModelVerify,
    [string]$ModelManifest = 'models\manifest.json',
    [string[]]$ExtraArgs = @(),
    [string]$ExtraArgLine = '',
    [string]$LogFile = '',
    [ValidateRange(0, 100)][int]$MaxRestarts = 5,
    [ValidateRange(1, 1440)][int]$RestartWindowMin = 60,
    [ValidateCount(1, 20)][ValidateRange(0, 3600)][int[]]$RestartDelaySec = @(10, 30, 60, 120, 300)
)
$ErrorActionPreference = 'Stop'

# The bind address, port, key, web UI, tools and MCP are fixed by this script
# (security audit B6/B7).
$fixedFlag = '^(--(host|port|api-key|api-key-file|connect|connect-code|tools|agent|reuse-port|webui|ui|' +
    'mcp-servers-config|mcp-servers-json|ui-mcp-proxy|webui-mcp-proxy|path|media-path|hf-token|slot-save-path|' +
    'log-prompts-dir|props|models-dir|models-preset)|-ag|-hft)(=|$)'
$extraTokens = @($ExtraArgs | ForEach-Object { "$_" -split '\s+' }) + @($ExtraArgLine -split '\s+')
$badFlag = @($extraTokens | Where-Object { $_ -match $fixedFlag })
if ($badFlag) {
    throw ("-ExtraArgs/-ExtraArgLine may not set $($badFlag -join ', '): serve.ps1 fixes --host, --port, the API key " +
        'and keeps the web UI, tools, MCP and the server''s file paths off.')
}
# A web session logs at -lv 3 or lower (security audit S-L1: higher levels may log
# bodies).
if ($Web) {
    $loud = @()
    for ($i = 0; $i -lt $extraTokens.Count; $i++) {
        $t = $extraTokens[$i]
        if ($t -match '^(-v|--verbose|--log-verbose)$') { $loud += $t; continue }
        if ($t -match '^(-lv|--verbosity|--log-verbosity)(=(.*))?$') {
            $v = if ($Matches[2]) { $Matches[3] } else { $extraTokens[$i + 1] }
            if ("$v" -notmatch '^[0-3]$') { $loud += "$t $v" }
        }
    }
    if ($loud) { throw "-Web keeps the server log at -lv 3 or lower; refused: $($loud -join ', ')" }
}

$binDir = Join-Path $PSScriptRoot '..\bin'
$exe = Join-Path $binDir 'llama-server.exe'
if (-not (Test-Path $exe)) { throw "llama-server.exe not found in $binDir. Run scripts/install.ps1 first." }

# One instance per port, held until this process exits (two at once would race on the
# key file and the port check below). -VerifyOnly and -PrintArgs start nothing and
# skip it.
$dryRun = $VerifyOnly -or $PrintArgs
$mutex = [Threading.Mutex]::new($false, "Global\LocalInferenceStudio-serve-$Port")
$owned = $false
if (-not $dryRun) {
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { Write-Host "another serve.ps1 holds port $Port"; exit 1 }
}
# Released in the finally below, not only at process exit: an in-process run
# (& serve.ps1) would otherwise keep the port's mutex until its pwsh exits.
try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
    if ($listener -and -not $dryRun) {
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
    $defaultModel = [IO.Path]::GetFullPath('models\qwen3.8-27b-uncensored\Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf', $repoRoot)
    $fallbackModel = [IO.Path]::GetFullPath('models\qwen3.8-27b-uncensored\Qwen3.8-27B-Uncensored-IQ3_XXS.gguf', $repoRoot)
    if (-not $PSBoundParameters.ContainsKey('KvType') -and $Model -ne $defaultModel -and $Model -ne $fallbackModel) { $KvType = 'q8_0' }
    if (-not $ChatTemplateFile -and $source -eq '-m' -and
        (@('models\qwen3.8-27b-gsq-rco', 'models\qwen3.8-27b-uncensored') | Where-Object {
            $Model.StartsWith([IO.Path]::GetFullPath($_, $repoRoot) + '\', 'OrdinalIgnoreCase') })) {
        $ChatTemplateFile = 'config\chat-templates\qwen3.8-27b.jinja'
    }
    if ($ChatTemplateFile) {
        $ChatTemplateFile = [IO.Path]::GetFullPath($ChatTemplateFile, $repoRoot)
        if (-not (Test-Path -LiteralPath $ChatTemplateFile -PathType Leaf)) { throw "Chat template not found: $ChatTemplateFile" }
    }
    $logsDir = Join-Path $repoRoot 'logs'
    $keyFile = Join-Path $logsDir 'api-key'
    $stopFile = Join-Path $logsDir ".stop-requested-$Port"
    if (-not $PrintArgs) { New-Item -ItemType Directory -Force -Path $logsDir | Out-Null }
    # A stop request from before this run is stale; one written while the checks below
    # run is honoured before the start.
    if (-not $dryRun) { Remove-Item -LiteralPath $stopFile -Force -ErrorAction Ignore }
    # A dry run neither rotates nor appends to -LogFile: its lines go to the console.
    if ($LogFile -and -not $dryRun) {
        # Relative to the current filesystem location, not the process cwd (which
        # Set-Location does not change); $PWD can be a non-filesystem drive (HKCU:, Env:).
        $LogFile = [IO.Path]::GetFullPath($LogFile, (Get-Location -PSProvider FileSystem).ProviderPath)
        $logDir = Split-Path -Parent $LogFile
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        if ((Test-Path -LiteralPath $LogFile) -and (Get-Item -LiteralPath $LogFile).Length -gt 50MB) {
            Move-Item -LiteralPath $LogFile -Destination "$LogFile.1" -Force
        }
    }
    # stop.ps1 writes its log marker into the stop file too; it cannot append to the log
    # while llama-server's output is redirected into it.
    function Get-StopRequest { "$(Get-Content -LiteralPath $stopFile -TotalCount 1 -ErrorAction Ignore) ($stopFile)" }
    function Get-RecentRestarts([datetime[]]$Times, [datetime]$Now, [int]$WindowMin) {
        @($Times | Where-Object { ($Now - $_).TotalMinutes -lt $WindowMin })
    }
    function Write-ServeLog([string]$Line) {
        if ($LogFile -and -not $dryRun) {
            Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $Line"
        } else { Write-Host $Line }
    }
    # Supply-chain checks (security audit S-O1, S-O2). Each returns 'ok', 'marker', 'warn'
    # or 'refuse' and a message. $pinned is read from install.ps1 as data: SafeGetValue
    # evaluates constants only and runs no code.
    function Test-ServerBinary([string]$BinDir, [string]$InstallScript) {
        $have = [ordered]@{}
        foreach ($n in 'llama-server.exe', 'llama-server-impl.dll') {
            $p = Join-Path $BinDir $n
            $have[$n] = if (Test-Path -LiteralPath $p -PathType Leaf) {
                (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower()
            } else { 'absent' }
        }
        if (-not (Test-Path -LiteralPath $InstallScript -PathType Leaf)) {
            return 'refuse', "$InstallScript not found: the llama-server pins are read from it"
        }
        $ast = [Management.Automation.Language.Parser]::ParseFile($InstallScript, [ref]$null, [ref]$null)
        $set = $ast.Find({ param($a) $a -is [Management.Automation.Language.AssignmentStatementAst] -and
                "$($a.Left)" -eq '$pinned' }, $true)
        $pinned = if ($set) { $set.Right.Expression.SafeGetValue() }
        if ($pinned -isnot [hashtable] -or -not $pinned.Count) {
            return 'refuse', "no `$pinned table of release pins in $InstallScript; llama-server not checked"
        }
        $exe = $have['llama-server.exe']
        $tag = Join-Path $BinDir 'llama-release.txt'
        $release = "$(Get-Content -LiteralPath $tag -TotalCount 1 -ErrorAction Ignore)".Trim()
        if (-not $release) {
            $release = @($pinned.Keys | Where-Object { $pinned[$_]['llama-server.exe'] -eq $exe })[0]
            if (-not $release) {
                $pins = @($pinned.Keys | ForEach-Object { "$_ $($pinned[$_]['llama-server.exe'])" }) -join '; '
                return 'refuse', ("llama-server.exe sha256 $exe matches no release pinned in scripts/install.ps1 " +
                    "($(if ($pins) { $pins } else { 'no pins found' })) and bin\llama-release.txt is absent; " +
                    'after an upgrade by hand write its release tag there')
            }
        }
        $pin = $pinned[$release]
        if (-not ($pin -and $pin['llama-server.exe'])) {
            return 'warn', "no llama-server.exe pin for release $release in scripts/install.ps1; not checked (sha256 $exe)"
        }
        $bad = @($have.Keys | Where-Object { $pin[$_] -and $pin[$_] -ne $have[$_] } |
                ForEach-Object { "$_ sha256 $($have[$_]), pinned for $release $($pin[$_])" })
        if ($bad) { return 'refuse', ($bad -join '; ') }
        $ok = "llama-server binaries match the $release pins ($(@($have.Keys | Where-Object { $pin[$_] }) -join ', '))"
        $none = @($have.Keys | Where-Object { -not $pin[$_] } | ForEach-Object { "$_ (sha256 $($have[$_]))" })
        if ($none) { return 'warn', "$ok; no $release pin for $($none -join ', '); not checked" }
        'ok', $ok
    }
    # At most once per boot: a marker with this boot time, path, size, mtime and manifest
    # sha256 skips the hash (the fallback file took 20 s on the reference machine).
    function Test-ModelHash([string]$Path, [string]$Manifest, [string]$Root, [string]$Marker) {
        $entry = $null
        if (Test-Path -LiteralPath $Manifest -PathType Leaf) {
            $entry = @((Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json).files |
                    Where-Object { [IO.Path]::GetFullPath($_.path, $Root) -eq $Path })[0]
        }
        if (-not $entry) { return 'warn', "no entry for $Path in $Manifest; model hash not checked" }
        $item = Get-Item -LiteralPath $Path
        # Unreadable boot time: no marker is taken or written, the file is hashed.
        $boot = try { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().Ticks } catch { $null }
        $mark = [ordered]@{
            boot = $boot
            path = $Path; size = $item.Length; mtime = $item.LastWriteTimeUtc.Ticks; sha256 = $entry.sha256
        }
        $old = try { Get-Content -LiteralPath $Marker -Raw -ErrorAction Stop | ConvertFrom-Json } catch { $null }
        if ($null -ne $boot -and $old -and -not @($mark.Keys | Where-Object { "$($old.$_)" -ne "$($mark[$_])" }).Count) {
            return 'marker', "model sha256 verified earlier this boot ($Marker); not hashed again"
        }
        if ($item.Length -ne [long]$entry.size) {
            return 'refuse', "$Path is $($item.Length) bytes, $Manifest says $($entry.size)"
        }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower()
        if ($hash -ne $entry.sha256) { return 'refuse', "$Path sha256 $hash, $Manifest says $($entry.sha256)" }
        $note = if ($null -eq $boot) { 'boot time unreadable, no marker written' } else {
            $mark | ConvertTo-Json | Set-Content -LiteralPath $Marker
            "marker $Marker written"
        }
        'ok', "model sha256 matches $Manifest ($([Math]::Round($sw.Elapsed.TotalSeconds, 1)) s); $note"
    }
    function Confirm-Check([scriptblock]$Check) {
        $Result = try { & $Check } catch { 'refuse', "check failed: $($_.Exception.Message)" }
        if ($Result[0] -eq 'refuse') {
            Write-ServeLog "serve.ps1: refusing to start: $($Result[1])"
            throw "serve.ps1: refusing to start: $($Result[1])"
        }
        Write-ServeLog "serve.ps1: $(if ($Result[0] -eq 'warn') { 'WARNING ' })$($Result[1])"
    }
    if (-not $PrintArgs) {
        Confirm-Check { Test-ServerBinary $binDir (Join-Path $PSScriptRoot 'install.ps1') }
        if ($source -ne '-m') { Confirm-Check { 'warn', "model hash not checked: $Model is an -hf download" } }
        elseif ($SkipModelVerify) { Confirm-Check { 'warn', 'model hash check skipped (-SkipModelVerify)' } }
        else {
            $verifyMarker = Join-Path $logsDir 'model-verify.json'
            Confirm-Check { Test-ModelHash $Model ([IO.Path]::GetFullPath($ModelManifest, $repoRoot)) $repoRoot $verifyMarker }
        }
        if ($VerifyOnly) { exit 0 }
        # stop.ps1 ran while the checks did (the model hash can take 20 s)
        if (Test-Path -LiteralPath $stopFile) { Write-ServeLog "serve.ps1: not starting: $(Get-StopRequest)"; exit 0 }
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
        '--api-key-file', $keyFile,
        '--no-webui',
        '--metrics',
        '--host', '127.0.0.1', '--port', "$Port"
    )
    if (-not $WithMmproj) { $cmdArgs += '--no-mmproj' }
    if ($Web) { $cmdArgs += '-lv', '3' }
    if ($NCpuMoe -gt 0) { $cmdArgs += '--n-cpu-moe', "$NCpuMoe" }
    if ($ChatTemplateFile) { $cmdArgs += '--chat-template-file', $ChatTemplateFile }
    if ($Model -eq $fallbackModel -and -not $NoMtp) {
        if ($Ctx -gt 65536) {
            if ($PSBoundParameters.ContainsKey('Ctx')) { Write-Warning 'MTP skipped: only measured to fit all-GPU up to -Ctx 65536 (Phase 3e); pass -NoMtp to silence' }
        } else {
            $cmdArgs += '--spec-type', 'draft-mtp', '--spec-draft-n-max', '2'
        }
    }
    $cmdArgs += $ExtraArgs
    $cmdArgs += $ExtraArgLine -split '\s+' | Where-Object { $_ }

    $cmdLine = "$exe $($cmdArgs -join ' ')"
    if ($PrintArgs) { Write-Host $cmdLine; exit 0 }
    # Per-start API key. The file is deleted and recreated so this user owns it, its ACL is
    # set (current user only, no inherited entries) while it is empty, then the key is written.
    Remove-Item -LiteralPath $keyFile -Force -ErrorAction Ignore
    New-Item -ItemType File -Path $keyFile | Out-Null
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow'))
    Set-Acl -LiteralPath $keyFile -AclObject $acl
    $apiKey = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    [IO.File]::WriteAllText($keyFile, "$apiKey`n")
    # Free VRAM per GPU before each start (resilience audit W4: 858 MiB free once, so a
    # reload after a crash can fail). A hung nvidia-smi is left behind after the timeout.
    function Get-VramFree([int]$TimeoutMs = 10000) {
        try {
            $smi = Get-Command nvidia-smi -CommandType Application -ErrorAction Stop | Select-Object -First 1
            $si = [Diagnostics.ProcessStartInfo]::new($smi.Source, '--query-gpu=memory.free --format=csv,noheader,nounits')
            $si.UseShellExecute = $false
            $si.RedirectStandardOutput = $true
            $p = [Diagnostics.Process]::Start($si)
            if (-not $p.WaitForExit($TimeoutMs) -or $p.ExitCode -ne 0) { return 'unavailable' }
            $mib = @($p.StandardOutput.ReadToEnd() -split '\r?\n' | ForEach-Object Trim | Where-Object { $_ })
            if ($mib.Count -and -not @($mib | Where-Object { $_ -notmatch '^\d+$' }).Count) {
                return (@($mib | ForEach-Object { "$_ MiB" }) -join ', ')
            }
        } catch { }
        'unavailable'
    }
    # llama-server reads these variables as flags: they would get round the refusal above.
    $envOverrides = @('LLAMA_ARG_AGENT', 'LLAMA_ARG_TOOLS', 'LLAMA_ARG_CONNECT', 'LLAMA_ARG_CONNECT_CODE',
        'LLAMA_ARG_MCP_SERVERS_CONFIG', 'LLAMA_ARG_MCP_SERVERS_JSON', 'LLAMA_ARG_UI_MCP_PROXY', 'LLAMA_ARG_STATIC_PATH',
        'LLAMA_ARG_REUSE_PORT', 'LLAMA_API_KEY', 'LLAMA_ARG_HOST', 'LLAMA_ARG_PORT', 'LLAMA_ARG_ENDPOINT_PROPS')
    if ($Web) { $envOverrides += 'LLAMA_ARG_LOG_VERBOSITY' }
    $cleared = @($envOverrides | Where-Object { Test-Path "Env:$_" })
    foreach ($v in $cleared) { Remove-Item "Env:$v" -ErrorAction Ignore }
    if ($cleared) { Write-ServeLog "serve.ps1: cleared $($cleared.Count) llama-server env overrides ($($cleared -join ', '))" }
    $restarts = @()
    while ($true) {
        Write-ServeLog "serve.ps1: vram free: $(Get-VramFree)"
        if ($LogFile) {
            Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $cmdLine"
            & $exe @cmdArgs *>> $LogFile
            $code = $LASTEXITCODE
            Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] llama-server exited $code"
        } else {
            Write-Host $cmdLine
            & $exe @cmdArgs
            $code = $LASTEXITCODE
        }
        if (Test-Path -LiteralPath $stopFile) { Write-ServeLog "serve.ps1: not restarting: $(Get-StopRequest)"; break }
        if ($code -eq 0) { break }
        $now = Get-Date
        $restarts = @(Get-RecentRestarts $restarts $now $RestartWindowMin)
        if ($restarts.Count -ge $MaxRestarts) {
            Write-ServeLog ("serve.ps1: giving up: llama-server exited $code after $($restarts.Count) restarts " +
                "in the last $RestartWindowMin min (-MaxRestarts $MaxRestarts)")
            break
        }
        $delay = $RestartDelaySec[[Math]::Min($restarts.Count, $RestartDelaySec.Count - 1)]
        $restarts += $now
        Write-ServeLog "serve.ps1: restart $($restarts.Count) of $MaxRestarts in $delay s: llama-server exited $code"
        for ($s = 0; $s -lt $delay -and -not (Test-Path -LiteralPath $stopFile); $s++) { Start-Sleep -Seconds 1 }
        if (Test-Path -LiteralPath $stopFile) { Write-ServeLog "serve.ps1: not restarting (during the restart wait): $(Get-StopRequest)"; break }
    }
    exit $code
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
