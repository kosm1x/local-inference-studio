"""loop-guard: PreToolUse hook (matcher *) that denies an identical tool call repeated in a loop.

Rule, per session: keep the last WINDOW counted calls as hashes of (tool_name, canonical
JSON of tool_input). An incoming call identical to >= THRESHOLD of them is denied; the
first and second repeat always pass. Write/Edit/MultiEdit/NotebookEdit are never counted
in the window; a mutation that differs from the previous one clears the window, because a
re-read or a re-run test after a change is not a loop. A mutation identical to the
previous two mutations (the third in a row; other calls in between do not break the run)
is denied: it usually changes nothing on disk. A Bash/PowerShell command with a
wait word at command position (sleep, until, timeout, Start-Sleep, Wait-Process,
Wait-Job, Wait-Event) is a poll whose result changes with time, as is a POLL_TOOLS call:
never counted or denied. A denied call is not added to the window, so a loop stays
denied until the model calls something else.
A DRIFT_RE web call (class search or read) that is a drift repeat of the previous call of
its class (search: query words a superset of, or overlapping at Jaccard >= DRIFT_JACCARD
with, the previous ones; read: the same page) is denied from the third drift repeat
in a row on (a non-matching call of the class resets the run, other tools do not). More
than WEB_BURST_MAX searches in a row with no non-web tool call between them are denied.

State: <tempdir>/lis-loop-guard/<session_id lowercased>.json, written atomically under a
lock file; a lock older than LOCK_STALE_S is broken. State files older than 24 h are
pruned on every run (state, lock, temp and stale-lock names only). Corrupt state is
discarded (the window restarts). Any error (bad input, input over MAX_INPUT, missing or
unsafe session_id, lock timeout, a state dir that is a link or junction) gives no
decision: no output, exit 0. Deterministic, stdlib only, run with `python -I`. ASCII only.
"""
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.parse

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
# Web tools by what they do (W-21: 31 searches, each the previous query plus a word or
# two). The three lis-web search tools spend paid quota (Brave, Exa, Jina keys); web_read
# and web_read_tweet are keyless. Drift is tracked per class, so a provider switch with
# the same drifting query is still compared with the previous search.
DRIFT_RE = {'search': re.compile(r'mcp__.+__(?:web|exa|jina)_search|WebSearch'),
            'read': re.compile(r'mcp__.+__web_read(?:_tweet)?|WebFetch')}
DRIFT_JACCARD = 0.8    # search token-set overlap at or above this is a near-repeat
WEB_BURST_MAX = 20     # searches in a row; the next one is denied (operator ruling pending)


def state_dir():
    return os.path.join(tempfile.gettempdir(), 'lis-loop-guard')


# <sid>.json, its lock, a temp write and a broken lock: the only names prune() removes
STATE_NAME = re.compile(r'[a-z0-9_-]{1,128}\.json(?:\.lock(?:\.\d+\.stale)?|\.\d+\.tmp)?')


