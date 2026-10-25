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
