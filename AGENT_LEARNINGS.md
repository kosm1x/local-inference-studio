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
