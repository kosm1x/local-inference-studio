# Agent learnings — local-inference-studio

## Standing rules

- Every built commit gets a scoped qa-auditor pass before push; warnings become a follow-up commit, never a silent amend of content.
- Git commit messages go through a message file (`git commit -F <abs path>`), never a PowerShell here-string piped to `-F -` and never `git log --format=%B` round-tripped through `-replace` (both lose newlines or fail).
- Anything that crosses into WSL from PowerShell is wrapped in `bash -c '...'`: PowerShell expands a bare `~` to the Windows profile before `wsl` sees it, so `wsl -- rm -rf ~/x` silently misses.
- A bench number without a saved console log is UNVERIFIED: tee every `bench/run.ps1` run to `bench/results/<stamp>-<label>.log`.
- A decode warm-up request is discarded before the median; the first request on a cold server is not a sample.
- GPU work is single-tenant: a benching agent checks `nvidia-smi` compute apps and port 8081 before `stop.ps1`, and restores the Scheduled Task afterwards.
- Vendor "fits a 16 GB GPU" claims are measured against the desktop's 1.3 to 2.0 GiB already resident, never against 16 GB.
- A driver that starts `serve.ps1` with `Start-Process` passes ONE argument string with `-ExtraArgLine "-lv 4"` quoted inside it; an `-ArgumentList` array splits `'-lv 4'` into two tokens (llama-server then gets `--port 4` and a bare `-lv`). Check the first line of the server log (the command line) before trusting a driver loop.
- Scripted doc edits detect `
` per file before matching, apply every edit before any `git add`, and the diff stat is checked against the intended file list (a half-applied script shipped one of four fixes on 10-24).
- A brief's claim about a model (MTP head, template, fit) is read from `config/models.md` or the GGUF header before dispatch, never from memory; the subagent verifies it again on arrival.
- Code or doc text containing backslashes goes through the Write or Edit tool, never a Bash heredoc or `python -c`: the Bash tool collapses a doubled backslash to one (hit 3 times: 10-24 3d, 10-24 lean set, 10-25 permissions).
- A permission allow prefix for a command that takes file-valued options cannot be made safe by a hook that reads tokens before the shell expands them; allow such commands only through the hook's own recogniser, never a glob rule.
- A hook that allows commands gives no decision on any segment with a shell expansion (`$`, backtick, unquoted `{}`/`*?[]`/`~`), and every verb handler AND the env-prefix filter are allow-lists; no grammar over expansions survives audit (6 rounds, 2026-10-25).

## 2026-10-24 — P3 to P5: bench matrix, Saluki/GSQ-RCO/Orca, vLLM spike

- **Mistake:** P3 part B published a decode median that included the cold first request (Qwen3.6 104 vs 134 tok/s). → Discard one warm-up; the audit's cross-check of per-run values caught it.
- **Mistake:** per-run spread figures were written into the summary from console output nobody saved. → Tee every run; unsaved figures are marked UNVERIFIED.
- **Mistake:** `git commit -F -` with a PowerShell here-string failed with "pathspec did not match", and a later `--amend` built from `git log --format=%B` collapsed the message to one line. → Message file in the scratchpad, always.
- **Mistake:** a subagent committed with an Opus trailer and a WSL username in the ROADMAP. → Brief states the exact trailer; audit checks for usernames.
- **Better:** fit questions get answered by the `-lv 4` placement lines (layers on GPU, CPU_Mapped MiB, KV MiB, free MiB) captured in the same run as the numbers.
- **Better:** the GSQ-RCO MTP head runs on stock llama.cpp `--spec-type draft-mtp`; test MTP at the context where the model fits all-GPU, since its ~1.3 GB cost otherwise spills layers and hides the speed-up.

## 2026-10-24 — Phase 3c: Qwen3.8-27B-Uncensored GGUF

- **Mistake:** repeated the logged `-lv 4` split in a Start-Process driver (three dead starts, each "health NOT ok after 2 s"), then broke the retry by re-assigning a split array into a `[string]` param, which PowerShell joins back into one space-separated string. → Promoted to Standing rules; split into a new variable, never back into a typed param.
- **Better:** a background poll (port 8081, `pgrep vllm` in WSL, `memory.used`) that also accepts "llama-server back on :8080" as the other agent's done signal ended the GPU wait without guessing.

## 2026-10-24 — Phase 3d: agentic-loop comparison

