# Permission allow-list assessment — plan (2026-10-25)

Operator ruling (15), 2026-10-25: in local sessions the only actions that block or ask,
auto mode or not, are writes and deletes of critical files. Everything else runs.
Reason: the auto-mode classifier on the local model fails on time, not on merit
(two live sessions: 20 verdicts, 7 timeouts, 0 denials; every timeout sat behind a
verdict that hit the 2,112-token output cap). Allow rules are checked before the
classifier, so a correct allow list removes the queue that kills harmless calls.

Same model and context as the last run: Orca IQ3_XXS, 131072, no MTP, lean wrapper.

## 0. Facts to verify first (one `-p` run each, read the server log and the result JSON)

| # | Claim | Test | Pass |
|---|---|---|---|
| V1 | An `allow` rule skips the classifier in auto mode | `-p` with one allowed read-only command, `--permission-mode auto` | 0 requests at >30K `n_tokens` in the server log |
| V2 | Rules in the per-run `--settings` file are honoured | same run, rules only in `%TEMP%\lis-settings-*.json` | V1 passes with no change to `~/.claude/settings.json` |
| V3 | `ask` beats `allow` when both match | `Bash(*)` allow + `Bash(rm *)` ask; run `rm` of a scratch file in `-p` | `permission_denials` lists it; file still there |
| V4 | Compound commands: every segment must match | `allow Bash(ls *)`, run `ls; rm x` | denied or classified, not allowed |
| V5 | `powershell -Command "..."` is matched on its prefix only | allow `Bash(powershell -NoProfile -Command Get-*)`, run a `Remove-Item` inside the quotes | shows whether the prefix rule is blind to the payload (expected: it is) |
| V6 | Windows paths in `Edit`/`Write`/`Read` rules | `ask Write(//C:/Users/*/.claude/**)` and `Write(C:\\Users\\**)`; write a scratch file under `.claude` | one syntax asks; record which |
| V7 | `-p` mode treats `ask` as a denial, not a hang | V3's run finishes under the timebox | `num_turns` advances, `is_error` false |
| V8 | Hooks still fire on allowed commands | allowed `kill -1`-shaped command | kill-guard denial text in the result |
| V12 | A PreToolUse hook `permissionDecision: "allow"` skips the classifier in auto mode | hook in the per-run `--settings` returns allow for `wmic os get Caption` (no allow rule matches it); `-p` auto | **PASS** (2026-10-25): 2 requests, both session-sized (12,839 and 13,190 `n_tokens`), 0 classifier-sized; the command ran (it failed with exit 127: `wmic` is not on Git Bash's PATH); wall 16 s |
| V13 | A hook `deny` whose reason says "do not retry; the operator must run this" stops the retry loop | same hook returning deny with that reason; same command; `--max-turns 8` | **PASS** (2026-10-25): 1 denial, then the model reported the block and stopped (`num_turns` 2, success, 8 s). V7's bare `ask` rule denial was retried 4 times to `error_max_turns` |

Any FAIL here changes the design below before anything is built.

## 1. Corpus: what a recon actually runs

Extract every tool call from the five recon transcripts (RUN 1, RUN 2, RUN 3, live A,
live B) into `bench/perm/corpus.jsonl`: command, tool, outcome (ok / blocked /
denied / error), classifier time if known. About 70 Bash calls, 3 Read, 2 Write.

Classify each into one bucket:

| Bucket | Examples from the corpus | Intended verdict |
|---|---|---|
| R1 host inspection | `powershell -NoProfile -Command Get-CimInstance ...`, `wmic ... get`, `nvidia-smi`, `systeminfo`, `df`, `uptime`, `hostname` | allow |
| R2 file read | `ls`, `cat`, `head`, `find`, `Read` tool | allow |
| R3 toolchain versions | `node -v`, `git --version`, `python --version`, `pnpm -v`, `uv --version`, `claude --version` | allow |
| R4 repo read | `git status`, `git branch`, `git log`, `git -C <dir> ...` read subcommands | allow |
| R5 service state | `docker version`, `docker context ls`, `wsl --list --verbose`, `Get-Process`, `Get-ScheduledTask` | allow |
| O1 outbound read | `gh auth status`, `curl` to localhost, `ssh <vps> <read-only>` | ruling: see §4 |
| S1 script execution | `bash /z/repos/kosm1x/PC/vps-probe.sh` | ruling: see §4 |
| W1 non-critical write | `Write` under the cwd, `mkdir`, `echo > scratch` | allow |
| W2 critical write/delete | anything under §3 | ask |

## 2. Two candidate rule sets, both measured

**A. Curated allow + classifier fallback.** Allow R1–R5 and W1 by prefix. W2 asks.
Unlisted commands still go to the classifier. Keeps the judge for the unknown;
the queue shrinks to the unlisted remainder.

**B. Broad allow + critical ask.** `Bash(*)`, `Read(**)`, `Write(**)`, `Edit(**)` allowed;
W2 asks. The classifier never runs. The hooks (kill-guard, git-secret-guard) and the
ask rules are the whole guard.

Ruling (15) as stated points at B. A is kept in the matrix so the cost of the judge
on the remainder is a measured figure, not an assumption.

## 3. Critical files (draft for the operator to confirm or edit)

Writes or deletes here ask; reads are allowed.

- `C:\Users\<user>\.claude\**` (settings, hooks, memory, agents)
- `C:\Users\<user>\.ssh\**`, `~/.ssh/**` inside WSL
- `C:\Windows\**`, `C:\Program Files\**`, `C:\Program Files (x86)\**`, `C:\ProgramData\**`
- `**/.env`, `**/.env.*`, `**/*.pem`, `**/*.key`, `**/token`, `C:\Users\<user>\.cache\huggingface\token`
- `**/.git/**` internals (history rewrite goes through git commands, see below)
- The repos themselves against deletion: `rm -r`/`Remove-Item -Recurse` anywhere under `Z:\repos`

Commands treated as critical writes regardless of path:

- `rm -r*`, `rm -f*`, `del /s`, `rmdir /s`, `Remove-Item -Recurse`, `Remove-Item -Force`
- `git push --force*`, `git reset --hard*`, `git clean*`, `git checkout -- *`, `git branch -D*`, `git rebase*`
- `format`, `diskpart`, `Remove-Partition`, `Clear-Disk`, `mkfs*`, `dd *`
- `reg add`/`reg delete`, `Set-ItemProperty HKLM:*`, `schtasks /create|/delete`, `Register-ScheduledTask`, `Unregister-ScheduledTask`, `sc *`, `Stop-Service`, `Set-Service`
- `wsl --unregister*`, `wsl --import*`, `docker rm*`, `docker system prune*`, `docker volume rm*`
- Process kills: already denied by the kill-guard hook; the rule set does not relax it.
- Anything that reaches the VPS with a write (`ssh ... rm|systemctl|docker|git push`): §4.

Prefix rules cannot see inside `powershell -Command "..."`, `bash -c "..."`, or a
script file (V5). The assessment states this limit; the mitigation is the hooks plus
the ask rule on the interpreter shapes that take an inline payload with a write verb
(`Bash(powershell * Remove-Item*)` style rules are tested in V5 for whether the
matcher sees past the first word).

## 4. Rulings (operator, 2026-10-25)

1. **A and B**: both rule sets are built and measured; the numbers decide.
2. **Critical list**: the §3 draft is the baseline ("the obvious list"); amend on evidence.
3. **Outbound read-only is allowed**, including reviewing the VPS over SSH. The earlier
   hand rejection of `gh auth status` was a mistake. Condition from this side: a prefix
   rule cannot tell `ssh host cat` from `ssh host rm`, so SSH commands are allowed by
   prefix only when the remote command is read-only by inspection; an SSH command whose
   payload carries a write verb (`rm`, `systemctl`, `docker`, a push, `tee`, `>`,
   `mv`, `chmod`, `kill`) is not allowed by rule and falls to the judge (set A) or to a
   payload-scanning hook (set B). The VPS house rules (mc.db read-only, deploy
   operator-only) are unchanged.
4. **Scripts are reviewed by the judge before they run.** `bash <file>`, `pwsh -File`,
   `python <file>` and `node <file>` on a file the session did not write this turn are
   never allowed by rule; they go to the classifier. The judge can only review what is in
   the transcript, so the gate must put the script text there: a PreToolUse hook on the
   script-execution shapes returns `ask` with the file's first 60 lines in the reason, so
   the judge sees the content (V9 tests that auto mode routes a hook `ask` to the
   classifier and that the reason reaches it). If V9 fails, the hook denies once with
   "cat the file, then re-run", which puts the content in the transcript for the next
   judgement.

## 4a. Added verifications

| # | Claim | Test | Pass |
|---|---|---|---|
| V9 | A hook `permissionDecision: ask` in auto mode goes to the classifier, and `permissionDecisionReason` is in what it judges | hook on `bash *.sh` returning ask + the script text; run a harmless script in `-p` auto | classifier request appears in the server log and the tool runs (or is denied) with the reason visible in the classifier diagnostic |
| V10 | `hooks` in the per-run `--settings` file are honoured | the V9 hook defined only there | the hook fires (side effect: its reason text in the result) |
| V11 | `ask` in `-p` auto mode with no hook: classifier or hard denial | `Bash(rm *)` ask rule, run `rm scratch` | record which; it decides whether set B's critical asks are judged or refused unattended |

## 5. Build

- `config/claude-settings.json`: `permissions.allow` / `permissions.ask` per the chosen
  set; the existing `deny` (WebSearch, WebFetch, Agent, Workflow) stays.
- `claude-local.ps1`: no change if V2 passes; otherwise the rules go into a project
  `.claude/settings.json` written into the cwd by the wrapper (ruling needed, it
  touches the user's project).
- `bench/perm/run.ps1`: replays the corpus through `claude -p` one command per run,
  reads `permission_denials` and counts classifier requests from the server log,
  writes `bench/results/<stamp>-perm-<set>.json`. Expected verdict per command lives
  in the corpus file, so the run is a pass/fail table, not a reading exercise.
- `docs/SETUP.md` step 8: the rule set, the critical list, what asks, and the V5 limit.

## 6. Graded re-run (RUN 4)

Same prompt, same cwd (`Z:\repos\kosm1x\PC`), `-p`, auto mode, hooks on, with the
chosen rule set. Grade against the fixed checklist: 8 volumes with J and K flagged,
GPU named, CPU, RAM, OS build, toolchain, Docker/WSL state, repo sweep, VPS link.

Targets:

| Metric | RUN 3 (no rules) | Target |
|---|---|---|
| Classifier requests | 7 | 0 (set B) or only the unlisted remainder (set A) |
| Timeouts on R1–R5 commands | 1 | 0 |
| Wall time | 5.7 min | under 3 min |
| Checklist items present | 8 of 14 | 14 of 14 |
| False statements | 0 | 0 |

One rep is a measurement, three reps is a result; the ROADMAP records which.

## 7. What this does not fix

- The `$_`-through-bash and silenced-stderr traps: a policy-text change, separate commit.
- The classifier's 2,112-token cap and client timeout: Claude Code internals, not
  tunable from the wrapper as far as is known (UNVERIFIED; one check in V0 if an
  env var exists).
- Script-file and inline-interpreter payloads: a prefix matcher cannot read them;
  the hooks are the only guard there.
