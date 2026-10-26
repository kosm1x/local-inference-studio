"""loop-guard: PreToolUse hook (matcher *) that denies an identical tool call repeated in a loop.

Rule, per session: keep the last WINDOW counted calls as hashes of (tool_name, canonical
JSON of tool_input). An incoming call identical to >= THRESHOLD of them is denied; the
first and second repeat always pass. Write/Edit/MultiEdit/NotebookEdit are never counted
or denied; a mutation that differs from the previous one clears the window, because a
re-read or a re-run test after a change is not a loop. A Bash/PowerShell command with a
wait word at command position (sleep, until, timeout, Start-Sleep, Wait-Process,
Wait-Job, Wait-Event) is a poll whose result changes with time, as is a POLL_TOOLS call:
never counted or denied. A denied call is not added to the window, so a loop stays
denied until the model calls something else.

State: <tempdir>/lis-loop-guard/<session_id lowercased>.json, written atomically under a
lock file; a lock older than LOCK_STALE_S is broken. State files older than 24 h are
pruned on every run. Corrupt state is discarded (the window restarts). Any error (bad
input, input over MAX_INPUT, missing or unsafe session_id, lock timeout) gives no
decision: no output, exit 0. Deterministic, stdlib only, run with `python -I`. ASCII only.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time

WINDOW = 12            # counted calls kept per session
THRESHOLD = 3          # earlier identical calls in the window that make the next one a deny
MAX_INPUT = 1_000_000  # stdin bytes; above this, no decision and no state change
MAX_AGE_S = 24 * 3600  # state files older than this are deleted
LOCK_WAIT_S = 2.0
LOCK_STALE_S = 10.0
MUTATION_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
SHELL_TOOLS = {'Bash', 'PowerShell'}
# Tools that read a background command's output, a poll like a wait word (tool names
# UNVERIFIED on Claude Code 2.1.310).
POLL_TOOLS = {'BashOutput', 'TaskOutput'}
# A wait word only at command position: start, after ; & | ( { a quote or a newline, after
# do/then. The quotes cover a payload such as powershell -Command 'Start-Sleep 5; Get-Job';
# they also make a quoted word such as echo "sleep" a poll, which is accepted.
WAIT_RE = re.compile(r'(?i)(?:^\s*|[;&|(\n\'"{]\s*|\b(?:do|then)\s+)'
                     r'(?:sleep|until|timeout|start-sleep|wait-(?:process|job|event))'
                     r'(?![\w-])')
SESSION_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def state_dir():
    return os.path.join(tempfile.gettempdir(), 'lis-loop-guard')


def call_hash(tool_name, tool_input):
    canon = json.dumps(tool_input, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256((tool_name + '\0' + canon).encode('utf-8')).hexdigest()[:16]


def fresh():
    return {'calls': [], 'denied': {}, 'last_mut': None}


def load(path):
    try:
        with open(path, 'r', encoding='ascii') as f:
            s = json.load(f)
    except FileNotFoundError:
        return fresh()
    except (OSError, ValueError, UnicodeDecodeError):
        return fresh()  # corrupt state is ignored, never trusted
    if not (isinstance(s, dict) and isinstance(s.get('calls'), list) and isinstance(s.get('denied'), dict)
            and all(isinstance(h, str) for h in s['calls'])
            and all(isinstance(v, int) for v in s['denied'].values())):
        return fresh()
    s.setdefault('last_mut', None)
    s['calls'] = s['calls'][-WINDOW:]
    return s


def reason(tool_name, n, denials):
    if denials >= 2:
        return (f'loop guard: this exact {tool_name} call was denied {denials} times already and '
                f'was made {n} times among the last {WINDOW} counted calls. Stop calling it. '
                'Answer now from the results you already have, or report what blocks you in one '
                'paragraph.')
    return (f'loop guard: this exact {tool_name} call was made {n} times among the last {WINDOW} '
            'counted calls and is identical to an earlier one. If nothing it reads has changed '
            'since, do not repeat it. Use the earlier result, change approach, or report '
            'what blocks you in one paragraph. If the tool you want is not in your tool '
            'set, say so instead of retrying a substitute.')


def step(state, tool_name, tool_input):
    """Pure rule: returns (decision or None, new state). decision = (kind, reason)."""
    cmd = tool_input.get('command')
    if tool_name in POLL_TOOLS or (tool_name in SHELL_TOOLS and isinstance(cmd, str)
                                   and WAIT_RE.search(cmd)):
        return None, state
    h = call_hash(tool_name, tool_input)
    calls, denied = list(state['calls']), dict(state['denied'])
    if tool_name in MUTATION_TOOLS:
        if h != state.get('last_mut'):
            calls, denied = [], {}
        return None, {'calls': calls, 'denied': denied, 'last_mut': h}
    n = calls.count(h)
    if n >= THRESHOLD:
        denied[h] = denied.get(h, 0) + 1
        return ('deny', reason(tool_name, n, denied[h] - 1)), {'calls': calls, 'denied': denied,
                                                               'last_mut': state.get('last_mut')}
    calls = (calls + [h])[-WINDOW:]
    denied = {k: v for k, v in denied.items() if k in calls}
    return None, {'calls': calls, 'denied': denied, 'last_mut': state.get('last_mut')}


def prune(d, now):
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        if not name.endswith(('.json', '.lock', '.tmp', '.stale')):
            continue
        p = os.path.join(d, name)
        try:
            # a .stale file is a broken lock that its claimer failed to remove
            if name.endswith('.stale') or now - os.path.getmtime(p) > MAX_AGE_S:
                os.remove(p)
        except OSError:
            pass


def acquire(lock):
    end = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except (FileExistsError, PermissionError):
            # Windows: a lock deleted while another waiter stats it stays "delete pending"
            # for a moment, and creating it then fails with PermissionError: busy, retry.
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_STALE_S:
                    # claim by rename: of several waiters only one breaks the lock
                    stale = f'{lock}.{os.getpid()}.stale'
                    os.rename(lock, stale)
                    os.remove(stale)
                    continue
            except OSError:
                pass
            if time.monotonic() > end:
                return False
            time.sleep(0.02)


def save(path, s):
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(s, f, separators=(',', ':'))
    os.replace(tmp, path)


def run(raw):
    if len(raw) > MAX_INPUT:
        sys.stderr.write('loop-guard: input over 1 MB; no decision\n')
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    sid, tool, ti = data.get('session_id'), data.get('tool_name'), data.get('tool_input')
    if not (isinstance(sid, str) and SESSION_RE.fullmatch(sid) and isinstance(tool, str)
            and tool and isinstance(ti, dict)):
        return None
    d = state_dir()
    os.makedirs(d, exist_ok=True)
    prune(d, time.time())
    path = os.path.join(d, sid.lower() + '.json')
    lock = path + '.lock'
    if not acquire(lock):
        sys.stderr.write('loop-guard: state busy; no decision\n')
        return None
    try:
        decision, new = step(load(path), tool, ti)
        save(path, new)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    return decision


def main():
    try:
        decision = run(sys.stdin.buffer.read(MAX_INPUT + 1))
    except Exception:  # never block a session on a guard bug: no decision
        return 0
    if decision:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                                 'permissionDecision': decision[0],
                                                 'permissionDecisionReason': decision[1]}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
