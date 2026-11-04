# Regrade: rungs 2 and 3 with the batch C trust checks

- Date: 2026-11-04
- Base: HEAD `5f799b3` plus the uncommitted batch C change to `bench/ladder/longrun.py`
  and `bench/ladder/grade.py`, and for rung 3 `bench/ladder/stalefig.py`
- Ledger rows: T-1, T-2, T-3, T-4, T-6 ([ledger](2026-10-30-ledger.md))

Batch C adds report-only trust checks to the long-fix grader. They are new fields in the
graded JSON and a `trust (report-only):` console line. They do not change `bar_met`,
`bar_reason`, `facts_gate`, `instruction_violations` or any other existing field. The
definitions are in the `longrun.py` docstring; the tests are in
`bench/ladder/tests/longrun_test.py` (`test_count_lines_unbacked`,
`test_cadence_runs_and_shell_redirect_writes`, `test_fixed_names_inexact_and_missing`,
`test_fixed_count_agrees_in_summary`, `test_exact_command_violations`). Rung 3 has the
same `exact_command_violations` field in `stalefig.py`, tested in
`bench/ladder/tests/stalefig_test.py` (`test_exact_command_violations`).

| Row | Field | What it counts |
|---|---|---|
| T-1 | `count_lines_unbacked` | BEFORE and CHECK lines (final or retracted) with no distinct earlier run that printed their pair |
| T-2 | `facts_retracted.count` (existing, reused) | lines held in an earlier facts state with no copy in the final file |
| T-2 | `cadence_runs` | `{done, asked}`: test runs of any form; 2 plus the modules in the prompt's run list |
| T-2 | `shell_redirect_writes` | Bash commands with a `>` or `>>` redirection into the facts file, by command |
| T-3 | `fixed_names_inexact`, `fixed_names_missing` | FIXED names not a manifest name; of those, none even with `mNN ` dropped |
| T-4 | `claim_fixed_count_agrees` (existing, reused) | `Fixed: N` equals the FIXED lines in the final facts file |
| T-6 | `exact_command_violations` | test runs whose command is not exactly the test command |

## Method

Each of the 17 long-fix sets and the 9 stale-figure sets under `bench/results/` was
copied to a scratch directory and graded there with
`python -I bench/ladder/grade.py <copy base>`. No file under `bench/results/` was
written. Each copy was graded twice, with the grader before and after the change, and
the two JSON files were compared key by key.

## Table

bar_met: the on-disk `.json`, then the regrade. Removed: `facts_retracted.count`. Fixed:
the claim's `Fixed:` value, the FIXED lines, and `claim_fixed_count_agrees`.

| stamp | bar_met disk / regrade | unbacked | removed | cadence done / asked | redirects | inexact / missing | Fixed: claim / lines / agrees | exact-cmd violations |
|---|---|---|---|---|---|---|---|---|
| 20261026-122359 | null / null | 0 | 0 | 3 / 8 | 2 | 0 / 0 | 48 / 48 / true | 0 |
| 20261026-132833 | null / true | 1 | 7 | 8 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261026-141312 | false / false | 1 | 6 | 7 / 8 | 0 | 0 / 0 | 48 / 47 / false | 0 |
| 20261026-143441 | false / false | 0 | 5 | 8 / 8 | 0 | 0 / 0 | 48 / 44 / false | 1 |
| 20261026-154601 | false / false | 0 | 0 | 4 / 8 | 0 | 0 / 0 | null / 24 / false | 0 |
| 20261026-162203 | null / null | 0 | 0 | 3 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261026-163439 | false / false | 5 | 0 | 2 / 8 | 0 | 48 / 0 | 48 / 48 / true | 0 |
| 20261026-175551 | true / true | 0 | 1 | 3 / 14 | 0 | 0 / 0 | 96 / 96 / true | 0 |
| 20261026-181610 | false / false | 0 | 10 | 9 / 14 | 0 | 6 / 6 | 96 / 96 / true | 0 |
| 20261026-183719 | false / false | 1 | 0 | 8 / 14 | 4 | 0 / 0 | 96 / 96 / true | 0 |
| 20261104-111707 | true / true | 0 | 3 | 7 / 8 | 0 | 0 / 0 | 48 / 48 / true | 1 |
| 20261104-113400 | false / false | 0 | 3 | 4 / 8 | 0 | 0 / 0 | null / 24 / false | 0 |
| 20261104-114741 | null / null | 0 | 6 | 8 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261104-151857 | false / false | 2 | 4 | 5 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261104-153814 | true / true | 0 | 3 | 5 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261104-155730 | false / false | 0 | 2 | 8 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |
| 20261104-163102 | null / null | 0 | 2 | 3 / 8 | 0 | 0 / 0 | 48 / 48 / true | 0 |

