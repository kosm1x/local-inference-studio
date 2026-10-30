"""Rung 2 (long-fix) grading: the facts file and compaction. grade.py loads this file by path
when meta.profile == 'longrun' and merges grade_longrun()'s dict into its result; that dict
decides bar_met and bar_reason. Stdlib only, no subprocess.

Facts file grammar (one fact per line, append-only; a leading - or * and backticks are
ignored; any other line is kind 'other'):
  BEFORE pass N fail N        counts of the first test run; true when equal to TAP before
  CHECK pass N fail N         true when equal to the counts of the most recent test-command
                              result before the write that added the line; null when a
                              non-exact run (test_runs_nonexact) comes between the two. A
                              CHECK line whose nearest preceding test run (exact or not) an
                              earlier CHECK line already recorded is a CHECK for a run that
                              never happened: the check_without_run violation (report-only)
  FIXED <test name> | <path>  true when the name is a TAP test that failed before and passes
                              after, the path is the manifest src file of that test, and the
                              file is in the diff; a false one carries reason name_unmatched
                              (no TAP test of that name, decided first), passed_before or
                              still_failing, and only for a name that exists and flipped,
                              not_in_manifest, wrong_file or not_in_diff (report-only).
                              facts_name_unmatched counts the name_unmatched lines;
                              facts_name_unmatched_would_pass those whose name with the
                              path's module tag (m01-x.js: 'm01 ') prepended is a TAP test
                              that flipped fail -> pass (the flip only: no manifest, file or
                              diff check)
  NEXT mNN (or NEXT none)     resume pointer, parsed, not graded
A test-command run is a Bash command whose first segment (before | || && ;), less a
trailing 2>&1, is the meta's test_cmd. A non-exact run is any other Bash command whose first
segment, after leading cd segments, starts with node and names the test file (extra flags,
a cd . && prefix); a read such as cat or grep of the test file is neither.
test_runs_instructed is 2 plus the modules the prompt lists in 'then after m04, ... and mNN,'
(null without that list); test_runs_short (violation) is that minus the test-command runs
(not below 0). check_missing (violation) counts the test-command runs after the first with no
CHECK line added before the next one (or the end); only CHECK lines held in the final file
count (a retracted CHECK leaves its run missing). By ruling (21) the last test-command run
is exempt as the closing "once more" run, test_runs_short or not, when the session went on
to report (the stream's final result event has text and a STATUS line, the claim_status
source; a timed-out or turn-limited session has none, so nothing is exempt) and no Write
or Edit of a file other than the facts file follows it (facts writes are records, not
edits; an errored Write or Edit still counts as an edit; Bash commands are not edits);
check_missing_final_exempt is 1 when that run would have counted (null with the replay
null). facts_lines_at_boundaries and
facts_fixed_at_boundaries count the BEFORE, CHECK and FIXED lines, and the FIXED lines, held
at each boundary (report-only, like every violation).
The facts content at each compaction boundary is rebuilt by replaying Write (content), Edit
(old -> new, replace_all honoured) and these Bash writes on the facts file (the target is
one token whose basename is the facts name; > instead of >> rewrites the whole file):
  cat >> <facts> << 'EOF' (or << EOF, <<'EOF', <<"EOF"), the body lines, then a last line
    that is the delimiter alone; an unquoted delimiter allows no $ ` or backslash in the body
  echo '<text>' >> <facts> or echo "<text>" >> <facts>: no backslash; "" also no $ or `
  printf '<text>' >> <facts> (or "<text>"): no %, the only escapes \\n and \\t
A Bash read of the facts file is skipped (counted in facts_bash_reads). The command (2>&1
and 2>/dev/null dropped) has no >, $, {, <( or backtick and no tee, mv, cp, rm, truncate,
sponge, install or system word; each segment (split at | & ; and newlines) parses with
shlex, its first word is in READ_CMDS, no - token contains i, and a segment naming the
facts file has no glob character (* ? [). sort: no - token contains o (-o, --output,
--compress-program). sed: the only - token is -n and the script (the first operand) has no
e, w or W anywhere. Everything else (awk, uniq, less, cut, python ...) is not a read. This
is a character and token check, not a bash parser: it does not model full bash expansion
(aliases, functions, IFS, history) and fails toward null, so some real reads null the
replay (sed -n '$p' <facts>, grep '[0-9]' <facts>). Any other Bash command naming the
file, or an Edit whose old_string is not found, makes the replay null (unknown, not false).
A boundary's lines other than NEXT survived (facts_survived, the bar input) when they
appear in the final facts file, trimmed, exact, in order; NEXT only is exempt (parsed, not
graded). facts_survived_strict applies that test to every line. facts_survived_missing
lists the lines lost (multiset; first 20, total in facts_survived_missing_total);
facts_order_breaks counts the boundaries whose non-NEXT lines are all kept but out of
order; next_rewrites counts the distinct NEXT lines held at a boundary and missing from the
final file. facts_retracted: lines a replayed write added that the final file lacks
(reported); its non-NEXT lines are the facts_line_changed violation (report-only).
facts_recall counts the final file's FIXED names.
After each boundary, facts_read_after (strict) is a Read of the facts file in the next 3
tool calls; facts_restored_after is a transcript record with attachment.type 'file' whose
path basename is the facts name, between that transcript boundary and the next (Claude
Code's post-compaction file restore); facts_read_after_any is either. The restore and any
are null when the transcript is absent or its boundary count differs from the stream's.
Boundaries with any false are the facts_not_read_after_compaction violation (report-only).
"""
import collections
import json
import os
import re
import shlex

