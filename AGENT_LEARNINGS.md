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
- Scripted doc edits detect `\r\n` per file before matching, apply every edit before
  any `git add` and check the diff stat against the file list (10-24: 1 of 4 shipped).
- A brief's claim about a model (MTP head, template, fit) is read from `config/models.md` or the GGUF header before dispatch, never from memory; the subagent verifies it again on arrival.
- Code or doc text containing backslashes goes through the Write or Edit tool, never a Bash heredoc or `python -c`: the Bash tool collapses a doubled backslash to one (hit 3 times: 10-24 3d, 10-24 lean set, 10-25 permissions).
- A permission allow prefix for a command that takes file-valued options cannot be made safe by a hook that reads tokens before the shell expands them; allow such commands only through the hook's own recogniser, never a glob rule.
- A hook that allows commands gives no decision on any segment with a shell expansion (`$`, backtick, unquoted `{}`/`*?[]`/`~`), and every verb handler AND the env-prefix filter are allow-lists; no grammar over expansions survives audit (6 rounds, 2026-10-25).
- Grade a run by its artefact against a fixed fact checklist, never by server health.
- A ranking needs every contender to have a number on the same fixture (10-24 3d).
- Every figure or quoted string in a doc is copied from a named artifact (JSON, log,
  call log) in that artifact's order; a value remembered from the console, a wall
  time or a build-context size nobody saved is not written (11-06, 11-07 audits).
- How a session ended is read from docker events (`kill` signal, `die` exit code)
  and the per-run `history.jsonl`, never from the reply or a recollection (11-07:
  two runs a minute apart, one clean, one closed with the X).
- Every added line passes the identity grep before commit and every brief states
  the exact commit trailer (10-24: a subagent shipped an Opus trailer and a WSL
  username to this public repo).
- A brief that forbids a binary forbids it in version probes too; its version is
  recorded from the real-run path only (10-26: `claude --version` in a toolchain probe).

## 2026-10-24 — Phase 3d: agentic-loop comparison
- **Mistake:** started 3-rep loops on Saluki and GSQ-RCO without checking that their chat template accepts Claude Code's message order; every rep burned about 3 min on 11 HTTP 500 retries (`raise_exception('System message must be at the beginning.')`). → Before a long loop on a new GGUF, run one `-v` request and read the converted role order (the operator's SessionStart hook output arrives as a second, non-leading system message), or POST it to `/apply-template`.
- **Avoid:** under `pwsh -File`, an argument value that starts with `-` and contains `:` (`-ExtraArgLine "--chat-template-file Z:/x"`) is parsed as a `-name:value` token and fails with "Missing an argument for parameter". Pass it as ONE token `"-ExtraArgLine:<value>"`.

## 2026-10-25 — First real session on 65K+MTP+lean (PC recon, two runs compared)
- **Avoid:** auto permission mode on the local model: the classifier call (own system prompt + whole transcript, ~36K tokens) consumed 2x the GPU time of the work, timed out 9 times, denied 2 calls, and the detours inflated the context to the compaction threshold.
- **Avoid:** letting auto-compact fire mid-task on a 65,536 window: it triggered at ~36K; the model's own summary turned "J 135/4657, K 328/14902" into "mostly free" and the final report was written from the summary.
- **Better:** report-producing tasks write facts to a file as they go; the raw tool output is the only thing compaction cannot be trusted to keep.
- **Better:** llama-server's prompt cache restores interleaved conversations without re-prefill; one slot is not one conversation. Two full re-reads in 20 turns, both after long classifier generations.

## 2026-10-25 — Ruling 14: revert to 131K, RUN 3 of the PC recon
- **Mistake:** the RUN 2 verdict named compaction as the whole cause and auto mode as the fix; RUN 3 (131K, no compaction, one classifier timeout) was still incomplete: 6 of 8 volumes missing, GPU "not checked". -> Grade every run against a fixed checklist of the facts the task must contain (every volume, GPU, CPU, RAM, OS, toolchain, services) before naming a cause.
- **Mistake:** RUN 3 lost all three drive queries for three different reasons: one classifier timeout, one bash expansion of an unescaped `$_` inside `powershell -Command "..."`, one PowerShell precedence error (`-f $_.Size/1GB, ...`) hidden by `2>/dev/null`; the model fell back to `df` on C and Z. The first write-up blamed `$_` for both executed failures (audit catch). -> Read each failed call's result separately before naming one cause; a policy fix for `$_` covers one of the two.
- **Mistake:** wrote "compacted at about 36K" from the monitor's last n_tokens; the transcript's `compact_boundary.preTokens` says 39,098. -> Compaction size comes from the transcript metadata, not from the last server line before it.
- **Better:** the classifier cost is structural, not a RUN 2 accident: 7 classifier requests took about 240 s of RUN 3's 330 s of GPU time (2.7x the work). Auto mode on the local model is a cost figure the operator rules on, not a bug to fix.

