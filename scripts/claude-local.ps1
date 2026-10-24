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

  There is deliberately no param() block. A declared parameter binds claude's
  positional prompt (or any unmatched token such as --model) to itself and claims
  prefix matches (-m for -MaxContextTokens), and [CmdletBinding()] would drop $args
  and let common parameters (-Verbose, -Debug, -ProgressAction, ...) capture claude's
  -v/-d/-p. The one script option, -LisContextTokens N, is taken out of $args here.
.EXAMPLE
  pwsh scripts/claude-local.ps1 -p "list the files in this repo"
.EXAMPLE
  pwsh scripts/claude-local.ps1 -LisContextTokens 65536 -p "list the files in this repo"
#>
$LisContextTokens = 131072
$claudeArgs = [System.Collections.Generic.List[object]]$args
$i = $claudeArgs.IndexOf('-LisContextTokens')
if ($i -ge 0) {
    $LisContextTokens = [int]$claudeArgs[$i + 1]
    $claudeArgs.RemoveRange($i, 2)
}

$set = [ordered]@{
    ANTHROPIC_BASE_URL                       = 'http://127.0.0.1:8080'
    ANTHROPIC_AUTH_TOKEN                     = 'local'
    ANTHROPIC_MODEL                          = 'local'
    ANTHROPIC_DEFAULT_OPUS_MODEL             = 'local'
    ANTHROPIC_DEFAULT_SONNET_MODEL           = 'local'
    ANTHROPIC_DEFAULT_HAIKU_MODEL            = 'local'
    CLAUDE_CODE_MAX_CONTEXT_TOKENS           = "$LisContextTokens"
    CLAUDE_CODE_AUTO_COMPACT_WINDOW          = "$LisContextTokens"
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

# Unset with Remove-Item: [Environment]::SetEnvironmentVariable($k, $null) leaves the
# variable defined as "" in PowerShell 7.6 / .NET 10.
$saved = @{}
foreach ($k in @($set.Keys) + $unset) {
    $saved[$k] = if (Test-Path "env:$k") { (Get-Item "env:$k").Value } else { $null }
}
$code = 1
try {
    foreach ($k in $set.Keys) { Set-Item "env:$k" $set[$k] }
    foreach ($k in $unset) { Remove-Item "env:$k" -ErrorAction Ignore }
    & claude --settings $settings @claudeArgs
    $code = $LASTEXITCODE
} finally {
    foreach ($k in $saved.Keys) {
        if ($null -eq $saved[$k]) { Remove-Item "env:$k" -ErrorAction Ignore }
        else { Set-Item "env:$k" $saved[$k] }
    }
}
exit $code
