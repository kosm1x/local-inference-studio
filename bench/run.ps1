#Requires -Version 7.0
<#
.SYNOPSIS
  Benchmark the RUNNING llama-server on 127.0.0.1:-Port and write one JSON result.
.DESCRIPTION
  Measures decode tok/s, 20K-token prefill (cold and prefix-cached), tool-call success
  over -ToolTrials /v1/messages requests and peak VRAM, then writes
  -OutDir/<yyyyMMdd-HHmmss>-<Label>.json (schema in bench/README.md) and prints a
  one-line summary. It does not start or stop the server; -Label, -Quant, -Ctx, -Ngl
  and -NCpuMoe are recorded as given, while server_build and flags are read from the
  server (/props and the listening process's command line).
  vram_mb_peak is the whole GPU (nvidia-smi), not just llama-server.
.EXAMPLE
  pwsh bench/run.ps1 -Label qwen3.6-35b-a3b -Quant UD-IQ3_XXS -Ctx 131072 -NCpuMoe 0
#>
[CmdletBinding()]
param(
    [int]$Port = 8080,
    [string]$ApiKey = 'local',
    [Parameter(Mandatory)][string]$Label,
    [string]$Quant = '',
    [int]$Ctx = 0,
    [string]$Ngl = 'auto',
    [int]$NCpuMoe = 0,
    [int]$ToolTrials = 20,
    [int]$PrefillTokens = 20000,
    [string]$OutDir = (Join-Path $PSScriptRoot 'results')
)
$ErrorActionPreference = 'Stop'

$base = "http://127.0.0.1:$Port"
$bearer = @{ Authorization = "Bearer $ApiKey" }
$anthropic = @{ 'x-api-key' = $ApiKey; 'anthropic-version' = '2023-06-01' }

function Invoke-Json([string]$Path, $Body, [hashtable]$Headers = $bearer) {
    Invoke-RestMethod -Method Post -Uri "$base$Path" -Headers $Headers -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Depth 10 -Compress) -TimeoutSec 1800
}
function Get-Median([double[]]$Values) {
    $s = $Values | Sort-Object
    if ($s.Count -eq 0) { return $null }
    if ($s.Count % 2) { return $s[[int][math]::Floor($s.Count / 2)] }
    return ($s[$s.Count / 2 - 1] + $s[$s.Count / 2]) / 2
}

$health = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10
if ($health.status -ne 'ok') { throw "/health status is '$($health.status)', expected 'ok'" }
$props = Invoke-RestMethod -Uri "$base/props" -Headers $bearer -TimeoutSec 10
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Ignore | Select-Object -First 1
$flags = $null
if ($listener) {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)").CommandLine
    $flags = ($cmd -replace '^\s*("[^"]*"|\S+)\s*', '')
}

# Deterministic English filler: seeded word lists, so every run sends the same tokens.
$rng = [Random]::new(42)
$subj = 'The engineer', 'A small team', 'The old library', 'Our customer', 'The river', 'A quiet student',
    'The night shift', 'The committee', 'A delivery driver', 'The museum guide', 'The weather station', 'My neighbor'
$verb = 'reviewed', 'carried', 'described', 'repaired', 'measured', 'painted', 'questioned', 'organized',
    'translated', 'photographed', 'ignored', 'celebrated'
$obj = 'the broken bridge', 'a long report', 'the morning schedule', 'three wooden chairs', 'the harbor lights',
    'an unfinished map', 'the spring harvest', 'a stack of letters', 'the city budget', 'the northern trail'
$tail = 'before sunrise.', 'with great care.', 'during the storm.', 'after a short debate.', 'for the second time.',
    'without any help.', 'near the old station.', 'while the market closed.', 'in under an hour.', 'as planned.'
