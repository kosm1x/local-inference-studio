"""verify_claims_report: deterministic cross-check of the verifier sessions' verdicts.

Usage: python -I scripts/verify_claims_report.py <run.json> <out.json>
       python -I scripts/verify_claims_report.py --retry <ledger.json>

<run.json> is written by scripts/verify-claims.ps1: {"document", "root", "batch",
"wall_s", "aborted", "claims" (the extractor's array), "plan_skipped" (the extractor's
plan-section count), "deterministic" ([{finding, line}] from verify-doc FAIL lines),
"sessions" ([{ids, stdout, server_n_tokens}])}.
Each session's stdout is a `claude -p --output-format json` envelope whose `result`
must be a JSON array of {id, verdict, evidence} (a fence or prose around it is
tolerated: else the last `[{...}]` in the text that decodes and holds a `verdict` key
is taken, so an array echoed in the prose before or after the answer does not win). A
sent claim without a valid answer is `verifier-failed`. Evidence that names a relative
path existing under the root is evidence-backed (existence only; absolute and `..`
paths are never touched). A true or
false verdict whose evidence cites `path:line` and quotes a span of 12+ characters is
evidence-confirmed when that span occurs within +-3 lines of the cited line (files
read only inside the root and under 8 MB). Prints the honest count, writes everything
to <out.json>; exit 1 if any claim is false (verifier or verify-doc) or
verifier-failed, else 0.

A run.json with "resume" (the path of an earlier <out.json>) takes the claims, the
deterministic findings and the sessions of that ledger, keeps every decided verdict
and fills only its verifier-failed claims from the new sessions (numbered after the
old ones); <out.json> must be another file. --retry prints the JSON array of a
ledger's verifier-failed claims, the only ones a resume sends again.
"""
import json
import os
import re
import sys

VERDICTS = ('true', 'false', 'unverifiable')
TOKEN = re.compile(r'[\w./\\-]+')
CITE = re.compile(r'([\w./\\-]+):(\d+)')
START = re.compile(r'\[\s*\{')
QUOTED = re.compile(r'"([^"]{12,})"|`([^`]{12,})`')
SLACK = 3        # an evidence quote may sit this many lines from the cited line
MAX_READ = 8_000_000


def inside(root, path):
    """True if path resolves (symlinks and junctions too) to a place under root."""
    rp = os.path.normcase(os.path.realpath(path))
    return rp.startswith(os.path.normcase(os.path.join(os.path.realpath(root), '')))


def rel_under(root, tok):
    """tok as a relative path that exists under root, else None. A token with a drive,
    a leading slash or a `..` part is refused before any file system call."""
    tok = tok.replace('\\', '/').rstrip('.:,;')
    if (('/' not in tok and '.' not in tok) or tok.startswith('/') or ':' in tok
            or '..' in tok.split('/')):
        return None
    p = os.path.join(root, tok)
    return tok if inside(root, p) and os.path.exists(p) else None


def answers(stdout):
    """(envelope dict, list of answer dicts or None) from one session's stdout."""
    env = None
    for text in (stdout.strip(), stdout[stdout.find('{'):stdout.rfind('}') + 1]):
        try:
            env = json.loads(text)
            break
        except ValueError:
            continue
    if not isinstance(env, dict):
        return {}, None
    res = env.get('result')
    if not isinstance(res, str):
        return env, None
    try:
        arr = json.loads(res.strip())
    except ValueError:
        arr = None
    if not isinstance(arr, list):
        arr, end, dec = None, 0, json.JSONDecoder()
        for m in START.finditer(res):
            if m.start() < end:
                continue    # inside an array already decoded
            try:
                got, end = dec.raw_decode(res, m.start())
            except ValueError:
                continue
            if isinstance(got, list) and any(isinstance(a, dict) and 'verdict' in a for a in got):
                arr = got    # an echoed claim list after the answer does not replace it
    if arr is None:
        return env, None
    return env, [a for a in arr if isinstance(a, dict)]


def backed(evidence, root):
    found = []
    for tok in TOKEN.findall(evidence):
        rel = rel_under(root, tok)
        if rel and rel not in found:
            found.append(rel)
    return found


