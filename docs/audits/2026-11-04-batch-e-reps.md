# Batch E reps: the facts file back in context after compaction

- Date: 2026-11-04
- Base: HEAD `3cad430` plus the uncommitted batch E change
  (`scripts/hooks/facts-inject.py`, the `longrun` profile of `scripts/claude-local.ps1`,
  the `facts_context_after` and `facts_injected_after` fields of
  `bench/ladder/longrun.py`)
- Ledger row: T-9 ([ledger](2026-10-30-ledger.md))
- Case: `long-fix` at `-ContextTokens 65536` (the budget that compacts; the default
  131072 budget compacts 0 times on this fixture), the default file, reasoning off, no
  other session on the server, reps one at a time

## What the two reps show

| rep | turns | wall s | exit | tests after | compactions | context after boundary | restore after boundary | injected (log) | bar |
|---|---|---|---|---|---|---|---|---|---|
| 192930 | 96 | 1223.0 | 0 | 72 of 72 | 5 | 5 of 5 (scratch regrade) | true at 5 of 5 | void, see below | `false: record_intact` |
| 200016 | 77 | 1193.4 | 1 (thrash) | 66 of 72 | 5 | 5 of 5 | true at 1 of 5 (the last) | yes at 5 of 5 | `false: claim_agrees, compaction_ok, record_intact` |

Fields per boundary, in order, for rep 200016: `facts_restored_after` false, false,
false, false, true; `facts_context_after` true at all five; `facts_injected_after` true
at all five; `facts_read_after` (a Read of the file) false at all five (the strict Read
was true at 4 of the 80 boundaries in the 15 older sets). The hook's context is the
only thing that brought the facts file back at the first four boundaries of that rep,
which is the case T-9 was opened for (the facts file read first after compaction in
0 of 50 boundaries). `facts_read_after_boundary_any` is true at all five on both reps.

Rep 192930 ran while the hook was being changed (the log format gained `injected=`
mid-rep), so its on-disk `facts_injected_*` fields are void: three log lines are in the
old format and two in the new. Its transcript has the hook's `hook_additional_context`
attachment after all five boundaries (a scratch regrade under the final grader gives
`facts_context_after` 5 of 5); its on-disk grade predates that field. On that rep the
built-in restore was also true at all five boundaries, so `any` would have been true
without the hook; rep 200016 is the one that separates the two.

## The reps' own bars

Neither rep meets the long-fix bar, and the bar is not what T-9 measures. Rep 192930
fixed 48 of 48 failing tests in 96 turns and failed `record_intact` by rewriting the
`NEXT` line in place twice. Rep 200016 fixed 42 (modules m01 to m21; m22 to m24 still
fail) and ended with Claude Code's thrash exit (three compactions each refilling the
budget within three turns), which `compaction_ok` and `claim_agrees` record (the claim
is the thrash message, no STATUS line); it also rewrote a `NEXT` line in place once.
The thrash exit is the known shape of a 65536 run on this fixture: rep 154601
(2026-10-26, ROADMAP rung 2 series 2 rep 1) ended the same way, and by `duration_ms`
compaction took 57 % of the wall on 192930, 66 % on 200016 and 50 to 72 % over the
65536 sets on disk.

## Limits

- Two reps, one budget. The restore is false at some boundary in 11 of the 15 older
  long-fix sets with boundaries (20 of 80 boundaries), so the pattern is not specific
  to this rep.
- The log is report-only: lis-guard denies a Bash command that names it literally and
  the per-run settings deny Edit and Write of it, but a globbed or computed name still
  reaches it. The transcript check does not read the log.
- `facts_context_after` proves the attachment is in the transcript, not that the model
  used it; whether the facts file is honoured after compaction stays measured by
  `facts_survived` and `redo_after_compaction` (0 on both reps).
