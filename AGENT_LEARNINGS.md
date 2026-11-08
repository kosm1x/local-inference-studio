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
- Code or doc text containing backslashes goes through the Write or Edit tool, never a Bash heredoc or `python -c`: the Bash tool collapses a doubled backslash to one (hit 4 times: 10-24 3d, 10-24 lean set, 10-25 permissions, 11-08 fold).
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
- `date` runs before every timestamp written anywhere, memory files included; a
  commit is stamped from `git log`, never from recall (11-04: two guessed times).

## 2026-10-25 — PC recon runs 1 to 3 (65K+MTP+lean, then ruling 14 back to 131K)
- **Avoid:** letting auto-compact fire mid-task on a 65,536 window: it triggered at ~36K; the model's own summary turned "J 135/4657, K 328/14902" into "mostly free" and the final report was written from the summary.
- **Better:** report-producing tasks write facts to a file as they go; the raw tool output is the only thing compaction cannot be trusted to keep.
- **Mistake:** the RUN 2 verdict named compaction as the whole cause and auto mode as the fix; RUN 3 (131K, no compaction, one classifier timeout) was still incomplete: 6 of 8 volumes missing, GPU "not checked". -> Grade every run against a fixed checklist of the facts the task must contain (every volume, GPU, CPU, RAM, OS, toolchain, services) before naming a cause.
- **Mistake:** RUN 3 lost all three drive queries for three different reasons: one classifier timeout, one bash expansion of an unescaped `$_` inside `powershell -Command "..."`, one PowerShell precedence error (`-f $_.Size/1GB, ...`) hidden by `2>/dev/null`; the model fell back to `df` on C and Z. The first write-up blamed `$_` for both executed failures (audit catch). -> Read each failed call's result separately before naming one cause; a policy fix for `$_` covers one of the two.
- **Mistake:** wrote "compacted at about 36K" from the monitor's last n_tokens; the transcript's `compact_boundary.preTokens` says 39,098. -> Compaction size comes from the transcript metadata, not from the last server line before it.
- **Better:** the classifier cost is structural, not a RUN 2 accident: 7 classifier requests took about 240 s of RUN 3's 330 s of GPU time (2.7x the work). Auto mode on the local model is a cost figure the operator rules on, not a bug to fix.

## 2026-10-25 - Ruling 15 build: rule set A, lis-guard hook, perm bench
- **Mistake:** in PowerShell, `$s = Invoke-RestMethod ...` overwrote `$S` (the scratch path): variables are case-insensitive, and the `--debug-file` went nowhere. -> Distinct names, never case variants.
- **Mistake:** edited `scripts/hooks/lis-guard.py` while the AH bench was calling it per tool use, so one run could mix versions. -> Freeze every file a running bench reads; park edits in the scratchpad and re-run after.
- **Better:** a hook `deny` whose reason says "not retryable; report it to the operator" ends the `-p` retry loop after one attempt (V13), where a bare ask-rule denial is retried to `--max-turns` (V7).
- **Better:** the debug log names every permission path: `classifier_request_started/finished ... outcome=`, `tool_dispatch_start ... permissionDecisionMs=` and `Hook ... returned permissionDecision:`; the bench reads them instead of guessing from the server log.

## 2026-10-25 - lis-guard audits R1 to R8, policy-text levers (merged)
- **Mistake:** a verb-list grammar (`uniq a OUT`, `tree -o`, `rg --pre`, `curl -D` all
  allowed), a 200 KB read cap followed by `allow`, broad allow prefixes sitting before
  the hook, then three curl grammars and a `$(...)` placeholder that all failed audit
  (word-split `-o F`, `${Y@P}`, brace-built `-{delete,delete}` deleting a scratch tree,
  `GIT_EXTERNAL_DIFF` through a deny-list env filter). -> Per-verb ARGUMENT allow-lists;
  a cap yields no decision; any `$`, backtick, brace, glob or `~` = no decision;
  `ENV_SAFE` allow-list; after 3 strikes remove the allow prefix, not a 4th grammar.
- **Mistake:** the local model reported counts it never computed and cited a stale
  script with `2>/dev/null` on probes. -> Every number is copied from a tool output;
  read a script before citing it; never silence stderr on a probe.
- **Avoid:** `powershell -Command "... $_ ..."` and unquoted `~` in `wsl -- ssh -i ~/..`
  through the Bash tool (bash expands both). -> Single-quote the payload, quote `'~/'`.

## 2026-11-04 - MTP A/B run (three arms, operator restarts)
- **Mistake:** `git push` piped to `tail` with its one-letter count flag was refused
  by the hook guard (read as skip-hooks). -> Bare counts beside `git`.
- **Avoid:** calling a 1-of-3 tally the A/B result when every miss was a thrash exit, a
  facts gate or a format line. -> Rule from the per-rep figures that move.
- **Mistake:** a brief compressed a fetch report into two false card facts; a grader was
  overruled from the rep's report (the rep had rewritten the fixture's contract
  comment); proof figures came from memory; a stub matched a record shape the brief
  described. -> Quote fetches verbatim; read the fixture and the diff first; "every
  rep" figures come from a script over `bench/results`; stubs copy real records.