## 2026-10-25 - Ruling 15 build: rule set A, lis-guard hook, perm bench
- **Mistake:** in PowerShell, `$s = Invoke-RestMethod ...` overwrote `$S` (the scratch path): variables are case-insensitive, and the `--debug-file` went nowhere. -> Distinct names, never case variants.
- **Mistake:** edited `scripts/hooks/lis-guard.py` while the AH bench was calling it per tool use, so one run could mix versions. -> Freeze every file a running bench reads; park edits in the scratchpad and re-run after.
- **Avoid:** a scratch dir named `build`: a PreToolUse hook protects it as generated output and refuses Edit.
- **Better:** a hook `deny` whose reason says "not retryable; report it to the operator" ends the `-p` retry loop after one attempt (V13), where a bare ask-rule denial is retried to `--max-turns` (V7).
- **Better:** the debug log names every permission path: `classifier_request_started/finished ... outcome=`, `tool_dispatch_start ... permissionDecisionMs=` and `Hook ... returned permissionDecision:`; the bench reads them instead of guessing from the server log.

## 2026-10-25 — lis-guard audit R1: FAIL (25+ false allows)
- **Mistake:** the hook's read-only grammar was a VERB list with "any arguments" for most verbs; `uniq a OUT`, `tree -o`, `sort -uo`, `nvidia-smi -f`, `wmic ... delete`, `date --set`, curl `-D/--cookie-jar`, ssh `-o ProxyCommand=` and PowerShell `% Delete` / `. $f` / `.$m()` all got `allow`. A safety allow-list is per-verb ARGUMENT shapes, never verb names -> the check that catches it: for every allowed verb ask "which of its options write a file, run a program or change state", and probe each one before the first live run.
- **Mistake:** my own-review commit ADDED `uniq`, `tree`, `rg` as "read-only verbs" without reading their man pages; `rg --pre` runs a program, `uniq` and `tree -o` write files. -> No verb enters the allow list without its write/exec options enumerated in the same commit.
- **Mistake:** docs said "no decision goes to the classifier"; it goes to the ALLOW RULES first, so a hook pass + a broad prefix rule (`git branch*`, `curl -s http://127.0.0.1:*`, `Get-*`) = unjudged write. -> Trace the full decision chain (hook -> deny rules -> ask rules -> allow rules -> classifier) before writing one sentence about where a case lands.
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

