"""Unit tests for scripts/hooks/loop-guard.py. Run: python -I scripts/hooks/tests/loop-guard_test.py [hook]

Exit 0 = all pass. The optional argument is a hook file to test instead of the default
(used to prove that file mutants go red; the WINDOW, THRESHOLD and acquire mutants are
pinned in-suite below). End-to-end cases run the
hook as Claude Code does (stdin JSON, python -I) with TEMP/TMP/TMPDIR pointed at a
throwaway directory, so no real session state is touched.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, '..', 'loop-guard.py')
spec = importlib.util.spec_from_file_location('loop_guard', HOOK)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

A = ('Glob', {'pattern': 'scripts/**/*'})
B = ('Glob', {'pattern': 'bench/*'})
C = ('Glob', {'pattern': 'docs/**'})
D = ('Glob', {'pattern': 'config/*'})
R = ('Read', {'file_path': 'src/text.js'})
T = ('Bash', {'command': 'node --test'})


def other(i):
    return ('Read', {'file_path': f'f{i}.txt'})


CHECKS = [0]


def seq(calls):
    """Feed calls through the pure rule; return the decision kinds ('deny' or None)."""
    s, out = g.fresh(), []
    for name, ti in calls:
        d, s = g.step(s, name, ti)
        out.append(d[0] if d else None)
    return out


def core(fail):
    """Rule cases. fail(name) records a failure. Used on the real module and on mutants."""
    def want(name, got, exp):
        CHECKS[0] += 1
        if got != exp:
            fail(f'{name}: want {exp} got {got}')

    want('first and second repeat pass, third repeat denied', seq([A] * 4), [None, None, None, 'deny'])
    want('loop keeps being denied', seq([A] * 6), [None, None, None, 'deny', 'deny', 'deny'])
    want('cycle of 4: 12 calls pass, the third repeat of each is denied',
         seq([A, B, C, D] * 4), [None] * 12 + ['deny'] * 4)
    want('reordered keys are one call (canonical JSON)',
         seq([('Grep', {'pattern': '.', 'path': 'x'}), ('Grep', {'path': 'x', 'pattern': '.'})] * 2),
         [None, None, None, 'deny'])
    # window: 3 x A then 9 others keeps all three A in the last 12 -> deny; 10 others -> one A slid out
    want('window 12 still holds 3 earlier calls', seq([A] * 3 + [other(i) for i in range(9)] + [A])[-1], 'deny')
    want('window slides after 12 calls', seq([A] * 3 + [other(i) for i in range(10)] + [A])[-1], None)
    want('window slides (12 others)', seq([A] * 3 + [other(i) for i in range(12)] + [A])[-1], None)
    # mutation tools
    edit = ('Edit', {'file_path': 'src/text.js', 'old_string': 'a', 'new_string': 'b'})
    want('identical Edit: third in a row denied', seq([edit] * 6), [None, None] + ['deny'] * 4)
    want('identical Write: third in a row denied', seq([('Write', {'file_path': 'x', 'content': 'y'})] * 5),
         [None, None] + ['deny'] * 3)
    wa = ('Write', {'file_path': 'src/a.ts', 'content': 'X'})
    wa2 = ('Write', {'file_path': 'src/a.ts', 'content': 'Y'})
    wb = ('Write', {'file_path': 'src/b.ts', 'content': 'X'})
    cat = ('Bash', {'command': 'cat src/a.ts'})
    want('identical Write x3: third denied', seq([wa] * 3), [None, None, 'deny'])
    want('identical Write x2: both pass', seq([wa] * 2), [None, None])
    want('a differing Write passes', seq([wa, wa, wa2]), [None, None, None])
    want('a differing Write resets the run', seq([wa, wa, wa2, wa2, wa]), [None] * 5)
    want('a non-mutation does not reset the run', seq([wa, wa, cat, wa]), [None, None, None, 'deny'])
    want('a denied Write stays denied until a different one',
         seq([wa, wa, wa, wa, wa2]), [None, None, 'deny', 'deny', None])
    same = ('Edit', {'file_path': 'src/a.ts', 'old_string': 'a', 'new_string': 'a'})
    want('identical no-op Edit x3: third denied', seq([same] * 3), [None, None, 'deny'])
    want('same content to another path is not identical', seq([wa, wa, wb]), [None, None, None])
    s = g.fresh()
    for name, ti in [wa, wa, wa2]:
        _, s = g.step(s, name, ti)
    want('a differing Write sets mut_repeat to 0', s.get('mut_repeat'), 0)
    s, ds = g.fresh(), []
    for name, ti in [wa] * 4:
        d, s = g.step(s, name, ti)
        ds.append(d)
    rm = ds[2][1] if ds[2] else ''
    CHECKS[0] += 1
    if not ('loop guard' in rm and 'Write of src/a.ts' in rm
            and 'identical to the previous 2 Write/Edit calls' in rm
            and 'If another tool changed the file since' in rm
            and 'stop and continue with the next step' in rm
            and 'read the file back' not in rm
            and all(ord(ch) < 128 for ch in rm)):
        fail(f'identical mutation reason wording: {rm!r}')
    want('a denied mutation keeps counting', s.get('mut_repeat'), 3)
    edits = [('Edit', {'file_path': 'src/text.js', 'old_string': str(i), 'new_string': 'z'}) for i in range(4)]
    want('re-run after each new edit is not a loop',
         seq([T, edits[0], T, edits[1], T, edits[2], T, edits[3], T]), [None] * 9)
    want('re-read after a new edit is not a loop', seq([R, R, R, edits[0], R]), [None] * 5)
    want('an identical repeated Edit does not reset the window', seq([R, edit, R, edit, R, edit, R, edit, R])[-1],
         'deny')
    # polls
    wait = ('Bash', {'command': 'timeout 590 bash -c "until grep -q done out.txt; do sleep 10; done"'})
    want('a wait command is never denied', seq([wait] * 6), [None] * 6)
    want('Start-Sleep poll is never denied', seq([('PowerShell', {'command': 'Start-Sleep 5; Get-Job'})] * 5),
         [None] * 5)
    want('curl --connect-timeout is not a wait word', seq([('Bash', {'command': 'curl --connect-timeout 2 x'})] * 4)[-1],
         'deny')
    want('a wait word as an argument is not a poll',
         seq([('Bash', {'command': 'grep -rn timeout src/'})] * 4), [None, None, None, 'deny'])
    want('wait word after && is a poll',
         seq([('Bash', {'command': 'cd out && sleep 5'})] * 4), [None] * 4)
    want('wait word on a new line is a poll',
         seq([('Bash', {'command': 'cd out\nsleep 5'})] * 4), [None] * 4)
    want('Wait-Job after a pipe is a poll',
         seq([('PowerShell', {'command': 'Get-Job | Wait-Job -Timeout 5'})] * 4), [None] * 4)
    want('wait word inside a quoted powershell payload is a poll',
         seq([('Bash', {'command': "powershell -NoProfile -Command 'Start-Sleep 5; Get-Job'"})] * 4),
         [None] * 4)
    want('wait word in a { } group is a poll',
         seq([('Bash', {'command': '{ sleep 1; }'})] * 4), [None] * 4)
    for poll in ('BashOutput', 'TaskOutput'):
        want(f'{poll} is a poll, never denied',
             seq([(poll, {'bash_id': 'b1'})] * 5), [None] * 5)
    want('non-wait Bash loop is denied', seq([T] * 4)[-1], 'deny')
    # reasons
    s, ds = g.fresh(), []
    for name, ti in [A] * 6:
        d, s = g.step(s, name, ti)
        ds.append(d)
    r1 = ds[3][1] if ds[3] else ''
    CHECKS[0] += 3
    if not ('loop guard' in r1 and 'Glob' in r1 and 'was made 3 times among the last 12 counted calls' in r1
            and 'do not repeat it' in r1 and 'report what blocks you' in r1
            and 'has not changed' not in r1):
        fail(f'first deny reason wording: {r1!r}')
    r3 = ds[5][1] if ds[5] else ''
    if not ('denied 2 times' in r3 and 'Stop calling it' in r3
            and 'or report what blocks you' in r3):
        fail(f'escalated reason after 2 denials: {r3!r}')
    if not all(ord(ch) < 128 for d in ds if d for ch in d[1]):
        fail('reason must be ASCII')


def lock_cases(fail):
    """acquire takes the lock file and a second acquire waits, then gives up. Used on the
    real module and on the acquire mutant."""
    CHECKS[0] += 2
    with tempfile.TemporaryDirectory() as t:
        lock = os.path.join(t, 'x.json.lock')
        old_wait = g.LOCK_WAIT_S
        g.LOCK_WAIT_S = 0.1
        try:
            if not (g.acquire(lock) and os.path.exists(lock)):
                fail('acquire must create the lock file')
            if g.acquire(lock):
                fail('a second acquire while the lock is held must return False')
        finally:
            g.LOCK_WAIT_S = old_wait


def permission_case(fail):
    """Windows: creating a lock that is still "delete pending" raises PermissionError;
    acquire must treat it as busy and retry, not raise."""
    CHECKS[0] += 1
    with tempfile.TemporaryDirectory() as t:
        lock = os.path.join(t, 'x.json.lock')
        real, n = g.os.open, [0]

        def flaky(*a, **k):
            n[0] += 1
            if n[0] == 1:
                raise PermissionError(13, 'delete pending', lock)
            return real(*a, **k)
        g.os.open = flaky
        try:
            if g.acquire(lock) is not True:
                fail('acquire after a PermissionError must retry and take the lock')
        except Exception as e:
            fail(f'acquire after a PermissionError raised {e!r}')
        finally:
            g.os.open = real
            if os.path.exists(lock):
                os.remove(lock)


def run_hook(env, payload, raw=None):
    inp = raw if raw is not None else json.dumps(payload)
    r = subprocess.run([sys.executable, '-I', HOOK], input=inp.encode('utf-8') if isinstance(inp, str) else inp,
                       capture_output=True, env=env, timeout=20)
    out = r.stdout.decode('ascii', 'replace').strip()
    dec = json.loads(out)['hookSpecificOutput']['permissionDecision'] if out else None
    return r.returncode, dec, r.stderr.decode('utf-8', 'replace')


def e2e(fail):
    with tempfile.TemporaryDirectory() as t:
        env = dict(os.environ, TEMP=t, TMP=t, TMPDIR=t)
        sd = os.path.join(t, 'lis-loop-guard')

        def call(sid, tool=A, raw=None):
            p = {'session_id': sid, 'tool_name': tool[0], 'tool_input': tool[1], 'cwd': t,
                 'hook_event_name': 'PreToolUse'}
            if sid is None:
                del p['session_id']
            return run_hook(env, p, raw)

        CHECKS[0] += 16  # e2e checks below, one per block
        got = [call('s1')[1] for _ in range(4)]
        if got != [None, None, None, 'deny']:
            fail(f'e2e third repeat denied: {got}')
        if call('s2')[1] is not None:
            fail('e2e another session_id is isolated')
        # corrupt state: no decision, no traceback, state starts fresh
        with open(os.path.join(sd, 's3.json'), 'w') as f:
            f.write('{not json')
        rc, dec, err = call('s3')
        if rc != 0 or dec is not None or 'Traceback' in err:
            fail(f'e2e corrupt state must give no decision: rc={rc} dec={dec} err={err[:120]!r}')
        with open(os.path.join(sd, 's3.json')) as f:
            if len(json.load(f)['calls']) != 1:
                fail('e2e corrupt state is replaced by a fresh one')
        with open(os.path.join(sd, 's4.json'), 'w') as f:
            json.dump({'calls': 'x', 'denied': []}, f)
        if call('s4')[1] is not None:
            fail('e2e wrong-shape state must give no decision')
        # oversized input: no decision, state untouched
        big = ('Read', {'file_path': 'x' * (g.MAX_INPUT + 10)})
        for _ in range(5):
            rc, dec, err = call('s5', big)
        if rc != 0 or dec is not None or os.path.exists(os.path.join(sd, 's5.json')):
            fail(f'e2e oversized input must give no decision and no state: rc={rc} dec={dec}')
        # missing / unsafe session_id
        for sid in (None, '', '../evil', 'a/b', 'x' * 200, 5, 'a\n'):
            for _ in range(4):
                rc, dec, err = call(sid)
            if rc != 0 or dec is not None:
                fail(f'e2e session_id {sid!r} must give no decision: rc={rc} dec={dec}')
                break  # one check: fail once
        if os.path.exists(os.path.join(t, 'evil.json')):
            fail('e2e path traversal wrote outside the state dir')
        # malformed input
        for raw in ['', '{not json', '[1, 2]', '"s"', json.dumps({'session_id': 's6', 'tool_name': 'Read'}),
                    json.dumps({'session_id': 's6', 'tool_name': 'Read', 'tool_input': 'x'}),
                    json.dumps({'session_id': 's6', 'tool_input': {}}), b'\xff\xfe\x00']:
            rc, dec, err = call('s6', raw=raw)
            if rc != 0 or dec is not None or 'Traceback' in err:
                fail(f'e2e malformed {raw!r:.40} must give exit 0 and no output: rc={rc} err={err[:120]!r}')
                break  # one check: fail once
        # prune: a 25 h old file goes, a 1 h old file stays
        old, new = os.path.join(sd, 'old.json'), os.path.join(sd, 'new.json')
        for p, age in ((old, 25 * 3600), (new, 3600)):
            with open(p, 'w') as f:
                f.write('{}')
            os.utime(p, (time.time() - age, time.time() - age))
        strays = [os.path.join(sd, x) for x in ('Other.json', 'a.b.json', 'x.txt.lock')]
        for p in strays:                        # audit C1: not state names, never pruned
            with open(p, 'w') as f:
                f.write('{}')
            os.utime(p, (time.time() - 25 * 3600,) * 2)
        call('s7')
        if os.path.exists(old) or not os.path.exists(new):
            fail(f'e2e prune: old exists={os.path.exists(old)} new exists={os.path.exists(new)}')
        CHECKS[0] += 1
        if not all(os.path.exists(p) for p in strays):
            fail('e2e prune removed a name that is not a state name')
        for p in strays:                        # the leftover check below reads .lock names
            if os.path.exists(p):
                os.remove(p)
        # parallel calls (one tool batch): 8 hook processes started together from threads
        # overlap; the lock keeps every call
        start = threading.Barrier(8)

        def par(i):
            start.wait()
            call('s8', ('Read', {'file_path': f'p{i}'}))
        threads = [threading.Thread(target=par, args=(i,)) for i in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        with open(os.path.join(sd, 's8.json')) as f:
            n = len(json.load(f)['calls'])
        if n != 8:
            fail(f'e2e parallel calls: want 8 recorded, got {n}')
        # a stale lock (20 s old, a crashed hook) is broken and the call is recorded
        lock = os.path.join(sd, 's9.json.lock')
        open(lock, 'w').close()
        os.utime(lock, (time.time() - 20, time.time() - 20))
        call('s9')
        s9 = os.path.join(sd, 's9.json')
        if not (os.path.exists(s9) and len(json.load(open(s9))['calls']) == 1):
            fail('e2e stale lock: the call was not recorded')
        # session_id case does not split a window; a non-ASCII tool name is hashed
        got = [call(sid)[1] for sid in ('S10', 'S10', 's10', 's10')]
        if got != [None, None, None, 'deny']:
            fail(f'e2e session_id case must share one window: {got}')
        uni = ('Gr\u00e9p', {'pattern': '\u00e9t\u00e9'})
        got = [call('s11', uni)[1] for _ in range(4)]
        if got != [None, None, None, 'deny']:
            fail(f'e2e non-ASCII tool name: {got}')
        w = ('Write', {'file_path': 'src/a.ts', 'content': 'X'})
        got = [call('s12', w)[1] for _ in range(3)]
        if got != [None, None, 'deny']:
            fail(f'e2e identical Write: {got}')
        if any(name.endswith(('.lock', '.tmp', '.stale')) for name in os.listdir(sd)):
            fail('e2e left a lock, tmp or stale file behind')


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
        print(f'SKIP loop-guard {kind} at the state path: {e!r}')
        return False


def link_cases(fail):
    """Audit C1: a junction or symlink planted at the state path (or above it) would aim
    the prune and the write at another dir. The hook keeps no state there and gives no
    decision (it cannot count without state); the target's old package.json stays."""
    for kind, above in (('junction', False), ('junction', True), ('symlink', False)):
        with tempfile.TemporaryDirectory() as t:
            victim = os.path.join(t, 'victim')
            os.makedirs(os.path.join(victim, 'lis-loop-guard'))
            pj = os.path.join(victim, 'package.json')
            with open(pj, 'w') as f:
                f.write('{}')
            os.utime(pj, (time.time() - 30 * 3600,) * 2)
            link = os.path.join(t, 'up' if above else 'lis-loop-guard')
            if not plant_link(kind, victim, link):
                continue
            tmp = link if above else t
            env = dict(os.environ, TEMP=tmp, TMP=tmp, TMPDIR=tmp)
            try:
                p = {'session_id': 'sess-c1', 'tool_name': A[0], 'tool_input': A[1], 'cwd': t,
                     'hook_event_name': 'PreToolUse'}
                got = [run_hook(env, p)[1] for _ in range(4)]
                tag = f'{kind}{" above the state dir" if above else ""}'
                CHECKS[0] += 3
                if got != [None] * 4:
                    fail(f'link {tag}: want no decision on every call, got {got}')
                if not os.path.exists(pj):
                    fail(f'link {tag}: the old package.json was pruned')
                if sorted(os.listdir(victim)) != ['lis-loop-guard', 'package.json'] or os.listdir(
                        os.path.join(victim, 'lis-loop-guard')):
                    fail(f'link {tag}: state written in the target: {sorted(os.listdir(victim))}')
            finally:
                try:
                    os.unlink(link)
                except OSError:
                    os.rmdir(link)


