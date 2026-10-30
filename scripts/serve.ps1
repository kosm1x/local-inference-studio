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
  Qwen sampling, --host/--port, --reasoning-format auto, --reasoning off, --api-key-file
  logs/api-key, --no-webui and --no-mmproj (the vision projector is skipped unless
  -WithMmproj).
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

$binDir = Join-Path $PSScriptRoot '..\bin'
$exe = Join-Path $binDir 'llama-server.exe'
if (-not (Test-Path $exe)) { throw "llama-server.exe not found in $binDir. Run scripts/install.ps1 first." }

# One instance per port, held until this process exits (two at once would race on the
# key file and the port check below).
$mutex = [Threading.Mutex]::new($false, "Global\LocalInferenceStudio-serve-$Port")
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { Write-Host "another serve.ps1 holds port $Port"; exit 1 }
# Released in the finally below, not only at process exit: an in-process run
# (& serve.ps1) would otherwise keep the port's mutex until its pwsh exits.
try {
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
    # Per-start API key. The file is deleted and recreated so this user owns it, its ACL is
    # set (current user only, no inherited entries) while it is empty, then the key is written.
    $logsDir = Join-Path $repoRoot 'logs'
    $keyFile = Join-Path $logsDir 'api-key'
    $stopFile = Join-Path $logsDir ".stop-requested-$Port"
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
    Remove-Item -LiteralPath $keyFile -Force -ErrorAction Ignore
    New-Item -ItemType File -Path $keyFile | Out-Null
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow'))
    Set-Acl -LiteralPath $keyFile -AclObject $acl
    $apiKey = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    [IO.File]::WriteAllText($keyFile, "$apiKey`n")
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction Ignore
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
    }
    # stop.ps1 writes its log marker into the stop file too; it cannot append to the log
    # while llama-server's output is redirected into it.
    function Get-StopRequest { "$(Get-Content -LiteralPath $stopFile -TotalCount 1 -ErrorAction Ignore) ($stopFile)" }
    function Get-RecentRestarts([datetime[]]$Times, [datetime]$Now, [int]$WindowMin) {
        @($Times | Where-Object { ($Now - $_).TotalMinutes -lt $WindowMin })
    }
    function Write-ServeLog([string]$Line) {
        if ($LogFile) { Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $Line" } else { Write-Host $Line }
    }
    # llama-server reads these variables as flags: they would get round the refusal above.
    $envOverrides = @('LLAMA_ARG_AGENT', 'LLAMA_ARG_TOOLS', 'LLAMA_ARG_CONNECT', 'LLAMA_ARG_CONNECT_CODE',
        'LLAMA_ARG_MCP_SERVERS_CONFIG', 'LLAMA_ARG_MCP_SERVERS_JSON', 'LLAMA_ARG_UI_MCP_PROXY', 'LLAMA_ARG_STATIC_PATH',
        'LLAMA_ARG_REUSE_PORT', 'LLAMA_API_KEY', 'LLAMA_ARG_HOST', 'LLAMA_ARG_PORT', 'LLAMA_ARG_ENDPOINT_PROPS')
    $cleared = @($envOverrides | Where-Object { Test-Path "Env:$_" })
    foreach ($v in $cleared) { Remove-Item "Env:$v" -ErrorAction Ignore }
    if ($cleared) { Write-ServeLog "serve.ps1: cleared $($cleared.Count) llama-server env overrides ($($cleared -join ', '))" }
    $restarts = @()
    while ($true) {
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