- **Mistake:** started 3-rep loops on Saluki and GSQ-RCO without checking that their chat template accepts Claude Code's message order; every rep burned about 3 min on 11 HTTP 500 retries (`raise_exception('System message must be at the beginning.')`). → Before a long loop on a new GGUF, run one `-v` request and read the converted role order (the operator's SessionStart hook output arrives as a second, non-leading system message), or POST it to `/apply-template`.
- **Mistake:** the loop fixture had a `package.json`; the operator's `~/.bashrc` runs `fnm env --use-on-cd`, so any `cd <dir> && node ...` inside Claude Code's Bash tool failed in `fnm use` and one rep timed out at 30 min while debugging fnm. → A fixture carries no `package.json`, `.nvmrc` or `.node-version`; `node --test` discovers `test/*.test.js` alone.
- **Avoid:** under `pwsh -File`, an argument value that starts with `-` and contains `:` (`-ExtraArgLine "--chat-template-file Z:/x"`) is parsed as a `-name:value` token and fails with "Missing an argument for parameter". Pass it as ONE token `"-ExtraArgLine:<value>"`.
- **Avoid:** heredocs through the Bash tool collapse `\\` to `\`, and Python text-mode writes CRLF on Windows; write template or escape-heavy files with the Write tool, or open with `newline=''`.
- **Mistake:** a Python edit script asserted on `\n` patterns against files that are CRLF on disk (ROADMAP, models.md); the first edit passed, the script died, and a commit went out with one of four fixes. → Detect `\r\n` per file before matching, apply all edits before any `git add`, and check the diff stat lists every intended file.
- **Better:** when a contender's wall time is quoted "on both fixtures", check that the other contenders produced a number on both; a comparison with one finisher is a measurement, not a ranking (audit catch).

## 2026-10-24 — Ruling 6 cutover (Orca IQ3_XXS default)

- **Mistake:** the brief claimed the Orca GGUF has "no MTP head", but `config/models.md` (header table: `nextn_predict_layers` 1) and the live log (`blk.64.*` unused tensors) show it has one. → Check `nextn_predict_layers` in `config/models.md` (and the server log) before asserting a model has or lacks MTP.
- **Mistake:** template detection compared a non-normalised path; `GetFullPath` ran only on relative inputs, so an absolute forward-slash `-Model` skipped `--chat-template-file` (HTTP 500 under Claude Code) (audit catch). → Normalise every path before any prefix test.
- **Better:** the logon task log runs at verbosity 3 and carries no placement lines; capture fit with ONE `-lv 4` start on :8081 after stopping the task server (two 27B servers cannot share the card), then restart the task.

## 2026-10-24 — Session close (orchestration)

- **Mistake:** the orchestrator's brief for the cutover asserted "no MTP head" from memory; the repo's own table said otherwise. → Promoted to Standing rules.
- **Mistake:** the Phase 3d summary's "fastest on both fixtures" passed the orchestrator's read before the audit caught that only one contender finished on the old fixture. → Rankings need every contender to have a number on the same fixture.
- **Better:** every built commit went through qa-auditor before push (3d, 3d residuals, ruling 6, ruling 6 residuals); each audit found a real wording or edge-case gap, none found a wrong number.
- **Better:** a 3-strike stop on identical 500s (Saluki r1-r3 + GSQ-RCO r1) and a redirect to capture ONE failing request found the template cause in one pass; the fix then unblocked four model files.

## 2026-10-24 — Live monitoring of the Orca default

- **Mistake:** reported the running context size by summing prompt-in and tokens-out per turn (said ~67K); the server's own `stop processing: n_tokens` line peaked at 45,417. → Read the server's count; the sum ignores compaction and parallel conversations.
- **Better:** a `tail -F | grep --line-buffered` monitor on `prompt eval time|eval time|total time|truncated = [1-9]|exited|error` gives one event per turn with the cache hit/miss visible in the prompt token count (tens = hit, tens of thousands = full re-read).
- **Better:** judge a model's agentic cost from a real session's decode share (here 90 %) before optimising prefill; the loop bench over-weighted prefill because every rep started cold.

## 2026-10-24 — Ruling 13 lean set

- **Mistake:** repeated the logged heredoc trap: a Python heredoc wrote `Z:\\repos` into a doc, the Bash tool collapsed it to `Z:\repos`, Python read `\r` as a carriage return, and `git ls-files --eol` flagged the file `w/-text`. → Doc text with backslashes goes through the Edit tool; after any scripted edit run `git ls-files --eol <files>` and a control-character grep on the diff.
- **Better:** the brief expected `-LisFull` to restore the old 25.6K prompt; it measured 21,908 because the settings deny of Agent and Workflow stays on, which also turned the audit's "deny removes the schema" observation into a VERIFIED pair (run (b) 21,911). Predict a switch's result from every layer it leaves in place, not only the flags it drops.
- **Better:** Claude Code's session transcript carries a `prompt_snapshot` attachment with the full system prompt; it proves an `--append-system-prompt` reached the request builder when the server log runs below prompt verbosity.

## 2026-10-25 — First real session on 65K+MTP+lean (PC recon, two runs compared)

- **Mistake:** declared the lean run healthy from server stats (0 server errors, all cache hits); the report it produced was wrong on two disks and silent on the GPU. -> Judge a run by its artefact against ground truth, not by the serving log.
- **Avoid:** auto permission mode on the local model: the classifier call (own system prompt + whole transcript, ~36K tokens) consumed 2x the GPU time of the work, timed out 9 times, denied 2 calls, and the detours inflated the context to the compaction threshold.
- **Avoid:** letting auto-compact fire mid-task on a 65,536 window: it triggered at ~36K; the model's own summary turned "J 135/4657, K 328/14902" into "mostly free" and the final report was written from the summary.
- **Better:** report-producing tasks write facts to a file as they go; the raw tool output is the only thing compaction cannot be trusted to keep.
- **Better:** llama-server's prompt cache restores interleaved conversations without re-prefill; one slot is not one conversation. Two full re-reads in 20 turns, both after long classifier generations.

## 2026-10-25 — Ruling 14: revert to 131K, RUN 3 of the PC recon

- **Mistake:** the RUN 2 verdict named compaction as the whole cause and auto mode as the fix; RUN 3 (131K, no compaction, one classifier timeout) was still incomplete: 6 of 8 volumes missing, GPU "not checked". -> Grade every run against a fixed checklist of the facts the task must contain (every volume, GPU, CPU, RAM, OS, toolchain, services) before naming a cause.
- **Mistake:** RUN 3 lost all three drive queries for three different reasons: one classifier timeout, one bash expansion of an unescaped `$_` inside `powershell -Command "..."`, one PowerShell precedence error (`-f $_.Size/1GB, ...`) hidden by `2>/dev/null`; the model fell back to `df` on C and Z. The first write-up blamed `$_` for both executed failures (audit catch). -> Read each failed call's result separately before naming one cause; a policy fix for `$_` covers one of the two.
- **Mistake:** wrote "compacted at about 36K" from the monitor's last n_tokens; the transcript's `compact_boundary.preTokens` says 39,098. -> Compaction size comes from the transcript metadata, not from the last server line before it.
- **Avoid:** judging a run by server health (no compaction, no truncation, no denials): RUN 3 was clean on every server metric and still omitted the two nearly-full disks.
- **Better:** the classifier cost is structural, not a RUN 2 accident: 7 classifier requests took about 240 s of RUN 3's 330 s of GPU time (2.7x the work). Auto mode on the local model is a cost figure the operator rules on, not a bug to fix.

## 2026-10-25 - Ruling 15 build: rule set A, lis-guard hook, perm bench
- **Mistake:** wrote the dry matcher and the corpus sanitiser through Bash heredocs with backslash literals; both died on a SyntaxError and the fix attempts through `sed` and `python -c` hit the same collapse. -> Promoted to Standing rules: Write/Edit tool, or `chr(92)`.
- **Mistake:** in PowerShell, `$s = Invoke-RestMethod ...` overwrote `$S` (the scratch path): variables are case-insensitive, and the `--debug-file` went nowhere. -> Distinct names, never case variants.
- **Mistake:** edited `scripts/hooks/lis-guard.py` while the AH bench was calling it per tool use, so one run could mix versions. -> Freeze every file a running bench reads; park edits in the scratchpad and re-run after.
- **Avoid:** a scratch dir named `build`: a PreToolUse hook protects it as generated output and refuses Edit.
- **Better:** a hook `deny` whose reason says "not retryable; report it to the operator" ends the `-p` retry loop after one attempt (V13), where a bare ask-rule denial is retried to `--max-turns` (V7).
- **Better:** the debug log names every permission path: `classifier_request_started/finished ... outcome=`, `tool_dispatch_start ... permissionDecisionMs=` and `Hook ... returned permissionDecision:`; the bench reads them instead of guessing from the server log.

## 2026-10-25 — RUN 4 (rules + lis-guard): permission layer fixed, report still 7/14

- **Mistake (the local model's, logged for the policy text):** RUN 4 trusted a leftover probe script in the cwd (`repo-sweep.sh`, written by RUN 2 with a Docker path that never exists) and reported "Docker Desktop is not installed"; a direct `Test-Path` would have shown the binary. -> A recon never cites a script it did not write this session without reading it first; stale helpers in a cwd are inputs to verify, not facts.
- **Mistake (the model's):** chose `Get-PhysicalDisk` over `Get-Volume`, so the report lists six drive models with no letters or free space and misses J and K at 2-3 % free; GPU and the llama-server process omitted for the third run in a row. -> A fixed recon checklist in the prompt or policy is the next lever; the harness is no longer the cause (0 classifier requests, 0 timeouts, 162 s).
- **Better:** 16 Bash calls, 15 allowed by lis-guard in 91-119 ms each and 1 by rule; zero classifier calls; wall 162 s vs 342 s (RUN 3) and ~53 min (RUN 2). The allow-list premise held exactly as Phase 0 measured it.
- **Avoid:** grading a run by its permission metrics: RUN 4 met every harness target and scored lower than RUN 3 on the report (7/14 vs 8/14), with two false statements.

## 2026-10-25 — lis-guard audit R1: FAIL (25+ false allows)

- **Mistake:** the hook's read-only grammar was a VERB list with "any arguments" for most verbs; `uniq a OUT`, `tree -o`, `sort -uo`, `nvidia-smi -f`, `wmic ... delete`, `date --set`, curl `-D/--cookie-jar`, ssh `-o ProxyCommand=` and PowerShell `% Delete` / `. $f` / `.$m()` all got `allow`. A safety allow-list is per-verb ARGUMENT shapes, never verb names -> the check that catches it: for every allowed verb ask "which of its options write a file, run a program or change state", and probe each one before the first live run.
- **Mistake:** my own-review commit ADDED `uniq`, `tree`, `rg` as "read-only verbs" without reading their man pages; `rg --pre` runs a program, `uniq` and `tree -o` write files. -> No verb enters the allow list without its write/exec options enumerated in the same commit.
- **Mistake:** docs said "no decision goes to the classifier"; it goes to the ALLOW RULES first, so a hook pass + a broad prefix rule (`git branch*`, `curl -s http://127.0.0.1:*`, `Get-*`) = unjudged write. -> Trace the full decision chain (hook -> deny rules -> ask rules -> allow rules -> classifier) before writing one sentence about where a case lands.
- **Mistake:** 9 of 22 mutants survived: every guard without a pinning test. -> Mutation RED first (standing rule) applies to every branch of a safety hook, not just the headline ones.
- **Mistake:** a 200 KB read cap followed by `allow` let a 10 MB script with a trailing `rm -rf` through. -> A cap on a judged input yields NO DECISION, never the permissive verdict ([[tool-result-cap-is-a-design-constraint]]).
- **Avoid:** quadratic regex spans (`[^;|]*` before a literal) in a hook with a 10 s timeout; a 96 KB padded command took 17 s and the timeout turns a deny into a pass.
- **Better:** audit by attack table + mutation BEFORE the first interactive run, not in parallel with it; the operator ran Live C under the unaudited hook (disclosed as such, read-only task).
- **Better:** three audit rounds on a safety hook: R1 attack+mutation (FAIL, 25 allows), R2 re-attack 80 new shapes (PASS-W, 0 allows, 7 deny-misses), R3 fold check 10 mutants (PASS-W, rule-level residuals → ask rules). Ship after R3 with only UNVERIFIED-live items left.

