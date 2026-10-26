"""Unit tests for scripts/verify_claims_extract.py and scripts/verify_claims_report.py.
Run: python -I scripts/tests/verify_claims_report_test.py

Fixtures go into a temp "repo" and a sibling temp dir outside it that holds a file an
escaping path would name. Seven mutation pins rebuild a module from its source with one
guard removed and require the cases to go red. Exit 0 = all pass.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.join(HERE, '..', 'verify_claims_extract.py')
REPORT = os.path.join(HERE, '..', 'verify_claims_report.py')


def load(path, old=None, new=None):
    """The module at path; with old/new, a mutant built from its source with one edit."""
    if old is None:
        spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    with open(path, encoding='utf-8') as f:
        src = f.read()
    assert old in src, f'mutation target gone from {path}: {old!r}'
    mod = types.ModuleType('mutant')
    exec(compile(src.replace(old, new, 1), path, 'exec'), mod.__dict__)
    return mod


A_PS1 = ''.join(f'filler line {i}\n' for i in range(1, 5)) + \
    '$total = 546  # the CASES rows\n' + ''.join(f'filler line {i}\n' for i in range(6, 11))


def doc_text(outside):
    return '\n'.join([
        '# Heading with 5 numbers and `scripts/a.ps1`',          # 1 skipped
        'Para has `scripts/a.ps1` and',                          # 2
        'wraps here. Second sentence has 42 items.',             # 3
        'Plain sentence without tokens.',                        # 4
        '',                                                      # 5
        '- item one says `-Force` is used',                      # 6
        '  and continues. Item tail "quoted text here".',        # 7
        '- item two has 7 rows',                                 # 8
        '',                                                      # 9
        '| File | Lines |',                                      # 10
        '|---|---|',                                             # 11
        '| `scripts/a.ps1` | 10 |',                              # 12
        '',                                                      # 13
        '```text',                                               # 14
        'inside fence 99 `sub/b.py`.',                           # 15
        '```',                                                   # 16
        f'Escapes `../{outside}/secret.txt`, `/etc/hosts` and `sub/b.py` here.',  # 17
        'Repeated 3 times.',                                     # 18
        'Repeated 3 times.',                                     # 19
        'Calls `Get-Item` once.',                                # 20
        'Missing `nope/x.md` is a path that does not exist.',    # 21
        'Use a flag, e.g. `-Force` once.',                       # 22
        'Odd paths `C:foo/x.txt` and `\\\\host\\share\\x` count 2.',  # 23
        '',                                                      # 24
        '## Next steps',                                         # 25 plan heading
        'Add 3 tests to `scripts/a.ps1`.',                       # 26 skipped
        '| Step | Count |',                                      # 27
        '|---|---|',                                             # 28
        '| one | 4 |',                                           # 29 skipped
        '## After',                                              # 30
        'After has 6 items.',                                    # 31
        ''])


def extractor_cases(x, root, outside):
    """(name, ok) pairs for the extractor module x."""
    cs, planned = x.extract(doc_text(outside), root)
    by = {c['claim']: c for c in cs}
    one = by.get('Para has `scripts/a.ps1` and wraps here.')
    skipped, _ = x.extract(doc_text(outside), root, skip={3})
    odd = by.get('Odd paths `C:foo/x.txt` and `\\\\host\\share\\x` count 2.', {})
    esc = [c for c in cs if c['claim'].startswith('Escapes')]
    words, words_planned = x.extract('## Explanation\nIt has 3 parts.\n'
                                     '## Suggested done-check\nRun 2 tests.\n'
                                     '## Planet facts\nMars has 2 moons.\n', root)
    levels, levels_planned = x.extract('## Next steps\nAdd 2 docs.\n### Details\nIt has 4 parts.\n'
                                       '## Notes\nNotes has 5 parts.\n### Plan B\nB has 6 parts.\n'
                                       '### Other\nOther has 7 parts.\n', root)
    return [
        ('sentence joined across wrapped lines', one is not None and (one['line'], one['end'],
                                                                     one['kind']) == (2, 3, 'path')
         and one['paths'] == ['scripts/a.ps1']),
        ('second sentence starts on its own line',
         by.get('Second sentence has 42 items.', {}).get('line') == 3),
        ('sentence without a token dropped', 'Plain sentence without tokens.' not in by),
        ('list item continuation joined', by.get('item one says `-Force` is used and continues.',
                                                 {}).get('kind') == 'identifier'),
        ('quote kind', by.get('Item tail "quoted text here".', {}).get('kind') == 'quote'),
        ('list item ends at its last line', by.get('item two has 7 rows', {}).get('end') == 8),
        ('table row is one claim with its header',
         by.get('| File | Lines | | `scripts/a.ps1` | 10 |', {}).get('line') == 12),
        ('table header and separator skipped', not any(c['line'] in (10, 11) for c in cs)),
        ('heading skipped', not any(c['line'] == 1 for c in cs)),
        ('fenced code skipped', not any(14 <= c['line'] <= 16 for c in cs)),
        ('escaping paths never listed', len(esc) == 1 and esc[0]['paths'] == ['sub/b.py']),
        ('dedupe identical claims', sum(c['claim'] == 'Repeated 3 times.' for c in cs) == 1),
        ('identifier kind', by.get('Calls `Get-Item` once.', {}).get('kind') == 'identifier'),
        ('missing path: kind path, not listed', by.get(
            'Missing `nope/x.md` is a path that does not exist.', {}).get('paths', 0) == []),
        ('ids are 1..n', [c['id'] for c in cs] == list(range(1, len(cs) + 1))),
        ('skip-lines drops every claim spanning the line',
         not any(c['line'] <= 3 <= c['end'] for c in skipped) and len(skipped) == len(cs) - 2),
        ('--max keeps the first N', [c['claim'] for c in x.extract(doc_text(outside), root,
                                                                   limit=2)[0]]
         == [c['claim'] for c in cs[:2]]),
        ('no split after e.g.', by.get('Use a flag, e.g. `-Force` once.', {}).get('line') == 22),
        ('drive-relative and UNC paths never listed', odd.get('paths') == [] and
         x.safe_rel('C:foo/x.txt') is None and x.safe_rel('\\\\host\\share\\x') is None),
        ('plan-section claims skipped and counted',
         planned == 2 and not any(25 <= c['line'] <= 29 for c in cs)),
        ('claims after the next heading kept', by.get('After has 6 items.', {}).get('line') == 31),
        ('plan heading words match whole words only',
         [c['claim'] for c in words] == ['It has 3 parts.', 'Mars has 2 moons.']
         and words_planned == 1),
        ('a child heading under a plan heading stays skipped',
         'It has 4 parts.' not in [c['claim'] for c in levels]),
        ('a plan sub-heading skips only to the next heading of its level',
         [c['claim'] for c in levels] == ['Notes has 5 parts.', 'Other has 7 parts.']
         and levels_planned == 3),
    ]


def envelope(result, turns=3):
    return json.dumps({'type': 'result', 'num_turns': turns, 'duration_ms': 9000,
                       'usage': {'input_tokens': 20000, 'cache_read_input_tokens': 500},
                       'permission_denials': [], 'result': result})


def claim(i, line=2):
    return {'id': i, 'line': line, 'end': line, 'claim': f'claim {i}', 'paths': [],
            'kind': 'number'}


def run_of(results, ids, det=(), root='.'):
    """A run.json dict: one session per (stdout, ids) pair."""
    cl = sorted({i for b in ids for i in b})
    return {'document': os.path.join(root, 'doc.md'), 'root': root, 'batch': 1, 'wall_s': 12.4,
            'aborted': None, 'claims': [claim(i, line=i + 1) for i in cl],
            'deterministic': list(det),
            'sessions': [{'ids': b, 'stdout': s, 'server_n_tokens': [21000, 23500]}
                         for s, b in zip(results, ids)]}


def ans(*rows):
    return json.dumps([{'id': i, 'verdict': v, 'evidence': e} for i, v, e in rows])


def report_cases(r, root, outside):
    """(name, ok) pairs for the report module r."""
    q = '"$total = 546  # the CASES rows"'
    rows = ans((1, 'true', f'scripts/a.ps1:5 {q}'), (2, 'false', 'sub/b.py says 3'),
               (3, 'unverifiable', 'a plan'))

    def verdicts(stdout, ids=(1, 2, 3)):
        rep = r.report(run_of([stdout], [list(ids)], root=root))
        return [e['verdict'] for e in rep['ledger']], rep

    got, rep = verdicts(envelope(rows))
    fence, _ = verdicts(envelope('```json\n' + rows + '\n```'))
    prose, _ = verdicts(envelope('Here is the result: ' + rows + ' Done.'))
    bad, _ = verdicts(envelope('I ran out of turns.'))
    junk, _ = verdicts('not json at all')
    miss, _ = verdicts(envelope(ans((1, 'true', 'x'), (99, 'false', 'y'), (2, 'maybe', 'z'))))
    strid, _ = verdicts(envelope(json.dumps([{'id': '2', 'verdict': 'false', 'evidence': ''}])),
                        ids=(2,))
    brack, _ = verdicts(envelope('It defines `Get-Median([double[]]$Values)` twice.\n\n' + rows))
    one = ans((1, 'false', 'sub/b.py'))
    fake, _ = verdicts(envelope('The claim said [{"id":1,"verdict":"true","evidence":"x"}] '
                                'but:\n' + one + '\nNote [x] after.'), ids=(1,))
    echo, _ = verdicts(envelope(one + '\nThe claims sent were [{"id": 0}].'), ids=(1,))
    twice, _ = verdicts(envelope(ans((1, 'true', 'x')) + '\nCorrected:\n' + one), ids=(1,))
    # shapes of the two answers the slice fallback lost in the resumed proof runs
    proof1, _ = verdicts(envelope(
        'All elements check out.\n\n- line 144 (`$cfg.env[\'AUTO_COMPACT\']`).\n'
        '- line 165 writes `{"mcpServers":{}}`.\n\n' + json.dumps([{
            'id': 1, 'verdict': 'true', 'evidence': ':165 writes ({"mcpServers":{}})'}])),
        ids=(1,))
    proof2, _ = verdicts(envelope(
        'Still defined twice.\n\n- `bench\\run.ps1:47` -> `function Get-Median([double[]]$V) {`'
        '\n\n' + json.dumps([{'id': 1, 'verdict': 'false', 'evidence':
                              'bench\\\\run.ps1:47 `function Get-Median([double[]]$V) {`'}])),
        ids=(1,))

    def entry(verdict, evidence):
        rep = r.report(run_of([envelope(ans((1, verdict, evidence)))], [[1]], root=root))
        return rep['ledger'][0]
    near = entry('false', f'scripts/a.ps1:7 {q}')            # quote 2 lines away
    far = entry('false', f'scripts/a.ps1:9 {q}')             # 4 lines away
    short = entry('true', 'scripts/a.ps1:5 "$total = 5"')    # under 12 chars
    wrong = entry('true', 'scripts/a.ps1:5 "this text is not in the file"')
    tick = entry('true', 'scripts/a.ps1:4 `$total = 546  # the CASES`')
    unb = entry('true', 'the docs say so')
    gone = entry('true', 'nowhere/x.py:3 "something long enough"')
    opened = []
    real_open = r.__dict__.get('open', open)

    def spy(path, *a, **k):
        opened.append(os.path.realpath(path))
        return real_open(path, *a, **k)
    r.open = spy
    try:
        secret = f'"outside secret line one"'
        up = entry('false', f'../{outside}/secret.txt:1 {secret}')
        absol = entry('false', os.path.join(os.path.dirname(root), outside, 'secret.txt')
                      .replace('\\', '/') + f':1 {secret}')
        inside_read = entry('true', f'scripts/a.ps1:5 {q}')
    finally:
        r.open = real_open
    outside_reads = [p for p in opened if not p.startswith(os.path.realpath(root))]
    det = [{'finding': 'FAIL sum: "x" at line 3', 'line': 3}]
    rd = r.report(run_of([envelope(ans((2, 'false', 'sub/b.py')))], [[2]], det=det, root=root))
    text = r.honest_count(run_of([envelope(rows)], [[1, 2, 3]], root=root), rep, 'doc.md')
    run = run_of([envelope(rows)], [[1, 2, 3]], root=root)
    run['plan_skipped'] = 4
    return [
        ('valid array', got == ['true', 'false', 'unverifiable']),
        ('fenced array', fence == got),
        ('prose-wrapped array', prose == got),
        ('`[` in the prose before the array', brack == got),
        ('an array echoed in the prose before the answer does not win', fake == ['false']),
        ('an array without a verdict after the answer does not win', echo == ['false']),
        ('of two answer arrays the last wins', twice == ['false']),
        ('proof shapes: prose `[` before the array', proof1 == ['true'] and proof2 == ['false']),
        ('invalid result -> all verifier-failed', bad == ['verifier-failed'] * 3),
        ('invalid envelope -> all verifier-failed', junk == ['verifier-failed'] * 3),
        ('missing, unknown-id and bad-verdict answers -> verifier-failed',
         miss == ['true', 'verifier-failed', 'verifier-failed']),
        ('string id accepted', strid == ['false']),
        ('evidence-backed', rep['ledger'][1]['backed'] == ['sub/b.py']),
        ('unbacked evidence', unb['backed'] == [] and not unb['confirmed']),
        ('missing path not backed', gone['backed'] == []),
        ('unverifiable is never backed', rep['ledger'][2]['backed'] == []),
        ('confirmed within +-3 lines', near['confirmed'] and rep['ledger'][0]['confirmed']),
        ('backtick quote confirmed', tick['confirmed']),
        ('not confirmed 4 lines away', far['backed'] and not far['confirmed']),
        ('quote under 12 chars not confirmed', not short['confirmed']),
        ('quote not in the file not confirmed', not wrong['confirmed']),
        ('.. evidence path not backed or confirmed', up['backed'] == [] and not up['confirmed']),
        ('absolute evidence path not backed or confirmed',
         absol['backed'] == [] and not absol['confirmed']),
        ('files outside root never read', outside_reads == [] and len(opened) == 1
         and inside_read['confirmed']),
        ('counts', rep['counts']['true'] == 1 and rep['counts']['false'] == 1
         and rep['counts']['backed'] == 2 and rep['counts']['confirmed'] == 1),
        ('deterministic finding on a sent false claim', rd['counts']['det_sent'] == 1
         and rd['counts']['det_also_false'] == 1),
        ('honest count head', text.split('\n')[0] == 'verify-claims v2: doc.md' and
         'claims extracted: 3   sent to the verifier: 3 in 1 sessions (batch 1)' in text and
         'evidence-backed: 2 of 2   evidence-confirmed by the harness: 1 of 2' in text and
         'wall: 12 s   turns: 3   peak prompt tokens: 23500' in text and
         text.split('\n')[2] == 'plan-section claims skipped: not recorded'),
        ('plan-section count printed', 'plan-section claims skipped: 4' in r.honest_count(
            run, r.report(run), 'doc.md')),
        ('false claims listed', '  line 3: claim 2 -- sub/b.py says 3' in text),
    ]


def resume_cases(r, root, tmp):
    """(name, ok) pairs for --retry and a resumed run of the report module r."""
    first = r.report(run_of([envelope(ans((1, 'true', 'sub/b.py'), (2, 'false', 'sub/b.py'))),
                             envelope('I ran out of turns.'), envelope(ans((5, 'unverifiable',
                                                                              'a plan')))],
                            [[1, 2], [3, 4], [5, 6]], root=root))
    old = {'ledger': first['ledger'], 'claims': first['claims'], 'sessions': first['sessions'],
           'deterministic': [{'line': 9, 'claim': 'FAIL x', 'verdict': 'deterministic-false',
                              'evidence': 'verify-doc'}], 'plan_skipped': 5}
    retry = [c['id'] for c in r.to_retry(old)]
    # claim 3 recovered, claim 4 still failed; claim 6 not sent again; claim 1 re-answered
    run = run_of([envelope(ans((3, 'true', 'sub/b.py'))), envelope(ans((4, 'maybe', 'x'))),
                  envelope(ans((1, 'false', 'flip')))], [[3], [4], [1]], root=root)
    run['resume'] = 'old.verify.json'
    rr = r.report(run, old)
    v = {e['id']: e['verdict'] for e in rr['ledger']}
    text = r.honest_count(run, rr, 'doc.md').split('\n')
    return [
        ('retry lists only verifier-failed claims', retry == [3, 4, 6]),
        ('resume keeps decided verdicts', v == {1: 'true', 2: 'false', 3: 'true',
                                               4: 'verifier-failed', 5: 'unverifiable',
                                               6: 'verifier-failed'}),
        ('resume keeps the old deterministic findings',
         rr['counts']['deterministic-false'] == 1),
        ('resumed sessions numbered after the old ones', len(rr['sessions']) == 6 and
         [e['session'] for e in rr['ledger'] if e['id'] in (3, 4)] == [4, 5]),
        ('retried and recovered', rr['retried'] == [3, 4] and rr['recovered'] == [3]),
        ('resume lines after verdicts', text[4] == 'resumed from: old.verify.json' and
         text[5] == 'retried: 2   recovered: 1   still failed: 2' and
         text[3].startswith('verdicts: true 2   false 1   unverifiable 1   verifier-failed 2')),
        ('resume head counts this run', text[1] == 'claims extracted: 6   sent to the verifier: '
         '2 in 3 sessions (batch 1)'),
        ('resume keeps the old plan-section count', text[2] == 'plan-section claims skipped: 5'),
    ]


def cli_cases(root, tmp):
    """(name, ok) pairs for the two command lines and the report's exit codes."""
    out = []
    path = os.path.join(tmp, 'run.json')

    def exit_of(run):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(run, f)
        p = subprocess.run([sys.executable, '-I', REPORT, path, os.path.join(tmp, 'out.json')],
                           capture_output=True, text=True, timeout=30)
        return p.returncode
    ok = envelope(ans((1, 'true', 'scripts/a.ps1'), (2, 'unverifiable', 'plan')))
    out.append(('exit 0 when nothing is false or failed', exit_of(run_of([ok], [[1, 2]],
                                                                           root=root)) == 0))
    with open(os.path.join(tmp, 'out.json'), encoding='utf-8') as f:
        written = json.load(f)
    out.append(('ledger JSON written', len(written['ledger']) == 2 and 'honest_count' in written))
    out.append(('exit 1 on a false claim', exit_of(run_of(
        [envelope(ans((1, 'false', 'x')))], [[1]], root=root)) == 1))
    out.append(('exit 1 on a deterministic-false', exit_of(run_of(
        [ok], [[1, 2]], det=[{'finding': 'FAIL x at line 9', 'line': 9}], root=root)) == 1))
    out.append(('exit 1 on a verifier-failed', exit_of(run_of(
        [envelope('no')], [[1]], root=root)) == 1))
    p = subprocess.run([sys.executable, '-I', REPORT], capture_output=True, text=True, timeout=30)
    out.append(('report usage exit 2', p.returncode == 2))
    doc = os.path.join(root, 'doc.md')
    p = subprocess.run([sys.executable, '-I', EXTRACT, doc, '--root', root, '--max', '3',
                        '--skip-lines', '17'], capture_output=True, text=True, timeout=30,
                       encoding='utf-8')
    cs = json.loads(p.stdout) if p.returncode == 0 else []
    out.append(('extractor CLI --max and --skip-lines', len(cs) == 3 and
                not any(c['line'] <= 17 <= c['end'] for c in cs)))
    p = subprocess.run([sys.executable, '-I', EXTRACT, doc, '--root', root], capture_output=True,
                       text=True, timeout=30, encoding='utf-8')
    out.append(('extractor CLI prints the plan-section count to stderr', p.returncode == 0 and
                p.stderr.strip() == 'plan-section claims skipped: 2'))
    p = subprocess.run([sys.executable, '-I', EXTRACT, doc, '--max'], capture_output=True,
                       text=True, timeout=30)
    out.append(('extractor usage exit 2', p.returncode == 2))
    old_path = os.path.join(tmp, 'old.verify.json')
    exit_of(run_of([envelope(ans((1, 'true', 'sub/b.py'))), envelope('no')], [[1], [2]],
                   root=root))
    os.replace(os.path.join(tmp, 'out.json'), old_path)
    with open(old_path, 'rb') as f:
        before = f.read()
    p = subprocess.run([sys.executable, '-I', REPORT, '--retry', old_path], capture_output=True,
                       text=True, timeout=30, encoding='utf-8')
    out.append(('--retry CLI prints the failed claims', p.returncode == 0 and
                [c['id'] for c in json.loads(p.stdout)] == [2]))
    run = run_of([envelope(ans((2, 'true', 'sub/b.py')))], [[2]], root=root)
    run['resume'] = old_path
    code = exit_of(run)
    with open(os.path.join(tmp, 'out.json'), encoding='utf-8') as f:
        new = json.load(f)
    with open(old_path, 'rb') as f:
        same = f.read() == before
    out.append(('resume writes a new ledger, old one untouched', code == 0 and same and
                new['resumed_from'] == old_path and new['retried'] == [2] and
                new['recovered'] == [2] and len(new['ledger']) == 2))
    p = subprocess.run([sys.executable, '-I', REPORT, path, old_path], capture_output=True,
                       text=True, timeout=30)
    with open(old_path, 'rb') as f:
        same = f.read() == before
    out.append(('resume refuses to overwrite the old ledger', p.returncode == 2 and same))
    return out


