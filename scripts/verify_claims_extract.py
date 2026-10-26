"""verify_claims_extract: split a markdown document into checkable candidate claims.

Usage: python -I scripts/verify_claims_extract.py <doc.md> --root <root>
           [--max N] [--skip-lines L1,L2,...]

Prints a JSON array, one object per candidate claim: {"id", "line", "end", "claim",
"paths", "kind"}. A claim is a sentence (wrapped lines of a paragraph or list item are
joined, then split after `. `, `? ` or `! ` outside backticks, but not after `e.g.`,
`i.e.`, `vs.` or `etc.`; a list item ends at its last line) or a whole table row
prefixed with its header row, and it must hold a backticked repo path, a backticked
identifier (`Get-Foo`, `-Param`, `foo()`, UPPER_CASE), a number or a "quoted string";
`kind` is the first of path, identifier, number, quote that it holds. Fenced code,
headings and table separator rows are skipped, and so is everything under a heading
that names a plan, next steps, a proposal, a recommendation or a suggestion, until the
next heading of the same or a higher level; the number of claims skipped that way goes
to stderr as `plan-section claims skipped: N`. `line`..`end` are the document lines
the claim spans; `paths` lists up to 3 backticked relative paths that exist under
<root> (realpath containment; absolute and `..` paths are never touched). Identical
claims are kept once. --skip-lines drops every claim whose span holds one of those
lines (figures already decided by verify-doc); --max N keeps the first N.
"""
import json
import os
import re
import sys

FENCE = re.compile(r'^\s*(```|~~~)')
ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')
TICK = re.compile(r'`([^`]+)`')
PATHLIKE = re.compile(r'[\w.*-]*[A-Za-z][\w.*-]*(?:/[\w.*-]+)*/?')
IDENT = re.compile(r'-[A-Za-z][\w-]*|[A-Z][a-z]+-[A-Z]\w*|[A-Za-z_][\w.]*\(\)|[A-Z][A-Z0-9_]{2,}')
NUMBER = re.compile(r'\d')
QUOTE = re.compile(r'"[^"\n]+"')
PLAN = re.compile(r'\b(?:plan(?:s|ned|ning)?|next|proposals?|recommend\w*|suggest\w*)\b', re.I)
ABBR = re.compile(r'(?<![\w.])(?:e\.g|i\.e|vs|etc)\.$', re.I)
MAX_CLAIM = 400
MAX_PATHS = 3


def inside(root, path):
    """True if path resolves (symlinks and junctions too) to a place under root."""
    rp = os.path.normcase(os.path.realpath(path))
    return rp.startswith(os.path.normcase(os.path.join(os.path.realpath(root), '')))


def safe_rel(tok):
    """A relative path without a drive, a leading slash or a `..` part, else None."""
    tok = tok.replace('\\', '/')
    if tok.startswith('/') or re.match(r'[A-Za-z]:', tok) or '..' in tok.split('/'):
        return None
    return tok


def is_path(tok):
    return bool(PATHLIKE.fullmatch(tok)) and ('/' in tok or re.search(r'\w\.[A-Za-z]\w*$', tok))


def units(text):
    """(text, [(offset, line)], under a plan heading) for each paragraph, list item and
    table row; a table data row comes prefixed with its header row."""
    out, cur, fenced, plan, row, header = [], None, False, False, None, ''
    plan_lvl = 0

    def flush():
        nonlocal cur
        if cur:
            out.append(cur + (plan,))
        cur = None
    for n, raw in enumerate(text.split('\n'), 1):
        line = raw.rstrip('\r')
        s = line.strip()
        if fenced or not s.startswith('|'):
            row, header = None, ''
        if FENCE.match(line):
            flush()
            fenced = not fenced
            continue
        if fenced or not s or s.startswith('#'):
            flush()
            if not fenced and s.startswith('#'):
                lvl = len(s) - len(s.lstrip('#'))
                if not (plan and lvl > plan_lvl):
                    plan, plan_lvl = bool(PLAN.search(s)), lvl
            continue
        if s.startswith('|'):
            flush()
            if not re.fullmatch(r'[|:\s-]+', s):
                out.append((header + s, [(0, n)], plan))
                row = s
            elif row and not header:
                out.pop()    # the row just before a separator is the header
                header = row + ' '
            continue
        m = ITEM.match(line)
        if m:
            flush()
            s = line[m.end():].strip()
        if cur is None:
            cur = (s, [(0, n)])
        else:
            cur = (cur[0] + ' ' + s, cur[1] + [(len(cur[0]) + 1, n)])
    flush()
    return out


def sentences(unit):
    """(sentence, first line, last line) pieces of one unit."""
    text, starts = unit[:2]

    def line_at(pos):
        return [n for o, n in starts if o <= pos][-1]
    out, begin, code = [], 0, False
    for i, ch in enumerate(text):
        if ch == '`':
            code = not code
        elif (not code and ch in '.?!' and (i + 1 == len(text) or text[i + 1] == ' ')
              and not ABBR.search(text, 0, i + 1)):
            out.append((begin, i + 1))
            begin = i + 1
    out.append((begin, len(text)))
    res = []
    for a, b in out:
        lead = len(text[a:b]) - len(text[a:b].lstrip())
        s = text[a:b].strip()
        if s:
            res.append((s, line_at(a + lead), line_at(b - 1)))
    return res


def kind_of(s):
    ticks = TICK.findall(s)
    if any(is_path(t) and safe_rel(t) for t in ticks):
        return 'path'
    if any(IDENT.fullmatch(t) for t in ticks):
        return 'identifier'
    if NUMBER.search(s):
        return 'number'
    if QUOTE.search(s):
        return 'quote'
    return None


def paths_of(s, root):
    found = []
    for t in TICK.findall(s):
        rel = safe_rel(t) if is_path(t) else None
        if rel and rel not in found and len(found) < MAX_PATHS:
            p = os.path.join(root, rel)
            if inside(root, p) and os.path.exists(p):
                found.append(rel)
    return found


def extract(text, root, skip=(), limit=0):
    """(claims, number of claims skipped under a plan heading)."""
    claims, seen, planned = [], set(), 0
    for u in units(text):
        for s, first, last in sentences(u):
            k = kind_of(s)
            s = s[:MAX_CLAIM]
            if not k or s in seen or any(first <= n <= last for n in skip):
                continue
            if u[2]:
                planned += 1
                continue
            seen.add(s)
            claims.append({'id': len(claims) + 1, 'line': first, 'end': last, 'claim': s,
                           'paths': paths_of(s, root), 'kind': k})
            if limit and len(claims) >= limit:
                return claims, planned
    return claims, planned


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8')
    args, root, limit, skip = list(argv), os.getcwd(), 0, ()
    try:
        for flag in ('--root', '--max', '--skip-lines'):
            if flag in args:
                i = args.index(flag)
                val = args.pop(i + 1)
                args.pop(i)
                if flag == '--root':
                    root = val
                elif flag == '--max':
                    limit = int(val)
                else:
                    skip = {int(x) for x in val.split(',') if x.strip()}
    except (IndexError, ValueError):
        args = []
    if len(args) != 1 or not os.path.isfile(args[0]) or not os.path.isdir(root):
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    with open(args[0], encoding='utf-8', errors='replace') as f:
        text = f.read()
    claims, planned = extract(text, os.path.realpath(root), skip, limit)
    print(json.dumps(claims, indent=1, ensure_ascii=False))
    print(f'plan-section claims skipped: {planned}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