## 2026-10-25 — policy-text levers (ruling 15 follow-up)

- **Mistake:** the local model reported counts it never computed (listed 16 and 30 dirs, wrote 18 and 33; wrote 46 for a 47-line sweep). -> The appended policy now says every number is copied from a tool output and counts come from `wc -l` / `Measure-Object`; grade RUN 5 on each count against its own tool output.
- **Mistake:** the local model cited a stale helper script left in the cwd ("Docker not installed") and appended `2>/dev/null` to probes, so a failed probe read as a fact. -> Policy: read a script before citing it, prefer a direct check, never silence stderr on a probe.
- **Avoid:** `powershell -NoProfile -Command "... $_ ..."` through the Bash tool (bash expands `$_`); also unquoted `~` in `wsl -d Ubuntu -- ssh -i ~/...` from Git Bash, which expands to the Windows home and fails with "Permission denied (publickey)". -> Single-quote the PowerShell payload (inner strings in double quotes work) and quote `'~/.ssh/...'`; both verified from Git Bash 2026-10-25.
- **Better:** the model name lives in `/props` `model_path` (needs `Authorization: Bearer local`); `/v1/models` only returns the alias `local`. A policy change is measured with `/tokenize` on the evaluated string plus one same-cwd `-p` A/B (152 -> 540 tokens; +388 on the prompt, both methods agree). Name the VPS by its IP in a policy: the `mail` alias does not resolve inside WSL.
- **Mistake:** three grammar attempts on the curl write holes failed audit: a substring blacklist (R3: `-w @-`, `-w @fmt.txt`, `-w "$F"`), a value whitelist (R4: unquoted `-w %{o..o}utput{FILE}`, brace-expanded after the hook reads it), then glob/brace-built paths (R5: `-so C:/Users/u/.cl?ude/x`, `-so ~/.c{l..l}aude/x`) admitted by the `curl -s(S) http://127.0.0.1:8080/*` allow prefixes. -> The fix was removing the allow prefix (curl now runs only on the hook's own allow), not a fourth grammar; 3-strike rule. **Better:** fail closed on metacharacters in file arguments, no parsing: the hook denies a curl file argument or `-w` value holding `? * [ { } $` or a backtick, and a hook deny also beats a user-level `Bash(curl:*)` (VERIFIED live: `-so <dir>/.cl?ude/x` denied, nothing written).
- **Mistake:** a repo allow rule was removed as "the" curl allow, but the wrapper also loads user settings, and a user-level `Bash(curl:*)` admitted `curl ... -so out.txt` with the hook on (VERIFIED live). -> Read the debug log's "Adding N allow rule(s) to destination 'userSettings'" line before claiming what a session allows.
- **Mistake:** `seg_readonly` replaced each `$(...)` with a one-word placeholder after checking its inner verbs, which hid the word-split: `curl URL/$(printf 'a %so F' -)` was allowed and bash turned it into `-o F` (also `find`, `sort`, `git log`, unquoted `$X`). -> The R8 fix (no decision on an unquoted `$` or backtick, assignments excepted) failed R7 audit too: a quoted expansion is still a flag (`find D "$(printf -- -delete)"` deleted dirs), `X=${Y@P}` runs a command, a backtick inside double quotes runs one, and `[[ Z -eq 1 ]]` evaluates arithmetic. Now any `$` or backtick in a segment means no decision, `[[`/`[`/`test` are not read-only, and a PowerShell payload may hold `$_` only where bash leaves it (single quotes or `\$`).
- **Mistake:** `find`, `tree` and `rg` kept deny-lists (`-delete`, `-o`, `--pre`) after every other verb became an allow-list, so a brace-built flag got through: `find D -{delete,delete}` was allowed and deleted a scratch tree (also `rg --{pre,pre}=sh`, `tree X -{o,}OUT`, `find X *` with a planted `-delete` file). -> Check that every verb handler is an allow-list (unknown token = no decision), and treat unquoted braces, globs and `~` as expansions like `$`.
- **Mistake:** the env-prefix filter was a deny-list (`PATH`, `LD_PRELOAD`, `NODE_OPTIONS`, ...) and missed the git exec family: `GIT_EXTERNAL_DIFF=<script> git diff --ext-diff` was allowed and ran the script live with no denial (also `GIT_CONFIG_*` core.fsmonitor, `PAGER`, `GIT_PAGER`, `GIT_CONFIG_GLOBAL`, `GIT_DIR`). -> Any list that names the dangerous members is a deny-list and will miss one; the filter is now `ENV_SAFE`, a list of harmless names.

## 2026-10-26 — bench/ladder harness (build + dry-run only)
- **Mistake:** ran `claude --version` in a toolchain probe while the brief said never launch `claude`. -> When a brief forbids a binary, leave it out of version probes too; record the version in the real-run path only.
- **Better:** under `-LisTask` (`--allowedTools` refused) a bench task can still run its test command without a prompt by copying the fixture to its repo-relative path, so the committed exact allow rule matches; a scratch stub wrapper exercises the whole non-dry path without a session.