def real_dir(d):
    """True when d is a directory itself: not a symlink or junction (a reparse point), and
    no link in a parent (audit C1: a planted link aims the prune and the write elsewhere)."""
    try:
        st = os.lstat(d)
    except OSError:
        return False
    return (stat.S_ISDIR(st.st_mode) and not os.path.islink(d)
            and not getattr(st, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
            and os.path.normcase(os.path.realpath(d)) == os.path.normcase(os.path.abspath(d)))


def call_hash(tool_name, tool_input):
    canon = json.dumps(tool_input, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256((tool_name + '\0' + canon).encode('utf-8')).hexdigest()[:16]


def fresh():
    return {'calls': [], 'denied': {}, 'last_mut': None, 'mut_repeat': 0,
            'drift_prev': {}, 'drift_run': {}, 'drift_denied': {}, 'web_run': 0}


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
    s.setdefault('mut_repeat', 0)
    r = s['mut_repeat']
    if not (isinstance(r, int) and not isinstance(r, bool) and r >= 0):
        return fresh()
    for k, v in (('drift_prev', {}), ('drift_run', {}), ('drift_denied', {}), ('web_run', 0)):
        s.setdefault(k, v)
    p, w = s['drift_prev'], s['web_run']

    def count(x):
        return isinstance(x, int) and not isinstance(x, bool) and x >= 0
    if not (isinstance(p, dict)
            and all(v is None or (isinstance(v, list) and all(isinstance(t, str) for t in v))
                    for v in p.values())
            and all(isinstance(s[k], dict) and all(count(x) for x in s[k].values())
                    for k in ('drift_run', 'drift_denied'))
            and count(w)):
        return fresh()
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


def mut_reason(tool_name, tool_input, n):
    path = tool_input.get('file_path') or tool_input.get('notebook_path')
    target = path if isinstance(path, str) and path else 'the same input'
    return (f'loop guard: this {tool_name} of {target} is identical to the previous {n} '
            'Write/Edit calls. If another tool changed the file since, write different '
            'content or use that tool; otherwise the file already has this content: stop '
            'and continue with the next step.')


def drift_reason(tool_name, n, told, cls):
    if cls == 'read':
        r = (f'loop guard: this {tool_name} fetches the same page as the previous {n} '
             f'read{"s" if n > 1 else ""} (same host, path and query). Re-reading it with other '
             'options returns the same content. Use what you already have, read a different '
             'page, or report what you found.')
    else:
        r = (f'loop guard: this {tool_name} query is a near-repeat of the previous {n} (same '
             'words plus a few more). Narrowing by appending words is not a new search. Use '
             'the results you already have, change the query substantially, or report what '
             'you found.')
    if told >= 1:
        r += (f' You were already told this {told} time{"s" if told > 1 else ""}: do not try '
              'another variation.')
    return r


def burst_reason():
    return (f'loop guard: {WEB_BURST_MAX} searches in a row without acting on any result. '
            'Stop searching: summarize what you found or use a result.')


def web_class(tool_name):
    return next((c for c, r in DRIFT_RE.items() if r.fullmatch(tool_name)), None)


def drift_tokens(cls, tool_input):
    """search: sorted unique words of the query; read: one token, the lower-cased host,
    unquoted path (one trailing / dropped) and sorted query parameters of the url
    (fragment dropped; ?page=N stays a new page). A call without its string field falls
    back to the canonical JSON."""
    canon = json.dumps(tool_input, sort_keys=True, ensure_ascii=True)
    if cls == 'read':
        url = tool_input.get('url')
        if not isinstance(url, str):
            return [canon]
        try:
            u = urllib.parse.urlsplit(url.strip().lower())
            path = urllib.parse.unquote(u.path)
            if len(path) > 1 and path.endswith('/'):
                path = path[:-1]
            qs = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(u.query,
                                                                      keep_blank_values=True)))
            return [(u.hostname or '') + path + (f'?{qs}' if qs else '')]
        except ValueError:
            return [url.strip().lower()]
    text = tool_input.get('query')
    return sorted(set(re.findall(r'\w+', (text if isinstance(text, str) else canon).lower())))


def is_drift(prev, cur):
    a, b = set(prev), set(cur)
    return bool(a) and (b >= a or len(a & b) >= DRIFT_JACCARD * len(a | b))


def step(state, tool_name, tool_input):
    """Pure rule: returns (decision or None, new state). decision = (kind, reason)."""
    cmd = tool_input.get('command')
    if tool_name in POLL_TOOLS or (tool_name in SHELL_TOOLS and isinstance(cmd, str)
                                   and WAIT_RE.search(cmd)):
        return None, dict(state, web_run=0)
    h = call_hash(tool_name, tool_input)
    calls, denied = list(state['calls']), dict(state['denied'])
    rep = state.get('mut_repeat', 0)
    if tool_name in MUTATION_TOOLS:
        if h != state.get('last_mut'):
            calls, denied, rep = [], {}, -1
        rep += 1
        new = dict(state, calls=calls, denied=denied, last_mut=h, mut_repeat=rep, web_run=0)
        if rep >= 2:
            return ('deny', mut_reason(tool_name, tool_input, rep)), new
        return None, new
    n = calls.count(h)
    if n >= THRESHOLD:
        denied[h] = denied.get(h, 0) + 1
        return ('deny', reason(tool_name, n, denied[h] - 1)), dict(state, calls=calls,
                                                                   denied=denied)
    web = {'web_run': 0}
    cls = web_class(tool_name)
    if cls:
        toks, prev = drift_tokens(cls, tool_input), state['drift_prev'].get(cls)
        run, told = state['drift_run'].get(cls, 0), state['drift_denied'].get(cls, 0)
        drift = prev is not None and is_drift(prev, toks)
        if drift and run >= 2:
            return (('deny', drift_reason(tool_name, run + 1, told, cls)),
                    dict(state, drift_denied={**state['drift_denied'], cls: told + 1}))
        search = cls == 'search'
        if search and state['web_run'] >= WEB_BURST_MAX:
            return ('deny', burst_reason()), state
        web = {'drift_prev': {**state['drift_prev'], cls: toks},
               'drift_run': {**state['drift_run'], cls: run + 1 if drift else 0},
               'drift_denied': {**state['drift_denied'], cls: told if drift else 0},
               'web_run': state['web_run'] + 1 if search else state['web_run']}
    calls = (calls + [h])[-WINDOW:]
    denied = {k: v for k, v in denied.items() if k in calls}
    return None, dict(state, calls=calls, denied=denied, **web)


def prune(d, now):
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        if not STATE_NAME.fullmatch(name):
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
    if not real_dir(d):
        sys.stderr.write('loop-guard: state dir is a link; no decision\n')
        return None
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