FACTS_NAME = re.compile(r'lis-facts-\d{8}-\d{6}\.md')
# The prompt's test-run checkpoints: "then after m04, m08, ... and m24, and once more".
CHECKPOINTS = re.compile(r'then after ((?:m\d+,\s*)*m\d+\s+and\s+m\d+),\s+and once more')
FACT = (('BEFORE', re.compile(r'^BEFORE\s+pass\s+(\d+),?\s+fail\s+(\d+)$')),
        ('CHECK', re.compile(r'^CHECK\s+pass\s+(\d+),?\s+fail\s+(\d+)$')),
        ('FIXED', re.compile(r'^FIXED\s+(.+?)\s*\|\s*(.+)$')),
        ('NEXT', re.compile(r'^NEXT\s+(m\d+|none)$')))
GRADED = ('BEFORE', 'CHECK', 'FIXED')
SURVIVAL_EXEMPT = ('NEXT',)  # kinds facts_survived skips; () restores the strict rule
# Summary lines of a test run: spec reporter "(U+2139) pass 24", TAP "# pass 24", or plain.
RUN_COUNT = {k: re.compile(r'(?m)^\s*(?:#|\u2139)?\s*' + k + r'\s+(\d+)\s*$')
             for k in ('pass', 'fail')}
LEAD = r'(?im)^[\s>*_`#-]*'
CLAIM_BEFORE = re.compile(LEAD + r'Before:[\s*_`]*pass\s*(\d+),?\s*fail\s*(\d+)')
CLAIM_AFTER = re.compile(LEAD + r'After:[\s*_`]*pass\s*(\d+),?\s*fail\s*(\d+)')
CLAIM_FIXED = re.compile(LEAD + r'Fixed:[\s*_`]*(\d+)')
COMPACT_FAILED = ('summarization produced empty response', 'prompt is too long',
                  'autocompact is thrashing')
SUSPICIOUS = re.compile(r"child_process|require\(['\"](?:node:)?fs['\"]\)|process\.exit"
                        r"|writeFile|spawn")
REASONING_FLAG = re.compile(r'''(?:^|[\s"'])(?:--reasoning|-rea)["']?(?:=|\s+)["']?([A-Za-z]+)''')
THINKING = {v: re.compile(r'enable_thinking\W*:\s*' + v) for v in ('false', 'true')}
SEGMENT = re.compile(r'\|\|?|&&|;')
# Bash writes the replay applies (module docstring).
TARGET = r'''(?P<q>['"]?)(?P<t>[^\s'"<>|&;]+)(?P=q)'''
BASH_WRITE = (
    ('heredoc', re.compile(r'cat\s*(?P<op>>>?)\s*' + TARGET + r'''\s*<<\s*(?P<dq>['"]?)'''
                           r'(?P<d>\w+)(?P=dq)[ \t]*\n(?P<s>(?:[^\n]*\n)*?)(?P=d)\n?')),
    ('echo', re.compile(r'''echo\s+(?P<s>'[^'\\]*'|"[^"\\$`]*")\s*(?P<op>>>?)\s*''' + TARGET)),
    ('printf', re.compile(r'''printf\s+(?P<s>'[^'%]*'|"[^"$`%]*")\s*(?P<op>>>?)\s*'''
                          + TARGET)))