$sb = [Text.StringBuilder]::new()
$tokens = @()
while ($tokens.Count -lt $PrefillTokens) {
    for ($i = 0; $i -lt 3000; $i++) {
        [void]$sb.Append("$($subj[$rng.Next($subj.Count)]) $($verb[$rng.Next($verb.Count)]) ")
        [void]$sb.Append("$($obj[$rng.Next($obj.Count)]) $($tail[$rng.Next($tail.Count)]) ")
    }
    $tokens = @((Invoke-Json '/tokenize' @{ content = $sb.ToString() }).tokens)
}
# Exact token counts: /completion accepts a token-id array as the prompt.
$prefillPrompt = [int[]]$tokens[0..($PrefillTokens - 1)]
$decodePrompt = [int[]]$tokens[0..199]

# VRAM sampler: whole-GPU memory.used every 500 ms until stopped.
$vramJob = Start-ThreadJob -ScriptBlock {
    while ($true) {
        nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
        Start-Sleep -Milliseconds 500
    }
}
try {
    # a. decode
    $decodeRuns = foreach ($r in 1..3) {
        $t = (Invoke-Json '/completion' @{ prompt = $decodePrompt; n_predict = 256; cache_prompt = $false; ignore_eos = $true }).timings
        Write-Host ("decode run {0}: {1:N1} tok/s ({2} tokens)" -f $r, $t.predicted_per_second, $t.predicted_n)
        [double]$t.predicted_per_second
    }

    # b. prefill, cold then prefix-cached
    $prefillRuns = foreach ($r in 1..3) {
        $t = (Invoke-Json '/completion' @{ prompt = $prefillPrompt; n_predict = 1; cache_prompt = $false }).timings
        Write-Host ("prefill run {0}: {1:N0} ms, {2:N0} tok/s ({3} tokens)" -f $r, $t.prompt_ms, $t.prompt_per_second, $t.prompt_n)
        $t
    }
    # The first cache_prompt=true request fills the slot cache; the second one is the hit.
    $null = Invoke-Json '/completion' @{ prompt = $prefillPrompt; n_predict = 1; cache_prompt = $true }
    $cached = (Invoke-Json '/completion' @{ prompt = $prefillPrompt; n_predict = 1; cache_prompt = $true }).timings
    Write-Host ("prefill cached: {0:N0} ms ({1} tokens evaluated)" -f $cached.prompt_ms, $cached.prompt_n)

    # c. tool calls: two tools, each message needs exactly one of them.
    $tools = @(
        @{ name = 'get_weather'; description = 'Get the current weather for a city.'
           input_schema = @{ type = 'object'; required = @('city')
               properties = @{ city = @{ type = 'string'; description = 'City name, e.g. Mexico City' } } } },
        @{ name = 'run_tests'; description = 'Run the test suite at a path in the repository and return the results.'
           input_schema = @{ type = 'object'; required = @('path')
               properties = @{ path = @{ type = 'string'; description = 'Test file or directory, e.g. tests/unit' } } } }
    )
    $cases = @(
        @('get_weather', 'city', 'What is the weather in Mexico City right now?'),
        @('run_tests', 'path', 'Run the tests in tests/unit and tell me what fails.'),
        @('get_weather', 'city', 'Is it raining in London at the moment?'),
        @('run_tests', 'path', 'Please execute the test file src/parser.test.js.'),
        @('get_weather', 'city', 'How hot is it in Tokyo today?'),
        @('run_tests', 'path', 'I changed the auth module; run the tests under tests/auth.'),
        @('get_weather', 'city', 'Check the current weather in Buenos Aires for me.'),
        @('run_tests', 'path', 'Run test/slugify.test.js and report the result.'),
        @('get_weather', 'city', 'Should I bring a coat in Toronto right now? Look up the weather.'),
        @('run_tests', 'path', 'Kick off the integration tests in tests/integration.'),
        @('get_weather', 'city', 'What are the current conditions in Madrid?'),
        @('run_tests', 'path', 'Verify my fix by running the tests at packages/core/test.'),
        @('get_weather', 'city', 'Get me the live weather for Sydney.'),
        @('run_tests', 'path', 'Run the e2e suite located at e2e/.'),
        @('get_weather', 'city', 'Is it windy in Chicago right now?'),
        @('run_tests', 'path', 'Run the tests in lib/utils/__tests__ please.'),
        @('get_weather', 'city', 'What temperature is it in Cairo at this moment?'),
        @('run_tests', 'path', 'Can you run spec/models/user_spec.rb?'),
        @('get_weather', 'city', 'Tell me the current weather in Oaxaca.'),
        @('run_tests', 'path', 'Run the regression tests in tests/regression and summarize.')
    )
    $pass = 0; $wrong = 0; $noCall = 0; $badArgs = 0; $errors = 0
    $latencies = [Collections.Generic.List[double]]::new()
    for ($i = 0; $i -lt $ToolTrials; $i++) {
        $want, $field, $msg = $cases[$i % $cases.Count]
        $body = @{ model = 'local'; max_tokens = 4096; tools = $tools; messages = @(@{ role = 'user'; content = $msg }) }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        try { $resp = Invoke-Json '/v1/messages' $body $anthropic }
        catch { $errors++; Write-Host "tool $($i + 1): ERROR $($_.Exception.Message)"; continue }
        $latencies.Add($sw.Elapsed.TotalMilliseconds)
        $uses = @($resp.content | Where-Object type -eq 'tool_use')
        $hit = $uses | Where-Object name -eq $want | Select-Object -First 1
        $verdict = if (-not $uses) { $noCall++; 'no_call' }
            elseif (-not $hit) { $wrong++; "wrong_tool ($($uses[0].name))" }
            elseif ([string]::IsNullOrWhiteSpace("$($hit.input.$field)")) { $badArgs++; 'bad_args' }
            else { $pass++; 'pass' }
        Write-Host ("tool {0}: {1} {2:N0} ms" -f ($i + 1), $verdict, $sw.Elapsed.TotalMilliseconds)
    }
} finally {
    Stop-Job $vramJob
    $vram = @(Receive-Job $vramJob | ForEach-Object { [int]"$_".Trim() })
    Remove-Job $vramJob -Force
}

