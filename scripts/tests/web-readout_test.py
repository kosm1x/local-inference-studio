"""Unit tests for scripts/web-readout.py.
Run: python -I scripts/tests/web-readout_test.py

Synthetic transcripts are written to a temp dir laid out like a web-session log
(`<run>/projects/-work/*.jsonl`, a history.jsonl and an mcp-logs dir beside it).
Nothing under logs/ is read. Exit 0 = all pass.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'web-readout.py')
spec = importlib.util.spec_from_file_location('web_readout', SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def ts(m):
    return f'2026-01-01T10:{m:02d}:00.000Z'


def use(m, uid, name='Bash', **inp):
    return {'type': 'assistant', 'timestamp': ts(m), 'message': {'content': [
        {'type': 'tool_use', 'id': uid, 'name': name, 'input': inp}]}}


def block(uid, text, err):
    return {'type': 'tool_result', 'tool_use_id': uid, 'is_error': err, 'content': text}


def res(m, uid, text, err=False, kind=None, extra=()):
    row = {'type': 'user', 'timestamp': ts(m), 'message': {'content': [
        block(uid, [{'type': 'text', 'text': text}] if m % 2 and isinstance(text, str)
              else text, err), *extra]}}
    if kind:
        row['toolDenialKind'] = kind
    return row


def hook(tool, name, reason):
    return f'PreToolUse:{tool} hook error: {name}: {reason}'


TOKEN = 'sk-' + 'x1' * 12
KEY40 = 'abcdefghij' * 4
RM = 'echo proof-x'
PR = 'permission-rule'
LEAD = [{'type': 'image', 'source': {}},                    # leading non-text block
        {'type': 'text', 'text': '\n  ' + hook('Bash', 'repeat-guard', 'same command again')}]
# (Bash command, exact --grep verdict) in call order
CALLS = [('ls -la', 'allowed'), ('echo proof-post', 'denied:' + PR),
         (RM, 'denied:lis-guard'), (RM, 'denied:lis-guard'), (RM, 'denied:repeat-guard'),
         ('echo proof-push', 'denied:automode-blocked'), ('make build', 'ran:error'),
         ('echo <masked>', 'allowed'), ('ls -la', 'allowed'), (RM, 'allowed'),
         ('cat a', 'allowed'), ('pwd', 'denied?:' + PR), ('id', 'denied?:' + PR),
         ('whoami', 'allowed'), ('date', 'no-result')]


def rows():
    r = [{'type': 'system', 'subtype': 'init'},             # no timestamp
         use(1, 'u1', command='ls -la'), res(1, 'u1', 'total 0'),
         use(2, 'u2', command='echo proof-post'),
         res(2, 'u2', 'Permission to use Bash with command curl', True, PR),
         use(3, 'u3', command=RM),                           # hook name wins over the kind
         res(3, 'u3', hook('Bash', 'lis-guard', 'proof-x matched; critical'), True, PR),
         use(4, 'u4', command=RM),
         res(4, 'u4', hook('Bash', 'lis-guard', 'proof-x matched; critical'), True, PR),
         use(5, 'u5', command=RM), res(5, 'u5', LEAD, True),
         use(6, 'u6', command='echo proof-push'),
         res(6, 'u6', 'Permission for this action was denied by the classifier', True,
             'automode-blocked'),
         {'type': 'system', 'subtype': 'compact_boundary', 'timestamp': ts(7)},
         {'type': 'user', 'isCompactSummary': True, 'timestamp': ts(7),
          'message': {'content': 'summary'}},
         use(8, 'u8', 'Read', file_path='a.txt'), res(8, 'u8', 'abc'),
         use(9, 'u9', 'mcp__web__search', query='q'),
         res(9, 'u9', hook('mcp__web__search', 'loop guard', 'this exact call 3 times'), True,
             PR),
         use(10, 'u10', 'mcp__web__read', url='u'), res(10, 'u10', '{"error":"422"}', True),
         use(11, 'u11', command='make build'),
         res(11, 'u11', 'Exit code 2\nmake: *** error', True),
         use(12, 'u12', command='echo ' + TOKEN), res(12, 'u12', TOKEN),
         use(13, 'u13', command='ls -la'), res(13, 'u13', 'total 0'),
         use(14, 'u14', command=RM), res(14, 'u14', 'Exit code 1', 1),        # 1 is not True
         use(15, 'u15', command='cat a'),
         res(15, 'u15', hook('Bash', 'lis-guard', 'not an error result')),   # not a denial
         use(16, 'u16', command='pwd'), res(16, 'u16', '/w', False, PR),     # kind, no error
         use(17, 'u17', command='id'), use(17, 'u18', command='whoami'),
         res(17, 'u17', 'Permission to use Bash', True, PR, [block('u18', 'root', False)]),
         use(18, 'u19', command='date'),                                     # unpaired
         use(18, 'u20', 'mcp__web__read', url='v'), res(18, 'u20', 'ok'),  # mcp, no error
         use(19, None, command='ls -la'), use(19, ['x'], command='ls -la'),  # bad ids skipped
         use(19, '', command='ls -la'),
         res(19, ['x'], 'Exit code 9', True), res(19, None, 'Exit code 9', True),
         # an api-request-blob repeats message content: it must not count
         {'type': 'api-request-blob', 'toolDenialKind': PR, 'message': {'content': [
             {'type': 'tool_use', 'id': 'u1', 'name': 'Bash', 'input': {'command': 'ls'}},
             {'type': 'tool_result', 'tool_use_id': 'u3', 'is_error': True,
              'content': hook('Bash', 'lis-guard', 'dup')}]}}]
    lines = [json.dumps(x) for x in r[:3]] + ['{not json', '[1, 2]', ''] + \
        [json.dumps(x) for x in r[3:]]
    return lines, r


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def cli(*args):
    return subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True,
                          text=True, encoding='utf-8', timeout=30)


def comp(path, boundaries, summaries):
    write(path, [json.dumps({'type': 'system', 'subtype': 'compact_boundary'})] * boundaries
          + [json.dumps({'type': 'user', 'isCompactSummary': True})] * summaries)
    return w.readout(path)['compactions']


def tests(tmp):
    box = os.path.join(tmp, 'mcp-logs-box')        # an mcp-logs name ABOVE the given root
    run = os.path.join(box, 'web-1', 'home', 'cfg')
    t1 = os.path.join(run, 'projects', '-work', 'a.jsonl')
    lines, dicts = rows()
    write(t1, lines)
    write(os.path.join(run, 'projects', '-work', 'b.jsonl'), [json.dumps(use(1, 'z', 'Grep'))])
    write(os.path.join(run, 'history.jsonl'), ['{}'])
    write(os.path.join(run, 'projects', 'history.jsonl'), ['{}'])
    write(os.path.join(box, 'web-1', 'cache', 'projects', 'mcp-logs-x', 'c.jsonl'), ['{}'])
    write(os.path.join(box, 'web-1', 'other', 'd.jsonl'), ['{}'])
    write(os.path.join(tmp, 'projects', 'run', 'other', 'e.jsonl'), ['{}'])
    os.makedirs(os.path.join(tmp, 'empty'))
    t3 = os.path.join(tmp, 'h.jsonl')
    long_hook, key_hook = 'hook ' * 12, 'sk-' + 'q9' * 5
    write(t3, [json.dumps(x) for x in (
        use(1, 'a', command='x'), res(1, 'a', hook('Bash', long_hook, 'r'), True),
        use(2, 'b', command='y'), res(2, 'b', hook('Bash', key_hook, 'r'), True),
        use(3, 'c', command='echo w1'),          # hook text NOT at the start: no denial
        res(3, 'c', 'Exit code 1\n' + hook('Bash', 'lis-guard', 'x'), True),
        use(4, 'd', command='echo k1'), res(4, 'd', 'Permission denied', True, key_hook),
        use(5, 'e', command='echo k2'), res(5, 'e', 'Permission denied', True, long_hook))])
    c3 = os.path.join(tmp, 'c3.jsonl')
    write(c3, [json.dumps({'type': 'user', 'isCompactSummary': v}) for v in (1, 'true')])
    r = w.readout(t1)
    grep = w.readout(t1, rx=w.re.compile(''))['grep']
    stamped = [d for d in dicts if isinstance(d.get('timestamp'), str)]
    s = w.readout(t1, since=w.when(ts(8)))
    s2 = w.readout(t1, since=w.when('2026-01-01T11:08:00+01:00'))
    h3 = w.readout(t3, rx=w.re.compile(''))
    text = w.text_of(w.readout(t1, rx=w.re.compile('echo')))
    rel = [os.path.relpath(p, box).replace('\\', '/') for p in w.find(box)]
    js = cli(t1, '--json', '--grep', 'ls')
    obj = json.loads(js.stdout) if js.returncode == 0 else {}
    js3 = cli(t3, '--json', '--grep', '.')
    plain = cli(os.path.join(box, 'web-1'))
    bad_since, bad_rx = cli(t1, '--since', 'yesterday'), cli(t1, '--grep', '(')
    jwt, slash = 'eyJhbGci.eyJzdWIi.c2ln', 'Zk8Qw3Lm9Tx2/Vb7Np4Rs6Hj1Yc5Df0Ga8Ke3Uo'
    straddle = w.clip('word ' * 22 + KEY40, 120)
    UUID = '12345678-1234-1234-1234-123456789abc'
    path = '/usr/lib/x86_64-linux-gnu/libzstd.so.1 src/client/components/BoardView.tsx'
    return [
        ('tools counted by name; blob rows and bad ids ignored',
         r['tools'] == {'Bash': 15, 'Read': 1, 'mcp__web__search': 1, 'mcp__web__read': 2}),
        ('denial rows counted by kind', r['denials'] == {PR: 6, 'automode-blocked': 1}),
        ('hook denials by hook (leading whitespace and non-text block tolerated)',
         r['hook_denials'] == {'lis-guard': 2, 'repeat-guard': 1, 'loop guard': 1}),
        ('hook reasons grouped with counts',
         r['hook_reasons'][0] == ['lis-guard', 'proof-x matched; critical', 2]),
        ('other errors are ran:error results only',
         sorted(t for t, _ in r['other_errors']) == ['Exit code 2 | make: *** error',
                                                     '{"error":"422"}']),
        ('compaction boundary + summary count once', r['compactions'] == 1),
        ('compactions: 2 boundaries / 1 summary', comp(os.path.join(tmp, 'c1'), 2, 1) == 2),
        ('compactions: 1 boundary / 2 summaries', comp(os.path.join(tmp, 'c2'), 1, 2) == 2),
        ('a truthy non-True isCompactSummary does not count', w.readout(c3)['compactions'] == 0),
        ('longest run is consecutive only (a later repeat does not add)',
         r['identical_bash_run'] == {'count': 3, 'command': RM}),
        ('mcp error count', r['mcp_errors'] == 2),
        ('malformed lines counted, blank skipped',
         r['malformed'] == 2 and r['rows'] == len(dicts)),
        ('first/last and duration', r['first'] == ts(1) and r['last'] == ts(19)
         and r['duration'] == '0h18m'),
        ('--since drops earlier and unstamped rows',
         s['first'] == ts(8) and s['rows'] == sum(d['timestamp'] >= ts(8) for d in stamped)
         and s['compactions'] == 0 and s['denials'] == {PR: 3} and s['tools']['Bash'] == 9),
        ('--since compares datetimes, not strings', s2 == s),
        ('--grep: one row per call, each with its exact verdict',
         [(g['command'], g['verdict']) for g in grep] == [(c, v) for c, v in CALLS]),
        ('--grep: unpaired call has an empty result', grep[-1]['result'] == ''),
        ('hook name clipped to 40 chars everywhere',
         list(h3['hook_denials'])[0] == w.clip(long_hook, 40) and
         len(h3['hook_reasons'][0][0]) == 40 and h3['grep'][0]['verdict'] ==
         'denied:' + w.clip(long_hook, 40)),
        ('key-like hook name masked in text and --json', h3['grep'][1]['verdict'] ==
         'denied:<masked>' and js3.returncode == 0 and key_hook not in js3.stdout
         and key_hook not in w.text_of(h3)),
        ('an error whose hook text is not at the start is ran:error',
         h3['grep'][2]['verdict'] == 'ran:error' and len(h3['hook_denials']) == 2),
        ('toolDenialKind clipped and masked', h3['denials'] == {'<masked>': 1,
                                                               w.clip(long_hook, 40): 1}
         and [g['verdict'] for g in h3['grep'][3:]] == ['denied:<masked>',
                                                       'denied:' + w.clip(long_hook, 40)]),
        ('a known prefix after = masked', w.clip('X=sk-abc', 99) == 'X=<masked>'),
        ('token-like values masked in text', TOKEN not in text and '<masked>' in text),
        ('prefix-less letters-only key masked', w.clip('k ' + KEY40, 99) == 'k <masked>'),
        ('JWT masked by its prefix', w.clip('t ' + jwt, 99) == 't <masked>'),
        ('slash secret masked', w.clip(slash, 99) == '<masked>'
         and w.clip(slash.replace('/', '+'), 99) == '<masked>'),
        ('mask before truncation', KEY40[:5] not in straddle and straddle.endswith('<masked>')),
        ('UUID and 40-hex masked', w.clip(UUID + ' ' + 'ab12' * 10, 99) == '<masked> <masked>'),
        ('ordinary long paths stay readable', w.clip(path, 99) == path),
        ('a path with a 32+ char part masked', w.clip('/w/' + KEY40 + '/x', 99) == '<masked>'),
        ('a slash run with + or = masked', w.clip('/a/b/' + 'c+d' * 10, 99) == '<masked>'
         and w.clip('/a/b/' + 'c=d' * 10, 99) == '<masked>'),
        ('long text truncated', len(w.clip('y ' * 200, 120)) == 120),
        ('discovery judges projects/mcp-logs below the root',
         rel == ['web-1/home/cfg/projects/-work/a.jsonl',
                 'web-1/home/cfg/projects/-work/b.jsonl']
         and w.find(os.path.join(tmp, 'projects', 'run')) == []),
        ('discovery from a root named projects', [os.path.relpath(p, run).replace('\\', '/')
                                                  for p in w.find(os.path.join(run, 'projects'))]
         == ['projects/-work/a.jsonl', 'projects/-work/b.jsonl']),
        ('--json prints one object with grep matches', js.returncode == 0 and
         obj.get('grep', [{}])[0].get('verdict') == 'allowed' and obj.get('rows') == len(dicts)),
        ('text mode prints every transcript', plain.returncode == 0 and
         plain.stdout.count('== ') == 2 and 'tools: Grep 1' in plain.stdout),
        ('bad --since exits 2 without a traceback',
         bad_since.returncode == 2 and 'Traceback' not in bad_since.stderr),
        ('bad --grep regex exits 2 without a traceback',
         bad_rx.returncode == 2 and 'Traceback' not in bad_rx.stderr),
        ('--since with a trailing Z accepted', cli(t1, '--since', ts(8)).returncode == 0),
        ('exit 2 on a missing path', cli(os.path.join(tmp, 'nope')).returncode == 2),
        ('exit 2 on a directory without transcripts',
         cli(os.path.join(tmp, 'empty')).returncode == 2),
    ]


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix='wro-'))
    try:
        cases = tests(tmp)
    finally:
        shutil.rmtree(tmp)
    fails = [n for n, ok in cases if not ok]
    for n in fails:
        print(f'FAIL {n}')
    print(f'{len(cases) - len(fails)}/{len(cases)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
