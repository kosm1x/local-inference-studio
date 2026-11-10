"""Unit tests for scripts/hooks/repeat-guard.py.
Run: python -I scripts/hooks/tests/repeat-guard_test.py [hook]

Exit 0 = all pass. The optional argument is a hook file to test instead of the default.
The RATIO and MIN_SIMILAR mutants are pinned in-suite below (their red checks are printed).
Fixtures (fixtures/repeat-loop-*.jsonl) are the two attractor loops of the 2026-11-10 UTC web
session, reduced to assistant text, tool names and short user prompts; turn_duration rows
mark where a real Stop fired. End-to-end cases run the hook as Claude Code does (stdin
JSON, python -I) with TEMP/TMP/TMPDIR pointed at a throwaway directory.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
        else os.path.join(HERE, '..', 'repeat-guard.py'))
spec = importlib.util.spec_from_file_location('repeat_guard', HOOK)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
FIX = os.path.join(HERE, 'fixtures')
CHECKS = [0]
VERBOSE = [True]

HEALTHY = [
    'I read src/server/index.ts and the route table: /api/puzzles is registered after the '
    'static middleware, so a request for it never reaches the handler.',
    'Moving the API router above express.static fixed the 404. The puzzles endpoint now '
    'returns 200 with a JSON array of ten entries when I query it with curl.',
    'Next I ran the unit tests. Two fail in board.test.ts: the en passant case expects the '
    'captured pawn to be removed from the square behind the target, and it is not.',
    'The bug is in applyMove: it clears the destination square of the capture instead of '
    'the square one rank behind it. I changed the index arithmetic for both colours.',
    'All board tests pass now (forty one of forty one). I also added a case for a black en '
    'passant capture on the a-file, since the edge column was not covered before.',
    'Looking at the frontend next: the puzzle view renders the board but the move list is '
    'empty because the component reads data.moves while the API sends data.solution.',
    'I renamed the field on the client side rather than the server, because the database '
    'schema and two other consumers already use solution as the column name.',
    'The dev server reloads cleanly after the change and the move list shows the expected '
    'three moves for the first puzzle. Nothing in the console reports an error.',
    'Remaining work from the plan: rating updates after a solved puzzle and the daily '
    'streak counter. Neither is started; both need a small migration first.',
    'Summary: fixed the router order, the en passant capture and the field name; tests '
    'pass; the migration for ratings is the next step and needs your go-ahead.',
]


def load(name):
    with open(os.path.join(FIX, name), encoding='ascii') as f:
        return [json.loads(x) for x in f if x.strip()]


def row(text, mid, tool=True):
    c = [{'type': 'text', 'text': text}] + ([{'type': 'tool_use', 'name': 'Bash'}] if tool else [])
    return {'type': 'assistant', 'message': {'id': mid, 'role': 'assistant', 'content': c}}


def rows_of(texts):
    return [row(t, f'h{i:03d}') for i, t in enumerate(texts)]


def replay(rows):
    """Evaluate the rule after every assistant row, as if a Stop fired there, with no
    stored state. Returns [(text-turn number, similar count, ratios)] for every row that
    would block."""
    out = []
    for i, r in enumerate(rows):
        if r.get('type') != 'assistant':
            continue
        texts = g.turn_texts(rows[:i + 1])
        n = g.similar(texts)
        if n and not (out and out[-1][0] == len(texts)):
            out.append((len(texts), n, [round(x, 3) for x in g.ratios(texts)]))
    return out


def replay_events(rows):
    """The registered events in order, with the stored state carried between them: a
    PostToolUse after every assistant row holding a tool_use (the row is on disk before
    its tool_result row), a Stop at every turn_duration row. Returns
    [(fixture row number, event, text-turn number, similar count)] for every block and
    the fixture row numbers where the stored text was cleared."""
    stored, blocks, cleared = None, [], []
    for i, r in enumerate(rows):
        c = (r.get('message') or {}).get('content')
        post = r.get('type') == 'assistant' and isinstance(c, list) and any(
            b.get('type') == 'tool_use' for b in c)
        stop = r.get('type') == 'system' and r.get('subtype') == 'turn_duration'
        if not (post or stop):
            continue
        texts = g.turn_texts(rows[:i + 1])
        n, new = g.step(texts, stored)
        if n:
            blocks.append((i + 1, 'post' if post else 'stop', len(texts), n))
        elif stored is not None and new is None:
            cleared.append(i + 1)
        stored = new
    return blocks, cleared


def core(fail):
    """Rule cases. fail(name) records a failure. Used on the real module and on mutants."""
    def want(name, got, exp):
        CHECKS[0] += 1
        if got != exp:
            fail(f'{name}: want {exp} got {got}')

    fens = load('repeat-loop-fens.jsonl')
    texts = g.turn_texts(fens)
    loop = [k + 1 for k, t in enumerate(texts) if t.startswith("i'm clearly in a loop.")]
    b = replay(fens)
    if VERBOSE[0]:
        print(f'fens: {len(texts)} text turns, loop turns {loop[:3]}..., blocks at '
              f'text-turn {b[0][0] if b else None} similar {b[0][1] if b else None} '
              f'ratios {b[0][2] if b else None}')
    want('fens: first block at the 3rd near-identical turn', b[0][0] if b else None, loop[2])
    want('fens: that block counts 3 similar turns', b[0][1] if b else None, 3)
    want('fens: no block before it', [x for x in b if x[0] < loop[2]], [])
    want('fens: every later turn to the 13th blocks (14 and 15 are 961 chars, 0.739 to the '
         '1236-char ones; the 16th is 395 chars)', [x[0] for x in b], list(range(loop[2], 14)))
    watch = load('repeat-loop-watch.jsonl')
    b = replay(watch)
    if VERBOSE[0]:
        print(f'watch: blocks at text-turns {[x[0] for x in b]}; first similar '
              f'{b[0][1] if b else None} ratios {b[0][2] if b else None}')
    want('watch: first block at text-turn 9 (05:33:38)', b[0][0] if b else None, 9)
    want('watch: blocks at 9, 12, 14 (16 and 17: 2 similar with digits and whole texts)',
         [x[0] for x in b], [9, 12, 14])
    want('watch: first block counts 3 similar turns', b[0][1] if b else None, 3)
    # PostToolUse + Stop in order, state carried: one warning per run of similar replies
    b, cl = replay_events(fens)
    if VERBOSE[0]:
        print(f'events fens: blocks (row, event, text-turn, similar) {b}; cleared at rows {cl}')
    want('events fens: one block, PostToolUse at row 11 (text-turn 5, 03:00:36)',
         b, [(11, 'post', 5, 3)])
    want('events fens: a 961-char loop reply (0.739 to the 1236-char ones) clears at row 30',
         cl, [30])
    b, cl = replay_events(watch)
    if VERBOSE[0]:
        print(f'events watch: blocks (row, event, text-turn, similar) {b}; cleared at rows {cl}')
    want('events watch: PostToolUse blocks at rows 25, 32, 36 (text-turns 9, 12, 14)',
         [(x[0], x[1], x[2]) for x in b],
         [(25, 'post', 9), (32, 'post', 12), (36, 'post', 14)])
    want('events watch: each re-block follows a reply under RATIO to the stored text',
         cl, [27, 34, 38])
    p = g.normalize(HEALTHY[0])
    x = g.normalize(HEALTHY[1])
    seq, stored, got = [p, p, p], None, []
    for t in ([], [p], [x], [p]):          # block, suppressed, changed (clears), re-armed
        seq = seq + t
        n, stored = g.step(seq, stored)
        got.append((n, stored is not None))
    want('step: block, same loop suppressed, a changed reply clears, the loop re-blocks',
         got, [(3, True), (0, True), (0, False), (5, True)])
    want('step: stored text is the latest turn compared text',
         g.step([p] * 3, None)[1], g.key(p))
    long = ''.join(f'w{i} ' for i in range(400))
    want('key: a text over PREFIX + SUFFIX is its head and tail',
         g.key(long), long[:g.PREFIX] + long[-g.SUFFIX:])
    want('key: a text of PREFIX + SUFFIX chars or less is whole', g.key(long[:1000]), long[:1000])
    want('key: a changed tail of a long text counts',
         round(g.ratio(long, long[:-300] + 'z' * 300), 2) < g.RATIO, True)
    # the auditor's false positive (a local-model run, 2026-10-26): templated status
    # replies with different file names and numbers are not a loop
    fp = [g.normalize(f'{a} is {n} lines (read in one pass, complete; Read shows a trailing '
                      f'empty line {n + 1}, wc-style count is {n}). {b} is {m} lines (read in '
                      f'one pass, complete; Read shows a trailing empty line {m + 1}, '
                      f'wc-style count is {m}).')
          for a, n, b, m in (('scripts/claude-local.ps1', 187, 'config/x.jinja', 182),
                             ('bench/README.md', 172, 'bench/perm/run.ps1', 143),
                             ('scripts/serve.ps1', 127, 'docs/evaluation-2026-10-24.md', 118),
                             ('docs/landscape-2026-10-24.md', 114, 'scripts/install.ps1', 86),
                             ('bench/perm/corpus.jsonl', 86, 'scripts/smoke.ps1', 82))]
    want('templated replies with different names and numbers: no block', g.similar(fp), 0)
    want('healthy: 10 varied turns never block', replay(rows_of(HEALTHY)), [])
    want('healthy: no event blocks', replay_events(rows_of(HEALTHY)), ([], []))
    want('healthy: 10 varied turns read as 10 turns', len(g.turn_texts(rows_of(HEALTHY))), 10)
    para = HEALTHY[0]
    want('three identical long turns block', g.similar([g.normalize(para)] * 3), 3)
    want('two identical long turns do not block', g.similar([g.normalize(para)] * 2), 0)
    short = 'I am going to check the server log again now. ' * 2   # 94 chars
    want('short identical turns never block', g.similar([g.normalize(short)] * 6), 0)
    want('3 similar in the last 6 (not adjacent) block',
         g.similar([g.normalize(t) for t in [para, HEALTHY[1], para, HEALTHY[2], HEALTHY[3],
                                             para]]), 3)
    want('a similar turn 7 back is outside the window',
         g.similar([g.normalize(t) for t in [para, para] + HEALTHY[1:6] + [para]]), 0)
    want('backticks are ignored',
         g.similar([g.normalize(para.replace('route', r)) for r in ('`route`', 'route', '`route')]),
         3)
    want('digits count', g.normalize('Ran 12 `tests`'), 'ran 12 tests')
    # one message id spread over several rows is one turn; tool-only and sidechain rows skip
    split = [row(HEALTHY[0], 'x1'), {'type': 'assistant', 'message': {
        'id': 'x1', 'content': [{'type': 'text', 'text': 'and more'}]}},
             {'type': 'assistant', 'message': {'id': 'x2', 'content': [
                 {'type': 'tool_use', 'name': 'Read'}]}},
             dict(row(HEALTHY[1], 'x3'), isSidechain=True), {'type': 'user', 'message': {
                 'content': HEALTHY[2]}}]
    want('rows of one message id join; tool-only, sidechain and user rows skip',
         g.turn_texts(split), [g.normalize(HEALTHY[0] + '\nand more')])
    want('an agent transcript (main=False) keeps its sidechain rows',
         g.turn_texts(split, main=False),
         [g.normalize(HEALTHY[0] + '\nand more'), g.normalize(HEALTHY[1])])
    err = [row(HEALTHY[0], 'e1'), dict(row(HEALTHY[1], 'e2'), isApiErrorMessage=True),
           {'type': 'assistant', 'message': {'id': 'e3', 'model': '<synthetic>', 'content': [
               {'type': 'text', 'text': HEALTHY[2]}]}}]
    want('API error and <synthetic> assistant rows skip', g.turn_texts(err),
         [g.normalize(HEALTHY[0])])
    want('output: PostToolUse, Stop, SubagentStop take top-level decision block',
         [g.output(ev, 'r') for ev in ('PostToolUse', 'Stop', 'SubagentStop')],
         [{'decision': 'block', 'reason': 'r'}] * 3)
    want('output: PostToolUseFailure takes hookSpecificOutput.additionalContext',
         g.output('PostToolUseFailure', 'r'),
         {'hookSpecificOutput': {'hookEventName': 'PostToolUseFailure', 'additionalContext': 'r'}})
    r = g.reason(4)
    CHECKS[0] += 1
    if not (r.startswith('repeat guard: your last 4 replies are near-identical.')
            and 'Do not restate it.' in r and r.endswith('Then stop.')
            and all(ord(ch) < 128 for ch in r)):
        fail(f'reason wording: {r!r}')


def run_hook(env, payload, raw=None):
    inp = raw if raw is not None else json.dumps(payload).encode('utf-8')
    r = subprocess.run([sys.executable, '-I', HOOK], input=inp, capture_output=True,
                       env=env, timeout=30)
    out = r.stdout.decode('ascii', 'replace').strip()
    dec = json.loads(out) if out else None
    return r.returncode, dec, r.stderr.decode('utf-8', 'replace')


def e2e(fail):
    def want(name, got, exp):
        CHECKS[0] += 1
        if got != exp:
            fail(f'e2e {name}: want {exp} got {got}')

    with tempfile.TemporaryDirectory() as t:
        env = dict(os.environ, TEMP=t, TMP=t, TMPDIR=t)
        sd = os.path.join(t, 'lis-repeat-guard')

        def write(name, rows):
            p = os.path.join(t, name)
            with open(p, 'w', encoding='utf-8', newline='\n') as f:
                f.writelines(json.dumps(x) + '\n' for x in rows)
            return p

        def stop(sid, path, **kw):
            p = dict({'session_id': sid, 'transcript_path': path, 'cwd': t,
                      'hook_event_name': 'Stop', 'stop_hook_active': False}, **kw)
            rc, dec, err = run_hook(env, p)
            if rc != 0 or 'Traceback' in err:
                fail(f'e2e {sid}: rc={rc} err={err[:160]!r}')
            return dec.get('decision') if isinstance(dec, dict) else dec

        fens = load('repeat-loop-fens.jsonl')
        cut = [i for i, r in enumerate(fens) if r.get('subtype') == 'turn_duration']
        last = [b['text'] for b in fens[cut[0] - 1]['message']['content'] if b['type'] == 'text']
        stop1 = write('fens-stop1.jsonl', fens[:cut[0]])
        rc, dec, _ = run_hook(env, {'session_id': 's0', 'transcript_path': stop1,
                                    'hook_event_name': 'Stop', 'stop_hook_active': False,
                                    'last_assistant_message': last[0]})
        want('fens: the real Stop at 03:09:08 passes (2 of its last 6 replies are 961 chars)',
             dec, None)
        real = write('fens-loop.jsonl', fens[:27])   # through text-turn 13, 03:08:34
        rc, dec, _ = run_hook(env, {'session_id': 's1', 'transcript_path': real,
                                    'hook_event_name': 'Stop', 'stop_hook_active': False})
        want('fens: a Stop after text-turn 13 blocks', (dec or {}).get('decision'), 'block')
        want('fens: the reason counts 6 replies', (dec or {}).get('reason', '').startswith(
            'repeat guard: your last 6 replies are near-identical.'), True)
        s1 = os.path.join(sd, 's1.json')
        want('fens: a block stores the latest turn compared text',
             g.load(s1) if os.path.exists(s1) else None, g.key(g.turn_texts(fens[:27])[-1]))
        want('the same loop again: suppressed', stop('s1', real), None)
        want('the state stays while the loop text is the latest turn', os.path.exists(s1), True)
        changed = write('fens-changed.jsonl', fens[:27] + [row(HEALTHY[0], 'zz1')])
        want('a changed reply: no block', stop('s1', changed), None)
        want('a changed reply clears the state (re-armed)', os.path.exists(s1), False)
        want('re-armed: the loop blocks again', stop('s1', real), 'block')
        want('session_id case shares one state (S1 after the s1 block: suppressed)',
             stop('S1', real), None)
        want('stop_hook_active true: no block, even with no state',
             stop('s2', real, stop_hook_active=True), None)
        want('stop_hook_active true writes no state', os.path.exists(os.path.join(sd, 's2.json')),
             False)
        s2 = os.path.join(sd, 's2.json')

        def read(p):
            if not os.path.exists(p):
                return None
            with open(p, 'rb') as f:
                return f.read()

        stop('s2', real)
        before = read(s2)
        want('a block writes the s2 state', before is not None, True)
        want('stop_hook_active true with a changed reply: no block',
             stop('s2', changed, stop_hook_active=True), None)
        want('stop_hook_active true leaves the state alone', read(s2), before)
        # PostToolUse: the same transcript fields; the output is top-level decision block
        post = dict(hook_event_name='PostToolUse', tool_name='Bash', tool_input={'command': 'ls'},
                    tool_response={'stdout': '', 'stderr': ''}, tool_use_id='toolu_x')
        pre = write('fens-post.jsonl', fens[:11])
        rc, dec, _ = run_hook(env, dict({'session_id': 's16', 'transcript_path': pre}, **post))
        want('PostToolUse at fixture row 11: {decision: block, reason} only',
             sorted(dec) if isinstance(dec, dict) else dec, ['decision', 'reason'])
        want('PostToolUse: the next call in the same loop is suppressed',
             stop('s16', write('fens-post2.jsonl', fens[:13]), **post), None)
        want('PostToolUse at row 9 (text-turn 4, 2 identical turns): no block',
             stop('s17', write('fens-post0.jsonl', fens[:9]), **post), None)
        want('PostToolUse inside an agent (agent_id set): no decision',
             stop('s19', pre, agent_id='a9', agent_type='general-purpose', **post), None)
        want('PostToolUse inside an agent writes no state', read(os.path.join(sd, 's19.json')),
             None)
        fail_ev = dict(hook_event_name='PostToolUseFailure', tool_name='Bash',
                       tool_input={'command': 'ls'}, tool_use_id='toolu_y',
                       error='Command exited with non-zero status code 1', is_interrupt=False)
        rc, dec, _ = run_hook(env, dict({'session_id': 's20', 'transcript_path': pre}, **fail_ev))
        want('PostToolUseFailure at fixture row 11: hookSpecificOutput.additionalContext only',
             (sorted(dec), sorted(dec.get('hookSpecificOutput') or {}),
              (dec.get('hookSpecificOutput') or {}).get('hookEventName'),
              str((dec.get('hookSpecificOutput') or {}).get('additionalContext')).startswith(
                  'repeat guard: your last 3 replies')) if isinstance(dec, dict) else dec,
             (['hookSpecificOutput'], ['additionalContext', 'hookEventName'],
              'PostToolUseFailure', True))
        want('PostToolUseFailure inside an agent: no decision',
             stop('s21', pre, agent_id='a9', **fail_ev), None)
        with open(os.path.join(sd, 's18.json'), 'w') as f:
            f.write('{not json')
        want('corrupt state counts as none: the loop blocks', stop('s18', real), 'block')
        healthy = write('healthy.jsonl', rows_of(HEALTHY))
        want('healthy transcript: no block', stop('s3', healthy), None)
        para = HEALTHY[0]
        two = write('two.jsonl', rows_of([HEALTHY[1], para, para]))
        want('last_assistant_message missing from the file counts as the latest turn',
             stop('s4', two, last_assistant_message=para + ' Let me check again.'), 'block')
        want('last_assistant_message equal to the last turn is not counted twice',
             stop('s5', two, last_assistant_message='  ' + para.upper()), None)
        shorts = write('short.jsonl', rows_of(['Checking the server log once more now.'] * 6))
        want('short texts: no block', stop('s6', shorts), None)
        want('unreadable path: no decision', stop('s7', os.path.join(t, 'missing.jsonl')), None)
        want('directory as path: no decision', stop('s8', t), None)
        want('no transcript_path: no decision', stop('s9', None), None)
        # oversize input: no decision, no state
        big = json.dumps({'session_id': 's10', 'transcript_path': real, 'hook_event_name': 'Stop',
                          'pad': 'x' * (g.MAX_INPUT + 10)}).encode()
        rc, dec, err = run_hook(env, None, big)
        want('oversize input: no decision', (rc, dec), (0, None))
        want('oversize input: no state', os.path.exists(os.path.join(sd, 's10.json')), False)
        # MAX_INPUT boundary: exactly MAX_INPUT bytes are read and decided, one more is not
        base = {'session_id': 's23', 'transcript_path': real, 'hook_event_name': 'Stop', 'pad': ''}
        base['pad'] = 'x' * (g.MAX_INPUT - len(json.dumps(base).encode()))
        exact = json.dumps(base).encode()
        rc, dec, _ = run_hook(env, None, exact)
        want('input of exactly MAX_INPUT bytes: decided (block)',
             (len(exact), (dec or {}).get('decision')), (g.MAX_INPUT, 'block'))
        base['session_id'] = 's24'
        rc, dec, _ = run_hook(env, None, json.dumps(base).encode() + b' ')
        want('input of MAX_INPUT + 1 bytes: no decision', dec, None)
        # the state file name is lower-cased (NTFS would hide a case mismatch on lookup)
        stop('S25X', real)
        want('state file name is the lower-cased session id',
             [x for x in os.listdir(sd) if x.lower() == 's25x.json'], ['s25x.json'])
        # the tail: a loop at the end of a file over TAIL_BYTES blocks; one before it does not
        pad = rows_of([f'{i} ' + HEALTHY[i % 10] for i in range(4000)])
        loop = rows_of([para] * 3)
        tail1 = write('tail1.jsonl', pad + loop)
        want('tail: the padded file is over TAIL_BYTES', os.path.getsize(tail1) > g.TAIL_BYTES,
             True)
        want('tail: a loop after more than TAIL_BYTES of turns blocks', stop('s11', tail1),
             'block')
        want('tail: a loop followed by varied turns does not block',
             stop('s12', write('tail2.jsonl', loop + pad)), None)
        # SubagentStop reads agent_transcript_path (every row isSidechain: true, as in a real
        # agent transcript) and keys state by agent
        agent = write('agent.jsonl', [dict(r, isSidechain=True) for r in fens[:27]])
        sub = dict(hook_event_name='SubagentStop', agent_id='a1', agent_transcript_path=agent)
        want('SubagentStop: the agent transcript (all sidechain rows) loops -> block',
             stop('s13', healthy, **sub), 'block')
        mixed = write('mixed.jsonl', rows_of(HEALTHY)
                      + [dict(r, isSidechain=True) for r in fens[:27]])
        want('main transcript: sidechain loop rows mixed in are ignored', stop('s22', mixed),
             None)
        want('SubagentStop: state keyed by session and agent',
             os.path.exists(os.path.join(sd, 's13.a1.json')), True)
        want('SubagentStop: the main session is not suppressed by it', stop('s13', real), 'block')
        want('SubagentStop without agent_id: no decision',
             stop('s14', healthy, hook_event_name='SubagentStop', agent_transcript_path=real),
             None)
        # malformed input and unsafe session ids
        for raw in [b'', b'{not json', b'[1, 2]', b'"s"', b'\xff\xfe\x00',
                    json.dumps({'transcript_path': real}).encode(),
                    json.dumps({'session_id': '../evil', 'transcript_path': real}).encode(),
                    json.dumps({'session_id': 'a\n', 'transcript_path': real}).encode(),
                    json.dumps({'session_id': 5, 'transcript_path': real}).encode()]:
            rc, dec, err = run_hook(env, None, raw)
            CHECKS[0] += 1
            if rc != 0 or dec is not None or 'Traceback' in err:
                fail(f'e2e malformed {raw[:40]!r}: rc={rc} dec={dec} err={err[:120]!r}')
        want('no file written outside the state dir', os.path.exists(os.path.join(t, 'evil.json')),
             False)
        # prune: a 25 h old state file goes, a 1 h old one stays
        old, new = os.path.join(sd, 'old.json'), os.path.join(sd, 'new.json')
        for p, age in ((old, 25 * 3600), (new, 3600)):
            with open(p, 'w') as f:
                f.write('{}')
            os.utime(p, (os.path.getmtime(p) - age,) * 2)
        strays = [os.path.join(sd, x) for x in ('Other.json', 'a.b.c.json', 'x.txt')]
        for p in strays:                        # audit C1: not state names, never pruned
            with open(p, 'w') as f:
                f.write('{}')
            os.utime(p, (os.path.getmtime(p) - 25 * 3600,) * 2)
        stop('s15', healthy)
        want('prune', (os.path.exists(old), os.path.exists(new)), (False, True))
        want('prune keeps names that are not state names', [os.path.exists(p) for p in strays],
             [True] * 3)
        want('no tmp file left behind',
             [n for n in os.listdir(sd) if n.endswith('.tmp')], [])


def plant_link(kind, target, link):
    """A directory junction (Windows) or symlink at link pointing at target; False, with a
    printed SKIP, when this PC cannot make one (no _winapi, an unprivileged symlink)."""
    try:
        if kind == 'junction':
            import _winapi
            _winapi.CreateJunction(target, link)
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (ImportError, OSError, AttributeError) as e:
        print(f'SKIP repeat-guard {kind} at the state path: {e!r}')
        return False


def link_cases(fail):
    """Audit C1: a junction or symlink planted at the state path (or above it) would aim
    the prune and the write at another dir. The hook keeps no state there; the loop still
    blocks, on every Stop (no one-warning suppression without state); the target's old
    package.json stays and nothing is written in it."""
    def want(name, got, exp):
        CHECKS[0] += 1
        if got != exp:
            fail(f'link {name}: want {exp} got {got}')

    fens = load('repeat-loop-fens.jsonl')
    for kind, above in (('junction', False), ('junction', True), ('symlink', False)):
        with tempfile.TemporaryDirectory() as t:
            victim = os.path.join(t, 'victim')
            os.makedirs(os.path.join(victim, 'lis-repeat-guard'))
            pj = os.path.join(victim, 'package.json')
            with open(pj, 'w') as f:
                f.write('{}')
            os.utime(pj, (os.path.getmtime(pj) - 30 * 3600,) * 2)
            real = os.path.join(t, 'fens-loop.jsonl')
            with open(real, 'w', encoding='utf-8', newline='\n') as f:
                f.writelines(json.dumps(x) + '\n' for x in fens[:27])
            link = os.path.join(t, 'up' if above else 'lis-repeat-guard')
            if not plant_link(kind, victim, link):
                continue
            tmp = link if above else t
            env = dict(os.environ, TEMP=tmp, TMP=tmp, TMPDIR=tmp)
            try:
                p = {'session_id': 'sess-c1', 'transcript_path': real, 'cwd': t,
                     'hook_event_name': 'Stop', 'stop_hook_active': False}
                res = [run_hook(env, p) for _ in range(2)]
                got = [(r[1] or {}).get('decision') for r in res]
                tag = f'{kind}{" above the state dir" if above else ""}'
                want(f'{tag}: the loop blocks on each Stop', got, ['block', 'block'])
                want(f'{tag}: stderr note', [r[2].replace('\r\n', '\n') for r in res],
                     ['repeat-guard: state dir is a link or not real; no state\n'] * 2)
                want(f'{tag}: old package.json kept', os.path.exists(pj), True)
                want(f'{tag}: nothing written in the target', (sorted(os.listdir(victim)), os.listdir(
                    os.path.join(victim, 'lis-repeat-guard'))), (['lis-repeat-guard', 'package.json'], []))
            finally:
                try:
                    os.unlink(link)
                except OSError:
                    os.rmdir(link)


def main():
    fails = []
    core(fails.append)
    e2e(fails.append)
    link_cases(fails.append)
    n = CHECKS[0] + 3  # rule and e2e checks, plus the 3 mutation pins below
    VERBOSE[0] = False
    old_output = g.output
    g.output = lambda ev, r: {'decision': 'block', 'reason': r}   # the old single shape
    red = []
    try:
        core(red.append)
    except Exception as e:
        red.append(repr(e))
    g.output = old_output
    print(f'mutant output -> decision block for every event: {len(red)} red: '
          + '; '.join(x.split(': want')[0] for x in red))
    if not red:
        fails.append('mutation pin: output old shape stayed green')
    VERBOSE[0] = False
    for const, val in (('RATIO', 0.99), ('MIN_SIMILAR', 99)):
        old = getattr(g, const)
        setattr(g, const, val)
        red = []
        try:
            core(red.append)
        except Exception as e:
            red.append(repr(e))
        setattr(g, const, old)
        print(f'mutant {const} {old}->{val}: {len(red)} red: '
              + '; '.join(x.split(': want')[0] for x in red))
        if not red:
            fails.append(f'mutation pin: {const} {old}->{val} stayed green')
    for f in fails:
        print('FAIL', ascii(f))
    print(f'{n - len(fails)}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
