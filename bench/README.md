# bench

Phase 3 measures, per model and quant on this machine: decode speed (tok/s),
prefill time for a 20K-token prompt, tool-call success over 20 fixed
`/v1/messages` prompts, peak VRAM, and whether the target context fits without
spilling into shared memory. Each run writes one JSON file to `bench/results/`
(gitignored).

## Usage

`bench/run.ps1` measures the server that is already running; it does not start or
stop one. Start the candidate with `scripts/serve.ps1` (or the logon task), then:

```powershell
pwsh bench/run.ps1 -Label qwen3.6-35b-a3b -Quant UD-IQ3_XXS -Ctx 131072 -NCpuMoe 0
```

Parameters: `-Port 8080`, `-ApiKey local`, `-Label` (required, model label),
`-Quant`, `-Ctx`, `-Ngl` (default `auto`), `-NCpuMoe` (these five are recorded as
given), `-ToolTrials 20`, `-PrefillTokens 20000`, `-OutDir bench/results`. It
prints one line per measurement, then a one-line summary with the result path.

Method:

- Decode: `/completion` with a fixed 200-token prompt, `n_predict` 256,
  `ignore_eos`, `cache_prompt` false; one warm-up request is sent and discarded
  (the first request after a server start decodes slower), then median of 3
  `timings.predicted_per_second`.
- Prefill: a deterministic English prompt (seeded word lists), tokenized with
  `/tokenize` and cut to exactly `-PrefillTokens` tokens, sent as a token array
  with `n_predict` 1, `cache_prompt` false; median of 3 `timings.prompt_ms` and
  `timings.prompt_per_second`. No warm-up request: `cache_prompt` false makes every
  run a cold prefill by design, and the decode warm-up has already run. Cached: the same prompt twice with `cache_prompt`
  true; the second request is recorded.
- Tool calls: `-ToolTrials` `/v1/messages` requests (`max_tokens` 4096) with two
  tools, `get_weather{city}` and `run_tests{path}`, rotating over 20 fixed user
  messages that each need exactly one of them. Pass = a `tool_use` block with the
  expected name and a non-empty required field.
- VRAM: `nvidia-smi` `memory.used` every 500 ms for the whole run; the maximum is
  whole-GPU usage, so other GPU processes count too.

## Result schema

| Field | Meaning |
| --- | --- |
| `model`, `quant`, `ctx`, `ngl`, `n_cpu_moe` | as given on the command line |
| `decode_tps` | median decode tok/s of the 3 measured runs (warm-up excluded) |
| `prefill_ms_20k`, `prefill_tps` | median cold prefill ms and tok/s for the prompt |
| `prefill_tokens` | prompt tokens the server evaluated (`timings.prompt_n`) |
| `prefill_ms_20k_cached` | prefill ms for the same prompt with `cache_prompt` true |
| `prefill_cached_tokens_eval` | tokens evaluated on that cached request |
| `toolcall_pass`, `toolcall_total` | passing requests / requests sent |
| `toolcall_wrong_tool`, `toolcall_no_call`, `toolcall_bad_args` | failure breakdown |
| `toolcall_errors` | requests that failed at HTTP level |
| `toolcall_latency_ms_median` | median wall time of the completed tool requests |
| `vram_mb_peak` | max whole-GPU `memory.used` (MiB) during the run |
| `server_build` | `/props` `build_info` |
| `flags` | command line of the process listening on `-Port` |
| `date` | ISO 8601 |
