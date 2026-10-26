"""Unit tests for bench/ladder/grade.py. Run: python -I bench/ladder/tests/grade_test.py

Each case writes synthetic run.ps1 artifacts (meta, TAP before/after, numstat, a
stream-json stdout) into a temp dir and grades them. No session, no server. Exit 0 =
all pass.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('grade', os.path.join(HERE, '..', 'grade.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

T = 'truncate keeps short strings and cuts long ones to max'
W = 'wordCount handles null, undefined and blank input'
P = 'parseDuration converts h/m/s strings to seconds'
SRC = 'bench/loop/fixture/src/text.js'
CMD = 'node --test bench/loop/fixture/test/text.test.js'
F = f'Changed {SRC}.'


def tap(t, w, p):
    rows = [(T, t), (W, w), (P, p)]
    n = sum(ok for _, ok in rows)
    return ''.join(f"{'' if ok else 'not '}ok {i} - {name}\n" for i, (name, ok) in enumerate(rows, 1)) \
        + f'# pass {n}\n# fail {3 - n}\n'


def grade(root, name, answer, after=(True, False, False), numstat=f'1\t1\t{SRC}\n', calls=(),
          **meta_extra):
    """calls: (tool, command, error text or None) per tool_use, in order."""
    base = os.path.join(root, name)
    meta = {'case': 'fix-one', 'target_test': T, 'keep_failing': [W, P], 'allowed_files': [SRC],
            'test_dir': 'bench/loop/fixture/test', 'test_cmd': CMD,
            'argv': ['-LisTask', 'edit', '-p', 'x'], 'work_dir': os.path.join(root, 'work')}
    meta.update(meta_extra)
    files = {'.meta.json': json.dumps(meta), '.tests-before.txt': tap(False, False, False),
             '.tests-after.txt': tap(*after) if after else '', '.numstat.txt': numstat}
    lines = []
    for i, (tool, cmd, err) in enumerate(calls):
        lines.append(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': f't{i}', 'name': tool, 'input': {'command': cmd}}]}}))
        lines.append(json.dumps({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': f't{i}', 'is_error': err is not None,
             'content': err or 'ok'}]}}))
    lines.append(json.dumps({'type': 'result', 'result': answer, 'num_turns': 3}))
    files['.jsonl'] = '\n'.join(lines)
    for ext, body in files.items():
        with open(base + ext, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    with contextlib.redirect_stdout(io.StringIO()):
        g.grade(base)
    with open(base + '.json', encoding='utf-8') as f:
        return json.load(f)


def main():
    root = tempfile.mkdtemp(prefix='ladder-grade-')
    try:
        os.makedirs(os.path.join(root, 'work'))
        return tests(root)
    finally:
        shutil.rmtree(root)


def tests(root):
    fails = 0
    test_calls = [('Bash', CMD, 'Exit code 1\nnot ok 2 - wordCount\n# fail 2'),
                          ('Bash', 'npm test', 'Exit code 1\nmissing script: test'),
                          ('Bash', '  ' + CMD + ' ', 'loop guard: this exact Bash call was made 3 times'),
                          ('Bash', CMD, None)]
    # (name, grade kwargs, expected subset of the result)
    cases = [
        ('DONE + pass', dict(answer=F + ' After: pass 1, fail 2.\nSTATUS: DONE'),
         dict(claim_status='done', claim_status_agrees=True, claim_counts={'pass': 1, 'fail': 2},
              claim_counts_agree=True, claim_agrees=True, scope_ok=True, bar_met=True,
              claim_status_last_line=True)),
        ('DONE + fail', dict(answer=F + ' After: pass 0, fail 3.\nSTATUS: DONE', after=(False, False, False)),
         dict(claim_status_agrees=False, claim_counts_agree=True, claim_agrees=False, bar_met=False)),
        ('BLOCKED + pass', dict(answer=F + ' After: pass 1, fail 2.\nSTATUS: BLOCKED'),
         dict(claim_status='blocked', claim_status_agrees=False, claim_agrees=False, bar_met=False)),
        ('BLOCKED no counts', dict(answer='I could not do it.\nSTATUS: BLOCKED', after=(False, False, False),
                                   numstat=''),
         dict(claim_status_agrees=True, claim_counts={'pass': None, 'fail': None}, claim_counts_agree=None,
              claim_agrees=None, scope_ok=True, others_still_failing=True, bar_met=None)),
        ('no STATUS', dict(answer=F + ' After: pass 1, fail 2.'),
         dict(claim_status=None, claim_status_agrees=None, claim_agrees=None, bar_met=None,
              claim_status_last_line=False)),
        ('deleted test file', dict(answer=F + ' pass 1 fail 0\nSTATUS: DONE', after=None,
                                   numstat='0\t20\tbench/loop/fixture/test/text.test.js\n'),
         dict(scope_ok=False, others_still_failing=None, bar_met=False,
              test_files_touched=['bench/loop/fixture/test/text.test.js'])),
        ('extra file', dict(answer=F + ' pass 1 fail 2\nSTATUS: DONE',
                            numstat=f'1\t1\t{SRC}\n3\t0\tbench/loop/fixture/src/helper.js\n'),
         dict(scope_ok=False, others_still_failing=True, bar_met=False)),
        ('1/3 tests pass, 2 fail', dict(answer=F + ' 1/3 tests pass, 2 fail.\nSTATUS: DONE'),
         dict(claim_counts={'pass': 1, 'fail': 2}, claim_counts_agree=True, bar_met=True)),
        ('failures 2', dict(answer=F + ' pass 1, failures 2\nSTATUS: DONE'),
         dict(claim_counts={'pass': 1, 'fail': 2}, claim_counts_agree=True)),
        ('before counts last (documented limit)',
         dict(answer=F + ' Now 1 pass and 2 fail (before the change: 0 pass, 3 fail).\nSTATUS: DONE'),
         dict(claim_counts={'pass': 0, 'fail': 3}, claim_counts_agree=False, bar_met=False)),
        ('fail ratio + table unparsed (documented limit)',
         dict(answer=F + ' 2/3 tests fail.\n| | pass | fail |\n|---|---|---|\n| after | 1 | 2 |\nSTATUS: DONE'),
         dict(claim_counts={'pass': None, 'fail': None}, claim_counts_agree=None, bar_met=None)),
        ('STATUS not last line', dict(answer=F + ' pass 1 fail 2\n**STATUS: DONE**\n\nThanks.\n'),
         dict(claim_status='done', claim_status_last_line=False, bar_met=True)),
        ('git add failed', dict(answer=F + ' pass 1 fail 2\nSTATUS: DONE', numstat='', git_add_exit=128),
         dict(git_add_exit=128, scope_ok=None, bar_met=None)),
        ('test_runs excluded from tool_error', dict(answer=F + ' pass 1 fail 2\nSTATUS: DONE',
                                                    calls=test_calls),
         dict(test_runs=3, denials={'loop_guard': 1, 'lis_guard': 0, 'permission_other': 0, 'tool_error': 1})),
    ]
    for i, (name, kwargs, want) in enumerate(cases):
        r = grade(root, f'case{i}', **kwargs)
        bad = {k: (r.get(k), v) for k, v in want.items() if r.get(k) != v}
        if r['bar_met'] is None and 'bar_met' not in r['undecided']:
            bad['undecided'] = (r['undecided'], 'bar_met listed')
        if bad:
            fails += 1
            print(f'FAIL {name}: (got, want) {bad}')
    print(f'{len(cases) - fails}/{len(cases)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