def sid_cases(fail):
    """In-process: a session_id with a trailing newline gives no decision, no error and
    no state (re.match with $ accepts it; the hook needs fullmatch)."""
    CHECKS[0] += 1
    with tempfile.TemporaryDirectory() as t:
        old = g.state_dir
        g.state_dir = lambda: t
        try:
            raw = json.dumps({'session_id': 'a\n', 'tool_name': 'Read',
                              'tool_input': {}}).encode()
            got = [g.run(raw) for _ in range(4)]
            if got != [None] * 4 or os.listdir(t):
                fail(f'session_id with a trailing newline: {got} files={os.listdir(t)}')
        except Exception as e:
            fail(f'session_id with a trailing newline raised {e!r}')
        finally:
            g.state_dir = old


def old_state_case(fail):
    """A state file written before mut_repeat existed loads and the rule still works."""
    CHECKS[0] += 1
    w = {'file_path': 'src/a.ts', 'content': 'X'}
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, 'old.json')
        with open(p, 'w', encoding='ascii') as f:
            json.dump({'calls': [], 'denied': {}, 'last_mut': g.call_hash('Write', w)}, f)
        s, got = g.load(p), []
        for _ in range(2):
            d, s = g.step(s, 'Write', w)
            got.append(d[0] if d else None)
        if got != [None, 'deny']:
            fail(f'old state file without mut_repeat: {got}')
        # a mutation counter that is not a non-negative int is corrupt state: fresh window
        for bad in ('x', None, True, -5, 1.5):
            CHECKS[0] += 1
            with open(p, 'w', encoding='ascii') as f:
                json.dump({'calls': [], 'denied': {}, 'last_mut': g.call_hash('Write', w),
                           'mut_repeat': bad}, f)
            try:
                s, got = g.load(p), []
                fresh = s == g.fresh()
                for _ in range(3):
                    d, s = g.step(s, 'Write', w)
                    got.append(d[0] if d else None)
            except Exception as e:
                got, fresh = repr(e), False
            if not fresh or got != [None, None, 'deny']:
                fail(f'mut_repeat {bad!r} must load as fresh state: fresh={fresh} got={got}')


