"""verify-doc: deterministic checks of the figures in a markdown document.

Usage: python -I scripts/verify-doc.py <file.md> [--root <repo root>]
       python -I scripts/verify-doc.py --hook   (PostToolUse hook, reads stdin JSON)

Checks (one line per finding; any FAIL -> exit 1; a usage error -> exit 2):
  sum    a total followed by a labelled split of 3 or more parts, "546 rows (172 deny,
         72 allow, 135 none)" or "86 rows: R1x22, R2x22, O1x13", or of 2 complementary
         parts, "13 scripts (3 tested, 10 untested)": the parts must add up to the
         total. Other 2-part lists are skipped: "10 calls (2 Bash, 3 Read)" is often a
         partial breakdown, not a partition. Remainders later in the sentence ("N
         [more] skipped|other|others|remaining|rest|left|pending|excluded|ignored")
         that close the gap exactly pass: "20 runs (12 pass, 5 fail) plus 3 skipped".
  count  "N PowerShell scripts", "N `.py` files" (also Python, JavaScript, Markdown;
         plural only): N must equal the number of such files in the repo (git
         ls-files, or a walk). Skipped when scoped ("in scripts/", "under `bench/`")
         or after an edit verb ("edits 3 PowerShell scripts"). "at|as of <commit>"
         within 40 characters after it ("10 PowerShell scripts at `3a2a5d8`") makes it
         historical: a mismatch is INFO, not FAIL. Known limit: an unrelated "at
         <commit>" that close ("the bug fixed at `3a2a5d8`") also downgrades it; the
         INFO line still shows the figure.
  lines  "`path` (N lines)", "`path`, N lines." and table rows "| `path` | N |" under
         a Lines/LOC header: N must equal the file's newline count (as wc -l). Only
         files inside the root and under 8 MB are read.
  path   a backticked repo path that does not exist -> INFO only, never fails
sum and count skip "double-quoted" text (a quotation) and figures inside backticks.
Stdlib only; the one subprocess is git ls-files.
"""
import json
import os
import re
import subprocess
import sys

NUM = r'(\d{1,3}(?:,\d{3})+|\d+)'
LABEL = r'`?[A-Za-z][\w-]*`?'
ITEM_NL = NUM + r'\s+' + LABEL + r'(?:\s+' + LABEL + r')?'   # 172 deny, 5 alpha rows
ITEM_LN = r'[A-Za-z][\w-]*\s*[x\u00d7]\s*' + NUM   # R1x22, R1 x 22 (multiplication sign)
SEP = r'\s*,\s*(?:and\s+)?|\s+and\s+'
TOTAL = re.compile(r'(?<![\w./:\u2013-])~?' + NUM + r'((?:\s+' + LABEL + r'){1,4})'
                   r'(?:\s*\(\s*|:\s+)((?:' + ITEM_NL + r'|' + ITEM_LN + r')(?:(?:' + SEP + r')'
                   r'(?:' + ITEM_NL + r'|' + ITEM_LN + r'))+)(?=\s*[).;]|\s*$)')
NOT_TOTAL = re.compile(r'(?i)\b(?:port|line|page|row|column|version|build|v)\s*$')
COUNT = re.compile(r'(?<![\w./-])(\d+)\s+(PowerShell|Python|JavaScript|Markdown|`?\.(?:ps1|py|js|md)`?)'
                   r'\s+(?:scripts|files)\b', re.I)
REMAINDER = re.compile(r'(?i)(?<![\w.])' + NUM + r'\s+(?:more\s+)?'
                       r'(?:skipped|other|others|remaining|rest|left|pending|excluded|ignored)(?![\w-])')
SHA = r'(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b'   # 7-40 hex, a digit and a letter
HISTORICAL = re.compile(r'\b(?:at|as of)\s+`?' + SHA)
SCOPED = re.compile(r'^\s*(?:in|under)\s+`?[\w./-]*/')
PAIRS = {frozenset(p) for p in [('pass', 'fail'), ('allow', 'deny'), ('passed', 'failed'),
                                 ('with', 'without'), ('true', 'false'), ('met', 'unmet')]}
EDIT_VERB = re.compile(r'(?i)\b(?:adds?|added|edit(?:s|ed)?|chang(?:e|es|ed)|touch(?:es|ed)?|'
                       r'modif(?:y|ies|ied)|remov(?:e|es|ed)|creat(?:e|es|ed)|delet(?:e|es|ed))'
                       r'\s+(?:\w+\s+){0,2}$')
EXT = {'powershell': 'ps1', 'python': 'py', 'javascript': 'js', 'markdown': 'md'}
INLINE_LINES = re.compile(r'`([^`\s]+)`\s*(?:\(\s*|,\s*)' + NUM + r'\s+lines?(?=\s*\)|[.,;]|\s*$)')
TABLE_LINES = re.compile(r'^\|\s*`([^`]+)`\s*\|\s*' + NUM + r'\s*\|')
PATH = re.compile(r'`([\w.-]+(?:/[\w.-]+)+\.[A-Za-z0-9]+)`')
MAX_READ = 8_000_000
MAX_CONTEXT = 9_000