def flat(s):
    return ' '.join(s.split())


def confirmed(evidence, root):
    """True if a quoted span of the evidence occurs near a cited path:line."""
    quotes = [flat(a or b) for a, b in QUOTED.findall(evidence)]
    for path, at in CITE.findall(evidence):
        rel = rel_under(root, path)
        p = os.path.join(root, rel) if rel else None
        if not quotes or not p or not os.path.isfile(p) or os.path.getsize(p) > MAX_READ:
            continue
        with open(p, encoding='utf-8', errors='replace') as f:
            lines = f.read().split('\n')
        n = int(at)
        window = flat(' '.join(lines[max(0, n - 1 - SLACK):n + SLACK]))
        if any(q in window for q in quotes):
            return True
    return False


def to_retry(old):
    """The claims of ledger old that came back verifier-failed."""
    failed = {e['id'] for e in old['ledger'] if e['verdict'] == 'verifier-failed'}
    return [c for c in old['claims'] if c['id'] in failed]


def report(run, old=None):
    root = os.path.realpath(run['root'])
    base = len(old['sessions']) if old else 0
    keep = {e['id']: e for e in (old['ledger'] if old else [])
            if e['verdict'] != 'verifier-failed'}
    claims = {c['id']: c for c in (old or run)['claims']}
    ledger, sessions = [], []
    for i, s in enumerate(run['sessions'], base + 1):
        env, arr = answers(s.get('stdout') or '')
        got = {}
        for a in arr or []:
            aid = a.get('id')
            aid = int(aid) if isinstance(aid, str) and aid.strip().isdigit() else aid
            if type(aid) is int and aid in s['ids'] and a.get('verdict') in VERDICTS:
                got.setdefault(aid, a)
        usage = env.get('usage') or {}
        prompt = (usage.get('input_tokens') or 0) + (usage.get('cache_read_input_tokens') or 0)
        sessions.append({'session': i, 'ids': s['ids'], 'parsed': arr is not None,
                         'turns': env.get('num_turns'), 'duration_ms': env.get('duration_ms'),
                         'usage': usage, 'subtype': env.get('subtype'),
                         'is_error': env.get('is_error'),
                         'permission_denials': env.get('permission_denials'),
                         'server_n_tokens': s.get('server_n_tokens') or [],
                         'peak_prompt': max(s.get('server_n_tokens') or [prompt]),
                         'result': env.get('result') if len(got) < len(s['ids']) else None})
        for cid in s['ids']:
            if cid in keep:
                continue
            c, a = claims[cid], got.get(cid)
            ev = str(a.get('evidence', '')) if a else ''
            e = {'id': cid, 'line': c['line'], 'end': c['end'], 'claim': c['claim'],
                 'verdict': a['verdict'] if a else 'verifier-failed', 'evidence': ev,
                 'session': i, 'backed': [], 'confirmed': False}
            if e['verdict'] in ('true', 'false'):
                e['backed'] = backed(ev, root)
                e['confirmed'] = bool(e['backed']) and confirmed(ev, root)
            ledger.append(e)
    retried = [e['id'] for e in ledger]
    recovered = [e['id'] for e in ledger if e['verdict'] != 'verifier-failed']
    if old:
        merged = {e['id']: e for e in old['ledger']}
        merged.update({e['id']: e for e in ledger})
        ledger = [merged[k] for k in sorted(merged)]
        det = old['deterministic']
    else:
        det = [{'line': d['line'], 'claim': d['finding'], 'verdict': 'deterministic-false',
                'evidence': 'verify-doc'} for d in run['deterministic']]
    count = {v: sum(e['verdict'] == v for e in ledger) for v in VERDICTS + ('verifier-failed',)}
    count['deterministic-false'] = len(det)
    count['backed'] = sum(bool(e['backed']) for e in ledger)
    count['confirmed'] = sum(e['confirmed'] for e in ledger)

    def hits(d):
        return [e for e in ledger if e['line'] <= d['line'] <= e['end']]
    sent = [d for d in det if hits(d)]
    count['det_sent'] = len(sent)
    count['det_also_false'] = sum(any(e['verdict'] == 'false' for e in hits(d)) for d in sent)
    return {'ledger': ledger, 'deterministic': det, 'counts': count, 'base': base,
            'sessions': (old['sessions'] if old else []) + sessions, 'retried': retried,
            'recovered': recovered, 'claims': list(claims.values()),
            'plan_skipped': (old or run).get('plan_skipped')}


