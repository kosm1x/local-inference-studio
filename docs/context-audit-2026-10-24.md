# Fresh-session context audit 2026-10-24

Question (operator): what fills the first prompt of a local Claude Code session, which
of it can be dropped without editing `~/.claude`, and how does the name "Fable" reach a
local session? Measured on the ruling 12 server (Orca IQ3_XXS, ctx 65536, q4_0 KV, MTP)
right after its cutover. Nothing here was implemented when it was measured; ruling 13
adopted the lean set (see "Adopted 2026-10-24" at the end).

Method:

- Every run is `claude-local.ps1 -p "reply with the single word ok" --output-format json
  --max-turns 1` (Claude Code 2.1.310), through a scratch copy of the wrapper whose only
  changes are `ANTHROPIC_BASE_URL` pointed at a logging pass-through proxy on :8090 (it
  saves each request body, then forwards to :8080 unchanged) and a settings path that a
  test can swap. The repo's `scripts/claude-local.ps1` and `config/claude-settings.json`
  were not edited for any test.
- "Prompt tokens" is the server's own count (`prompt eval time ... / N tokens` in
  `logs/llama-server.log`, equal to `usage.input_tokens` + `cache_read_input_tokens`).
- Per-source tokens: each segment of the captured request (system blocks, each tool
  schema as JSON, each `<system-reminder>` and each section of the non-leading system
  message) and each source file was tokenized with the live server's `POST /tokenize`.
  Segment sums land about 450 tokens under the server count (chat-template wrapping).
- Three cwds: a scratch dir outside `Z:\repos` (no git repo, empty memory dir), the repo
  root, and `Z:\repos` (umbrella) as a reference.

## 1. Fresh-session size per cwd (measured)

| cwd | MCP at first request | Prompt tokens | Share of the 65,536 window |
|---|---|---|---|
| scratch dir outside `Z:\repos` | none configured | 25,578 | 39 % |
| repo root | still connecting (`WaitForMcpServers` offered, 0 MCP tools) | 26,224 | 40 % |
| repo root | connected (26 MCP tools) | 32,988 | 50 % |
| `Z:\repos` (umbrella) | connected | 42,272 | 65 % |

- `modelUsage` keys: `local` only in every run (17 captured requests, all `"model":
  "local"`); `contextWindow` 65536; `is_error` false in every one-turn run.
- `usage`: `cache_creation_input_tokens` is always 0. A repeat of the scratch run
  reported `input_tokens` 4 and `cache_read_input_tokens` 25,574: llama-server reports
  its own prefix-cache reuse there (Claude Code's caching is off, `DISABLE_PROMPT_CACHING=1`).
- MCP at the first request is a race in `-p`: the repo root's MCP servers (from
  `Z:\repos\.mcp.json`, found by walking up from the cwd) were still connecting in one
  run and connected in the next three. An interactive session normally has them
  connected (UNVERIFIED).
- The server log (verbosity 3) does not record the request model or path; the proxy
  captures are the evidence for `"model": "local"`.
- Prefill at the measured ~1,610 tok/s: 25.6K = 15.9 s, 33K about 20 s, the lean set
  below (11.7K) about 7 s, per cold start or full re-read.

## 2. Sources, by tokens

Tokens are as they appear in the prompt (header lines included) unless the row says
"file". "cwd" = S scratch, R repo root, U umbrella.