def num(s):
    return int(s.replace(',', ''))


def is_year(s):
    return re.fullmatch(r'(?:19|20)\d\d', s) is not None


def inside(root, path):
    """True if path resolves (symlinks and junctions too) to a place under root."""
    rp = os.path.normcase(os.path.realpath(path))
    return rp.startswith(os.path.normcase(os.path.join(os.path.realpath(root), '')))


def complementary(items):
    """True for two parts that cover a whole: tested/untested, covered/non-covered, pass/fail."""
    a, b = (re.sub(r'^[\d,]+\s+', '', i.strip()).strip('`').lower() for i in items)
    return (frozenset((a, b)) in PAIRS
            or any(x == p + y for x, y in ((a, b), (b, a)) for p in ('un', 'non', 'non-', 'not ')))


def sentence(tail):
    """The rest of the sentence (or table cell) that tail starts in."""
    return re.split(r'\||[.!?](?:\s|$)', tail, maxsplit=1)[0]


def closes_gap(tail, gap):
    """True if the remainders ("plus 3 skipped") in the rest of the sentence, up to the
    next total (a remainder may start that total: "plus 3 skipped (2 a, 1 b)"), add up
    to exactly gap."""
    s = sentence(tail)
    nxt = TOTAL.search(s)
    cut = nxt.start() if nxt else len(s)
    return sum(num(r.group(1)) for r in REMAINDER.finditer(s) if r.start() <= cut) == gap


def historical(tail, n=None):
    """True if "at|as of <commit>" starts within 40 characters after the figure, before
    the next count and before any bare number other than n (the count's own value)."""
    s = sentence(tail)
    nxt = COUNT.search(s)
    s = s[:nxt.start()] if nxt else s
    bare = next((x for x in re.finditer(r'(?<![\w.])' + NUM + r'(?![\w.])', s) if num(x.group(1)) != n), None)
    s = s[:bare.start()] if bare else s
    return any(h.start() <= 40 for h in HISTORICAL.finditer(s))


def unquoted(s):
    """Same length, for the sum and count checks: a "quoted" span is reported speech, so
    it is blanked, and a figure inside a backtick span is code, so its digits become _
    (a digit inside a word or extension, `.ps1`, stays)."""
    s = re.sub(r'"[^"\n]*"', lambda m: ' ' * len(m.group(0)), s)
    return re.sub(r'`[^`]*`', lambda m: re.sub(r'(?<![\w.])\d+', lambda d: '_' * len(d.group(0)),
                                               m.group(0)), s)


def blocks(text):
    """Yield (text, line starts, kind): joined paragraphs and single table rows, code skipped.
    line starts = [(offset in text, line number)], to map a match back to its line."""
    para, fence = [], False
    for i, line in enumerate(text.split('\n'), 1):
        s = line.strip()
        if s.startswith('```'):
            fence = not fence
        new = fence or not s or s.startswith(('#', '|', '- ', '* ', '```')) or re.match(r'\d+\.\s', s)
        if new and para:
            yield join(para), 'p'
            para = []
        if not s and not fence:
            yield join([]), 'b'  # a blank line ends a table, so its header stops applying
        if fence or s.startswith('```') or not s:
            continue
        if s.startswith('|'):
            yield join([(i, s)]), 't'
        else:
            para.append((i, s.replace('**', '')))
    if para:
        yield join(para), 'p'


def join(lines):
    starts, pos = [], 0
    for i, s in lines:
        starts.append((pos, i))
        pos += len(s) + 1
    return ' '.join(s for _, s in lines), starts


def repo_files(root, ext):
    try:
        out = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard', '--', '*.' + ext],
                             cwd=root, capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return len([f for f in out.stdout.splitlines() if os.path.isfile(os.path.join(root, f))])
    except (OSError, subprocess.SubprocessError):
        pass
    n = 0
    for _, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != '.git']
        n += sum(f.lower().endswith('.' + ext) for f in files)
    return n


def line_count(path):
    """Newline count, or None for a file that is unreadable or over MAX_READ bytes."""
    try:
        if os.path.getsize(path) > MAX_READ:
            return None
        n = 0
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                n += chunk.count(b'\n')
        return n
    except OSError:
        return None


