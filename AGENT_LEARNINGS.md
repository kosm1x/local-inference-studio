# Agent learnings - local-inference-studio
## Standing rules
- Before push: a scoped qa-auditor pass on every built commit (warnings become a follow-up
  commit, never a silent amend); every added line passes the identity grep; every brief
  states the exact trailer (10-24: a wrong trailer and a WSL username shipped publicly).
- Git: messages go through a file (`git commit -F <abs path>`), never a PowerShell
  here-string to `-F -` or a `git log --format=%B` round trip (newlines lost); stamp
  commits from `git log`; `date` before any timestamp (memory files too). The hook guard
  reads any `-n` or one-letter count flag in a git command as skip-hooks: bare counts or
  awk ranges (11-04 `tail`, 11-09 `sed -n`).
- Quoting: PowerShell expands bare `~` before `wsl` (use `bash -c`); bash expands `$_`/`~`
  in `powershell -Command "..."` (single-quote it); `Start-Process serve.ps1` takes ONE
  string arg, `-ExtraArgLine "-lv 4"` inside (an array gives `--port 4`). Backslash/quote
  text uses Write/Edit, no heredoc or `python -c` (6x, 10-24 to 11-09).
- Tee every `bench/run.ps1` run to `bench/results/<stamp>-<label>.log`, cite it (no log =
  UNVERIFIED; a cold server's warm-up is no sample) and freeze its inputs (10-25
  lis-guard.py edit; 11-09 server swap: it benches whatever answers on 8080). GPU work is
  single-tenant: check `nvidia-smi` and port 8081 before `stop.ps1`; restore the task.
- A fit budget is serve.ps1's `vram free` start line (13.5 to 14.2 GB; the desktop holds
  1.3 to 2.0 GiB) minus `--fit on`'s 1,024 MiB, never a card's or vendor's 16 GB or 17.18
  GB; judge a fit by a decode probe and private RAM, not by loading (11-09 Gemma).
- Scripted doc edits detect `\r\n` per file before matching, apply every edit before any
  `git add` and check the diff stat against the file list (10-24: 1 of 4 shipped).
- A brief's model claim (MTP head, template, fit) is read from `config/models.md` or the
  GGUF header before dispatch and re-verified on arrival; a binary a brief forbids is
  forbidden in version probes too (version from the real-run path only, 10-26).
- Hooks: an allow prefix the hook cannot fully read is the hole (file-valued commands via
  its recogniser only; 3 failed grammars = remove the prefix; 10-25, 11-05); no decision
  on a segment with an expansion (`$`, backtick, unquoted `{}*?[]~`), the first check of
  any arg-reading rule; verbs, arguments, env-prefix filter = allow-lists.
- Test before arming: a deny rule ships with a positive oracle (random instances and
  expansion spellings must deny) and a converse one, not unit-row mutation alone (11-05
  x2); a loop, monitor or grep selector runs on a known state (c38; c51; 11-10).
- Grade a run from its artefacts on a fixed checklist (JSON `subtype`,
  `permission_denials`, call log, per-run home; end from docker `kill`/`die` and
  `history.jsonl`), never the reply (11-04), server health or memory; rank on one fixture.
  Rule A/Bs on scripted per-rep figures that move, per rung (flag `axis_exercised` false),
  never pooled (11-04 1-of-3, c51); `claude_version`/`bar_v` change = new series.
- Diagnose from the transcript before a fix: a context axis from peak prompt tokens, with
  range + requests past it (c51); a loop from per-turn hashes (same tool, input, output
  tokens = attractor; 11-09); a hook event by where it fails (in a turn = Pre/PostToolUse,
  between turns = Stop), the brief quoting the reference's firing condition (11-10).
- A local-model prompt names a mechanical route for what it must generate or check, plus a
  stop condition and fallback: its attractor is to copy or re-explain (11-09, 11-10).
- Every figure, count, tool order or quoted string in a doc or brief is copied from a
  named artifact in its order, after reading the field's definition (c34
  `permission_denials` holds commands; c51 `lines_removed` = git diff count). A behaviour,
  order, timing or mechanism claim is measured first and names its log line or read-back,
  else UNVERIFIED (c32; c34 pager; c45 14.7 MB fetch; 11-09; 11-10).
- A change re-runs every CLAUDE.md test that reads a file it touches, docs-only or not:
  lis-guard_test scans every repo script (11-04), install_verify_test checks the manifest
  `default` against serve.ps1's `-Model` (11-08), lisweb_test pins ps1 docstrings (c73
  left HEAD failing until c74). Never hex-escape a guarded literal.