| Source | Bytes | Tokens | Loaded in | Lever without editing `~/.claude` | Lever status |
|---|---|---|---|---|---|
| Built-in tool schemas, 22 tools (Monitor 1,963 · SendMessage 1,368 · Workflow 1,300 · CronCreate 1,233 · ScheduleWakeup 1,201 · Agent 1,109 · Bash 959 · EnterWorktree 952 · Grep 848 · ExitWorktree 609 · ReportFindings 590 · LSP 576 · Read 541 · NotebookEdit 435 · Skill 423 · ListAgents 283 · Edit 246 · TaskStop 197 · Glob 180 · Write 167 · CronDelete 117 · CronList 77) | 62,208 | 15,374 | S R U | `--tools Bash,Read,Edit,Write,Glob,Grep,Skill` (7 tools = 3,364) or the matching `--disallowedTools` list | VERIFIED: S 25,578 -> 12,193 (`--tools`, also drops the agent listing) |
| `~/.claude/projects/Z--repos/memory/MEMORY.md` (auto-memory) | 25,351 | 8,233 (file 8,163) | U only (the S and R memory dirs are empty) | start outside `Z:\repos` or in a repo below it; `--bare` | VERIFIED by cwd (absent in S and R) |
| MCP servers `context7`, `sequential-thinking`, `playwright` (3 servers, from `Z:\repos\.mcp.json`, enabled by the user settings' `enabledMcpjsonServers`): 26 tool schemas 6,039 (playwright 23 tools 3,919 · context7 2 tools 1,136 · sequential-thinking 984) + 3 MCP resource tools 530 + "MCP Server Instructions" 172; `WaitForMcpServers` (about 250) instead while they connect | - | about 6,741 | R U (S: none configured) | `--strict-mcp-config --mcp-config <empty {"mcpServers":{}}>` | VERIFIED: R 26,224 (connecting) / 32,988 (connected) -> 25,968; S unchanged 25,578 |
| `~/.claude/CLAUDE.md` | 14,121 | 3,722 (file 3,697) | S R U | `--bare`; `--setting-sources project,local` (drops the user scope: CLAUDE.md, rules, hooks, user agents, `permissions.deny`, `model: fable`, the env block) | VERIFIED: both remove it (see section 3) |
| SessionStart hook (`session-orient.sh` + `agent-learnings-orient.sh`: orientation lines, the first 8 lines of `~/.claude/NOW.md`, the project's `AGENT_LEARNINGS.md`) | S 3,849 / R 12,157 / U 7,325 stdout | S 1,434 · R 884 · U 2,351 (stdout tokenized: 1,417 / 3,651 / 2,342) | S R U | `--settings <scratch copy of config/claude-settings.json + "disableAllHooks": true>` | VERIFIED: S 25,578 -> 24,144 (-1,434); R 32,988 -> 32,089 (-899, both MCP connected) |
| Skills listing (system message; names only for most, a few with descriptions) | 5,814 | 1,457 | S R U | `--disallowedTools Skill` removes the listing and the Skill schema (-1,880) BUT the Workflow schema then grows 1,300 -> 5,258 | VERIFIED backfire: S 25,578 -> 27,624 (+2,046); only safe together with Workflow removed |
| Claude Code system prompt (`system[0]` + `system[1]`) | 5,765 | 1,328 (S) / 1,283 (R) | S R U | `--bare` (89 tokens) | VERIFIED, but `--bare` leaves 3 tools (Bash, Edit, Read) and drops all user context |
| Agent types listing ("Available agent types for the Agent tool": 16 agents; 17 in U with `Z:\repos\.claude\agents\qa-auditor.md`) + "launch multiple agents" line | 5,590 | 1,240 (U 1,365) | S R U | `--disallowedTools Agent` (listing goes with the Agent tool) | VERIFIED: with Agent,Workflow S 25,578 -> 21,911 (-3,667 = Agent 1,109 + Workflow 1,300 + listing 1,240 + 18) |
| `Z:\repos\CLAUDE.md` | 2,069 | 530 (file 509) | R U | start outside `Z:\repos`; `--bare` | VERIFIED by cwd (absent in S) |
| gitStatus context block | 921 | 273 | R (git repos) | `--exclude-dynamic-system-prompt-sections` moves it (does not drop it); `--bare` | UNVERIFIED |
| Repo `CLAUDE.md` | 714 | 233 (file 196) | R | none needed (small; carries this repo's rules) | - |
| Environment block (cwd, platform, shell, "You are powered by the model local.") | 725 to 826 | 173 to 227 | S R U | none (needed) | - |
| `~/.claude/rules/git.md` | 531 | 164 (file 134) | S R U | `--setting-sources project,local`; `--bare` | VERIFIED (absent in run h) |
| Attribution reminder (commit / PR trailer) | 579 | 137 | S R U | `--bare` | UNVERIFIED as a separate lever |
| `~/.claude/rules/testing.md`, `typescript.md` | 1,298 / 1,276 | 0 at start (files 335 / 345) | path-scoped (`paths:` frontmatter); load when a matching file is read | none needed | - |
| Repo `AGENT_LEARNINGS.md` | 8,055 | file 2,176; about 0 reaches the model at start | inside the R hook stdout | - | see finding F1 |
| `Z:\repos\AGENT_LEARNINGS.md` | 3,483 | file 956 | inside the U hook stdout (inline) | cwd | - |
| `~/.claude/NOW.md` | 11,552 | file 4,294; only its first 8 non-comment lines (long lines cut) reach the model, inside the hook stdout | S R U | `disableAllHooks` | VERIFIED with the hook row |
| Skill descriptions on disk (frontmatter) | plugins 23 SKILL.md 5,988 / `~/.claude/skills` 17 SKILL.md 10,522 | files 1,264 / 2,359 | not loaded as such: the listing above is what reaches the prompt | - | - |
| Agent descriptions on disk | `~/.claude/agents` 3 files 1,061 / `Z:\repos\.claude\agents` 1 file 558 | 223 / 113 | via the agent listing | - | - |
| Chat-template wrapping (server count minus segment sum) | - | about 450 | S R U | none | - |

Findings from the table:

- F1. The repo's SessionStart hook output is 12,157 bytes, over Claude Code's inline
  limit, so Claude Code saved it to a file under the session's project dir and injected
  only "Output too large (11.6KB)" plus a 2 KB preview (orientation lines and the top of
  `NOW.md`). The repo's `AGENT_LEARNINGS.md` standing rules therefore do NOT reach the
  model at session start in this repo, local or cloud (the same hook runs in both). In
  the scratch dir (no learnings file) and the umbrella (smaller file) the output is inline.
- F2. Tool schemas are the largest block (15,374 of 25,578 in S, 60 %). Thirteen tools that a
  single local model does not need in `-p` or interactive coding (Monitor, SendMessage,
  Workflow, CronCreate/Delete/List, ScheduleWakeup, Agent, ListAgents, TaskStop,
  EnterWorktree, ExitWorktree, ReportFindings) cost 10,999 tokens plus the 1,240-token
  agent listing.
- F3. `--disallowedTools Skill` alone makes the prompt bigger (+2,046): the Workflow
  schema inlines about 4,000 tokens of reference text when the Skill tool is absent.
- F4. The umbrella cwd costs 16.7K more than the scratch dir (MEMORY.md 8,233, MCP 6,741,
  larger hook output). A local session started in `Z:\repos` begins at 65 % of its window.

## 3. Lever runs (prompt tokens, server count)

| Run | cwd | Flags (on top of `claude-local.ps1`) | Prompt tokens | Delta | Status |
|---|---|---|---|---|---|
| baseline | S | - | 25,578 | - | measured |
| baseline | R | - (MCP still connecting) | 26,224 | - | measured |
| baseline | R | - (MCP connected; first request of a 3-turn run) | 32,988 | - | measured |
| baseline | U | - (MCP connected) | 42,272 | - | measured |
| (a) | S | `--strict-mcp-config --mcp-config <empty>` | 25,578 | 0 (no MCP here) | VERIFIED (no-op in S) |
| (a) | R | same | 25,968 | -256 vs connecting, -7,020 vs connected | VERIFIED |
| (b) | S | `--disallowedTools Agent,Workflow` | 21,911 | -3,667 | VERIFIED: removes both schemas and the agent listing |
| (c) | S | `--settings <scratch: repo overlay + "disableAllHooks": true>` | 24,144 | -1,434 | VERIFIED |
| (c) | R | same (MCP connected) | 32,089 | -899 vs 32,988 | VERIFIED |
| (d) | S | `--bare` | 1,277 | -24,301 | VERIFIED; tools Bash, Edit, Read only; no CLAUDE.md, hooks, skills, agents |
| (f) | S | `--disallowedTools Skill` | 27,624 | +2,046 | VERIFIED backfire (F3) |
| (g) | S | `--disallowedTools Agent` + `--append-system-prompt <draft in section 5>` | 23,377 | -2,201 (Agent schema + listing -2,349, appended prompt +148) | VERIFIED |
| (h) | R | `--setting-sources project,local` (MCP connected) | 26,765 | -6,223 vs 32,988 | VERIFIED: drops user CLAUDE.md, rules, hooks, user agents; also drops the user `permissions.deny` (`.env`, `~/.ssh`, `~/.aws` reads) and every guard hook |
| (i) | S | `--tools Bash,Read,Edit,Write,Glob,Grep,Skill` | 12,193 | -13,385 | VERIFIED |
| (e) lean | R | (a) + (c) + `--disallowedTools Agent,Workflow,Monitor,ScheduleWakeup,SendMessage,CronCreate,CronDelete,CronList,EnterWorktree,ExitWorktree,ReportFindings,ListAgents,TaskStop,NotebookEdit,LSP` | 11,701 | -14,523 vs 26,224, -21,287 vs 32,988 | VERIFIED; 7 tools left |

What each lever costs besides tokens:

- `disableAllHooks` also turns off the PreToolUse guards in `~/.claude/settings.json`
  (`file-protection.sh`, `git-secret-guard.sh`, `grep-sweep-reminder.sh`,
  `mcp-health-check.sh`), the PostToolUse `auto-format.sh`, the Stop
  `stop-test-reminder.sh` and the UserPromptSubmit `prompt-router.sh`. Saving 900 to
  1,400 tokens costs the secret and file-protection guards in unsupervised sessions.
  (The `kill-guard` hook named in the global CLAUDE.md is not in the settings hook list
  read on 2026-10-24; its registration is operator-only and was not checked further.)
- `--setting-sources project,local` drops the user `permissions.deny` and all user hooks
  for the same reason; it is also the one CLI lever that removes `model: fable` and the
  Opus env block at the source.
- `--bare` was ruled out by the operator (ruling 2: the global config stands in local
  sessions); listed for completeness.
- `--tools` (allow-list) is more robust than `--disallowedTools` (deny-list): a tool
  added by a later Claude Code release stays out. Dropping NotebookEdit and LSP is a
  judgment call (LSP is the typescript-lsp plugin's tool).

## 4. How "Fable" (and "Opus") reach a local session

| Path | What it says | Effect on a local session (`claude-local.ps1`) |
|---|---|---|
| `~/.claude/settings.json` `model` | `fable` | Overridden: `--settings config/claude-settings.json` sets `model: local` and the wrapper sets `ANTHROPIC_MODEL=local`. Every captured request: `"model": "local"`. |
| `~/.claude/settings.json` `env` | `CLAUDE_CODE_SUBAGENT_MODEL=opus`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000` | The wrapper unsets the two SUBAGENT vars for the child, and the repo overlay sets `CLAUDE_CODE_SUBAGENT_MODEL=local` and the compact window 65536 at `--settings` precedence. `_FORCE=1` can still come back from the settings env; with `SUBAGENT_MODEL=local` it forces `local` (Phase 2 VERIFIED subagent requests reached the local server as `local`). |
| `~/.claude/settings.json` `modelSettings` | per-model effort for `claude-fable-5-1` and `claude-opus-5-5` | No `local` entry; `effortLevel: high` is the global value. Harmless; effort handling against llama-server UNVERIFIED. |
| `Z:\repos\.claude\settings.json` (project settings) | `model: fable`, the same three env vars | Applies only with cwd `Z:\repos`; the CLI overlay wins there too (umbrella run: `modelUsage` `local` only). |
| `~/.claude/CLAUDE.md` "Model roles" and "This machine" sections | Fable (main) plans and orchestrates and "does not write production code or tests itself"; Opus subagents do the work; the qa-auditor is a separate subagent | Loaded in every local session (inside the 3,722 tokens). This is the behavioral leak: it tells the single local model to delegate. Its model names do not change routing. |
| Agent files `model:` pins | `model: opus` in `~/.claude/agents` (bundle-size-auditor, supabase-migration-reviewer, ui-agent), `Z:\repos\.claude\agents\qa-auditor.md` and the five kosm1x-workflows plugin agents | Resolve through `ANTHROPIC_DEFAULT_OPUS_MODEL=local` / `CLAUDE_CODE_SUBAGENT_MODEL=local`, so a spawned subagent is the same local model (Phase 2). |
| Skill trailers | no skill under `~/.claude/skills` or the kosm1x-workflows plugin names Fable or Opus; the `claude-api` skill listing names the model family (API reference, not routing) | none |
| Agent tool schema | no `model` parameter is exposed in the captured schema | none |
| Requested model (step 5) | `modelUsage` keys `local` only in every run (S, R, U, all levers) | No finding: nothing requested a cloud model name. |
| `/model` picker | not run (interactive only) | UNVERIFIED. Expected: the aliases resolve to `local` because `ANTHROPIC_MODEL` and the three `ANTHROPIC_DEFAULT_*_MODEL` vars are `local`; whether Fable is listed is not known. |

Operator-side edits: none needed for routing (every request already goes to `local`).
Optional, operator-only, to stop the CLAUDE.md role text from steering local sessions:
add one line under "Model roles" in `~/.claude/CLAUDE.md`, for example "Local sessions
(`claude-local.ps1`, base URL 127.0.0.1) run one local model: no orchestrator/subagent
split; the rest of this section does not apply." The `--append-system-prompt` paragraph
below does the same from the repo side.

## 5. Policy for local sessions: one model does everything

Goal: no orchestrator/subagent split and no Fable/Opus roles in local sessions.
Mechanisms, ranked (1 as the `--tools` allow-list, 2 and 3 adopted by ruling 13):

1. Hard: remove the delegation tools in `scripts/claude-local.ps1`:
   `--disallowedTools Agent,Workflow` (VERIFIED -3,667 tokens and the agent listing
   disappears). Workflow must go with Agent (it runs agents), and Skill must not be
   removed on its own (F3). Optionally the rest of the agent-coordination and scheduling
   tools (SendMessage, ListAgents, TaskStop, Monitor, ScheduleWakeup, Cron*), or the
   `--tools Bash,Read,Edit,Write,Glob,Grep,Skill` allow-list (VERIFIED 12,193 in S).
2. Belt and braces: `config/claude-settings.json` `permissions.deny` gains `"Agent"`
   and `"Workflow"`. Observed, not A/B tested: the existing `WebSearch`/`WebFetch` deny
   entries are absent from every captured tool list, so a settings deny appears to remove
   the schema as well.
3. Soft: `--append-system-prompt` with the paragraph below (112 words; VERIFIED cost
   +148 tokens, run g). It counters the CLAUDE.md role text, which a deny cannot remove.

Draft text:

> This session runs on one local model served by llama-server on this machine. You are
> the only agent: do all work directly with your own tools and never spawn subagents,
> agent teams or workflows. Ignore every instruction about Fable, Opus, Sonnet or other
> model roles, orchestrator and subagent splits, or delegating implementation, tests or
> audits to a subagent; those rules apply to cloud sessions only. Sessions here may run
> long and unsupervised, so before any destructive or irreversible action (deleting
> files, git reset or force-push, stopping processes, editing config outside the working
> repo) verify the exact target first and prefer the reversible option. Keep answers
> short: the context window is 65,536 tokens.

Candidate lean sets for the operator (all from section 3):

| Set | Flags | Prompt tokens (R, MCP connected baseline 32,988) | Keeps |
|---|---|---|---|
| Policy only | 1 + 3 (Agent, Workflow + append) | about 29,500 (estimate: R minus 3,667 plus 148) | everything else |
| Policy + MCP off | 1 + 3 + (a) | about 22,400 (estimate) | hooks, CLAUDE.md, skills |
| Lean | (e) + 3 | about 11,850 (11,701 VERIFIED without the append, + 148) | CLAUDE.md, repo rules, skills, 7 tools; no hooks (guards off) |
| Lean with hooks | (e) minus (c) + 3 | about 12,700 (estimate: + the 884-token hook preview) | as Lean, plus the guard hooks |

UNVERIFIED in this audit: interactive sessions (MCP connect timing, `/model` picker);
whether `--tools` without Skill also drops the skills listing without inflating Workflow
(Workflow is absent in that set, so it should); `--exclude-dynamic-system-prompt-sections`;
the attribution reminder as a separate lever; agentic quality with the lean tool set.

## Adopted 2026-10-24 (ruling 13)

The operator ruled the lean set with hooks on: `scripts/claude-local.ps1` adds `--tools
Bash,Read,Edit,Write,Glob,Grep,Skill`, `--strict-mcp-config --mcp-config <per-run empty
{"mcpServers":{}}>` and `--append-system-prompt` with the section 5 text verbatim;
`config/claude-settings.json` denies `Agent` and `Workflow`; `-LisFull` omits the three
flags. Measured on the live server (same one-turn call, prompt = `usage.input_tokens` +
`cache_read_input_tokens` = the server's `prompt eval` count):

| cwd | Before | After | Note |
|---|---|---|---|
| scratch dir outside `Z:\repos` | 25,578 | 12,347 | = run (i) 12,193 + append 148 + 6 |
| repo root | 26,224 (MCP connecting) / 32,988 (connected) | 12,775 | "Lean with hooks" estimate was about 12,700 |
| scratch dir, `-LisFull` | 25,578 | 21,908 | settings deny alone; = run (b) 21,911, so the deny does remove the Agent and Workflow schemas and the agent listing (item 2 now VERIFIED by this pair) |

All runs `is_error` false, `modelUsage` `local` only. First agentic loop on 65536 + MTP +
lean (`bench/loop/run.ps1 -Reps 1`): PASS 3/3, 6 turns, 40.7 s wall, 0 tool errors, first
request 12,587 tokens; one rep, variance UNVERIFIED. The policy text appears in the
session transcript's `prompt_snapshot`; the server log (verbosity 3) records no prompt
text, so server-side receipt rests on the token delta. Still UNVERIFIED: interactive
sessions on the lean set, and the lean set on harder tasks.
