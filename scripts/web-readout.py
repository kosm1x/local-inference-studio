"""web-readout: per-session scorecard for Claude Code web-session transcripts (read-only).

Usage: python -I scripts/web-readout.py <path> [--json] [--since ISO] [--grep REGEX]

<path> is a transcript .jsonl, or a directory searched recursively for .jsonl files
under a `projects` directory (history.jsonl and mcp-logs are skipped; both are judged
on the path below <path>, plus <path>'s own name). Per transcript: first/last timestamp
and duration, row count (malformed lines counted), compactions, tool calls by name,
denial rows by `toolDenialKind`, hook denials (`PreToolUse:<tool> hook error: <hook>:
<reason>`) by hook and by reason, other error results, the longest run of
byte-identical consecutive Bash commands and the MCP tool error count.
Only `assistant` tool_use and `user` tool_result blocks with a string id count:
`api-request-blob` rows repeat message content and would double-count. --since ISO
keeps rows stamped at or after ISO (a naive ISO is read as UTC; unstamped rows are
dropped). --grep REGEX lists each matching Bash call with its verdict:
  allowed           the result is not an error and no denial kind applies
  denied:<hook>     an error result naming a PreToolUse hook (wins over a kind)
  denied:<kind>     an error result, alone in a row that carries toolDenialKind
  denied?:<kind>    the kind is ambiguous: the row holds several results (error ones
                    get this, non-error ones are allowed) or the lone result is no error
  ran:error         the call was permitted and ran, but its result is an error
  no-result         no tool_result pairs with the call
--json prints one JSON object per transcript. Each header prints the transcript path,
whose file name is a session id. Printed text is masked, then truncated: a known key
prefix (sk-, ghp_, eyJ, ...) masks its run, as does any 32+ char run that does not read
as a path; a shorter run without a known prefix is NOT masked.
Exit 0, or 2 on a bad option or when no transcript is found.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

HOOK = re.compile(r'PreToolUse:(\S+) hook error: ([^:\n]+):\s*(.*)', re.S)
SECRET = re.compile(r'(?<![\w+/.-])(sk-|ghp_|gho_|github_pat_|xox[a-z]-|AKIA|eyJ)[\w+/=.-]+'
                    r'|(?<![\w+/=.-])[\w+/=.-]{32,}', re.A)   # a prefix may follow `=`
SHIFT = re.compile(r'(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])')


def mask(m):
    """A long run stays only when it reads as a path: it has a `/`, no `+` or `=`, every
    part under 32 chars and few case/digit shifts (random keys shift every few chars)."""
    s = m.group(0)
    if (m.group(1) is None and '/' in s and '+' not in s and '=' not in s
            and max(map(len, s.split('/'))) < 32 and len(SHIFT.findall(s)) <= len(s) / 10):
        return s
    return '<masked>'


def clip(text, n):
    """text on one line, key-like runs masked, then cut to n chars."""
    text = SECRET.sub(mask, ' | '.join(str(text).split('\n')))
    return text if len(text) <= n else text[:n - 3] + '...'


def result_text(content):
    """The text of a tool_result's content (a string or a list of blocks), stripped."""
    if isinstance(content, list):
        content = ' '.join(str(b.get('text', '')) for b in content if isinstance(b, dict))
    return content.strip() if isinstance(content, str) else ''


def when(stamp):
    """An aware datetime from an ISO stamp (naive = UTC), or None."""
    try:
        d = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def find(path):
    """Transcript paths under path (or path itself when it is a file), sorted."""
    if os.path.isfile(path):
        return [path]
    out = []
    for d, _, files in os.walk(path):
        rel = os.path.relpath(d, path).replace('\\', '/').split('/')
        base = os.path.basename(os.path.abspath(path))
        if 'projects' not in [base] + rel or any('mcp-logs' in p for p in rel):
            continue
        out += [os.path.join(d, f) for f in files
                if f.endswith('.jsonl') and f != 'history.jsonl']
    return sorted(out)


def duration(first, last):
    """'XhYYm' between two ISO stamps, or None when either does not parse."""
    a, b = when(first), when(last)
    if a is None or b is None:
        return None
    s = int((b - a).total_seconds())
    return f'{s // 3600}h{s % 3600 // 60:02d}m'


def okid(x):
    return isinstance(x, str) and x != ''


def blocks_of(o, typ, key):
    """The row's content blocks of type typ whose `key` id is a non-empty string."""
    msg = o.get('message')
    blocks = msg.get('content') if isinstance(msg, dict) else None
    if o.get('type') != ('assistant' if typ == 'tool_use' else 'user') or \
            not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict) and b.get('type') == typ
            and okid(b.get(key))]


def verdict(err, hook, kind, alone):
    if hook:
        return 'denied:' + hook
    if kind and err:
        return ('denied:' if alone else 'denied?:') + kind
    if kind and alone:
        return 'denied?:' + kind
    return 'ran:error' if err else 'allowed'


