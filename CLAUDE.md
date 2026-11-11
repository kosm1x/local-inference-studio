# CLAUDE.md — local-inference-studio

Constraints for agents working in this repo:

- No Ollama, no LM Studio. Backend of record is llama.cpp `llama-server` (native Windows).
- Never build llama.cpp from source here: there is no toolchain (no nvcc, cmake, cargo). Use the prebuilt release zips via `scripts/install.ps1`.
- Never commit binaries or models (`bin/`, `models/`, `*.gguf`, `*.zip` are gitignored).
- Scripts never pipe to a shell (`irm | iex`, `curl | bash`).
- Mark any claim not verified on this machine as UNVERIFIED.
- Scripts are PowerShell 7 (`#Requires -Version 7.0`); Git Bash only for POSIX helpers.
- `container/` holds the lis-web image's Dockerfile; `scripts/web-image.ps1` builds it
  (operator-run; `claude-local.ps1 -LisWeb` runs web sessions in it).
- Bench results are JSON under `bench/results/` (gitignored); schema in `bench/README.md`.
- `pwsh -NoProfile -File scripts/test-all.ps1` runs the fast suites below in one go
  (`-Full` adds the property and lisweb suites, `-Only <text>` filters by path).
- `python -I scripts/web-readout.py <run dir or .jsonl>` prints a web session's
  scorecard (tools, denials, hook reasons); `--grep <regex>` gives one verdict per call.
- Tests, run from the repo root exactly as written:
  `python -I scripts/hooks/tests/lis-guard_test.py`,
  `python -I scripts/hooks/tests/lis-guard_property_test.py`,
  `python -I scripts/hooks/tests/loop-guard_test.py`,
  `python -I scripts/hooks/tests/repeat-guard_test.py`,
  `python -I scripts/hooks/tests/facts-inject_test.py`,
  `python -I bench/ladder/tests/grade_test.py`,
  `python -I bench/ladder/tests/gen_longfix_test.py`,
  `python -I bench/ladder/tests/longrun_test.py`,
  `python -I bench/ladder/tests/gen_stalefig_test.py`,
  `python -I bench/ladder/tests/stalefig_test.py`,
  `python -I bench/ladder/tests/gen_blocked_test.py`,
  `python -I bench/ladder/tests/blocked_test.py`,
  `python -I bench/ladder/tests/gen_bait_test.py`,
  `python -I bench/ladder/tests/bait_test.py`,
  `python -I scripts/tests/verify-doc_test.py`,
  `python -I scripts/tests/verify_claims_report_test.py`,
  `python -I scripts/tests/web-readout_test.py`,
  `python -I scripts/tests/resilience_test.py`,
  `python -I scripts/tests/claude_settings_test.py`,
  `python -I scripts/tests/install_verify_test.py`,
  `python -I scripts/tests/lisweb_test.py` (its container half needs Docker and the
  lis-web image),
  `node --test web/test/*.test.mjs` (the lis-web MCP server; needs
  `npm ci --prefix web` once) and
  `node --test bench/loop/fixture/test/text.test.js` (3 fail by design).