def check(doc, root):
    with open(doc, encoding='utf-8', errors='replace') as f:
        text = f.read()
    out, seen, counts, header, prev = [], set(), {}, [], None
    for (blk, starts), kind in blocks(text):
        if kind == 'b':
            prev = None
            continue

        def at(pos):
            return [i for o, i in starts if o <= pos][-1]
        cells = [c.strip() for c in blk.strip('|').split('|')] if kind == 't' else [blk]
        if kind == 't' and all(re.fullmatch(r':?-+:?', c) for c in cells if c):
            continue
        if kind != 't' or prev != 't':
            header = cells
        prev = kind
        for cell in cells:
            plain = unquoted(cell)
            for m in TOTAL.finditer(plain):
                vals = [a or b for a, b in re.findall(ITEM_NL + r'|' + ITEM_LN, m.group(3))]
                labels = [re.search(r'[A-Za-z][\w-]*', i).group(0).lower() for i in re.split(SEP, m.group(3))]
                total, got = num(m.group(1)), sum(num(v) for v in vals)
                # a split has 3+ parts (or 2 complementary ones), one distinct label each,
                # none above the total: "4070 Ti SUPER (16375 MiB, 15111 MiB, 1264 MiB)" is not one
                if ((len(vals) == 2 and not complementary(re.split(SEP, m.group(3))))
                        or any(is_year(v) for v in [m.group(1)] + vals)
                        or len(set(labels)) < len(labels) or any(num(v) > total for v in vals)
                        or NOT_TOTAL.search(plain[:m.start()])):
                    continue
                if total != got and not closes_gap(plain[m.end():], total - got):
                    out.append(f'FAIL sum: "{m.group(0).strip()}" (doc says {total}, measured '
                               f'{" + ".join(vals)} = {got}) at line {at(blk.find(cell) + m.start())}')
        plain = unquoted(blk)
        for m in COUNT.finditer(plain):
            if SCOPED.search(plain[m.end():]) or EDIT_VERB.search(plain[:m.start()]):
                continue
            ext = EXT.get(m.group(2).lower(), m.group(2).strip('`.').lower())
            if ext not in counts:
                counts[ext] = repo_files(root, ext)
            if num(m.group(1)) != counts[ext] and historical(blk[m.end():], num(m.group(1))):
                out.append(f'INFO count: "{m.group(0)}" historical figure, not checked against the '
                           f'live tree (doc says {m.group(1)}, live {counts[ext]}) at line {at(m.start())}')
            elif num(m.group(1)) != counts[ext]:
                out.append(f'FAIL count: "{m.group(0)}" (doc says {m.group(1)}, measured '
                           f'{counts[ext]} .{ext} files) at line {at(m.start())}')
        hits = list(INLINE_LINES.finditer(blk))
        t = TABLE_LINES.match(blk) if kind == 't' else None
        if t and len(header) > 1 and re.fullmatch(r'(?i)lines|loc', header[1].strip(' *')):
            hits.append(t)
        for m in hits:
            p = os.path.join(root, m.group(1))
            n = line_count(p) if inside(root, p) and os.path.isfile(p) else None
            if n is not None and n != num(m.group(2)):
                out.append(f'FAIL lines: {m.group(1)} (doc says {m.group(2)}, measured {n}) '
                           f'at line {at(m.start())}')
        for m in PATH.finditer(blk):
            p = m.group(1)
            if (p not in seen and '..' not in p.split('/')
                    and not os.path.exists(os.path.join(root, p))):
                seen.add(p)
                out.append(f'INFO path not found (proposed or wrong): {p} at line {at(m.start())}')
    return sorted(out, key=lambda f: not f.startswith('FAIL'))


def hook():
    data = json.load(sys.stdin)
    root = os.path.realpath(data.get('cwd') or os.getcwd())
    fp = os.path.join(root, data['tool_input']['file_path'])
    if not fp.lower().endswith('.md') or not inside(root, fp) or not os.path.isfile(fp):
        return
    found = check(fp, root)
    if not found:
        return
    rel = os.path.relpath(os.path.realpath(fp), root).replace('\\', '/')
    msg = (f'verify-doc findings for {rel} (check each FAIL against the source; a scoped or '
           f'partial figure is not an error; INFO is advisory):')
    for i, f in enumerate(found):
        if len(msg) + len(f) + 1 > MAX_CONTEXT - 100:  # 100: room for the "+N more" line
            me = os.path.abspath(__file__).replace('\\', '/')
            me = f'"{me}"' if ' ' in me else me
            msg += f'\n+{len(found) - i} more; run: python -I {me} {rel}'
            break
        msg += '\n' + f
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': msg}}))


def main(argv):
    if '--hook' in argv:
        try:
            hook()
        except Exception:
            pass  # a hook failure must never fail the Write
        return 0
    sys.stdout.reconfigure(errors='backslashreplace')
    args, root = list(argv), os.getcwd()
    if '--root' in args:
        i = args.index('--root')
        if i + 1 >= len(args):
            print('verify-doc: --root needs a value', file=sys.stderr)
            return 2
        root = args.pop(i + 1)
        args.pop(i)
    if len(args) != 1 or not os.path.isfile(args[0]) or not os.path.isdir(root):
        print('verify-doc: need one existing <file.md> and an existing --root\n'
              + __doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    found = check(args[0], os.path.abspath(root))
    print('\n'.join(found) if found else 'verify-doc: 0 findings')
    return 1 if any(f.startswith('FAIL') for f in found) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
