#Requires -Version 7.0
<#
.SYNOPSIS
  Run Claude Code against the local llama-server. Extra arguments go to `claude`.
.DESCRIPTION
  Sets the env block from docs/landscape-2026-10-24.md for this process only, runs
  `claude @args`, then restores the previous values so the calling shell is unchanged.

  IMPORTANT (this machine): ~/.claude/settings.json pins subagents to Opus via
  CLAUDE_CODE_SUBAGENT_MODEL=opus + CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1, and the main
  session to `model: fable`. Neither model exists locally.
  - The two SUBAGENT vars are unset for the child below. They are also defined in the
    settings.json `env` block, which Claude Code applies itself and which may win over
    the process env, so config/claude-settings.json is passed via --settings to set
    CLAUDE_CODE_SUBAGENT_MODEL=local and model=local at CLI precedence.
  - ANTHROPIC_MODEL must override `model: fable`.
  Both are UNVERIFIED: confirm in P2 from the model names in the llama-server log.

  Do not add script parameters whose names prefix-match claude's short flags
  (-p, -c, -r, ...): PowerShell would bind them here instead of passing them on.
.EXAMPLE
  pwsh scripts/claude-local.ps1 -p "list the files in this repo"
#>
param([int]$MaxContextTokens = 131072)

$set = [ordered]@{
    ANTHROPIC_BASE_URL                       = 'http://127.0.0.1:8080'
    ANTHROPIC_AUTH_TOKEN                     = 'local'
    ANTHROPIC_MODEL                          = 'local'
    ANTHROPIC_DEFAULT_OPUS_MODEL             = 'local'
    ANTHROPIC_DEFAULT_SONNET_MODEL           = 'local'
    ANTHROPIC_DEFAULT_HAIKU_MODEL            = 'local'
    CLAUDE_CODE_MAX_CONTEXT_TOKENS           = "$MaxContextTokens"
    CLAUDE_CODE_MAX_OUTPUT_TOKENS            = '16384'
    API_TIMEOUT_MS                           = '1800000'
    CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS   = '1'
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
    DISABLE_PROMPT_CACHING                   = '1'
    ENABLE_TOOL_SEARCH                       = 'false'
    CLAUDE_CODE_ATTRIBUTION_HEADER           = '0'
}
# ANTHROPIC_API_KEY is unset too: it would take precedence over the bearer token and
# send a real key to the local server.
$unset = 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE', 'ANTHROPIC_API_KEY'
$settings = Join-Path $PSScriptRoot '..\config\claude-settings.json'

$saved = @{}
foreach ($k in @($set.Keys) + $unset) { $saved[$k] = [Environment]::GetEnvironmentVariable($k) }
$code = 1
try {
    foreach ($k in $set.Keys) { [Environment]::SetEnvironmentVariable($k, $set[$k]) }
    foreach ($k in $unset) { [Environment]::SetEnvironmentVariable($k, $null) }
    & claude --settings $settings @args
    $code = $LASTEXITCODE
} finally {
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
}
exit $code