def readout(path, since=None, rx=None):
    """The scorecard dict for one transcript (since: aware datetime, rx: compiled)."""
    rows = bad = comp_b = comp_s = mcp_err = 0
    first = last = None
    tools, kinds, hooks, reasons, errors = Counter(), Counter(), Counter(), Counter(), Counter()
    uses, bash, results = {}, [], {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except ValueError:
                o = None
            if not isinstance(o, dict):
                bad += 1
                continue
            ts = o.get('timestamp') if isinstance(o.get('timestamp'), str) else None
            if since and (when(ts) is None or when(ts) < since):
                continue
            rows += 1
            if ts:
                first, last = first or ts, ts
            comp_b += o.get('subtype') == 'compact_boundary'
            comp_s += o.get('isCompactSummary') is True
            kind = clip(o['toolDenialKind'], 40) if o.get('toolDenialKind') else None
            if kind and o.get('type') == 'user':
                kinds[kind] += 1
            for b in blocks_of(o, 'tool_use', 'id'):
                name = clip(b.get('name'), 60)
                tools[name] += 1
                uses[b['id']] = name
                if name == 'Bash':
                    inp = b.get('input') if isinstance(b.get('input'), dict) else {}
                    bash.append((b['id'], ts, str(inp.get('command', ''))))
            res = blocks_of(o, 'tool_result', 'tool_use_id')
            for b in res:
                text = result_text(b.get('content'))
                err = b.get('is_error') is True
                h = HOOK.match(text) if err else None
                hook = clip(h.group(2), 40) if h else None
                if hook:
                    hooks[hook] += 1
                    reasons[(hook, clip(h.group(3), 100))] += 1
                v = verdict(err, hook, kind, len(res) == 1)
                if v == 'ran:error':
                    errors[clip(text, 100)] += 1
                if err and uses.get(b['tool_use_id'], '').startswith('mcp__'):
                    mcp_err += 1
                results[b['tool_use_id']] = (v, clip(text, 80))
    run, best, prev = 0, (0, ''), None
    for _, _, cmd in bash:
        run = run + 1 if cmd == prev else 1
        prev = cmd
        if run > best[0]:
            best = (run, cmd)
    out = {'path': path, 'rows': rows, 'malformed': bad, 'first': first, 'last': last,
           'duration': duration(first, last), 'compactions': max(comp_b, comp_s),
           'tools': dict(tools.most_common()), 'denials': dict(kinds.most_common()),
           'hook_denials': dict(hooks.most_common()),
           'hook_reasons': [[h, r, n] for (h, r), n in reasons.most_common(10)],
           'other_errors': [[t, n] for t, n in errors.most_common(5)],
           'identical_bash_run': {'count': best[0], 'command': clip(best[1], 120)},
           'mcp_errors': mcp_err}
    if rx is not None:
        out['grep'] = [{'timestamp': ts, 'verdict': results.get(i, ('no-result', ''))[0],
                        'result': results.get(i, ('', ''))[1], 'command': clip(cmd, 160)}
                       for i, ts, cmd in bash if rx.search(cmd)]
    return out


def text_of(r):
    """The compact text scorecard for one readout dict."""
    def pairs(d):
        return ', '.join(f'{k} {v}' for k, v in d.items()) or '-'
    lines = [f"== {r['path']}",
             f"rows {r['rows']} (malformed {r['malformed']})  first {r['first']}  "
             f"last {r['last']}  duration {r['duration']}",
             f"compactions {r['compactions']}   mcp errors {r['mcp_errors']}",
             f"tools: {pairs(r['tools'])}",
             f"denials: {pairs(r['denials'])}",
             f"hook denials: {pairs(r['hook_denials'])}"]
    lines += [f'  {n:4d}  {h}: {t}' for h, t, n in r['hook_reasons']]
    lines.append('other errors:' + ('' if r['other_errors'] else ' -'))
    lines += [f'  {n:4d}  {t}' for t, n in r['other_errors']]
    run = r['identical_bash_run']
    lines.append(f"longest identical Bash run: {run['count']}"
                 + (f"x  {run['command']}" if run['count'] else ''))
    if 'grep' in r:
        lines.append(f"grep: {len(r['grep'])} matching Bash calls")
        lines += [f"  {g['timestamp']}  {g['verdict']}  [{g['result']}]  {g['command']}"
                  for g in r['grep']]
    return '\n'.join(lines)


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(prog='web-readout.py')
    ap.add_argument('path')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--since')
    ap.add_argument('--grep')
    a = ap.parse_args(argv)
    since = when(a.since) if a.since is not None else None
    if a.since is not None and since is None:
        print(f'--since: not an ISO timestamp: {a.since!r}', file=sys.stderr)
        return 2
    try:
        rx = re.compile(a.grep) if a.grep is not None else None
    except re.error as e:
        print(f'--grep: bad regex: {e}', file=sys.stderr)
        return 2
    paths = find(a.path) if os.path.exists(a.path) else []
    if not paths:
        print(f'no transcript found under {a.path}', file=sys.stderr)
        return 2
    for p in paths:
        r = readout(p, since, rx)
        print(json.dumps(r) if a.json else text_of(r) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