- **Mistake:** new repo scripts shipped without `lis-guard_test.py`, whose deny table
  scans every repo script. -> Run the full CLAUDE.md test list before such a commit;
  never hex-escape a guarded literal to dodge the scan.

## 2026-11-05 — S-B3 per-run hook copies: glob coverage (audit C1 rounds 2-3)
- **Mistake:** modelled the stamp in `lis-hooks-<x>` as free text, so any `*`-led glob with 5 literals (`ls src/*.test.js`, `cat logs/*-error.log`) became a guard file and was denied; the corpus had deny rows only, no converse rows. -> A glob-to-name model gives its free slot the real alphabet (`[0-9-]` for a stamp or pid) and ships with converse rows plus a property oracle both ways (ordinary globs never deny; fnmatch-true globs always deny).
- **Better:** before building a new matcher, measure the simpler route against the old guard (here: mirroring the copies under `scripts\hooks\`); the measurement showed which rows each route misses.

## 2026-11-05 — S-O3 user scope off, S-B4 inline code and session-written files (c32)
- **Mistake:** the brief assumed a pre-existing file edited in-run keeps its birthtime; measured false (the Edit tool rewrites the file: new birthtime on NTFS and ReFS), and the first fold then stated "only an in-place write keeps the birthtime", while the auditor measured NTFS tunneling (delete and recreate within 15 s keeps the OLD birthtime). -> A file-time rule is proven by measuring the exact tool's write path and the volume's quirks before a doc states it; judge birth AND mtime.
- **Mistake:** the run-target rule stat'ed the file before the command ran, so `cp new.py f.py && python f.py` and every grouped form (`( )`, `{ }`, `if`, backticks, `bash -c --`) got no decision; found by the auditor, not the corpus. -> A rule over run targets judges the command's own writers and missing targets, and walks every grouping form the walker already handles for `$( )`.
- **Mistake:** the new property invariant checked only the converse (ordinary commands never deny), so disabling the rule kept 23531 cases green. -> Every new deny rule ships with a positive oracle (random instances must deny) and a converse one; mutation over the unit rows alone proves little.
- **Better:** when a settings scope is excluded, read what it carried (the debug log's "Adding N allow rule(s) to destination 'userSettings'") and name every bench whose inputs change; with user scope on, "no decision" means allow in a rep, and with it off, deny in a lean `-p` session.

## 2026-11-05 — Restart proofs, the harness's own warnings (c34)
- **Mistake:** the S-O3 live proof's debug log carried six `[WARN] [permissions]` lines (every `Write(path)` deny rule inert, the `git -C *` allow rules approving `-c`/`--exec-path`) and the proof was graded only on the figures it was run for; the warnings sat in a gitignored log for 18 hours. -> Every live proof gets a `[WARN]` grep of its debug log before the row is marked LANDED; the harness's own warnings are findings.
- **Better:** a row that "waits on the next start" is proven from the log lines the restart wrote (stop marker, pin check, hash-marker reuse, vram line, launch) and the endpoints with the new key, not from the first `/health` ok; the live stop-marker order differed from the stub's (serve.ps1 quotes it after the exit line while it holds the log) and the row now states the measured order.
- **Mistake:** the S-B8 rule read only tokens starting with `-` before the git subcommand, although the standing rule says a hook fails on any unquoted expansion; the auditor's `{-c,core.fsmonitor=...}` and `$'-c'` forms got no decision and bash ran them. -> Every new token-reading rule starts with the expansion clause (`$`, `{`, `[`, `*`, `?`, backtick before the judged position = deny) and its positive oracle includes expansion spellings.
- **Mistake:** the docs' exploit example (`-c core.pager='touch pwned' log -1` "ran its pager") was written from the harness's warning, not from a run; git skips the pager without a TTY, while `-c core.fsmonitor=<cmd> status` does run. -> An exploit example in a doc is executed once in a scratch repo before it is written; otherwise it is marked UNVERIFIED.
- **Better:** the third audit round hit the same class (expansion, re-quoted wsl payload, backslash-newline) and the 3-strike rule moved the fix off the tokenizer: the wildcard allow rules were removed (the hook already allows the benign forms, an undecided shape now meets no rule) and the hook judges the joined text as a second view. A rule that approves a prefix the hook cannot fully read is the hole; patching the reader is the 4th variation.
- **Mistake:** two live-proof folders were written under `bench/results/` on the belief that the directory is gitignored; only loose-file patterns were, so six files with user paths and session ids sat untracked in a public repo. -> `git check-ignore -v <new path>` right after creating anything under an "ignored" directory; a pattern list is not a directory ignore.
- **Mistake:** the trailing-star live-proof fold quoted the denial reasons as if `permission_denials` held them (it holds only the commands; the reasons were the model's reply) and wrote "before any rule" when the log shows no rule-evaluation step. -> Cite only fields the artifact holds (print them first); an ordering claim needs a log line that shows the order, else say the log does not show it.

## 2026-11-05 — G run folded (c38)
- **Mistake:** the test-list extraction regex (`^\s*python -I`) matched zero CLAUDE.md lines because the commands are backticked mid-line, and the loop was started before its command count was checked; it "completed" with no test run. -> Print the extracted command count and compare it with the list's length before the loop starts, never after.
- **Better:** the R-C2 bar (2 h of wall time) was unreachable by the fixture's 79-module cap; saying so before the run and asking for the ruling let the run count without rework. A bar that no allowed input can meet is a ruling to request, not a run to repeat.

## 2026-11-05/06 - web access in a container, lis-web port (c39, c40)
- **Mistake:** the helper server ran in the session's cwd (tsx read the work tree's
  `tsconfig.json`) and the Jarvis mount exposed private source. -> Pin paths, chdir
  away; list what each mount exposes, by owner; the fix was a port into `web/`.
- **Avoid:** counting a regex secret filter as a control; what the container mounts is.
- **Better:** prove `host.docker.internal:8080` from inside a container before planning
  host network changes; container runs take relative names for file flags.

## 2026-11-07 - keys imported, keyed proofs (c43)
- **Mistake:** tried `ls -la .env` to verify the import by key names; the classifier
  denies every `.env*` read, names included. -> Verify a secret file through the
  consumer's own output (the server's `keys present:` stderr line), never the file.
- **Mistake:** wrote "exa then jina" from the prompt's order; the call log had jina
  first (the model chose). -> Quote tool order from the call log, not the prompt.
- **Better:** two sessions, three search calls, judged from JSON `subtype`,
  `permission_denials`, the call log and the cleanup counts, never from the reply.

## 2026-11-07 - W-10 interactive run, first web read, closed window (c45, c46)
- **Better:** an interactive run with no `-p` JSON is judged from the per-run home
  (`.claude.json` counts, the MCP log, the absent transcript).
- **Mistake:** "nothing from your profile" read as network-silent; a fresh home fetched
  a 14.7 MB plugin marketplace. -> List what the tool itself fetches first.
- **Avoid:** leaving a setup wizard's allow lines unread (`/auto-mode` wrote a blanket
  allow against an existing soft_deny).
- **Mistake:** briefed "five curl fetches" from memory (four ran, one denied); matched
  "closed after /exit" to the wrong run; called S-B2 closed by a `defaultMode` pin
  (Shift+Tab reached auto mode). -> Count from the transcript; pin the artifact to its
  run folder; a default is not a lock, test the runtime toggle.
- **Mistake:** the commit-message column check ran in the same command as the commit
  and six 73-75 column lines shipped. -> A check gates (`&&` on its exit code).

## 2026-11-08 - engine research, upgrade held, PR 30966, isolation assessment (c48)
- **Mistake:** `cd "$TMPDIR" 2>/dev/null || cd <scratch dir>` wrote a diff to whichever
  directory won; the next `sed` on the scratch path failed. -> One absolute scratch
  path per write, never a `cd` fallback chain.
- **Better:** a research report marks every figure M (card, date, source) or E, names
  the weaker arm of each comparison (the EXL3 blog's llama.cpp side ran Q3_K_M with a
  separate draft, slower than this repo), computes the bandwidth ceiling before any
  install, and states an upgrade's gain class first (fixes vs speed): told "fixes, no
  IQ3_XXS decode gain", the operator HELD b12198 in one line.
- **Avoid:** rating a boundary by its documented residuals alone; walk the host-side
  surfaces too (every loopback port behind `host.docker.internal`, a real work dir).

## 2026-11-08 - HF model survey, four files deleted, fallbacks verified (c49)
- **Better:** a header-only read of each GGUF tensor table (no model loaded) exposed
  what no card states: eight 1-bit tensors in the on-disk ISTA IQ3_XXS, none in the
  default. Read the tensor table before ranking a file or blaming its weights.
- **Mistake:** the aggregating script grouped tensors by a kind allow-list and dropped
  `attn_k`/`attn_v`, so its summary could not show the claim it was meant to check.
  -> Verify a derived claim with a per-item listing, never a second aggregate.
- **Better:** delete with the consumers in mind: manifest pruned, `-VerifyModels` 4 of
  4, tests green, doc rows keep their figures with "deleted <date>" in the file cell.

## 2026-11-08 - model test 1 on the ISTA file, 16 ladder reps, bench (c51, c52)
- **Mistake:** the "past 64K" rung was launched at the ladder's 81920 budget, which caps
  the window at 65,536 (the rep peaked at 49,092); a side note caught it, and the
  48-module rep at 131,072 did pass 64K. -> Prove a context axis from the transcript's
  peak prompt tokens, never from the budget figure.
- **Mistake:** a monitor filter on `relaunch` matched the wrapper banner on every poll,
  and the first bench run went to `tail` with no saved log (standing rule 7). -> Test a
  filter on the quiet state before arming it; `tee` every bench run, cite the logged one.
- **Mistake:** one rep 6 percent past 64K for 15 short requests was reported as the
  past-64K result; a side note called it thin, and the next reps reached 93K and 102K.
  -> State a context axis as the token range covered and the requests past the line.