$result = [ordered]@{
    model                      = $Label
    quant                      = $Quant
    ctx                        = $Ctx
    ngl                        = $Ngl
    n_cpu_moe                  = $NCpuMoe
    decode_tps                 = [math]::Round((Get-Median $decodeRuns), 2)
    prefill_ms_20k             = [math]::Round((Get-Median ($prefillRuns | ForEach-Object prompt_ms)), 1)
    prefill_tps                = [math]::Round((Get-Median ($prefillRuns | ForEach-Object prompt_per_second)), 1)
    prefill_tokens             = [int]$prefillRuns[0].prompt_n
    prefill_ms_20k_cached      = [math]::Round([double]$cached.prompt_ms, 1)
    prefill_cached_tokens_eval = [int]$cached.prompt_n
    toolcall_pass              = $pass
    toolcall_total             = $ToolTrials
    toolcall_wrong_tool        = $wrong
    toolcall_no_call           = $noCall
    toolcall_bad_args          = $badArgs
    toolcall_errors            = $errors
    toolcall_latency_ms_median = if ($latencies.Count) { [math]::Round((Get-Median $latencies), 0) } else { $null }
    vram_mb_peak               = if ($vram.Count) { [int]($vram | Measure-Object -Maximum).Maximum } else { $null }
    server_build               = $props.build_info
    flags                      = $flags
    date                       = (Get-Date).ToString('o')
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$safeLabel = $Label -replace '[^\w.-]', '_'
$outFile = Join-Path $OutDir "$((Get-Date).ToString('yyyyMMdd-HHmmss'))-$safeLabel.json"
$result | ConvertTo-Json | Set-Content -LiteralPath $outFile -Encoding utf8NoBOM
Write-Host ("{0} {1}: decode {2} tok/s | prefill {3} ms ({4} tok/s), cached {5} ms | tools {6}/{7} (wrong {8}, none {9}, args {10}, err {11}, p50 {12} ms) | vram peak {13} MB -> {14}" -f
    $Label, $Quant, $result.decode_tps, $result.prefill_ms_20k, $result.prefill_tps, $result.prefill_ms_20k_cached,
    $pass, $ToolTrials, $wrong, $noCall, $badArgs, $errors, $result.toolcall_latency_ms_median, $result.vram_mb_peak, $outFile)