Unbacked lines: 132833 and 141312 `BEFORE pass 0 fail 0`; 163439 five `CHECK pass 72 fail
0`; 183719 `CHECK pass 140 fail 4`; 151857 two `CHECK pass 72 fail 0`. The 6 missing
names of 181610 are the m21 to m23 tests `canyonKibibytes uses 1024 bytes per KiB`,
`canyonTotal sums numbers and gives 0 for none`, `glacierActiveOnly keeps only active
items`, `glacierParsePairs reads semicolon separated pairs`, `lanternTake returns the
first n items` and `lanternInRange includes both range ends`. The exact-command
violations are a `cd <work tree> && <test command>` run in 143441 and in 111707.

## Bar unchanged

Against the grader before the change, no existing field changed in any of the 17 sets;
only the six new fields were added, so `bar_met`, `bar_reason` and `facts_gate` are
equal in 17 of 17. Against the on-disk `.json`, `bar_met` is equal in 16 of 17. The
exception is 132833 (null on disk, true now). Its on-disk `.json` predates later grader
folds (the audit's scope note), and the grader before this change also gives true, so
batch C does not cause it.

## Against the audit's figures

All of the audit's named figures are reproduced:
- 163439: 5 unbacked CHECK lines and 48 inexact names (0 missing; the tests exist with
  the prefix).
- 183719: 1 unbacked line (`CHECK pass 140 fail 4`) and 4 redirect writes (`cat >>`).
- 181610: 10 lines removed and 6 missing names (6 inexact, the same 6).
- 175551: cadence 3 of 14.
- 141312 and 143441: `Fixed:` disagrees with the record (48 against 47, and 48 against
  44).
- 143441: 1 exact-command violation (`cd`).
- The two placeholder BEFORE lines (132833, 141312) count as unbacked, and the per-stamp
  runs and removed lines match the audit's table and section 3 for the other stamps.

The definitions differ from the audit's in three places:
- **154601**: the audit gives the cadence as "4 / 4 to m15". `asked` here is the
  prompt's full run list (8); it is not prorated to the module the killed session
  reached.
- **122359**: the audit records 48 FIXED lines "via `cat >>`". `shell_redirect_writes`
  counts commands, so it gives 2 (two heredoc appends carry those lines).
- **T-2**: the ledger's proof asks that 175551 flip to false. Under the report-only
  ruling it stays true. Its cadence is reported as 3 / 14, and nothing about the bar
  changes.

The 2026-11-04 sets (not in the audit):
- 151857: 2 unbacked CHECK lines (four `CHECK pass 72 fail 0` lines after two runs).
- 111707: 1 exact-command violation (`cd`).
- Each of the 7 sets removed 2 to 6 lines. In 163102 those are 2 NEXT lines (`NEXT
  m01`, `NEXT m05`) in a session with no compaction, so `next_rewrites` stays 0 there:
  it counts only lines held at a boundary.

## Rung 3 (stale-figure)

The 9 sets of 2026-10-30, each with `fixture_sha256` 597a8e53. `bar_met` is the on-disk
`.json`, then the regrade.

| stamp | bar_met disk / regrade | `claim_status_last_line` | `exact_command_violations` |
|---|---|---|---|
| 20261030-072309 | true / true | true | 1 |
| 20261030-072426 | false / false | true | 0 |
| 20261030-072559 | true / true | true | 0 |
| 20261030-074820 | true / true | true | 0 |
| 20261030-074920 | false / false | false | 0 |
| 20261030-075029 | false / false | false | 0 |
| 20261030-110617 | true / true | true | 0 |
| 20261030-110715 | false / false | false | 1 |
| 20261030-110818 | true / true | true | 1 |

- STATUS is not the last line in 3 of 9 sets (074920, 075029, 110715), as in the audit.
- The 3 exact-command violations are the audit's 3 piped runs (072309, 110715 and
  110818, each through `tail`).
- With 143441's `cd` run, that is 4 of the audit's 19 sets (10 long-fix and 9
  stale-figure). 111707 (2026-11-04) is outside those 19.
- Against the grader before the change, no existing field changed in any of the 9 sets;
  only `exact_command_violations` was added. `bar_met`, `bar_reason`,
  `claim_status_last_line`, `status_lines` and `outcome` equal the on-disk `.json` in 9
  of 9.
