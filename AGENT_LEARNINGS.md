# Agent learnings - local-inference-studio

## Standing rules
- Every built commit gets a scoped qa-auditor pass before push; warnings become a
  follow-up commit, never a silent amend.
- Commit messages go through a file (`git commit -F <abs path>`), never a PowerShell
  here-string piped to `-F -` or a `git log --format=%B` round trip (newlines lost).
- PowerShell expands a bare `~` before `wsl` sees it (wrap payloads in `bash -c`); via the
  Bash tool, bash expands `$_` and `~` in `powershell -Command "..."`: single-quote it.
- Tee every `bench/run.ps1` run to `bench/results/<stamp>-<label>.log` and cite the
  logged run (no log = UNVERIFIED); a cold server's warm-up request is not a sample.
- GPU work is single-tenant: check `nvidia-smi` compute apps and port 8081 before
  `stop.ps1`, and restore the Scheduled Task afterwards.
- A fit budget is serve.ps1's `vram free` start line (13.5 to 14.2 GB; the desktop holds
  1.3 to 2.0 GiB) minus `--fit on`'s 1,024 MiB, never a card's or vendor's 16 GB or
  17.18 GB; judge a fit by a decode probe and private RAM, not by loading (11-09 Gemma).
- `Start-Process serve.ps1` takes ONE argument string with `-ExtraArgLine "-lv 4"` quoted
  inside (an array gives `--port 4`); read the server log's first line before trusting it.
- Scripted doc edits detect `\r\n` per file before matching, apply every edit before
  any `git add` and check the diff stat against the file list (10-24: 1 of 4 shipped).
- A brief's model claim (MTP head, template, fit) is read from `config/models.md` or the
  GGUF header before dispatch, and the subagent verifies it again on arrival.
- Scripts and text with backslashes or quotes go through Write/Edit, never a heredoc or
  `python -c` (`\\` collapses, quoting breaks; 10-24 x2, 10-25, 11-08 x2, 11-09).
- An allow prefix the hook cannot fully read is the hole: allow file-valued commands via
  the hook's recogniser only; after 3 failed grammars remove the prefix (10-25, 11-05).
- No hook decision on any segment with an expansion (`$`, backtick, unquoted `{}*?[]~`);
  new arg-reading rules start with it; verbs, arguments, env-prefix filter = allow-lists.
- A new deny rule ships with a positive oracle (random instances, expansion spellings
  too, must deny) and a converse one; unit-row mutation alone proves little (11-05 x2).
- Grade a run from its artefacts against a fixed fact checklist (JSON `subtype`,
  `permission_denials`, call log, per-run home; its end from docker `kill`/`die` and
  `history.jsonl`), never the reply, server health or recollection; rank on one fixture.
- Every figure, count, tool order or quoted string in a doc or brief is copied from a
  named artifact in its order, after reading what the field holds and how it is defined;
  never from memory. A behaviour claim is measured first, else marked UNVERIFIED.
- Every added line passes the identity grep before commit and every brief states the
  exact commit trailer (10-24: a wrong trailer and a WSL username shipped publicly).
- A brief that forbids a binary forbids it in version probes too; record its version
  from the real-run path only (10-26).
- Run `date` before any timestamp (memory files too); stamp commits from `git log`.
- The hook guard refuses any `-n` or one-letter count flag in a command that runs git
  (read as skip-hooks): use bare counts or awk ranges (11-04 `tail`, 11-09 `sed -n`).
- Before arming a loop or monitor, test its selector on a known state: compare the
  extracted count with the list (c38: no test ran), run a filter on a quiet log (c51).