def main():
    root = tempfile.mkdtemp(prefix='vcr-root-')
    tmp = tempfile.mkdtemp(prefix='vcr-out-')
    try:
        return tests(os.path.realpath(root), os.path.realpath(tmp))
    finally:
        shutil.rmtree(root)
        shutil.rmtree(tmp)


def tests(root, tmp):
    outside = os.path.basename(tmp)
    os.makedirs(os.path.join(root, 'scripts'))
    os.makedirs(os.path.join(root, 'sub'))
    for rel, body in (('scripts/a.ps1', A_PS1), ('sub/b.py', 'y\n'),
                      ('doc.md', doc_text(outside))):
        with open(os.path.join(root, rel), 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    with open(os.path.join(tmp, 'secret.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('outside secret line one\n')
    x, r = load(EXTRACT), load(REPORT)
    cases = (extractor_cases(x, root, outside) + report_cases(r, root, outside)
             + resume_cases(r, root, tmp) + cli_cases(root, tmp))
    # mutation pins: each mutant must turn at least one of the named cases red
    skip_mut = load(EXTRACT, ' or any(first <= n <= last for n in skip)', '')
    red = [n for n, ok in extractor_cases(skip_mut, root, outside) if not ok]
    cases.append(('pin: skip-lines removed -> red', 'skip-lines drops every claim spanning '
                  'the line' in red))
    plan_mut = load(EXTRACT, '            if u[2]:\n                planned += 1\n'
                    '                continue\n', '')
    red = [n for n, ok in extractor_cases(plan_mut, root, outside) if not ok]
    cases.append(('pin: plan-section skip removed -> red',
                  'plan-section claims skipped and counted' in red))
    lvl_mut = load(EXTRACT, 'if not (plan and lvl > plan_lvl):', 'if True:')
    red = [n for n, ok in extractor_cases(lvl_mut, root, outside) if not ok]
    cases.append(('pin: heading level ignored -> red',
                  'a child heading under a plan heading stays skipped' in red))
    verdict_mut = load(REPORT, "any(isinstance(a, dict) and 'verdict' in a for a in got)",
                       'True')
    red = [n for n, ok in report_cases(verdict_mut, root, outside) if not ok]
    cases.append(('pin: verdict-key filter removed -> red',
                  'an array without a verdict after the answer does not win' in red))
    conf_mut = load(REPORT, 'if any(q in window for q in quotes):', 'if quotes:')
    red = [n for n, ok in report_cases(conf_mut, root, outside) if not ok]
    cases.append(('pin: quote-confirm removed -> red', 'not confirmed 4 lines away' in red))
    retry_mut = load(REPORT, " if c['id'] in failed]", ']')
    red = [n for n, ok in resume_cases(retry_mut, root, tmp) if not ok]
    cases.append(('pin: resend filter removed -> red',
                  'retry lists only verifier-failed claims' in red))
    keep_mut = load(REPORT, '            if cid in keep:\n                continue\n', '')
    red = [n for n, ok in resume_cases(keep_mut, root, tmp) if not ok]
    cases.append(('pin: keep-decided removed -> red', 'resume keeps decided verdicts' in red))
    fails = [n for n, ok in cases if not ok]
    for n in fails:
        print(f'FAIL {n}')
    print(f'{len(cases) - len(fails)}/{len(cases)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
