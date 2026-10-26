"""Replay a compaction-bench capture through loop-guard.py, as Claude Code would call it.

Run: python -I scripts/hooks/tests/loop-guard_replay.py [capture.jsonl ...] [--expect-first N]
Default capture: bench/results/compact-effort-low-forced-20261026-050211.capture.jsonl.
A missing capture (bench/results is gitignored) prints SKIP and is not an error.

Each main-loop response's tool_use blocks are fed, in order, to the real hook (subprocess,
stdin JSON, python -I, TEMP pointed at a throwaway dir, one session_id per capture).
Responses to a compaction summary request (last user text "CRITICAL: Respond with TEXT
ONLY") are skipped: Claude Code does not run their tool calls. Reported per capture:
turns, calls, denies, the 1-based call index and turn of the first deny, and the turns
saved if the model had answered on the turn after the first deny
(saved = num_turns from the sibling .result.json - (first deny turn + 1)). num_turns is
the result envelope's count, UNVERIFIED against the requests on the wire (a gap of 1 on
the loop runs), so "turns saved" is approximate.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, '..', 'loop-guard.py')
ROOT = os.path.join(HERE, '..', '..', '..')
DEFAULT = os.path.join(ROOT, 'bench', 'results', 'compact-effort-low-forced-20261026-050211.capture.jsonl')
MARK = 'CRITICAL: Respond with TEXT ONLY'


def last_user_text(req):
    msgs = req.get('messages') or []
    if not msgs:
        return ''
    c = msgs[-1].get('content')
    if isinstance(c, str):
        return c
    return ' '.join(b.get('text', '') for b in c or [] if isinstance(b, dict) and b.get('type') == 'text')


def turns_of(path):
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            o = json.loads(line)
            req, resp = o.get('request'), o.get('response')
            if not (isinstance(req, dict) and req.get('tools') and isinstance(resp, dict)):
                continue
            if MARK in last_user_text(req):
                continue
            out.append([(b['name'], b.get('input') or {}) for b in resp.get('content') or []
                        if isinstance(b, dict) and b.get('type') == 'tool_use'])
    return out


def replay(path):
    turns = turns_of(path)
    res = path.replace('.capture.jsonl', '.result.json')
    num_turns = json.load(open(res, encoding='utf-8')).get('num_turns') if os.path.exists(res) else None
    calls = denies = 0
    first = None
    with tempfile.TemporaryDirectory() as t:
        env = dict(os.environ, TEMP=t, TMP=t, TMPDIR=t)
        for ti, tool_uses in enumerate(turns, 1):
            for name, inp in tool_uses:
                calls += 1
                p = json.dumps({'session_id': 'replay', 'tool_name': name, 'tool_input': inp,
                                'hook_event_name': 'PreToolUse', 'cwd': t})
                r = subprocess.run([sys.executable, '-I', HOOK], input=p.encode(), capture_output=True,
                                   env=env, timeout=20)
                out = r.stdout.decode('ascii').strip()
                if out and json.loads(out)['hookSpecificOutput']['permissionDecision'] == 'deny':
                    denies += 1
                    if first is None:
                        first = (calls, ti, name, json.loads(out)['hookSpecificOutput']['permissionDecisionReason'])
    saved = num_turns - (first[1] + 1) if (first and num_turns) else 0
    name = os.path.basename(path).replace('.capture.jsonl', '')
    print(f'{name}: turns {len(turns)}, num_turns {num_turns}, calls {calls}, denies {denies}, '
          + (f'first deny at call {first[0]} (turn {first[1]}, {first[2]}), turns saved {saved}'
             if first else 'first deny: none'))
    if first:
        print(f'  reason: {first[3]}')
    return first[0] if first else None


def main():
    args = sys.argv[1:]
    expect = None
    if '--expect-first' in args:
        i = args.index('--expect-first')
        expect = int(args[i + 1])
        del args[i:i + 2]
    paths = args or [DEFAULT]
    firsts = []
    for p in paths:
        if os.path.exists(p):
            firsts.append(replay(p))
        else:
            # bench/results is gitignored: a fresh clone has no capture (bench/compact/run.ps1).
            print(f'SKIP capture not found: {os.path.normpath(p)}')
            firsts.append('skipped')
    if expect is not None and firsts[0] not in (expect, 'skipped'):
        print(f'FAIL first deny at call {firsts[0]}, expected {expect}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