## 2026-11-04 — MTP A/B run (three arms, operator restarts)
- **Mistake:** chained `bench/run.ps1` and `bench/ladder/run.ps1` in one command with no gap; the ladder's busy check (server log written < 10 s ago) refused the rep because of the bench's own last request. -> Leave 15 s between two users of the same server, or run the ladder first.
- **Mistake:** a Bash line that piped `git push` into `tail` with the short line-count flag was refused by the hook guard, which reads that one-letter flag beside git as the short form of the skip-hooks flag. -> In a Bash command that contains `git`, give `tail`/`head` a bare count (`tail -2`) and avoid that flag anywhere in the line.
- **Avoid:** calling a pass tally at n=3 the A/B result — both arms scored 1 of 3 and every miss was a thrash exit (Claude Code's own), a facts-gate or a report-format line. -> Report the tally as ruled AND the per-rep walls, compactions and bench figures; rule from the figures that move with the variable.
- **Better:** read shared GPU memory on the arm that fits before judging a spill: about 250 MiB shared is the floor (pinned host buffers) on both fitting arms (248 and 274 MiB), so arm C's 484 MiB was about 235 MiB of real spill, not 484.
- **Mistake:** compressed a web-fetch report into a docs brief and introduced two false card facts (a refusal figure against the wrong baseline, a quanter name the card never mentions); qa-auditor FAILED the diff against the live page. -> A brief that relays third-party facts quotes the fetch report verbatim per figure, and the audit of any card-derived text re-reads the page.
- **Mistake:** wrote two memory timestamps (17:3x, 17:5x) from a guess while the clock read 16:5x and 17:16; caught only when a later `date` call disagreed. -> `date` before every timestamp, no exception for memory files, and check the git log time when stamping a commit.
- **Mistake:** an implementer deleted list items and the blank line after them, then reported the separator intact; qa-auditor caught the ruled-out paragraph rendering as a lazy continuation of arm 2. -> After deleting a list tail, print the three lines around the seam; a subagent's "still separated" claim is not a check.
- **Mistake:** called a live grader verdict a design flaw (a blocked rep kept the other member of a contradictory test pair) and ruled the pair symmetric from the rep's own report, without reading the fixture: its contract comment names the answer, and the rep had rewritten that comment to match the test it kept. The grader was loosened, qa-auditor read the fixture and reversed it. -> Before overruling a grader on a live rep, read the fixture source and the rep's diff, not the rep's report; a rep that changes a contract comment is a trust finding, not a grader bug.
- **Mistake:** batch D's new repo scripts (bait.py, blocked.py, gen_bait.py and three tests) went in without a run of `lis-guard_test.py`, whose repo-script deny table runs `decide('python -I <file>')` on every repo script: one prose false deny (blocked.py's docstring naming the dd output operand) and five true positives (bait.py, gen_bait.py and three tests hold the literal dot-env, exfil and checkout shapes they detect or write), documented in the test's allowed set. -> Run the full CLAUDE.md test list before a commit that adds a repo script, not only the tests of the files changed.
- **Avoid:** assembling or hex-escaping a guarded literal in a repo file to get past lis-guard's script scan; a real literal that the scanner flags is a true positive and goes in the test's documented table with its reason.
- **Mistake:** two proof-doc figures were written from memory ("false at all five, as in every rep on disk"; "four older sets") and the auditor found 4 of 80 strict Reads and 11 of 15 sets with a failed restore. -> A figure about "every rep" or "N older sets" comes from a script over `bench/results/*.json`, run before the sentence is written, never from recall.
- **Avoid:** restating a wrapper's protection as a guarantee ("the session cannot write the log") when the guard matches a literal name — a globbed or computed name gets past it; say what the guard matches and mark the field report-only.
- **Better:** when a proof rep runs while its hook is being edited, declare the rep's log-derived fields void and re-run; the transcript-side check (`facts_context_after`) is the evidence that survives such edits.
- **Mistake:** the brief told the supervisor to match the result record as a line "starting `{"type":"result"`", and the stub was written to that spec, so the tests were green on a path that never fires on a real stream (Claude Code writes `duration_api_ms` first). -> A stub for an external record copies the shape of a real record on disk (bench/results), never the brief's description of it; parse JSON, never match key order.
- **Better:** when a fold adds a parser for harness output, the auditor's first probe is `grep -c` of the assumed shape over every stream on disk; 0 hits means the parser is dead.

