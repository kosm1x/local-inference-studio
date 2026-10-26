"""Unit tests for scripts/verify-doc.py. Run: python -I scripts/tests/verify-doc_test.py

Fixtures go into a temp "repo" with no .git, so the file count takes the os.walk
fallback. Exit 0 = all pass.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'verify-doc.py')
spec = importlib.util.spec_from_file_location('verify_doc', SCRIPT)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

TREE = {'a.ps1': 'x\ny\n', 'sub/b.ps1': 'x\n', 'sub/c.py': '1\n2\n3\n4\n'}
TREE.update({f'p/p{i}.ps1': '' for i in range(8)})  # 10 .ps1 files in all


def run(root, args, stdin=None):
    p = subprocess.run([sys.executable, '-I', SCRIPT, *args], cwd=root, input=stdin,
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout


def main():
    root = tempfile.mkdtemp(prefix='verify-doc-')
    out_dir = tempfile.mkdtemp(prefix='verify-doc-out-')
    try:
        return tests(root, out_dir)
    finally:
        shutil.rmtree(root)
        shutil.rmtree(out_dir)


def tests(root, out_dir):
    for rel, body in TREE.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), 'w', newline='\n') as f:
            f.write(body)
    with open(os.path.join(root, 'big.txt'), 'wb') as f:
        f.truncate(9_000_000)
    outside = os.path.join(out_dir, 'o.md')
    with open(outside, 'w') as f:
        f.write('20 cases (5 alpha, 6 beta, 7 gamma)\n')
    this_file = os.path.abspath(__file__).replace('\\', '/')
    up = '../' + os.path.basename(out_dir) + '/o.md'

    def doc(name, text):
        p = os.path.join(root, name)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        return p

    # (name, markdown, expected exit, substrings that must appear, substrings that must not)
    cases = [
        ('bad split', 'Intro.\n\nThere are 20 cases in total (5 alpha,\n6 beta, 7 gamma).\n', 1,
         ['FAIL sum:', 'doc says 20, measured 5 + 6 + 7 = 18', 'at line 3'], []),
        ('good split', 'There are 18 cases (5 alpha, 6 beta and 7 gamma).\n', 0, ['0 findings'], []),
        ('bad colon split', '`x.jsonl` (86 rows: R1x22, R2\u00d722, O1x13) is data.\n', 1,
         ['doc says 86, measured 22 + 22 + 13 = 57'], []),
        ('good colon split', 'The corpus (57 rows: R1x22, R2\u00d722, O1x13) is data.\n', 0, ['0 findings'], []),
        ('table cell split', '| Set | Note |\n|---|---|\n| A | 9 rows (4 deny, 4 allow, 0 ask) |\n', 1,
         ['doc says 9, measured 4 + 4 + 0 = 8', 'at line 3'], []),
        ('not splits', 'Passed 619/619 and 0/3 by design. Lines 60-96 (3 a, 4 b, 5 c). A 4070 Ti SUPER '
         '(16375 MiB, 15111 MiB, 1264 MiB). In 2026 runs (2025 old, 2024 older, 2023 oldest). '
         '5 runs (25 a, 3 b, 1 c).\n', 0, ['0 findings'], ['FAIL']),
        ('wrong ps count', 'All 3 PowerShell scripts are untested; 3 `.ps1` files.\n', 1,
         ['FAIL count: "3 PowerShell scripts" (doc says 3, measured 10 .ps1 files) at line 1',
          'FAIL count: "3 `.ps1` files"'], []),
        ('right counts', 'All 10 PowerShell scripts and 1 Python file.\n', 0, ['0 findings'], []),
        ('wrong table lines', '| File | Lines |\n|---|---|\n| `sub/c.py` | 5 |\n| `a.ps1` | 2 |\n', 1,
         ['FAIL lines: sub/c.py (doc says 5, measured 4) at line 3'], ['a.ps1']),
        ('right table lines', '| File | Lines |\n|---|---|\n| `sub/c.py` | 4 |\n', 0, ['0 findings'], []),
        ('table not lines', '| File | Checks |\n|---|---|\n| `sub/c.py` | 619 |\n', 0, ['0 findings'], []),
        ('inline lines', 'See `sub/c.py`\n(3 lines) and `a.ps1`, 2 lines.\n', 1,
         ['FAIL lines: sub/c.py (doc says 3, measured 4) at line 1'], ['FAIL lines: a.ps1']),
        ('missing path', 'Add `scripts/tests/new_test.py` and keep `sub/c.py`.\n', 0,
         ['INFO path not found (proposed or wrong): scripts/tests/new_test.py at line 1'],
         ['FAIL', 'sub/c.py']),
        # quoted text is reported speech, a figure in backticks is code: no sum/count check
        ('quoted count', 'The report says "11 PowerShell scripts" against the 10 it lists.\n', 0,
         ['0 findings'], []),
        ('unquoted count', 'The report says 11 PowerShell scripts against the 10 it lists.\n', 1,
         ['FAIL count: "11 PowerShell scripts" (doc says 11, measured 10 .ps1 files)'], []),
        ('quoted split', 'the split "546 rows (172 a, 72 b, 135 c, 55 d)" is wrong\n', 0,
         ['0 findings'], []),
        ('unquoted split', 'the split 546 rows (172 a, 72 b, 135 c, 55 d) is wrong\n', 1,
         ['doc says 546, measured 172 + 72 + 135 + 55 = 434'], []),
        ('backticked figures', 'Run `11 PowerShell scripts` and `546 rows (172 a, 72 b, 1 c)`.\n', 0,
         ['0 findings'], []),
        ('quoted path line count', 'In "notes" `sub/c.py` (3 lines) is cited.\n', 1,
         ['FAIL lines: sub/c.py (doc says 3, measured 4)'], []),
        ('code fence skipped', '```\n20 cases (5 alpha, 6 beta, 7 gamma)\n```\n', 0, ['0 findings'], []),
        # containment and size: absolute, ../ and over-8 MB files are not read
        ('absolute path not read', f'`{this_file}` (3 lines).\n', 0, ['0 findings'], ['FAIL']),
        ('../ path not read', f'`{up}` (3 lines) and `../x/y.py`.\n', 0, ['0 findings'], ['FAIL', 'INFO']),
        ('9 MB file skipped', '`big.txt`, 3 lines.\n', 0, ['0 findings'], ['FAIL']),
        # false-positive probes (auditor 4a-4e)
        ('4a scoped counts', '7 PowerShell scripts in scripts/ are untested. 2 PowerShell scripts under '
         '`bench/` run. This plan edits 3 PowerShell scripts. It edits 1 PowerShell script.\n', 0,
         ['0 findings'], ['FAIL']),
        ('4b partial 2-part list', 'The run made 10 calls (2 Bash, 3 Read).\n', 0, ['0 findings'], []),
        ('4c baseline header', '| File | Baseline |\n|---|---|\n| `sub/c.py` | 9 |\n', 0, ['0 findings'], []),
        ('4c lines changed header', '| File | Lines changed |\n|---|---|\n| `sub/c.py` | 9 |\n', 0,
         ['0 findings'], []),
        ('4c **Lines** header still checked', '| File | **Lines** |\n|---|---|\n| `sub/c.py` | 9 |\n', 1,
         ['FAIL lines: sub/c.py (doc says 9, measured 4)'], []),
        ('4d diff wording', '`sub/c.py` (16 lines added) and `sub/c.py`, 5 lines changed.\n', 0,
         ['0 findings'], []),
        ('4e port number', 'Port 8080 tests (8 pass, 2 fail). Port 8080 tests (3 pass, 2 fail, 1 skip).\n',
         0, ['0 findings'], []),
        # regression pins: true positives still fail
        ('pin wrong count', 'All 11 PowerShell scripts are untested.\n', 1,
         ['FAIL count: "11 PowerShell scripts" (doc says 11, measured 10 .ps1 files)'], []),
        # round 2: blank-separated tables keep their own headers, both orders
        ('Lines table then Checks table', '| File | Lines |\n|---|---|\n| `sub/c.py` | 4 |\n\n'
         '| File | Checks |\n|---|---|\n| `sub/c.py` | 619 |\n', 0, ['0 findings'], []),
        ('Checks table then Lines table', '| File | Checks |\n|---|---|\n| `sub/c.py` | 619 |\n\n'
         '| File | Lines |\n|---|---|\n| `sub/c.py` | 9 |\n', 1,
         ['FAIL lines: sub/c.py (doc says 9, measured 4) at line 7'], ['619']),
        ('Line header is line numbers', '| File | Line | Issue |\n|---|---|---|\n| `sub/c.py` | 12 | x |\n',
         0, ['0 findings'], []),
        # the scope qualifier must follow the count directly
        ('scope later in sentence', 'There are 11 PowerShell scripts, and the tests live in scripts/tests/.\n',
         1, ['FAIL count: "11 PowerShell scripts"'], []),
        ('in total is not a scope', '7 PowerShell scripts in total.\n', 1,
         ['FAIL count: "7 PowerShell scripts" (doc says 7, measured 10 .ps1 files)'], []),
        # 2 complementary parts are a partition
        ('complementary bad', '13 scripts (2 tested, 10 untested).\n', 1,
         ['doc says 13, measured 2 + 10 = 12'], []),
        ('complementary good', '13 scripts (3 tested, 10 untested).\n', 0, ['0 findings'], []),
        ('complementary pair and not-prefix', '10 tests (8 pass, 3 fail). 5 checks (2 met, 2 not met).\n', 1,
         ['doc says 10, measured 8 + 3 = 11', 'doc says 5, measured 2 + 2 = 4'], []),
    ]
    n = fails = 0
    for name, text, code, want, never in cases:
        n += 1
        got_code, out = run(root, [doc('d.md', text), '--root', root])
        bad = [w for w in want if w not in out] + [w for w in never if w in out]
        if got_code != code or bad:
            fails += 1
            print(f'FAIL {name}: exit {got_code} (want {code}), missing/forbidden {bad}\n{out}')

    # the absolute, ../ and big-file claims never reach line_count's read
    n += 1
    reads, saved = [], v.line_count
    v.line_count = lambda p: reads.append(p) or saved(p)
    try:
        v.check(doc('d.md', f'`{this_file}` (3 lines). `{up}` (3 lines).\n'), root)
    finally:
        v.line_count = saved
    if reads or v.line_count(os.path.join(root, 'big.txt')) is not None or v.line_count(root) is not None:
        fails += 1
        print(f'FAIL containment/size: read {reads}, big/dir must give None')

    # CLI usage errors exit 2, not 1
    for name, args in [('--root without value', [doc('d.md', 'x\n'), '--root']),
                       ('missing doc', [os.path.join(root, 'nope.md')])]:
        n += 1
        code, _ = run(root, args)
        if code != 2:
            fails += 1
            print(f'FAIL {name}: exit {code} (want 2)')

    # --hook: non-.md, outside the root, a bad .md, the cap
    bad_md = doc('bad.md', 'There are 20 cases in total (5 alpha, 6 beta, 7 gamma).\n')
    many = doc('many.md', ''.join(f'- `sub/c.py` (1 lines) and `nope/x{i}.py`.\n' for i in range(300)))

    def hook(path):
        code, out = run(root, ['--hook'], stdin=json.dumps(
            {'cwd': root, 'tool_name': 'Write', 'tool_input': {'file_path': path}}))
        ctx = json.loads(out)['hookSpecificOutput'] if out else {}
        return code, out, ctx.get('additionalContext', ''), ctx.get('hookEventName')

    for name, path, expect in [('hook non-md', os.path.join(root, 'sub', 'c.py'), None),
                               ('hook outside root', outside, None),
                               ('hook ../ outside root', up, None),
                               ('hook relative bad md', 'bad.md', 'FAIL sum:'),
                               ('hook bad md', bad_md, 'doc says 20, measured 5 + 6 + 7 = 18')]:
        n += 1
        code, out, ctx, event = hook(path)
        ok = code == 0 and (out == '' if expect is None else expect in ctx and event == 'PostToolUse'
                            and 'a scoped or partial figure is not an error' in ctx)
        if not ok:
            fails += 1
            print(f'FAIL {name}: exit {code}, out {out!r}')
    n += 1
    code, out, ctx, _ = hook(many)
    lines = ctx.split('\n')
    me = os.path.abspath(SCRIPT).replace('\\', '/')
    if not (code == 0 and len(ctx) <= 10_000 and re.search(r'\+\d+ more; run: python -I ', ctx)
            and lines[-1].endswith(f' {me} many.md') and lines[1].startswith('FAIL')
            and 'INFO' not in lines[1]):
        fails += 1
        print(f'FAIL hook cap: exit {code}, {len(ctx)} chars, first {lines[:2]}, last {lines[-1:]}')
    n += 1
    code, out = run(root, ['--hook'], stdin='not json')
    if code != 0 or out:
        fails += 1
        print(f'FAIL hook bad stdin: exit {code}, out {out!r}')
    # a read error inside the hook (check raising OSError, as for a locked file) -> exit 0
    n += 1
    old = sys.stdin, sys.stdout, v.check
    try:
        sys.stdin = io.StringIO(json.dumps({'cwd': root, 'tool_input': {'file_path': bad_md}}))
        sys.stdout = io.StringIO()
        v.check = lambda *a: (_ for _ in ()).throw(PermissionError('locked'))
        code, out = v.main(['--hook']), sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout, v.check = old
    if code != 0 or out:
        fails += 1
        print(f'FAIL hook read error: exit {code}, out {out!r}')

    # mutation pins: with the sum regex disabled the bad split is no longer caught, and
    # without the quote blanking the quoted count fails, so both cases above depend on them.
    n += 1
    saved, v.TOTAL = v.TOTAL, re.compile(r'(?!x)x')
    try:
        unpinned = [f for f in v.check(bad_md, root) if f.startswith('FAIL')]
    finally:
        v.TOTAL = saved
    if unpinned or not [f for f in v.check(bad_md, root) if f.startswith('FAIL sum')]:
        fails += 1
        print(f'FAIL pin: sum check removal must silence the bad split: {unpinned}')
    n += 1
    quoted = doc('q.md', 'The report says "11 PowerShell scripts" against the 10 it lists.\n')
    saved, v.unquoted = v.unquoted, lambda s: s
    try:
        unmasked = [f for f in v.check(quoted, root) if f.startswith('FAIL')]
    finally:
        v.unquoted = saved
    if not unmasked or [f for f in v.check(quoted, root) if f.startswith('FAIL')]:
        fails += 1
        print(f'FAIL pin: quote blanking removal must expose the quoted count: {unmasked}')

    print(f'{n - fails}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
