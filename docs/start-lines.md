# Start lines: every way to launch a session, one by one

Written 2026-11-06 for the first hands-on pass over all launch shapes. Each entry gives
the line, the use case, what it does, pros, cons and the heads-ups. The authority for
each flag is the help text at the top of `scripts/claude-local.ps1` and
`scripts/serve.ps1` (`Get-Help` works on both); docs/SETUP.md step 8 and
docs/web-access.md hold the long form. Where this page and the help text disagree,
the help text wins and this page is stale.

Conventions:

- `<repo>` is the checkout of this repository. Every line is `pwsh -NoProfile -File
  <repo>\scripts\<name>.ps1 ...`; the entries below show only what follows the script.
- Run the line from the directory the session should work in. Nothing a session does
  can change the profile or the guards it started with; only the launch line decides.
- "UNVERIFIED" marks behaviour that is documented or designed but has not been seen in a
  live run on this machine.

## Server

### `serve.ps1`

- Use when: the server is down and you want it back before the next logon (after a
  `stop.ps1`, or a crash the watchdog did not catch). The scheduled task runs this line
  at logon, so it is rarely typed.
- What: starts llama-server on 127.0.0.1:8080 with the default model, writes a fresh
  per-start key to `logs/api-key`, holds a port mutex, checks the binary against the
  pins in `scripts/install.ps1` and (once per boot) the model file against
  `models/manifest.json`.
- Pros: the pinned start; every session line below assumes exactly this server.
- Cons: a second start refuses on the port while one is up; after a `stop.ps1` the
  server stays down until the next logon or `Start-ScheduledTask`: neither `serve.ps1`
  (which restarts crashes) nor the watchdog (which covers hangs and a dead `serve.ps1`)
  restarts after an operator stop.
- Heads-up: `-Web` only caps the server log at level 3, refusing the levels that may
  log request bodies (UNVERIFIED); the session half (`-LisWeb`, below) does not need
  it.

### `serve.ps1 -VerifyOnly`

- Use when: you updated the llama.cpp binaries or the model file and want to know the
  pins still match before the next start, or you suspect a corrupt download.
- What: runs the binary and model hash checks and exits (0 = pass). Starts nothing,
  takes no mutex, writes no key, appends nothing to the server log (it does write
  `logs/model-verify.json` when the model hash runs and matches).