WS = 'mcp__lis-web__web_search'
WX = 'mcp__lis-web__exa_search'
WR = 'mcp__lis-web__web_read'
URL = 'https://example.com/models/small-llm'


def q(text, tool=WS):
    return (tool, {'query': text})


def rd(url, **kw):
    return (WR, dict(kw, url=url))


def after(calls):
    """State after feeding calls through step()."""
    s = g.fresh()
    for name, ti in calls:
        _, s = g.step(s, name, ti)
    return s


def run_of(calls, cls='search'):
    return after(calls)['drift_run'].get(cls)


def web_cases(fail):
    """W-21 drift rule (per class: search, read) and burst cap on searches."""
    def want(name, got, exp):
        CHECKS[0] += 1
        if got != exp:
            fail(f'{name}: want {exp} got {got}')

    words = 'chess rating assessment player skill level'.split()
    grow = [q(' '.join(['llama.cpp gguf model small llm'] + words[:i])) for i in range(6)]
    want('appending one word: drift repeats 1-2 pass, the 3rd and later deny', seq(grow),
         [None, None, None, 'deny', 'deny', 'deny'])
    s, ds = g.fresh(), []
    for name, ti in grow:
        d, s = g.step(s, name, ti)
        ds.append(d)
    r = ds[3][1] if ds[3] else ''
    CHECKS[0] += 1
    if not (r == (f'loop guard: this {WS} query is a near-repeat of the previous 3 (same '
                  'words plus a few more). Narrowing by appending words is not a new search. '
                  'Use the results you already have, change the query substantially, or '
                  'report what you found.')):
        fail(f'drift reason wording: {r!r}')
    CHECKS[0] += 1
    r4, r5 = (ds[4][1] if ds[4] else ''), (ds[5][1] if ds[5] else '')
    if not (r4 == r + ' You were already told this 1 time: do not try another variation.'
            and r5 == r + ' You were already told this 2 times: do not try another variation.'):
        fail(f'escalated drift reason on the 2nd and 3rd deny: {r4!r} {r5!r}')
    want('a drift deny changes only drift_denied', g.step(s, *grow[5])[1],
         dict(s, drift_denied={'search': 4}))
    s2 = s
    for name, ti in (q('weather forecast mexico'), q('weather forecast mexico city'),
                     q('weather forecast mexico city today'),
                     q('weather forecast mexico city today rain')):
        d, s2 = g.step(s2, name, ti)
    CHECKS[0] += 1
    if not (d and d[1] == r):
        fail(f'a reset run zeroes drift_denied (no escalation on the next chain): {d!r}')
    a, b = q('small llm for chess on a gpu'), q('weather forecast mexico city tomorrow')
    want('two unrelated queries alternating are never denied', seq([a, b] * 3), [None] * 6)
    want('reordered words are a drift repeat (Jaccard 1.0)',
         run_of([q('small llm chess rating'), q('rating chess llm small')]), 1)
    want('a query with 50% new words resets the run',
         run_of([q('small llm chess rating'), q('rating chess llm small'),
                 q('small llm cooking recipes')]), 0)
    want('9 words, 1 swapped (Jaccard 0.8 exactly) is a drift repeat',
         run_of([q('a b c d e f g h i'), q('a b c d e f g h z')]), 1)
    want('8 words, 1 swapped (Jaccard 0.78) is not a drift repeat',
         run_of([q('a b c d e f g h'), q('a b c d e f g z')]), 0)
    want('queries after an empty-token query pass', seq([q(x) for x in ('???', 'x y', 'p q', 'm n')]),
         [None] * 4)
    want('empty-token queries never drift from each other',
         seq([q(x) for x in ('???', '!!!', '...', '---', '***')]), [None] * 5)
    want('a case-only difference is a drift repeat',
         run_of([q('Small LLM Chess'), q('small llm chess')]), 1)
    # reads: one token, host + path + query string
    want('same url with another selector is a drift repeat',
         run_of([rd(URL), rd(URL, selector='main')], 'read'), 1)
    want('same url read 4 ways: the 3rd drift repeat denies',
         seq([rd(URL), rd(URL, selector='main'), rd(URL, engine='browser'), rd(URL, fresh=True)]),
         [None, None, None, 'deny'])
    s, ds = g.fresh(), []
    for name, ti in (rd(URL), rd(URL, selector='main'), rd(URL, engine='browser'),
                     rd(URL, fresh=True), rd(URL, wait_for='main')):
        d, s = g.step(s, name, ti)
        ds.append(d)
    rr = (f'loop guard: this {WR} fetches the same page as the previous 3 reads (same host, '
          'path and query). Re-reading it with other options returns the same content. Use what '
          'you already have, read a different page, or report what you found.')
    CHECKS[0] += 1
    if not (ds[3] and ds[3][1] == rr and ds[4] and ds[4][1] == rr + (
            ' You were already told this 1 time: do not try another variation.')):
        fail(f'read drift reason wording: {ds[3]!r} {ds[4]!r}')
    want('same url with a #fragment or upper case is a drift repeat',
         run_of([rd(URL), rd(URL.upper() + '#specs')], 'read'), 1)
    for name, u1, u2, exp in (
            ('a trailing / is the same page', 'https://example.com/page', 'https://example.com/page/', 1),
            ('a percent-encoded path is the same page', 'https://example.com/%70age',
             'https://example.com/page', 1),
            ('query parameter order is the same page', 'https://example.com/p?b=2&a=1',
             'https://example.com/p?a=1&b=2', 1),
            ('?page=1 and ?page=2 are different pages', 'https://example.com/p?page=1',
             'https://example.com/p?page=2', 0)):
        want(name, run_of([rd(u1), rd(u2)], 'read'), exp)
    try:
        got = seq([rd('http://[::1', selector=f'#s{i}') for i in range(4)])
    except Exception as e:
        got = repr(e)
    want('a malformed url falls back to its text: the 4th read is a drift deny, no raise', got,
         [None, None, None, 'deny'])
    want('sibling urls are not drift repeats',
         seq([rd(f'https://example.com/models/{m}') for m in ('a', 'b', 'c', 'd', 'e')]),
         [None] * 5)
    want('?page=2..5 are not drift repeats', seq([rd(f'{URL}?page={i}') for i in range(2, 6)]),
         [None] * 4)
    want('the same path on another host is not a drift repeat',
         run_of([rd(URL), rd(URL.replace('example.com', 'example.org'))], 'read'), 0)
    want('a read without a url string falls back to the canonical JSON',
         run_of([(WR, {'link': 'x'}), (WR, {'link': 'y'})], 'read'), 0)
    want('reads and searches keep separate classes',
         after([q('small llm'), rd(URL), q('small llm chess'), rd(URL, selector='main')])['drift_run'],
         {'search': 1, 'read': 1})
    want('exa_search after two drifting web_search calls is denied (class keying)',
         seq(grow[:3] + [q(grow[3][1]['query'], WX)]), [None, None, None, 'deny'])
    bash = ('Bash', {'command': 'ls models'})
    s = after([grow[0], grow[1], bash, grow[2], bash])
    want('a Bash call between drift repeats keeps drift_run', s['drift_run'], {'search': 2})
    want('a Bash call resets web_run', s['web_run'], 0)
    d = g.step(s, *grow[3])[0]
    want('drift repeats across Bash calls: the 3rd denies', d[0] if d else None, 'deny')
    rep = q('small llm for chess')
    s, ds = g.fresh(), []
    for name, ti in [rep] * 4:
        d, s = g.step(s, name, ti)
        ds.append(d)
    want('an exact repeated search: the existing rule denies the 4th',
         [d[0] if d else None for d in ds], [None, None, None, 'deny'])
    CHECKS[0] += 1
    if not (ds[3] and ds[3][1].startswith(f'loop guard: this exact {WS} call was made 3 times')):
        fail(f'an exact repeat must get the exact-repeat reason: {ds[3]!r}')
    want('an exact-repeat deny keeps drift_run and web_run',
         (s.get('drift_run'), s.get('web_run')), ({'search': 2}, 3))
    # burst cap: searches only
    distinct = [q(f'topic{i} subject{i} angle{i}') for i in range(31)]
    want('20 distinct searches pass, the 21st denies', seq(distinct[:21]), [None] * 20 + ['deny'])
    s, ds = g.fresh(), []
    for name, ti in distinct[:22]:
        d, s = g.step(s, name, ti)
        ds.append(d)
    CHECKS[0] += 1
    rb = ds[20][1] if ds[20] else ''
    if rb != ('loop guard: 20 searches in a row without acting on any result. Stop '
              'searching: summarize what you found or use a result.'):
        fail(f'burst reason wording: {rb!r}')
    want('a denied burst call does not count', s['web_run'], 20)
    reads = [rd(f'https://example.com/docs/page{i}') for i in range(25)]
    want('1 search + 25 reads never deny', seq(distinct[:1] + reads), [None] * 26)
    want('reads do not count toward the burst', after(distinct[:1] + reads)['web_run'], 1)
    want('after 20 searches a read passes, then the 21st search denies',
         seq(distinct[:20] + reads[:1] + distinct[20:21])[-2:], [None, 'deny'])
    want('a read does not reset the burst', seq(distinct[:20] + reads[:1] + distinct[20:21])[-1],
         'deny')
    mixed = []
    for i in range(30):
        if i and i % 10 == 0:
            mixed.append(other(i))
        mixed.append(distinct[i])
    want('30 distinct searches with a Read every 10 never deny', seq(mixed), [None] * 32)
    edit = ('Edit', {'file_path': 'notes.md', 'old_string': 'a', 'new_string': 'b'})
    wait = ('Bash', {'command': 'sleep 5'})
    for name, tool in (('an Edit', edit), ('a poll', wait),
                       ('a lookalike tool (fullmatch)', ('mcp__lis-web__web_search_x', {'query': 'x'}))):
        want(f'{name} resets web_run', after(distinct[:20] + [tool])['web_run'], 0)
    want('tool classes',
         [g.web_class(t) for t in ('WebSearch', 'WebFetch', WS, WX, 'mcp__lis-web__jina_search', WR,
                                   'mcp__lis-web__web_read_tweet', 'mcp__x__web_read', 'Read',
                                   'mcp__lis-web__web_search_x', 'mcp__lis-web__web_read_x')],
         ['search', 'read', 'search', 'search', 'search', 'read', 'read', 'read', None, None, None])