## 2026-11-05 — S-B3 per-run hook copies: glob coverage (audit C1 rounds 2-3)
- **Mistake:** modelled the stamp in `lis-hooks-<x>` as free text, so any `*`-led glob with 5 literals (`ls src/*.test.js`, `cat logs/*-error.log`) became a guard file and was denied; the corpus had deny rows only, no converse rows. -> A glob-to-name model gives its free slot the real alphabet (`[0-9-]` for a stamp or pid) and ships with converse rows plus a property oracle both ways (ordinary globs never deny; fnmatch-true globs always deny).
- **Better:** before building a new matcher, measure the simpler route against the old guard (here: mirroring the copies under `scripts\hooks\`); the measurement showed which rows each route misses.

## 2026-11-05 — S-O3 user scope off, S-B4 inline code and session-written files (c32)
- **Mistake:** the brief assumed a pre-existing file edited in-run keeps its birthtime; measured false (the Edit tool rewrites the file: new birthtime on NTFS and ReFS), and the first fold then stated "only an in-place write keeps the birthtime", while the auditor measured NTFS tunneling (delete and recreate within 15 s keeps the OLD birthtime). -> A file-time rule is proven by measuring the exact tool's write path and the volume's quirks before a doc states it; judge birth AND mtime.
- **Mistake:** the run-target rule stat'ed the file before the command ran, so `cp new.py f.py && python f.py` and every grouped form (`( )`, `{ }`, `if`, backticks, `bash -c --`) got no decision; found by the auditor, not the corpus. -> A rule over run targets judges the command's own writers and missing targets, and walks every grouping form the walker already handles for `$( )`.
- **Mistake:** the new property invariant checked only the converse (ordinary commands never deny), so disabling the rule kept 23531 cases green. -> Every new deny rule ships with a positive oracle (random instances must deny) and a converse one; mutation over the unit rows alone proves little.
- **Better:** when a settings scope is excluded, read what it carried (the debug log's "Adding N allow rule(s) to destination 'userSettings'") and name every bench whose inputs change; with user scope on, "no decision" means allow in a rep, and with it off, deny in a lean `-p` session.
- **Mistake:** the pre-commit ParseFile list carried a script that does not exist in this repo (`scripts/run.ps1`) from a compaction summary. -> `ls` the list before running it; the repo's actual `.ps1` files are the list.

## 2026-11-05 — Restart proofs, the harness's own warnings (c34)
- **Mistake:** the S-O3 live proof's debug log carried six `[WARN] [permissions]` lines (every `Write(path)` deny rule inert, the `git -C *` allow rules approving `-c`/`--exec-path`) and the proof was graded only on the figures it was run for; the warnings sat in a gitignored log for 18 hours. -> Every live proof gets a `[WARN]` grep of its debug log before the row is marked LANDED; the harness's own warnings are findings.
- **Better:** a row that "waits on the next start" is proven from the log lines the restart wrote (stop marker, pin check, hash-marker reuse, vram line, launch) and the endpoints with the new key, not from the first `/health` ok; the live stop-marker order differed from the stub's (serve.ps1 quotes it after the exit line while it holds the log) and the row now states the measured order.
- **Mistake:** the S-B8 rule read only tokens starting with `-` before the git subcommand, although the standing rule says a hook fails on any unquoted expansion; the auditor's `{-c,core.fsmonitor=...}` and `$'-c'` forms got no decision and bash ran them. -> Every new token-reading rule starts with the expansion clause (`$`, `{`, `[`, `*`, `?`, backtick before the judged position = deny) and its positive oracle includes expansion spellings.
- **Mistake:** the docs' exploit example (`-c core.pager='touch pwned' log -1` "ran its pager") was written from the harness's warning, not from a run; git skips the pager without a TTY, while `-c core.fsmonitor=<cmd> status` does run. -> An exploit example in a doc is executed once in a scratch repo before it is written; otherwise it is marked UNVERIFIED.
- **Better:** the third audit round hit the same class (expansion, re-quoted wsl payload, backslash-newline) and the 3-strike rule moved the fix off the tokenizer: the wildcard allow rules were removed (the hook already allows the benign forms, an undecided shape now meets no rule) and the hook judges the joined text as a second view. A rule that approves a prefix the hook cannot fully read is the hole; patching the reader is the 4th variation.
- **Mistake:** two live-proof folders were written under `bench/results/` on the belief that the directory is gitignored; only loose-file patterns were, so six files with user paths and session ids sat untracked in a public repo. -> `git check-ignore -v <new path>` right after creating anything under an "ignored" directory; a pattern list is not a directory ignore.
- **Mistake:** the trailing-star live-proof fold quoted the denial reasons as if `permission_denials` held them (it holds only the commands; the reasons were the model's reply) and wrote "before any rule" when the log shows no rule-evaluation step. -> Cite only fields the artifact holds (print them first); an ordering claim needs a log line that shows the order, else say the log does not show it.
- **Better:** a cheap, deterministic rc != 0 from a real claude.exe without touching the server: run `-p` in a scratch directory whose CLAUDE.md is far larger than the context (1.5 MB here); the first request gets a 400 overflow, the result is `is_error` with `terminal_reason` api_error (not max_turns), exit 1. A huge `-p` argument cannot do it (32K argv limit) and a tool read is capped before it reaches the model.

## 2026-11-05 — G run folded (c38)
- **Mistake:** the test-list extraction regex (`^\s*python -I`) matched zero CLAUDE.md lines because the commands are backticked mid-line, and the loop was started before its command count was checked; it "completed" with no test run. -> Print the extracted command count and compare it with the list's length before the loop starts, never after.
- **Mistake:** the dry run and the real run have different stamps (the stamp is taken at start), so the first look for the real run's artifacts used the dry run's stamp. -> Read the stamp from the run's own log line (`generated: ... manifest <stamp>`), never from an earlier invocation.
- **Better:** the R-C2 bar (2 h of wall time) was unreachable by the fixture's 79-module cap; saying so before the run and asking for the ruling let the run count without rework. A bar that no allowed input can meet is a ruling to request, not a run to repeat.

## 2026-11-05 - web access via Jarvis MCP in a container (c39)
- **Mistake:** the first web design left the jarvis-web server in the session's cwd (tsx
  read the work tree's `tsconfig.json`; eviction wrote to `<cwd>/data`); the audit's
  probe caught it. -> A helper process Claude Code starts inherits the untrusted work
  dir as cwd: pin config paths and chdir away before loading code.
- **Avoid:** counting a regex secret filter as a control (encoding, splitting and keyless
  shapes pass it); what the container mounts is the control.
- **Better:** prove the Docker host route from inside a container before planning host
  network changes; `host.docker.internal:8080` worked and saved an admin portproxy.

## 2026-11-06 - lis-web: web tools ported out of the Jarvis checkout
- **Mistake:** the Jarvis-mount design left the private Jarvis source readable in the
  container; an audit of a doc surfaced it. -> List what each mount exposes, by owner.
- **Better:** the operator ruled to decouple; the fix was a port into `web/`, not a
  mount tweak: no foreign source, build context or `.env` path is left in the launcher.
- **Mistake:** `--debug-file Z:\...\x.log` under `-LisWeb` wrote one file named after
  the whole path into /work. -> Container runs take relative names for file flags.

## 2026-11-07 - keys imported, keyed proofs (c43)
- **Mistake:** tried `ls -la .env` to verify the import by key names; the classifier
  denies every `.env*` read, names included. -> Verify a secret file through the
  consumer's own output (the server's `keys present:` stderr line), never the file.
- **Mistake:** wrote "exa then jina" from the prompt's order; the call log had jina
  first (the model chose). -> Quote tool order from the call log, not the prompt.
- **Mistake:** replaced a title's middle dots with `-` to keep the doc ASCII without
  saying so. -> Mark every altered character in a quoted string.
- **Better:** two sessions, three search calls, judged from JSON `subtype`,
  `permission_denials`, the call log and the cleanup counts, never from the reply.

## 2026-11-07 - W-10 interactive run, auto-mode wizard review (c45)
- **Better:** an interactive run with no `-p` JSON is judged from the per-run home:
  `.claude.json` (`lastDuration`, token counts, `hasTrustDialogAccepted`), the MCP
  log and the absence of a transcript said "no prompt sent".
- **Mistake:** read "nothing from your profile" as network-silent; claude's first
  start on a fresh home fetched a 14.7 MB plugin marketplace. -> List what the tool
  itself fetches before calling a container's network traffic the model's.
- **Avoid:** keeping a setup wizard's allow lines unread: the `/auto-mode` wizard
  wrote a blanket allow straight against an existing soft_deny. Read each line
  against the deny list before it stays.

## 2026-11-07 - first interactive web read, closed window, four-part build (c46)
- **Mistake:** briefed "five curl fetches allowed" from memory of the transcript;
  it held four run and one denied. -> Count tool calls from the transcript first.
- **Mistake:** matched the operator's "closed after /exit" to the leaking run; that
  run was a different window a minute earlier with no `/exit` in `history.jsonl`.
  -> Pin the artifact to its run folder before matching it to a recollection.
- **Mistake:** called S-B2 closed by a `defaultMode` pin; Shift+Tab reached auto
  mode in a pinned session. -> A default is not a lock; test the runtime toggle.
- **Better:** four additions to one implementer on the same files, each sent as a
  message carrying the measured facts, then one audit: no merge of parallel edits.
