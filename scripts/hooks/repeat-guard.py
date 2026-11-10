"""repeat-guard: PostToolUse(Failure) / Stop / SubagentStop hook; blocks on repeated replies.

Rule: read the last TAIL_BYTES of the transcript (transcript_path; agent_transcript_path
for SubagentStop), group the assistant rows by message id (one message = one turn), keep
each turn's text blocks (tool_use ignored; a turn without text is skipped; API error and
<synthetic> rows skipped; sidechain rows skipped in the main transcript only, since every
row of an agent transcript is one) and take the last TURNS turns. On Stop / SubagentStop
the hook input's last_assistant_message is appended as the latest turn unless the
transcript's last turn already equals it (the file may not hold the final message at
Stop time). Each text is normalized (lower case, backticks removed, whitespace
collapsed; digits kept), and its compared text (the whole text, or its first PREFIX and
last SUFFIX chars when longer) is matched against the latest turn's by difflib ratio. If
>= MIN_SIMILAR of those turns (the latest included) are >= RATIO similar and the latest
text is >= MIN_CHARS long, the hook blocks: top-level decision block with the reason
(on PostToolUse it goes next to the tool result, on Stop it is the model's next input),
except on PostToolUseFailure, whose reference documents only
hookSpecificOutput.additionalContext, so the reason goes there. The PostToolUse events
act inside a turn; Stop fires only when the model ends its turn. A PostToolUse(Failure)
event with an agent_id (a tool call inside an agent, whose transcript_path is the main
session's) gives no decision.

One warning per loop: a block stores the latest turn's compared text in
<tempdir>/lis-repeat-guard/<session id>[.<agent id>].json (lower-cased; atomic). While
the latest turn stays >= RATIO similar to the stored text, nothing blocks; once it is
not (or the tail holds no text turn), the file is removed and the rule is live again. A
Stop with stop_hook_active true gives no decision and leaves the state alone. State files
older than 24 h are pruned on every run (state names only); a corrupt state file counts as
none. A state dir that is a link or junction is not used: no prune, no state, so the rule
still blocks each loop turn but loses the one-warning suppression. Any error
(bad input, input over MAX_INPUT, missing or unsafe session id, unreadable transcript)
gives no decision: no output, exit 0. Deterministic, stdlib only, no network, run with
`python -I`. ASCII only.
"""
import difflib
import json
import os
import re
import stat
import sys
import tempfile
import time

TAIL_BYTES = 400_000   # transcript bytes read from the end
MAX_INPUT = 1_000_000  # stdin bytes; above this, no decision
TURNS = 6              # assistant turns compared, the latest included
MIN_SIMILAR = 3        # near-identical turns (the latest included) that block the stop
RATIO = 0.85           # difflib ratio that counts as near-identical
PREFIX = 600           # normalized head chars compared per turn
SUFFIX = 400           # plus the tail chars, for a text over PREFIX + SUFFIX
MIN_CHARS = 120       # the latest normalized text must be at least this long
MAX_AGE_S = 24 * 3600  # state files older than this are deleted
SESSION_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
STATE_NAME = re.compile(r'[a-z0-9_-]{1,128}(?:\.[a-z0-9_-]{1,128})?\.json(?:\.\d+\.tmp)?')


def state_dir():
    return os.path.join(tempfile.gettempdir(), 'lis-repeat-guard')


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


def normalize(text):
    return ' '.join(text.lower().replace('`', '').split())


def key(t):
    """The compared text: the whole text, or its head and tail when it is longer."""
    return t if len(t) <= PREFIX + SUFFIX else t[:PREFIX] + t[-SUFFIX:]


def tail_rows(path):
    """JSON object rows of the last TAIL_BYTES of a JSONL file (a cut first line dropped)."""
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        start = max(0, f.tell() - TAIL_BYTES)
        f.seek(start)
        data = f.read(TAIL_BYTES)
    if start:
        data = data[data.find(b'\n') + 1:] if b'\n' in data else b''
    rows = []
    for line in data.split(b'\n'):
        try:
            r = json.loads(line)
        except ValueError:  # blank, cut or non-UTF-8 lines are skipped
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def turn_texts(rows, main=True):
    """Normalized assistant text per turn, oldest first; turns without text are skipped, and
    so are API error and synthetic rows. main: the main transcript, whose sidechain rows
    are skipped (every row of an agent transcript is a sidechain row)."""
    order, by_id = [], {}
    for r in rows:
        m = r.get('message')
        if (r.get('type') != 'assistant' or (main and r.get('isSidechain') is True)
                or r.get('isApiErrorMessage') is True or not isinstance(m, dict)
                or m.get('model') == '<synthetic>'):
            continue
        c = m.get('content')
        parts = ([b['text'] for b in c if isinstance(b, dict) and b.get('type') == 'text'
                  and isinstance(b.get('text'), str)] if isinstance(c, list)
                 else [c] if isinstance(c, str) else [])
        mid = m.get('id')
        if isinstance(mid, str) and mid in by_id:
            by_id[mid].extend(parts)
            continue
        order.append(list(parts))
        if isinstance(mid, str):
            by_id[mid] = order[-1]
    return [t for t in (normalize('\n'.join(p)) for p in order) if t]