def web_state_case(fail):
    """W-21 state: old files without the new keys load; corrupt values load as fresh."""
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, 'old.json')
        base = {'calls': [], 'denied': {}, 'last_mut': None, 'mut_repeat': 0}
        CHECKS[0] += 1
        with open(p, 'w', encoding='ascii') as f:
            json.dump(base, f)
        s = g.load(p)
        if s != g.fresh():
            fail(f'state without the W-21 keys must load with defaults: {s!r}')
        CHECKS[0] += 1
        s = after([q('small llm'), q('small llm chess'), q('small llm chess gpu'),
                   q('small llm chess gpu cpu'), rd(URL)])
        g.save(p, s)
        if g.load(p) != s or s['drift_denied'] != {'search': 1, 'read': 0}:
            fail(f'W-21 state must round-trip through save and load: {s!r}')
        # the first W-21 build wrote drift_run as one int and drift_prev keyed by tool name
        bads = [('first-build shape', {'drift_prev': {WS: ['llm', 'small']}, 'drift_run': 1,
                                       'web_run': 2})]
        for key in ('drift_run', 'drift_denied'):
            bads += [(key, {key: v}) for v in ('x', None, True, -5, {'search': -1},
                                               {'search': True})]
        bads += [('web_run', {'web_run': v}) for v in ('x', None, True, -5)]
        bads += [('drift_prev', {'drift_prev': v}) for v in ('x', None, True, -5,
                                                            {'search': 'small llm'},
                                                            {'search': [1]})]
        for key, bad in bads:
            CHECKS[0] += 1
            with open(p, 'w', encoding='ascii') as f:
                json.dump(dict(base, calls=['abc'], **bad), f)
            try:
                fresh = g.load(p) == g.fresh()
            except Exception as e:
                fresh = repr(e)
            if fresh is not True:
                fail(f'{key} {bad!r} must load as fresh state: {fresh}')


def main():
    fails = []
    core(fails.append)
    lock_cases(fails.append)
    permission_case(fails.append)
    e2e(fails.append)
    link_cases(fails.append)
    sid_cases(fails.append)
    old_state_case(fails.append)
    web_cases(fails.append)
    web_state_case(fails.append)
    n = CHECKS[0] + 5  # rule, lock and e2e checks, plus the 5 mutation pins below
    # mutation pins: the core cases must go red when the constants are mutated
    for const, val in (('THRESHOLD', 4), ('WINDOW', 100), ('THRESHOLD', 2), ('WINDOW', 11)):
        old = getattr(g, const)
        setattr(g, const, val)
        red = []
        try:
            core(red.append)
        except Exception as e:
            red.append(repr(e))
        setattr(g, const, old)
        if not red:
            fails.append(f'mutation pin: {const} {old}->{val} stayed green')
    # mutation pin: acquire returning True without taking the lock
    real, red = g.acquire, []
    g.acquire = lambda lock: True
    try:
        lock_cases(red.append)
    finally:
        g.acquire = real
    if not red:
        fails.append('mutation pin: acquire without a lock stayed green')
    for f in fails:
        print('FAIL', f)
    print(f'{n - len(fails)}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
