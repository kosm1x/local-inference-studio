#Requires -Version 7.0
<#
.SYNOPSIS
  Smoke-test a running llama-server: /health, /v1/messages tool_use, /v1/messages/count_tokens.
.DESCRIPTION
  PASS (exit 0) when /health reports status "ok" and the /v1/messages reply contains a
  get_weather tool_use block with a non-empty input.city, else FAIL (exit 1).
  count_tokens is reported but does not fail the run (Claude Code falls back to an
  estimate without it).
  Qwen3.6 thinks by default: 256 tokens ended in thinking only and one run reached
  3841 thinking chars (2026-10-24), so the default is 4096. If FAIL shows only
  thinking blocks, raise -MaxTokens.
#>
[CmdletBinding()]
param(
    [int]$Port = 8080,
    [string]$Model = 'local',
    [int]$MaxTokens = 4096
)
$ErrorActionPreference = 'Stop'

$base = "http://127.0.0.1:$Port"
$headers = @{ 'x-api-key' = 'local'; 'anthropic-version' = '2023-06-01' }

try {
    $health = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10
    Write-Host "health: $($health | ConvertTo-Json -Compress)"
} catch {
    Write-Host "FAIL: /health unreachable at ${base}: $($_.Exception.Message)"
    exit 1
}
if ($health.status -ne 'ok') {
    Write-Host "FAIL: /health status is '$($health.status)', expected 'ok'"
    exit 1
}

$tools = @(@{
    name         = 'get_weather'
    description  = 'Get the current weather for a city.'
    input_schema = @{
        type       = 'object'
        properties = @{ city = @{ type = 'string'; description = 'City name, e.g. Mexico City' } }
        required   = @('city')
    }
})
$messages = @(@{
    role    = 'user'
    content = 'What is the weather in Mexico City right now? You must call the get_weather tool; do not answer from memory.'
})

$body = @{ model = $Model; max_tokens = $MaxTokens; tools = $tools; messages = $messages } | ConvertTo-Json -Depth 10
$resp = Invoke-RestMethod -Method Post -Uri "$base/v1/messages" -Headers $headers `
    -ContentType 'application/json' -Body $body -TimeoutSec 600

Write-Host "stop_reason: $($resp.stop_reason)"
foreach ($block in $resp.content) {
    switch ($block.type) {
        'tool_use' { Write-Host "[tool_use] $($block.name) $($block.input | ConvertTo-Json -Compress)" }
        'text'     { Write-Host "[text] $($block.text)" }
        'thinking' { Write-Host "[thinking] $($block.thinking.Length) chars" }
        default    { Write-Host "[$($block.type)] $($block | ConvertTo-Json -Compress -Depth 5)" }
    }
}

try {
    $countBody = @{ model = $Model; tools = $tools; messages = $messages } | ConvertTo-Json -Depth 10
    $count = Invoke-RestMethod -Method Post -Uri "$base/v1/messages/count_tokens" -Headers $headers `
        -ContentType 'application/json' -Body $countBody -TimeoutSec 60
    Write-Host "count_tokens: input_tokens=$($count.input_tokens)"
} catch {
    Write-Host "count_tokens: unavailable ($($_.Exception.Message))"
}

$call = @($resp.content | Where-Object {
    $_.type -eq 'tool_use' -and $_.name -eq 'get_weather' -and -not [string]::IsNullOrWhiteSpace($_.input.city)
}) | Select-Object -First 1
if ($call) {
    Write-Host "PASS: tool_use $($call.name) $($call.input | ConvertTo-Json -Compress)"
    exit 0
}
Write-Host 'FAIL: no get_weather tool_use block with a non-empty input.city in /v1/messages reply'
exit 1