- Walk what a boundary trusts, not its residuals: the host (each loopback port behind
  `host.docker.internal`, a real work dir), each mount by owner (c39), the helpers an
  allow calls (W-19 `\@`), every lookup through a newly writable dir (11-10); scope an
  allow or deny to where its premise or threat holds (W-19 LIS_CONTAINER=1; 11-10).
## 2026-10-25 - PC recon runs 1 to 3 (65K+MTP+lean, then ruling 14 back to 131K)
- **Avoid:** auto-compact mid-task at 65,536 (made "J 135/4657" "mostly free"); facts go
  to a file; local auto mode costs ~240 of 330 GPU s. One cause for 3 failed queries
  (timeout, `$_`, `-f` behind `2>/dev/null`): read each; size = `preTokens` (39,098).
## 2026-10-25 - Ruling 15 build: rule set A, lis-guard hook, perm bench
- **Mistake:** `$s` overwrote `$S` (PowerShell ignores case). A `deny` "not retryable;
  report it to the operator" ends the `-p` retry loop (asks retry to `--max-turns`).
## 2026-10-25 - lis-guard audits R1 to R8, policy-text levers (merged)
- **Mistake:** a 200 KB cap then `allow` (a cap = no decision); grammars beaten by `-o F`,
  `${Y@P}`, `-{delete,delete}`, `GIT_EXTERNAL_DIFF`; `2>/dev/null` on probes.
## 2026-11-04 - MTP A/B run (three arms, operator restarts)
- **Mistake:** a grader overruled from the report; a stub from the brief, not real data.
## 2026-11-05 - S-B3 per-run hook copies: glob coverage (audit C1 rounds 2-3)
- **Mistake:** the `lis-hooks-<x>` stamp as free text denied `ls src/*.test.js` -> give a
  glob's free slot the real alphabet (`[0-9-]`); measure the simpler route first.
## 2026-11-05 - S-O3 user scope off, S-B4 inline code and session-written files (c32)
- **Mistake:** missed NTFS tunneling (recreate in 15 s keeps birthtime) and Edit rewrites;
  a run-target rule stat'ed before the command ran -> judge birth AND mtime, the command's
  writers, all groupings (`( )`, `{ }`, `bash -c`); read what an excluded settings scope
  carried ("Adding N allow rule(s) to destination 'userSettings'").
## 2026-11-05 - Restart proofs, the harness's own warnings (c34)
- **Mistake:** 6 `[WARN]` log lines sat 18 h -> grep `[WARN]` pre-LANDED; prove "next
  start" by restart logs, not `/health`; `check-ignore` new `bench/results` paths.
## 2026-11-05 - G run folded (c38)
- **Better:** a bar no allowed input meets (2 h vs a 79-module cap): ask the ruling first.
## 2026-11-05/06 - web access in a container, lis-web port (c39, c40)
- **Mistake:** the helper server read the work tree's `tsconfig.json` -> pin paths, chdir
  away; mounts are the control, not a regex secret filter; prove
  `host.docker.internal:8080` from a container first.
## 2026-11-07 - keys imported, keyed proofs (c43)
- **Mistake:** `ls -la .env` (`.env*` reads are denied). -> Check `keys present:` stderr.
## 2026-11-07 - W-10 interactive run, first web read, closed window (c45, c46)
- **Mistake:** a `defaultMode` pin called a lock (test Shift+Tab); an /exit matched to the
  wrong run (pin its folder); `/auto-mode` wrote a blanket allow against a soft_deny,
  unread; a column check beside the commit (gate: `&&`).
## 2026-11-08 - engine research, upgrade held, PR 30966, isolation assessment (c48)
- **Better:** one absolute scratch path per write, no `cd` fallback chain; a report marks
  each figure M (card, date, source) or E, names each comparison's weaker arm, computes
  the bandwidth ceiling first, states an upgrade's gain class (b12198: fixes = HELD).
## 2026-11-08 - HF model survey, four files deleted, fallbacks verified (c49)
- **Mistake:** a kind-allow-list aggregate dropped `attn_k`/`attn_v` -> verify per item;
  read a GGUF's tensor table before ranking or blaming a file (eight 1-bit tensors in the
  ISTA IQ3_XXS); delete for consumers (manifest, `-VerifyModels`, tests).
## 2026-11-08 - model test 1 on the ISTA file, 16 ladder reps, bench (c51-c60)
- **Mistake:** the "past 64K" rung ran at budget 81920 (window 65,536, peak 49,092); one
  rep 6% past 64K for 15 requests was the result; a restart line omitted the stay-open
  console; sleep 15 s between reps (`run.ps1` refuses <10 s after a log change).
- **Better:** the fixture key derives from the server identity (`rep_key_inputs`,
  `fixture_sha256`); a default switch keeps a named fallback with its own measured rules
  (c60: `$fallbackModel`, q4_0 KV and MTP at 65536).
