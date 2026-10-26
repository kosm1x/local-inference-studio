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
    want('identical Edit is never denied', seq([edit] * 6), [None] * 6)
    want('Write is never denied', seq([('Write', {'file_path': 'x', 'content': 'y'})] * 5), [None] * 5)
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

        CHECKS[0] += 15  # e2e checks below, one per block
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
        call('s7')
        if os.path.exists(old) or not os.path.exists(new):
            fail(f'e2e prune: old exists={os.path.exists(old)} new exists={os.path.exists(new)}')
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
        if any(name.endswith(('.lock', '.tmp', '.stale')) for name in os.listdir(sd)):
            fail('e2e left a lock, tmp or stale file behind')


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


def main():
    fails = []
    core(fails.append)
    lock_cases(fails.append)
    permission_case(fails.append)
    e2e(fails.append)
    sid_cases(fails.append)
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