def honest_count(run, r, name):
    c, ss = r['counts'], r['sessions'][r['base']:]
    out = [f'verify-claims v2: {name}',
           f'claims extracted: {len(r["claims"])}   sent to the verifier: {len(r["retried"])} '
           f'in {len(ss)} sessions (batch {run["batch"]})',
           'plan-section claims skipped: '
           f'{"not recorded" if r["plan_skipped"] is None else r["plan_skipped"]}',
           f'verdicts: true {c["true"]}   false {c["false"]}   unverifiable {c["unverifiable"]}   '
           f'verifier-failed {c["verifier-failed"]}   deterministic-false '
           f'{c["deterministic-false"]}']
    if run.get('resume'):
        out += [f'resumed from: {os.path.basename(run["resume"])}',
                f'retried: {len(r["retried"])}   recovered: {len(r["recovered"])}   '
                f'still failed: {c["verifier-failed"]}']
    out += [f'evidence-backed: {c["backed"]} of {c["true"] + c["false"]}   evidence-confirmed by '
           f'the harness: {c["confirmed"]} of {c["backed"]}',
           f'deterministic findings also judged false by the verifier: {c["det_also_false"]} '
           f'of {c["det_sent"]}',
           f'wall: {round(run.get("wall_s") or 0)} s   turns: '
           f'{sum(s["turns"] or 0 for s in ss)}   peak prompt tokens: '
           f'{max([s["peak_prompt"] for s in ss] or [0])}',
           'false claims (deterministic first):']
    out += [f'  line {e["line"]}: {e["claim"]} -- {e["evidence"]}'
            for e in r['deterministic'] + [e for e in r['ledger'] if e['verdict'] == 'false']]
    vf = [f'{e["id"]} (line {e["line"]})' for e in r['ledger'] if e['verdict'] == 'verifier-failed']
    out.append(f'verifier-failed claims: {", ".join(vf) if vf else "(none)"}')
    if run.get('aborted'):
        out.append(f'aborted: {run["aborted"]}')
    return '\n'.join(out)


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    if len(argv) != 2:
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    if argv[0] == '--retry':
        with open(argv[1], encoding='utf-8') as f:
            print(json.dumps(to_retry(json.load(f)), indent=1, ensure_ascii=False))
        return 0
    with open(argv[0], encoding='utf-8') as f:
        run = json.load(f)
    old = None
    if run.get('resume'):
        if os.path.realpath(run['resume']) == os.path.realpath(argv[1]):
            print('refusing to overwrite the resumed ledger', file=sys.stderr)
            return 2
        with open(run['resume'], encoding='utf-8') as f:
            old = json.load(f)
    r = report(run, old)
    root, doc = os.path.realpath(run['root']), run['document']
    name = (os.path.relpath(os.path.realpath(doc), root) if inside(root, doc)
            else os.path.basename(doc))
    text = honest_count(run, r, name.replace('\\', '/'))
    print(text)
    full = {'document': doc, 'root': root, 'batch': run['batch'], 'wall_s': run.get('wall_s'),
            'aborted': run.get('aborted'), 'resumed_from': run.get('resume'),
            'retried': r['retried'], 'recovered': r['recovered'], 'honest_count': text,
            'plan_skipped': r['plan_skipped'], 'counts': r['counts'], 'ledger': r['ledger'],
            'deterministic': r['deterministic'], 'sessions': r['sessions'], 'claims': r['claims']}
    with open(argv[1], 'w', encoding='utf-8', newline='\n') as f:
        json.dump(full, f, indent=1, ensure_ascii=False)
    c = r['counts']
    return 1 if c['false'] + c['deterministic-false'] or c['verifier-failed'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
