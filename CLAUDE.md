# CLAUDE.md — local-inference-studio

Constraints for agents working in this repo:

- No Ollama, no LM Studio. Backend of record is llama.cpp `llama-server` (native Windows).
- Never build llama.cpp from source here: there is no toolchain (no nvcc, cmake, cargo). Use the prebuilt release zips via `scripts/install.ps1`.
- Never commit binaries or models (`bin/`, `models/`, `*.gguf`, `*.zip` are gitignored).
- Scripts never pipe to a shell (`irm | iex`, `curl | bash`).
- Mark any claim not verified on this machine as UNVERIFIED.
- Scripts are PowerShell 7 (`#Requires -Version 7.0`); Git Bash only for POSIX helpers.
- Bench results are JSON under `bench/results/` (gitignored); schema in `bench/README.md`.
- Tests, run from the repo root exactly as written:
  `python -I scripts/hooks/tests/lis-guard_test.py`,
  `python -I scripts/tests/verify-doc_test.py` and
  `node --test bench/loop/fixture/test/text.test.js` (3 fail by design).