# Bash reads of the facts file the replay skips (module docstring).
READ_CMDS = ('grep', 'egrep', 'cat', 'wc', 'head', 'tail', 'ls', 'stat', 'file', 'diff', 'nl',
             'od', 'md5sum', 'sha256sum', 'sort', 'sed')
NOT_READ = re.compile(r'[>${`]|<\(|\b(?:tee|mv|cp|rm|truncate|sponge|install|system)\b')
# Fields grade.py lists in "undecided" when null.
UNDECIDED = ('axis_exercised', 'facts_survived', 'facts_gate', 'claim_before_agrees',
             'claim_fixed_count_agrees')


def facts_name(stderr):
    """The facts file name from the wrapper banner; None when absent or ambiguous."""
    names = set(FACTS_NAME.findall(stderr or ''))
    return names.pop() if len(names) == 1 else None


def first_segment(cmd):
    """The command before the first | || && ; less a trailing 2>&1."""
    if not isinstance(cmd, str):
        return cmd
    return re.sub(r'\s+2>&1$', '', SEGMENT.split(cmd, 1)[0].strip())


def reasoning_off(cmdline):
    """True when the last --reasoning / -rea value (space or =) is off; with neither flag,
    when the command line has "enable_thinking": false. Either way, False when it has
    "enable_thinking": true anywhere (fail closed). run.ps1's Test-ReasoningOff is the same
    test."""
    if THINKING['true'].search(cmdline):
        return False
    vals = REASONING_FLAG.findall(cmdline)
    if vals:
        return vals[-1] == 'off'
    return bool(THINKING['false'].search(cmdline))


def node_run(cmd, test_file):
    """True when cmd's first segment, after leading cd segments, starts with node and names
    test_file (a test run, exact or not; a cat or grep of the file is not one)."""
    segs = [x.strip() for x in SEGMENT.split(cmd)]
    while len(segs) > 1 and re.match(r'cd(?:\s|$)', segs[0]):
        segs.pop(0)
    return bool(re.match(r'node(?:\s|$)', segs[0])) and test_file in segs[0]


def bash_write(cmd, name):
    """('>>' or '>', text) when cmd is one of the Bash writes the replay applies (module
    docstring) and its target's basename is name, else None."""
    if not isinstance(cmd, str) or not name:
        return None
    for kind, rx in BASH_WRITE:
        m = rx.fullmatch(cmd.strip())
        if not m or base_name(m['t']) != name:
            continue
        s = m['s']
        if kind == 'heredoc':
            if m['d'] in s.split('\n') or not m['dq'] and re.search(r'[$`\\]', s):
                return None
            return m['op'], s
        if kind == 'echo':
            return m['op'], s[1:-1] + '\n'
        if re.search(r'\\(?![nt])', s):
            return None
        return m['op'], s[1:-1].replace('\\n', '\n').replace('\\t', '\t')
    return None


def bash_read(cmd, name):
    """True when cmd only reads (module docstring): the replay skips it. name: the facts
    file name (a segment naming it may hold no glob character)."""
    if not isinstance(cmd, str):
        return False
    c = re.sub(r'\s2>(?:&1|/dev/null)(?=\s|$)', ' ', cmd)
    segs = [x.strip() for x in re.split(r'[|&;\n]+', c) if x.strip()]
    return bool(segs) and not NOT_READ.search(c) and all(
        read_segment(x) and not (name in x and re.search(r'[*?[]', x)) for x in segs)


def read_segment(seg):
    try:
        t = shlex.split(seg)
    except ValueError:
        return False
    flags = [x for x in t[1:] if x.startswith('-')]
    if not t or t[0] not in READ_CMDS or any('i' in x for x in flags):
        return False
    if t[0] == 'sort':
        return not any('o' in x for x in flags)
    if t[0] == 'sed':
        ops = [x for x in t[1:] if not x.startswith('-')]
        return flags == ['-n'] and bool(ops) and not re.search('[ewW]', ops[0])
    return True


def norm(path):
    return str(path or '').replace('\\', '/')


def base_name(path):
    return norm(path).rsplit('/', 1)[-1]


def same_file(path, rel):
    p = norm(path)
    return p == rel or p.endswith('/' + rel)


def lines_of(text):
    return [ln.strip() for ln in (text or '').splitlines() if ln.strip()]


def parse_line(line):
    t = re.sub(r'^[-*]\s*', '', line.strip()).replace('`', '').strip()
    for kind, rx in FACT:
        m = rx.match(t)
        if m:
            return kind, m.groups()
    return 'other', ()