## 2026-11-08 - default switch to the ISTA GSQ-RCO file (ruling (c))
- **Mistake:** the advice never said the ISTA file is STOCK, the default abliterated ->
  list every property the candidate lacks; never copy a chat's option letter.
## 2026-11-09 - icon proof, W-17, Gemma trial, trims, shortcut window (c64-c71)
- **Better:** a server-starting launcher runs AFTER every refusal, BEFORE any per-start
  secret read (serve.ps1 rewrites the key); a static call-order test pins it, no server.
- **Avoid:** blaming an agent for a stopped server (PSReadLine history, last line
  `stop.ps1` 00:43:35, showed the operator's console): check timestamps first, then ask.
- **Better:** a serve.ps1 trial clears the stop marker, so the watchdog relaunches the
  default ~3 min later (logs/watchdog.log: three failed 60 s polls); check /props.
- **Better:** `wt.exe` reuses an open Terminal (`-w new`: own window); see the parent PID.
- **Mistake:** wrote "the shortcut carries the switch" before the .lnk was edited; told
  the user lis-guard runs from the repo mount (S-B3 copies hooks at launch; open sessions
  keep the old one) -> claim an operator artifact after a timestamped read-back, a load
  path from the launcher docstring.
- **Better:** W-18's proof = two `-p` runs from an empty work dir: a `--continue` run that
  reports the first run's session id and answers from its turn proves mount, resume and
  append; `-p` leaves `history.jsonl` empty (UNVERIFIED).
- **Mistake:** asked the 27B model to invent 10 legal chess positions: it copied the two
  FENs 17 times (14 byte-identical Writes) past a compaction and 2 prompts; a random-play
  + eval-gap route landed first try. W-20: identical mutations no longer exempt.
## 2026-11-10 - web-session loop guards and the container profile (W-21 to W-24)
- **Mistake:** W-22 was briefed as a Stop hook; both loops ran inside one turn (text +
  tool_use rows, one ended by a user interrupt), so Stop would fire late or never.
- **Mistake:** a fix-round brief pinned "drop the url query string" and "treat
  `?page=2..5` as distinct pages" -> run the pins against each rule before sending: a pin
  is a test case; two that cannot both pass = a design bug.
- **Better:** a health-curl line carries a fallback (fails twice -> start the server in
  the background, report); a harness rule's first audit replays the incident transcript.
- **Mistake:** an env listing on `$1 ~ /LIS_/` printed a key value -> print names only; a
  ` 0BB8 ` grep of /proc/net/tcp missed the serving port (it follows a colon) -> `:0BB8 `.
- **Mistake:** said "only exit-2 stderr reaches the model" unread (both hooks deny via
  hookSpecificOutput JSON) -> read how each hook emits its decision first.
- **Mistake** (auditor's catch): model install dirs first on PATH + guard hooks run as
  bare `python` = fail-open via a model-installed `python` -> re-check each lookup through
  a writable dir (PATH, module paths, hook configs); pin interpreters by absolute path.
- **Avoid:** granting a capability without its launch flags (`--tmpfs /tmp` is noexec by
  default: "run tools from /tmp" was dead on arrival) -> probe `/proc/mounts`.
- **Better:** a ruling under the operator's broader directive (read-before-run for
  downloads) is credited to the session; a new deny scanning key names runs only in the
  container (the host scan broke the operator's test runs by file name).
- **Mistake** (auditor's catch, in three hooks): a temp state dir pruned by mtime with no
  link check = a deletion primitive via a planted junction -> lstat the dir, prune only
  state-shaped names, pin a junction row; sweep every hook that deletes anything.
- **Mistake:** a paste line for a resumed session told it to install llama-server, the
  opposite of the operator's last prompt there -> read the session's last real prompt
  (the `last-prompt` row) before writing a paste line.
- **Avoid:** a settings deny (`Bash(curl * -d*)`) is final: a hook allow never reaches it
  -> read `toolDenialKind` in the transcript (permission-rule vs hook vs automode).
- **Better:** live proof of a hook = a monitor on the run transcript for hook reasons,
  then replay each decision through the run's own hook copy (`docker exec -i`).
- **Mistake (W-25 build):** a path-literal check that resolves the operand and finds
  nothing judges nothing: git pathspec magic (`:/`, `:!x`) passed the top, walk and
  critical-path checks -> an operand grammar needs an explicit reject for every prefix
  the tool itself interprets (`:` for git, `-` for options, `~`).
- **Better:** the differential audit (old hook vs new hook over ~200 adversarial shapes,
  host and container, three cwds) found the only real gap; the mutant table found two
  unpinned branches. Keep both as the standing audit shape for guard changes.
