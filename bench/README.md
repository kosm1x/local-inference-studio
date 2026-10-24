# bench

Phase 3 measures, per model and quant on this machine: decode speed (tok/s),
prefill time for a 20K-token prompt, tool-call success over 20 fixed
`/v1/messages` prompts, peak VRAM, and whether the target context fits without
spilling into shared memory. Each run writes one JSON file to `bench/results/`
(gitignored) with the fields `model`, `quant`, `ctx`, `ngl`, `n_cpu_moe`,
`decode_tps`, `prefill_ms_20k`, `toolcall_pass`, `toolcall_total`,
`vram_mb_peak`, `date` (ISO 8601).