## 2026-10-25 - PC recon runs 1 to 3 (65K+MTP+lean, then ruling 14 back to 131K)
- **Avoid:** auto-compact mid-task on 65,536 (the summary made "J 135/4657" "mostly
  free"). -> Report tasks write facts to a file; local auto mode costs ~240 of 330 GPU s.
- **Mistake:** one cause for 3 failed queries (timeout, bash `$_`, `-f` precedence behind
  `2>/dev/null`); size off the monitor. -> Read each result; use `preTokens` (39,098).
## 2026-10-25 - Ruling 15 build: rule set A, lis-guard hook, perm bench
- **Mistake:** PowerShell `$s` overwrote `$S` (case-insensitive) -> distinct names; edited
  lis-guard.py mid-bench -> freeze every file a running bench reads.
- **Better:** a `deny` saying "not retryable; report it to the operator" ends the `-p`
  retry loop (ask denials retry to `--max-turns`); the debug log names each path.
## 2026-10-25 - lis-guard audits R1 to R8, policy-text levers (merged)
- **Mistake:** a 200 KB read cap followed by `allow`; grammars beaten by word-split
  `-o F`, `${Y@P}`, `-{delete,delete}`, `GIT_EXTERNAL_DIFF`. -> A cap yields no decision.
- **Mistake:** a stale script cited, `2>/dev/null` on probes. -> Never silence stderr.
## 2026-11-04 - MTP A/B run (three arms, operator restarts)
- **Avoid:** a 1-of-3 tally as the A/B result when every miss was a thrash exit, facts
  gate or format line. -> Rule from the per-rep figures that move.
- **Mistake:** a grader overruled from the rep's report; a stub built from the brief. ->
  Read fixture and diff; stubs copy real records; per-rep figures come from a script.
- **Mistake:** new scripts shipped without `lis-guard_test.py` (it scans every repo
  script). -> Run the full CLAUDE.md test list; never hex-escape a guarded literal.
## 2026-11-05 - S-B3 per-run hook copies: glob coverage (audit C1 rounds 2-3)
- **Mistake:** the `lis-hooks-<x>` stamp modelled as free text denied `ls src/*.test.js`.
  -> Give a glob model's free slot the real alphabet (`[0-9-]`).
- **Better:** measure the simpler route (mirrored copies) against the old guard first.
## 2026-11-05 - S-O3 user scope off, S-B4 inline code and session-written files (c32)
- **Mistake:** assumed an edit keeps birthtime (Edit rewrites), missed NTFS tunneling
  (recreate in 15 s keeps it). -> Measure the tool's write path; judge birth AND mtime.
- **Mistake:** the run-target rule stat'ed before the command ran. -> Judge the command's
  own writers and missing targets; walk every grouping form (`( )`, `{ }`, `bash -c`).
- **Better:** for an excluded settings scope, read what it carried ("Adding N allow
  rule(s) to destination 'userSettings'") and name every bench whose inputs change;
  with user scope on a no-decision is allow in a rep, off it is deny in a lean `-p` run.
## 2026-11-05 - Restart proofs, the harness's own warnings (c34)
- **Mistake:** six `[WARN] [permissions]` lines sat in a proof's debug log for 18 h. ->
  `[WARN]` grep every live proof's debug log before LANDED.
- **Better:** prove a "next start" row from the restart's log lines (stop marker, pin,
  hash reuse, vram, launch), not the first `/health` ok; state the measured order.
- **Mistake:** a `core.pager` exploit written from a warning (no pager without a TTY);
  `bench/results/` subfolders assumed ignored. -> Run it in a scratch repo first; run
  `git check-ignore -v <new path>` right after creating anything there.
- **Mistake:** denial reasons quoted from `permission_denials` (it holds commands); an
  order claimed with no log line. -> Print fields first; no log line, no order claim.
## 2026-11-05 - G run folded (c38)
- **Better:** a bar no allowed input meets (2 h vs a 79-module cap): ask the ruling first.
## 2026-11-05/06 - web access in a container, lis-web port (c39, c40)
- **Mistake:** the helper server read the work tree's `tsconfig.json`; the Jarvis mount
  exposed private source. -> Pin paths, chdir away; list each mount's exposure by owner.
- **Better:** a regex secret filter is no control, the mounts are; prove
  `host.docker.internal:8080` from a container first; file flags take relative names.
## 2026-11-07 - keys imported, keyed proofs (c43)
- **Mistake:** `ls -la .env` (`.env*` reads are denied). -> Check `keys present:` stderr.
## 2026-11-07 - W-10 interactive run, first web read, closed window (c45, c46)
- **Mistake:** "nothing from your profile" read as network-silent (a fresh home fetched
  14.7 MB) -> list what the tool fetches; a `defaultMode` pin called a lock -> test the
  runtime toggle (Shift+Tab); an /exit matched to the wrong run -> pin to its folder.
- **Avoid:** a setup wizard's allow lines left unread (`/auto-mode` wrote a blanket
  allow against a soft_deny); a column check beside the commit -> gate it with `&&`.