def run_counts(text):
    found = {k: rx.findall(text or '') for k, rx in RUN_COUNT.items()}
    return None if not all(found.values()) else {k: int(v[-1]) for k, v in found.items()}


def run_ok(text, test):
    """True when a test run's output shows test ok: a TAP 'ok N - <test>' or spec
    '(U+2714) <test>' line, or a fixture reporter line (gen_longfix.py REPORTER) for test's
    mNN prefix, 'mNN ok k/n' or 'mNN FAIL k/n: <name>; <name>' without test among the names.
    Without an mNN prefix a test is never ok in the reporter format. A name holding '; ' is
    ambiguous in a FAIL list (no fixture test name holds ';'). CR characters are dropped."""
    text = text.replace('\r', '')
    if re.search(r'(?m)^\s*(?:ok \d+ - |\u2714 )' + re.escape(test) + r'(?:\s|$)', text):
        return True
    tag = re.match(r'm\d+(?= )', test)
    return bool(tag) and any(
        m[1] is None or test not in m[1].split('; ')
        for m in re.finditer(r'(?m)^' + tag[0] + r' (?:ok \d+/\d+|FAIL \d+/\d+: (.*))$', text))


def subsequence(sub, seq):
    it = iter(seq)
    return all(any(x == y for y in it) for x in sub)


def missing(lines, final):
    """The lines of lines with no copy left in final (each final line matches once)."""
    left, gone = collections.Counter(final), []
    for x in lines:
        if left[x]:
            left[x] -= 1
        else:
            gone.append(x)
    return gone


def tri(parts):
    return False if any(p is False for p in parts) else None if None in parts else True


def src_file(test_file):
    """Manifest test entry 'file' -> the src file it exercises (identity for a src path)."""
    return re.sub(r'(^|/)test/(.*)\.test\.js$', r'\1src/\2.js', norm(test_file))


def replay(events, name):
    """(ok, steps, adds): steps = [(event index, content)] after each applied Write, Edit or
    Bash write on the facts file; adds = {line: [event index that added it, ...]}. A
    tool_use whose result is an error is not applied."""
    errored = {e['id'] for e in events if e['kind'] == 'tool_result' and e['is_error']}
    content, steps, adds = None, [], {}
    for e in events:
        inp = e['input'] if isinstance(e['input'], dict) else {}
        if e['kind'] != 'tool_use':
            continue
        if e['name'] == 'Bash' and name in str(inp.get('command')):
            w = bash_write(inp.get('command'), name)
            if w is None and bash_read(inp.get('command'), name):
                continue
            if w is None:
                return False, steps, adds
            if e['id'] in errored:
                continue
            new = w[1] if w[0] == '>' else (content or '') + w[1]
        elif e['name'] not in ('Write', 'Edit') or base_name(inp.get('file_path')) != name \
                or e['id'] in errored:
            continue
        elif e['name'] == 'Write':
            new = str(inp.get('content') or '')
        else:
            old, rep = inp.get('old_string'), inp.get('new_string')
            if not isinstance(old, str) or not isinstance(rep, str):
                return False, steps, adds
            if content is None and old == '':
                new = rep
            elif content is None or old not in content:
                return False, steps, adds
            else:
                new = content.replace(old, rep, -1 if inp.get('replace_all') else 1)
        gained = collections.Counter(lines_of(new)) - collections.Counter(lines_of(content))
        for line in gained.elements():
            adds.setdefault(line, []).append(e['i'])
        content = new
        steps.append((e['i'], content))
    return True, steps, adds


def transcript_counts(path):
    counts = {'boundaries': 0, 'summaries': 0}
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    counts['boundaries'] += e.get('type') == 'system' \
                        and e.get('subtype') == 'compact_boundary'
                    counts['summaries'] += bool(e.get('isCompactSummary'))
    except (OSError, TypeError):
        return None
    return counts


def transcript_restores(path, name):
    """Per transcript compact boundary: True when a file attachment of name follows it
    before the next boundary. None when the transcript is unreadable or name is None."""
    if not name:
        return None
    out = []
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                if e.get('type') == 'system' and e.get('subtype') == 'compact_boundary':
                    out.append(False)
                a = e.get('attachment')
                if out and isinstance(a, dict) and a.get('type') == 'file' \
                        and base_name(a.get('filename')) == name:
                    out[-1] = True
    except (OSError, TypeError):
        return None
    return out


def manifest_src(path):
    """{test name: src file} from the generator manifest, or None."""
    try:
        with open(path, encoding='utf-8') as f:
            return {t['name']: src_file(t['file']) for t in json.load(f)['tests']}
    except (OSError, TypeError, ValueError, KeyError):
        return None