def ratio(a, b):
    return difflib.SequenceMatcher(None, key(a), key(b), autojunk=False).ratio()


def ratios(texts):
    """Ratio of each of the last TURNS texts to the latest one (the latest gives 1.0)."""
    last = texts[-TURNS:]
    return [ratio(last[-1], t) for t in last]


def similar(texts):
    """The number of near-identical turns when the rule fires, else 0."""
    if len(texts) < MIN_SIMILAR or len(texts[-1]) < MIN_CHARS:
        return 0
    n = sum(1 for r in ratios(texts) if r >= RATIO)
    return n if n >= MIN_SIMILAR else 0


def step(texts, stored):
    """Pure rule: (similar count when this event blocks, else 0; the stored text after it).
    stored is the latest turn's compared text (key) at the last block, or None."""
    latest = key(texts[-1]) if texts else ''
    if stored is not None:
        if latest and ratio(latest, stored) >= RATIO:
            return 0, stored   # the same loop was already warned once
        stored = None
    n = similar(texts)
    return (n, latest) if n else (0, stored)


def load(path):
    try:
        with open(path, 'r', encoding='ascii') as f:
            s = json.load(f)
    except (OSError, ValueError):
        return None  # missing or corrupt state counts as none
    t = s.get('text') if isinstance(s, dict) else None
    return t if isinstance(t, str) else None


def reason(n):
    return (f'repeat guard: your last {n} replies are near-identical. You are repeating the '
            'same analysis. Do not restate it. In one paragraph: what you verified, what you '
            'did not, and the one next action or the question for the user. Then stop.')


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
            if now - os.path.getmtime(p) > MAX_AGE_S:
                os.remove(p)
        except OSError:
            pass


def save(path, s):
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        json.dump(s, f, separators=(',', ':'))
    os.replace(tmp, path)


def run(raw):
    if len(raw) > MAX_INPUT:
        sys.stderr.write('repeat-guard: input over 1 MB; no decision\n')
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    sid, aid = data.get('session_id'), data.get('agent_id')
    if not (isinstance(sid, str) and SESSION_RE.fullmatch(sid)):
        return None
    ev = data.get('hook_event_name')
    if ev == 'SubagentStop':
        if not (isinstance(aid, str) and SESSION_RE.fullmatch(aid)):
            return None
        name, path = f'{sid}.{aid}', data.get('agent_transcript_path')
    elif ev in ('PostToolUse', 'PostToolUseFailure') and aid is not None:
        return None  # a tool call inside an agent: transcript_path is the main session's
    else:
        name, path = sid, data.get('transcript_path')
    if data.get('stop_hook_active') is True:
        return None  # a stop hook continuation: no block, state left alone
    if not (isinstance(path, str) and os.path.isfile(path)):
        return None
    texts = turn_texts(tail_rows(path), main=ev != 'SubagentStop')
    lam = data.get('last_assistant_message')
    lam = normalize(lam) if isinstance(lam, str) else ''
    if lam and (not texts or texts[-1] != lam):
        texts.append(lam)
    d = state_dir()
    os.makedirs(d, exist_ok=True)
    ok = real_dir(d)  # a link at the state path: no state, the loop still blocks (C1)
    if not ok:
        sys.stderr.write('repeat-guard: state dir is a link or not real; no state\n')
    if ok:
        prune(d, time.time())
    mark = os.path.join(d, name.lower() + '.json')
    stored = load(mark) if ok else None
    n, new = step(texts, stored)
    if n:
        if ok:
            save(mark, {'text': new, 'similar': n})
        return reason(n)
    if ok and new is None and os.path.exists(mark):
        os.remove(mark)  # the loop is over (or the state was corrupt): the rule is live again
    return None


def output(ev, r):
    """The hook output for a block: PostToolUseFailure documents only additionalContext;
    the other events take top-level decision block with reason."""
    if ev == 'PostToolUseFailure':
        return {'hookSpecificOutput': {'hookEventName': ev, 'additionalContext': r}}
    return {'decision': 'block', 'reason': r}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        r = run(raw)
        if r:
            print(json.dumps(output(json.loads(raw).get('hook_event_name'), r)))
    except Exception:  # never block a session on a guard bug: no decision
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