## 2026-11-08 - engine research, upgrade held, PR 30966, isolation assessment (c48)
- **Mistake:** a `cd "$TMPDIR" || cd <scratch dir>` chain wrote a diff wherever it landed.
  -> One absolute scratch path per write, never a `cd` fallback chain.
- **Better:** a research report marks each figure M (card, date, source) or E, names
  each comparison's weaker arm (EXL3 blog: Q3_K_M plus a separate draft), computes the
  bandwidth ceiling first, states an upgrade's gain class (b12198: fixes, so HELD).
- **Avoid:** rating a boundary by its documented residuals alone; walk the host side
  (every loopback port behind `host.docker.internal`, a real work dir).
## 2026-11-08 - HF model survey, four files deleted, fallbacks verified (c49)
- **Better:** read a GGUF's tensor table (header only) before ranking a file or blaming
  its weights: it showed eight 1-bit tensors in the ISTA IQ3_XXS, none in the default.
- **Mistake:** an aggregate grouped by a kind allow-list dropped `attn_k`/`attn_v`. ->
  Verify a derived claim with a per-item listing, never a second aggregate.
- **Better:** delete for consumers: manifest, `-VerifyModels`, tests, "deleted <date>".
## 2026-11-08 - model test 1 on the ISTA file, 16 ladder reps, bench (c51-c60)
- **Mistake:** the "past 64K" rung ran at the 81920 budget (window 65,536, peak 49,092);
  one rep 6 percent past 64K for 15 requests was called the result. -> Prove a context
  axis from transcript peak prompt tokens; state the range and the requests past it.
- **Mistake:** a restart line omitted that its console window must stay open (closed
  twice). -> Name it; no `llama-server exited` line = the wrapper was killed, no crash.
- **Avoid:** back-to-back reps on a task-started server: `run.ps1` refuses when the
  server log changed in the last 10 s. Sleep 15 s between reps.
- **Mistake:** `lines_removed` 96/89 cited as facts rewrites (it is the git diff count;
  the trust line prints `facts_retracted` under that label); a "whole-file Write" claimed
  (one Write, one Edit). -> Read the grader's definition; check the transcript's calls.
- **Better:** the fixture key derives from the server identity; check `rep_key_inputs`
  in run.ps1 and `fixture_sha256` before calling a cross-model comparison unfair.
- **Mistake:** a strict-survival tally mixed rungs; series across client and grader
  versions compared as like-for-like. -> Tally per rung (say if `axis_exercised` is
  false); read `claude_version` and `bar_v` in every .meta.json; old baselines = history.
- **Better:** a default switch keeps the predecessor as a named fallback with its own
  measured rules (c60: `$fallbackModel` in serve.ps1, q4_0 KV and MTP at 65536).
## 2026-11-08 - default switch to the ISTA GSQ-RCO file (ruling (c))
- **Better:** run `install_verify_test.py` after any default change (it cross-checks the
  manifest `default` flag against the serve.ps1 `-Model` default).
- **Mistake:** the recommendation never said the ISTA file is STOCK, the ruled default
  abliterated; the operator reverted the same day. -> List every property the candidate
  lacks first; never copy a chat's option letter into a doc whose letters differ.
## 2026-11-09 - icon proof, W-17, Gemma trial, trims, shortcut window (c64-c71)
- **Better:** a server-starting launcher runs AFTER every refusal, BEFORE any per-start
  secret read (serve.ps1 rewrites the key); a static call-order test pins it, no server.
- **Avoid:** blaming an agent for a stopped server: PSReadLine history (last line
  `stop.ps1`, 00:43:35) showed the operator's console. Check timestamps first, then ask.
- **Avoid:** a bench left across a server swap benches whatever answers on 8080: stop it.
- **Better:** a serve.ps1 trial clears the stop marker, so the watchdog relaunches the
  default ~3 min after the window (three failed 60 s polls; logs/watchdog.log is the
  proof, not LastRunTime). Verify the model path from /props after every swap.
- **Mistake:** wrote "relaunches within seconds" from one sighting; the log said three
  minutes. -> A timing claim names the log line that measures it, or says UNVERIFIED.
- **Better:** `wt.exe` opens a tab in whichever Windows Terminal window is already
  open, so a shortcut session can land beside another and look like a different
  terminal; `-w new` gives it its own window. Read the process parent before guessing.