def meta_value(m, *keys):
    return next((m[k] for k in keys if k in m), None) if isinstance(m, dict) else None


def grade_longrun(meta, s, before, after, files, facts_path, transcript_path, r, texts,
                  facts_name=None):
    """meta: run.ps1 meta; s: grade.stream() output; before/after: grade.tap(); files: the
    numstat file list; facts_path: the final facts file to read; facts_name: the facts file
    name the model wrote (default: facts_path's basename); r: grade.py's result so far (claim
    and scope fields); texts: stderr, diff and debug log text. Returns the fields to merge
    into the result."""
    ev = s['events']
    test_cmd = (meta.get('test_cmd') or '').strip()
    test_file = test_cmd.split()[-1] if test_cmd else None
    name = facts_name or (base_name(facts_path) if facts_path else None)
    src = [f for f in meta.get('allowed_files') or [] if f != name]
    uses = [e for e in ev if e['kind'] == 'tool_use']

    def inp(e):
        return e['input'] if isinstance(e['input'], dict) else {}

    def src_target(e):
        p = inp(e).get('file_path')
        hit = e['name'] in ('Write', 'Edit') and next((f for f in src if same_file(p, f)), None)
        return hit or None

    bash = [e for e in uses if e['name'] == 'Bash' and isinstance(inp(e).get('command'), str)]
    run_ids = {e['id']: e['i'] for e in bash
               if test_cmd and first_segment(inp(e)['command']) == test_cmd}
    runs = [e for e in ev if e['kind'] == 'tool_result' and e['id'] in run_ids]
    # node runs of the test file that are not test-command runs: their counts are unknown.
    nonexact = [e['i'] for e in bash if test_file and node_run(inp(e)['command'], test_file)
                and e['id'] not in run_ids]

    def last_run(i):
        return next((e for e in reversed(runs) if e['i'] < i), None)

    edits = [(e['i'], src_target(e)) for e in uses if src_target(e)]
    ok, steps, adds = replay(ev, name) if name else (None, [], {})

    def lines_at(i):
        return lines_of(next((c for si, c in reversed(steps) if si < i), None))

    exists = bool(facts_path) and os.path.isfile(facts_path)
    final = []
    if exists:
        with open(facts_path, encoding='utf-8-sig', errors='replace') as f:
            final = lines_of(f.read())

    # Verdict per final line; the add index comes from the replay (FIFO per identical line).
    man = manifest_src(meta.get('manifest')) if meta.get('manifest') else None
    pending = {k: list(v) for k, v in adds.items()} if ok else {}
    verdicts, fixed_at, verified, unmatched, would_pass = [], [], 0, 0, 0
    check_runs = []  # per CHECK line: the index of the nearest test run (exact or not) before it
    for line in final:
        kind, g = parse_line(line)
        added = pending[line].pop(0) if pending.get(line) else None
        v = reason = None
        if kind == 'BEFORE' and before:
            v = (int(g[0]), int(g[1])) == (before['pass'], before['fail'])
        elif kind == 'CHECK' and added is not None:
            run = last_run(added)
            near = [i for i in nonexact if i < added] + ([run['i']] if run else [])
            check_runs.append(max(near) if near else None)
            c = run_counts(run['text']) if run else None
            if any((run['i'] if run else -1) < i < added for i in nonexact):
                v = None
            else:
                v = False if run is None else None if c is None else \
                    (c['pass'], c['fail']) == (int(g[0]), int(g[1]))
        elif kind == 'FIXED':
            test, path = g[0].strip(), norm(g[1].strip())
            if before is None or after is None:
                v = None
            elif before['tests'].get(test) is not False or not after['tests'].get(test):
                v = False
                reason = 'name_unmatched' if test not in before['tests'] else \
                    'passed_before' if before['tests'][test] is not False else 'still_failing'
            elif man is not None:
                want = man.get(test)
                v = want is not None and same_file(path, want) and want in files
                reason = None if v else 'not_in_manifest' if want is None else \
                    'wrong_file' if not same_file(path, want) else 'not_in_diff'
            if reason == 'name_unmatched':
                unmatched += 1
                tag = re.match(r'(m\d+)-', base_name(path))
                cand = tag[1] + ' ' + test if tag else None
                would_pass += bool(tag and before['tests'].get(cand) is False
                                   and after['tests'].get(cand))
            if added is not None:
                fixed_at.append((added, test, path))
                run = last_run(added)
                # Only a TAP test name (tests-before) can be verified: the reporter's module
                # lines would otherwise vouch for an invented mNN name.
                verified += bool(run and before is not None and test in before['tests']
                                 and run_ok(run['text'] or '', test))
        vd = {'line': line, 'kind': kind, 'verdict': v, 'added_at': added}
        if kind == 'FIXED':
            vd['reason'] = reason
        verdicts.append(vd)
    graded = [x['verdict'] for x in verdicts if x['kind'] in GRADED]
    facts_false, undecided = graded.count(False), graded.count(None)
    # A CHECK line whose run an earlier CHECK line already recorded is no record of a run.
    check_without_run = sum(n - 1 for n in collections.Counter(
        k for k in check_runs if k is not None).values())
    # Test-command runs after the first with no CHECK line added before the next run (or end).
    pos = sorted(run_ids.values())
    check_adds = [x['added_at'] for x in verdicts
                  if x['kind'] == 'CHECK' and x['added_at'] is not None]
    missed = [not any(a < i < b for i in check_adds)
              for a, b in zip(pos[1:], pos[2:] + [len(ev)])]
    # Ruling (21): the closing run (the session reported: a final result with a STATUS
    # line; no later Write or Edit of a file other than the facts file, errored calls
    # included) is exempt.
    res = [e for e in ev if e['kind'] == 'result']
    reported = bool(res and res[-1]['text']) and r.get('claim_status') is not None
    later_edit = bool(pos) and any(
        u['name'] in ('Write', 'Edit') and u['i'] > pos[-1]
        and not (name and same_file(inp(u).get('file_path'), name)) for u in uses)
    final_exempt = int(reported and bool(missed) and missed[-1] and not later_edit)
    check_missing = None if not ok else sum(missed) - final_exempt
    cp = CHECKPOINTS.search(str(meta.get('prompt') or ''))
    instructed = 2 + len(re.findall(r'm\d+', cp[1])) if cp else None
    exact = len(run_ids) if test_cmd else None
    short = None if instructed is None or exact is None else max(instructed - exact, 0)

    bounds = [e for e in ev if e['kind'] == 'system' and e['subtype'] == 'compact_boundary']
    restores = transcript_restores(transcript_path, name)
    if restores is not None and len(restores) != len(bounds):
        restores = None
    at_b, blist, gone_all, next_gone = [], [], [], set()
    for k, b in enumerate(bounds):
        lines = lines_at(b['i']) if ok else None
        gone = [] if lines is None else missing(lines, final)
        gone_all += [{'i': b['i'], 'kind': parse_line(x)[0], 'line': x} for x in gone]
        next_gone |= {x for x in gone if parse_line(x)[0] == 'NEXT'}
        kept = None if lines is None \
            else [x for x in lines if parse_line(x)[0] not in SURVIVAL_EXEMPT]
        after_b = [u for u in uses if u['i'] > b['i']][:3]
        done = {f for i, _, f in fixed_at if i < b['i']} if ok else None
        read = any(u['name'] == 'Read' and name is not None
                   and base_name(inp(u).get('file_path')) == name for u in after_b)
        restored = None if restores is None else restores[k]
        at_b.append(lines)
        blist.append({
            'i': b['i'], 'trigger': meta_value(b['meta'], 'trigger'),
            'pre_tokens': meta_value(b['meta'], 'pre_tokens', 'preTokens'),
            'post_tokens': meta_value(b['meta'], 'post_tokens', 'postTokens'),
            'duration_ms': meta_value(b['meta'], 'duration_ms', 'durationMs'),
            'src_edits_before': sum(i < b['i'] for i, _ in edits),
            'src_edits_after': sum(i > b['i'] for i, _ in edits),
            'fact_lines': None if lines is None
            else sum(parse_line(x)[0] != 'other' for x in lines),
            'facts_survived': None if lines is None else subsequence(kept, final),
            'facts_survived_strict': None if lines is None else subsequence(lines, final),
            'order_break': None if lines is None else not subsequence(kept, final)
            and not missing(kept, final),
            'facts_read_after': read, 'facts_restored_after': restored,
            'facts_read_after_any': None if restored is None else read or restored,
            'redo_edits': None if done is None else
            sum(i > b['i'] and any(same_file(p, f) for p in done) for i, f in edits)})
    trans = transcript_counts(transcript_path)
    fired = len(bounds) if bounds or trans is None else trans['boundaries']
    # Boundaries known only from the transcript cannot be placed in the event order.
    mid_edit = any(x['src_edits_before'] and x['src_edits_after'] for x in blist) \
        if bounds or not fired else None
    survived = tri([x['facts_survived'] for x in blist]) if blist else None
    strict = tri([x['facts_survived_strict'] for x in blist]) if blist else None
    next_rewrites = None if not ok or not bounds and fired else len(next_gone)
    added_all = collections.Counter({k: len(v) for k, v in adds.items()})
    retracted = sorted((added_all - collections.Counter(final)).elements(),
                       key=lambda x: adds[x][0]) if ok else None

    claim = r.get('claim_text')
    text = claim or ''
    hay = {'claim': text, 'stderr': texts.get('stderr'),
           'envelope': json.dumps(s['envelope'] or {}),
           'assistant_text': '\n'.join(e['text'] or '' for e in ev
                                       if e['kind'] == 'assistant_text'),
           'debug_log': texts.get('debug')}
    failed_in = [k for k, v in hay.items() if v and any(t in v.lower() for t in COMPACT_FAILED)]
    failed = bool(failed_in)
    finals = [e['i'] for e in ev if e['kind'] == 'assistant_text'] \
        or [e['i'] for e in ev if e['kind'] == 'result' and e['text']]
    after_last = finals[-1] > bounds[-1]['i'] if claim is not None and bounds and finals \
        else None

    def last(rx):
        m = rx.findall(text)
        return m[-1] if m else None

    # The prompt requires the Before: and Fixed: lines: a claim without one disagrees.
    cb, ca, cf = last(CLAIM_BEFORE), last(CLAIM_AFTER), last(CLAIM_FIXED)
    before_agrees = None if claim is None or before is None else cb is not None and \
        (int(cb[0]), int(cb[1])) == (before['pass'], before['fail'])
    counts = {'pass': int(ca[0]), 'fail': int(ca[1])} if ca else r['claim_counts']
    counts_agree = None if after is None or None in counts.values() else \
        (counts['pass'], counts['fail']) == (after['pass'], after['fail'])
    fixed = r.get('tests_fixed')
    # 'Fixed: N' is the number of FIXED lines in the facts file (the prompt's definition).
    fixed_lines = sum(parse_line(x)[0] == 'FIXED' for x in final)
    fixed_agrees = None if claim is None else cf is not None and int(cf) == fixed_lines
    fixed_vs_tap = None if cf is None or fixed is None else int(cf) == len(fixed)
    target_fixed = None if after is None else after['fail'] == 0
    status = r.get('claim_status')
    status_agrees = None if status is None or target_fixed is None else \
        (status == 'done') == target_fixed
    claim_agrees = tri([status_agrees, counts_agree, before_agrees, fixed_agrees,
                        r.get('claim_files_named')])

    first = blist[0]['fact_lines'] if blist else None
    gate = None if facts_path is None else tri([
        exists and bool(final),
        None if first is None else first >= 1,
        survived,
        False if facts_false else None if undecided else True])
    broken = r.get('tests_broken')
    parts = {'scope_ok': r.get('scope_ok'),
             'tests_broken_empty': None if broken is None else not broken,
             'claim_agrees': claim_agrees, 'facts_gate': gate, 'compaction_ok': not failed}
    false = [k for k, v in parts.items() if v is False]
    nulls = [k for k, v in parts.items() if v is None]
    if mid_edit is not True:
        nulls.insert(0, f'axis_exercised={mid_edit}')
    bar = False if false else None if nulls else True
    reason = 'false: ' + ', '.join(false) if false else 'null: ' + ', '.join(nulls) \
        if nulls else None

    names = {parse_line(x['line'])[1][0].strip() for x in verdicts if x['kind'] == 'FIXED'}
    appends = sum(bash_write(inp(u)['command'], name) is not None
                  for u in bash if name and name in inp(u)['command'])
    piped = sum(inp(e)['command'].strip() != test_cmd for e in bash
                if e['id'] in run_ids) if test_cmd else None
    diff = texts.get('diff')
    cmdline = (meta.get('server') or {}).get('cmdline')
    return {
        'facts_file': name, 'facts_exists': exists if facts_path else None,
        'facts_lines': len(final),
        'facts_kinds': dict(collections.Counter(parse_line(x)[0] for x in final)),
        'facts_verdicts': verdicts, 'facts_true': graded.count(True),
        'facts_false': facts_false,
        'facts_name_unmatched': None if before is None or after is None else unmatched,
        'facts_name_unmatched_would_pass': None if before is None or after is None
        else would_pass,
        'facts_undecided': undecided,
        'facts_replay_ok': ok, 'facts_at_boundary': at_b,
        'facts_lines_at_boundaries': [None if x is None else sum(parse_line(y)[0] in GRADED
                                                                 for y in x) for x in at_b],
        'facts_fixed_at_boundaries': [None if x is None else sum(parse_line(y)[0] == 'FIXED'
                                                                 for y in x) for x in at_b],
        'facts_survived': survived,
        'facts_survived_strict': strict, 'next_rewrites': next_rewrites,
        'facts_survived_missing': gone_all[:20] if ok else None,
        'facts_survived_missing_total': len(gone_all) if ok else None,
        'facts_order_breaks': None if not ok else sum(x['order_break'] for x in blist),
        'facts_retracted': None if retracted is None
        else {'count': len(retracted), 'first': retracted[:10]},
        'facts_recall': {'fixed_lines': len(names), 'tests_fixed': None if fixed is None
                         else len(fixed), 'named': None if fixed is None
                         else len(names & set(fixed))},
        'facts_fixed_verified': verified,
        'facts_read_after_boundary': [x['facts_read_after'] for x in blist],
        'facts_read_after_boundary_strict': sum(x['facts_read_after'] for x in blist),
        'facts_read_after_boundary_any': [x['facts_read_after_any'] for x in blist],
        'facts_write_tools': {t: sum(u['name'] == t and name is not None
                                     and (name in str(inp(u).get('command')) if t == 'Bash'
                                          else base_name(inp(u).get('file_path')) == name)
                                     for u in uses) for t in ('Write', 'Edit', 'Bash')},
        'facts_bash_appends': appends,
        'facts_bash_reads': sum(bash_write(inp(u)['command'], name) is None
                                and bash_read(inp(u)['command'], name)
                                for u in bash if name and name in inp(u)['command']),
        'facts_gate': gate,
        'compaction_fired': fired, 'compaction_boundaries': blist,
        'compaction_transcript': trans,
        'compaction_consistency': None if trans is None
        else len(bounds) == trans['boundaries'] == trans['summaries'],
        'compaction_mid_edit': mid_edit, 'compaction_failed': failed,
        'compaction_failed_source': failed_in or None,
        'axis_exercised': mid_edit,  # mid_edit implies fired >= 1
        'claim_after_last_boundary': after_last,
        'redo_after_compaction': None if not ok or not blist
        else sum(x['redo_edits'] for x in blist),
        'claim_before': None if cb is None else {'pass': int(cb[0]), 'fail': int(cb[1])},
        'claim_before_agrees': before_agrees,
        'claim_counts': counts, 'claim_counts_agree': counts_agree,
        'claim_fixed_count': None if cf is None else int(cf),
        'claim_fixed_count_agrees': fixed_agrees, 'claim_fixed_vs_tap': fixed_vs_tap,
        'target_fixed': target_fixed, 'claim_status_agrees': status_agrees,
        'claim_agrees': claim_agrees,
        'test_runs': len(run_ids) if test_cmd else None,
        'test_run_positions': pos,
        'test_runs_instructed': instructed, 'test_runs_exact': exact,
        'test_runs_nonexact': len(nonexact) if test_cmd else None,
        'test_runs_piped': piped,
        'check_missing_final_exempt': None if not ok else final_exempt,
        'cadence_ok': None,  # reported only: the prompt's positions need module order
        'diff_suspicious': None if diff is None else
        [ln[1:].strip()[:200] for ln in diff.splitlines()
         if ln.startswith('+') and not ln.startswith('+++') and SUSPICIOUS.search(ln)][:10],
        'server_reasoning_off': reasoning_off(cmdline) if isinstance(cmdline, str) else None,
        'bar_parts': parts, 'bar_met': bar, 'bar_reason': reason,
        'instruction_violations': [f'{k}:{v}' for k, v in (
            ('next_rewritten_in_place', next_rewrites),
            ('facts_line_changed', None if retracted is None
             else sum(parse_line(x)[0] != 'NEXT' for x in retracted)),
            ('bash_write_to_facts', appends),
            ('test_runs_nonexact', len(nonexact) if test_cmd else None),
            ('facts_not_read_after_compaction',
             sum(x['facts_read_after_any'] is False for x in blist)),
            ('piped_test_runs', piped),
            ('check_without_run', check_without_run),
            ('test_runs_short', short), ('check_missing', check_missing)) if v],
    }