- Pros: safe while the server runs.
- Cons: the model hash takes about 20 s cold when the per-boot marker is missing
  (measured on the 11.6 GB fallback; the default's time is UNVERIFIED).

### `stop.ps1`

- Use when: you need the GPU for something else, you are swapping models, or you want a
  clean restart.
- What: stops the listener on 8080 only if its process name is llama-server, writes a
  stop marker so `serve.ps1` does not restart it. Under the scheduled task the log
  then shows `llama-server exited -1` and `not restarting: [stop.ps1] stop requested`;
  the "stopped PID" line lands only when no `serve.ps1` holds the log (live
  2026-11-06, ledger R-W5).
- Cons: every open session loses its backend mid-turn.
- Heads-up: `-WhatIf` prints what it would stop. Operator-only: an agent session never
  runs it on its own.

## Without web access (host sessions)

All host lines deny WebFetch, WebSearch, Agent, Workflow and the PowerShell tool, run
`scripts/hooks/lis-guard.py` on every Bash command (critical writes denied),
`scripts/hooks/loop-guard.py` on every tool (the 4th identical call within the last 12
denied) and `scripts/verify-doc.py` after every Markdown write inside the working
directory. The hook copies live in a read-only per-run folder under the temp root and
stay there after exit. Your user-scope CLAUDE.md and `rules\` files load in every host
session; only the user settings file (allow/deny rules, hooks, env, plugins) is held
back unless `-LisFull` or `-LisUserScope` loads it.

### `claude-local.ps1` (no profile)

- Use when: a quick question or chore in a repo you own and trust, where you need
  neither a read-only guarantee nor verifier lines. The "just talk to the local model"
  line.
- What: the lean tool set (Bash, Read, Edit, Write, Glob, Grep, Skill), the model pins
  of your profile overridden to `local`, the per-run settings copy, the hooks above. No
  task policy, no verifier lines; the banner says "profile: none".
- Pros: closest to a plain Claude Code session.
- Cons: the model can edit anything the guards do not name.

### `claude-local.ps1 -LisTask review`

- Use when: an opinion, an audit, an explanation or a plan about a codebase, with the
  certainty that nothing changed: reviewing a pull, dissecting an unfamiliar or
  untrusted repo, "where is X handled".
- What: the review policy; Edit, Write and NotebookEdit removed from the tool list and
  denied by rule as well. The final answer is the deliverable.
- Pros: the safest profile for untrusted repos.
- Cons: the session cannot save a report file either; copy the answer out yourself.
- Heads-up: after exit the wrapper prints the verifier lines to run (`verify-doc.py`,
  `scripts/verify-claims.ps1`, `git status --porcelain` expecting no output).

### `claude-local.ps1 -LisTask edit`

- Use when: a bounded change in files you can name: fix this test, add this flag,
  rename this. The default working profile.
- What: the lean set plus the edit policy: change only the named files, run the tests
  before and after.
- Pros: hands-on work with the diff in front of you.
- Cons: the local model fabricates at times (it once reported a WebFetch title with no
  call made), so judge by the verifier lines and `git diff`, never by the reply.
- Heads-up: the guard files of this repo (among them the hooks, the wrapper itself,
  serve/stop/watchdog scripts, config, bin, `logs/api-key`, the exempted tests,
  `scripts/install.ps1`, `models/manifest.json`) are Edit-denied by absolute path in
  every profile.

### `claude-local.ps1 -LisTask longrun`

- Use when: an interactive session expected to outlive one context window, such as a
  refactor across many files, where test counts and figures must survive compaction.
- What: as edit, plus a facts file `lis-facts-<stamp>.md` in the working directory that
  the model appends verified figures to, and a SessionStart hook that puts that file
  back into context after every compaction (log `lis-facts-inject-<stamp>.log` in the
  temp root).
- Pros: compaction keeps the numbers.
- Cons: the facts file lands in the working tree, so `git status` is never clean until
  you delete it.
- Heads-up: the relaunch supervisor stays off without `-p`.

### `claude-local.ps1 -LisTask review -p "<prompt>"`

- Use when: a repeatable read-only check you can script: a nightly "summarize what
  changed", a grading pass over a repo, or a probe of the guards.
- What: the review profile, one prompt, exit when done.
- Pros: reproducible; with `--output-format json` the `permission_denials` field lists
  what the guards blocked.
- Cons: no steering mid-run.
- Heads-up: add `--output-format json --max-turns N --debug-file <path>`; judge from the
  JSON and the debug log, not from the prose.

### `claude-local.ps1 -LisTask edit -p "<prompt>"`

- Use when: a fire-and-forget fix with a clear done-check: "make the tests in this
  directory pass", "update the version in these three files".
- What: the edit profile in batch.
- Pros: unattended; the test command is the judge.
- Cons: a wrong fix lands in your tree before you see it; work on a branch.

### `claude-local.ps1 -LisTask longrun -LisRelaunchMax 1 -p "<prompt>"`

- Use when: an unattended multi-hour job: fix all failing modules, migrate a dataset,
  work through a checklist. The long-fix shape of the ladder.
- What: longrun in batch with the supervisor armed. A claude exit with rc != 0 starts
  one fresh `-p` session (never `--continue`); the facts file comes back through the
  SessionStart hook and the prompt tells it to run the test command and append a CHECK
  line before any edit. The default is 1 under longrun; 0 to 3 allowed; N > 0 needs
  longrun.
- Pros: designed to survive an autocompact thrash or a one-off crash. UNVERIFIED: no
  relaunched session has yet finished live (ledger R-W2 stays BUILT).
- Cons: a deterministic cause ends the relaunch the same way (the live relaunch died
  twice on a 1.5 MB CLAUDE.md); a session that ended on `max_turns` is not relaunched;
  a claude killed by .NET Process.Kill (rc -1) never is; a bench timeout kills the
  wrapper's whole tree, so no relaunch follows one.
- Heads-up: stdout passes through the wrapper line by line while armed; `--debug-file
  base.log` becomes `base.2.log` for the relaunch, but the `--debug-file=<path>` form is
  not rewritten and both sessions write one file.

### `claude-local.ps1 -LisFull`

- Use when: a built-in tool outside the lean seven, such as NotebookEdit for a notebook,
  or a comparison of the lean set against the full one.
- What: drops the tool list and the policy; keeps the strict empty MCP config and every
  deny rule.
- Pros: the only way to the full built-in tool set.
- Cons: refuses `-LisTask` (no profile, no verifier lines) and refuses `-LisWeb`, any
  `--mcp-config` and an allow of WebFetch, WebSearch or an MCP tool. It keeps user
  scope, so the allow rules of your user settings apply with no launcher rule over
  them (lis-guard still denies critical writes; ledger S-O3).
- Heads-up: Agent, Workflow and PowerShell remain denied here too.

### `-LisContextTokens 32768` (modifier)

- Use when: measuring a profile under frequent compaction, or faster turns on a huge
  repo when detail may be lost.
- What: lowers the autocompact window from the default 114688; the value is written
  into the per-run settings env as well.
- Cons: more compactions; pair with longrun if the figures matter.

### `-LisUserScope` (modifier)

- Use when: a task needs your user settings (allow/deny rules, hooks, env, plugins)
  inside the local session, in a repo you trust. Your CLAUDE.md and rules load
  without it.
- What: loads the user settings scope (off by default, ledger S-O3).
- Cons: user settings can set auto mode, so the switch is refused with `-LisWeb`, and it
  widens what the session sees of your profile.

### `-LisPrintArgs` (modifier, any line)

- Use when: trying any line for the first time, or finding out why a run behaved oddly.
- What: on the host prints the claude argument list and the per-run settings JSON, or
  under `-LisWeb` the docker argument list instead, and exits. The MCP config JSON
  prints only inside the container. Starts neither claude nor docker.

### `-LisNoMouse` (modifier, web lines only)

- Use when: the terminal's Ctrl+wheel font zoom is wanted during a web session.
  Observed 2026-11-10 in a `-LisWeb -LisTerminal` session: the zoom stopped once Claude
  Code had loaded, while Ctrl+Plus and Ctrl+Minus kept working.
- What: adds `-e CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` and then
  `-e CLAUDE_CODE_NO_FLICKER=0` to the docker line and `; classic renderer:
  CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1, CLAUDE_CODE_NO_FLICKER=0 (-LisNoMouse)` to
  the banner; nothing else. On 2026-11-11 a run with `CLAUDE_CODE_DISABLE_MOUSE=1`
  (the switch's first form; that name is no longer passed) did not restore the zoom.
  A read of the Claude Code 2.1.318 binary shows its renderer gate taking either of
  the two names as fullscreen off (a fresh home, as every web run has, otherwise
  gets fullscreen). Live 2026-11-11: the operator ran a session with the switch and
  reported that Ctrl+wheel zoom works.
- Cons: Claude Code's fullscreen renderer (its own scrolling, flicker-free redraw) is
  off; scrolling is the terminal's scrollback.
- Refused without `-LisWeb` and inside the container. Off by default.

### `-LisWebAuto` (modifier, web lines only)

- Use when: an attended web session (`-LisWeb -LisTerminal`) where a prompt per call
  costs more than a classifier, and only after the operator's own test of it.
- What: pins `permissions.defaultMode` to `auto` instead of `default` and adds the
  banner line `auto mode: ON (-LisWebAuto; ledger S-B2 reopened by the operator)`;
  nothing else. Shift+Tab reaches auto mode in any web session regardless of the
  switch (observed 2026-11-07, ledger W-13), which is why every `-LisWeb` session now
  carries the `autoMode` rules of `config/automode-web.json` (allow and soft_deny led
  by `"$defaults"`, the launcher throws when either lacks it; the environment array is
  prose without it). Refused without `-LisWeb` and with `-p`, `--print` or
  `--output-format`; `--permission-mode auto` and `-LisUserScope` stay refused. Off by
  default; `-LisWebAuto:false` is the same as leaving it out. Its tests run in
  `scripts/tests/lisweb_test.py`, whose container half starts a throwaway
  `docker run --rm` container of the lis-web image.
- Cons: the classifier is the local uncensored model, the one running the session, so a
  page that talks the session into a command can talk its judge into allowing it. It
  costs GPU time; measured on the host 2026-10-25 (AGENT_LEARNINGS.md, 10-25 entry):
  "7 classifier requests took about 240 s of RUN 3's 330 s of GPU time (2.7x the work)".
- Heads-up: an operator decision that reopens ledger S-B2 (ledger W-13). The rule
  block is UNVERIFIED live until the operator's first web session that shows it in
  effect. A fresh
  per-run home may show an auto-mode opt-in prompt on first use (UNVERIFIED).

## With web access (the lis-web container)

Web sessions never start claude on the host: `-LisWeb` runs it inside `lis-web:2.1.318`
with your working directory read-write at /work, this repo read-only at /lis (its
`.env` hidden behind an empty read-only file), a fresh per-run home at /home/lis and
nothing from your profile. The web tools are this repo's own `lis-web` server (`web/`,
copied into the image at /opt/lis-web; operator ruling 2026-11-06), independent of the
Jarvis checkout. The session gets five tools (`mcp__lis-web__web_search`,
`exa_search`, `jina_search`, `web_read`, `web_read_tweet`) and a policy sentence that
web content is untrusted. WebFetch and WebSearch stay denied. Proven live on the
lis-web server 2026-11-06 23:40 (docs/web-access.md "Proof").

Shared warnings for every web line:

- Egress is open. A prompt-injected model can send anything readable inside the
  container to an attacker in one `web_read` call (ledger W-8). Readable means: your
  working directory, this repo minus `.env`, the per-run home and logs, and the four
  env values (the three key names and the server key), which
  `echo $NAME` prints (ledger W-9). Nothing else of yours is mounted.
- The search tools need BRAVE_SEARCH_API_KEY, EXA_API_KEY and JINA_API_KEY in
  `<repo>\.env` (gitignored; the operator copies the three `KEY=VALUE` lines in);
  all three proven live 2026-11-06 23:5x (ledger W-4); `web_read` is keyless and
  proven live; `web_read_tweet` is keyless too (UNVERIFIED live).
- The launcher refuses to start while any `.env*` file other than `.env` and
  `.env.example` sits at the repo root (`.env.local`, `.env.bak`): move it out.
- Stale env files: each launch first deletes, unread, any `lis-web-<stamp>-<pid>.env`
  in `%TEMP%` whose pid is gone (a window closed with the X leaves one, ledger W-16),
  runs `docker rm -f` on that exact name unless `docker inspect` says it is still
  running (then it is left), and prints one line per file.
- Status line: model and context percentage from `scripts/statusline.mjs`
  (`lis-web  <model> | ctx:<n>%`, then ` | left:<n>%` or ` | left:<n>k` when the
  remaining figure or window size is given; ledger W-15); absent before 2026-11-07.
- Pass `--debug-file` as a relative name (`debug.log`); a Windows path becomes one
  mangled file name inside the container.
- The working directory must be a path on a local drive outside (and not above) your
  profile and this repo; junctions, subst drives, UNC paths and
  paths holding a comma or a double quote are refused.
- Per-run logs land in `<repo>\logs\web-<stamp>\logs\` (the call log `web-calls.log`
  is one host-only line per call); the transcript is under `...\home\.claude\`.
- After any web session both of these should list nothing; if either lists something,
  `docker rm -f <id>` and delete the file:

```
docker ps -q --filter name=lis-web
Get-ChildItem $env:TEMP -Filter lis-web-*.env
```

### `web-image.ps1`

- Use when: before the first web session, and again after a Claude Code upgrade or a
  change under `web/`. `-Check` only reports whether the image exists.
- What: builds `lis-web:2.1.318` from `container/Dockerfile` with the repo root as the
  context (`.dockerignore` keeps `.git`, `bin`, `models`, `logs`, `bench/results`,
  `web/node_modules` and `.env` out): node:24-bookworm-slim by digest, PowerShell
  pinned, Claude Code 2.1.318 verified by sha512 before install, the lis-web server
  from `web/` with `npm ci --omit=dev` from `web/package-lock.json`. About 1.36 GB.
- Heads-up: no parameter names another checkout; the build reads only this repo.

### `claude-local.ps1 -LisWeb -LisTask review -p "<prompt>"`

- Use when: a scripted research question that needs the live web and no file changes:
  "read these three URLs and summarize", "what does this changelog say", a daily
  digest. The safest web shape, and the one for any untrusted site.
- What: the review profile inside the container, batch.
- Pros: no Edit or Write tool, and the policy forbids writes by other means (Bash
  stays; lis-guard denies only critical writes); what it can leak is what it can read.
- Cons: the search tools fail without the three keys in `<repo>\.env`.

### `claude-local.ps1 -LisWeb -LisTask edit -p "<prompt>"`

- Use when: a change that needs a fact from the web first: "read the upstream API doc
  and update our client to match".
- What: the edit profile inside the container, batch.
- Heads-up: run it in a scratch copy of the project. The working directory is the one
  thing of yours the container can both write and exfiltrate.

### `claude-local.ps1 -LisWeb -LisTask longrun -LisRelaunchMax 1 -p "<prompt>"`

- Use when: an unattended web-heavy job that may outlive one context window: crawling
  a documentation set into notes, checking many packages against their registries.
- What: longrun with the supervisor, inside the container. The facts file lands in the
  mounted working directory.
- Cons: the longest exposure window of all web lines; same scratch-copy rule.

### `claude-local.ps1 -LisWeb -LisTerminal -LisTask review`

- Use when: hands-on web research in conversation: you steer, it reads and searches,
  nothing is written. The 2026-11-07 run was the live proof for ledger W-10 (LANDED).
- What: docker gets `-it`; the per-run home is seeded so Claude Code skips onboarding.
  That seed is designed to skip the "Security notes" prompt-injection screen too,
  which is why the policy sentence carries the warning instead. The folder trust
  prompt is not seeded and may appear every run, because the home is fresh. Live
  2026-11-07 15:30 (ledger W-10 LANDED): the session came up on the seeded home,
  the lis-web server connected with all three keys, `/exit` left 0 containers and
  0 env files; `hasTrustDialogAccepted` appears only after the seed, so the trust
  prompt was answered in the run (inferred; the dialog itself is not logged). No
  prompt was sent. The first interactive tool call ran 2026-11-07 16:13 (web-access.md
  "Proof"; ledger W-13, W-14).
- Desktop shortcut (operator, 2026-11-07, works): target
  `%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe`, arguments `-w new -d <workdir> pwsh
  -NoProfile -File <repo>\scripts\claude-local.ps1 -LisWeb -LisTerminal -LisStartServer
  -LisKeepState -LisTask edit --permission-mode acceptEdits`, start in `<workdir>` (an
  empty directory outside the profile). `-w new` (added 2026-11-09 18:40) gives the
  session its own Windows Terminal window; without it `wt.exe` adds a tab to whichever
  Windows Terminal window is already open (the 18:35 launch landed as a tab beside
  another session, which looked like a different terminal). `-LisStartServer` starts
  the server's scheduled task when
  `/health` is not ok and waits up to 180 s for it (proven 2026-11-09 01:10 against a
  stopped server: started, served and answered in 21 s wall).
  `-LisKeepState` (added 2026-11-09 19:15, ledger W-18, proven 19:27 with two `-p`
  runs): the transcripts persist in `<repo>\logs\web-state\<key>\` (the work
  directory's leaf name plus 8 hex digits of its path's SHA-1), so `/resume` and
  `--continue` find earlier runs of the same work directory; the prompt-history
  file there is UNVERIFIED until the first interactive run.
  Windows Terminal gives the font size; a bare `pwsh.exe` target opens
  conhost, where auto mode stays off by design (S-B2) and `acceptEdits` passes
  through. The tab closes on `/exit`; closing with the X leaves the key file to the
  next launch's sweep (W-16).
- Heads-up: on start the fresh home auto-installs the official plugin marketplace
  (declared source `anthropics/claude-plugins-official`; the download host is
  UNVERIFIED: a `.gcs-sha` marker, no `.git`) into the run folder, 621 files and
  14.7 MB on 2026-11-07, with no prompt sent (ledger W-12). Claude itself fetches
  on a fresh home before the model does anything.
- Cons: needs a real console window. Refused when stdin or stdout is redirected, with
  `-p`, `--print`, `--output-format` or `-LisTask longrun`.
- Warning: Ctrl+C should reach claude as a keystroke and the wrapper should still
  force-remove the container (UNVERIFIED). Closing the window with the X ends the
  wrapper before cleanup (observed 2026-11-07, ledger W-16): docker events show
  SIGTERM to the container (its sender is inferred) and `--rm` removes it, but the env
  file (the server key and any web keys) stays in the temp root until the next web
  launch sweeps
  it. Run the two checks above afterwards.

### `claude-local.ps1 -LisWeb -LisTerminal -LisTask edit`

- Use when: interactive work on a scratch copy where web facts come in as you go, for
  example porting an example from a vendor's site.
- What: as the terminal review line, with the edit profile.
- Heads-up: the scratch-copy rule and the cleanup checks apply unchanged.
