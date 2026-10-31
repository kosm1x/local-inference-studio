"""Property (fuzz) test for scripts/hooks/lis-guard.py (ruling 45, 2026-10-30).

The hook may deny, or give no decision (None, so the settings rules and the prompt decide),
for any input. It may allow only through its grammar. Every generated case is checked for:

  (i)   decide() returns allow, deny or None, never raises, and takes < 3 s (inputs <= 32 KB),
        < 1 s for a UNC path (the hook never looks one up: a random host would take seconds);
  (ii)  allow => the command is pure ASCII with no NUL and re-parses: each segment is a
        pwsh/powershell payload that ps_readonly() accepts with every cmdlet in
        FROZEN_PS_RO_SPEC and every property it names in its producer's FROZEN_PS_RO_PROPS
        (literal copies of the hook's tables, checked equal to them so drift is loud), a
        script run (bash/sh/source/pwsh -File) of a pure-ASCII, NUL-free file inside the repo
        with no credential or eval token, `bash -c` of such a command, safe env assignments,
        `git` with a subcommand in FROZEN_GIT_SUBS, or a command whose verb is in ALLOW_VERBS,
        and no word names a UNC or device path (//h/s, its backslash forms, //?/, also after
        -f, --x=, x= or @) other than a //Switch to pwsh, powershell or tasklist (Git Bash passes /Switch);
  (iii) allow of a path-sensitive command (a script run, or a payload with a path cmdlet) =>
        nothing in it moves the cwd (cwd_moves) and every script target is inside the repo
        (a cwd move before a non-path command, `cd x && git status`, stays allowed);
  (iv)  deny => a reason string;
  (v)   decide(x) == decide(x); a pwsh option dash spelled U+2013/2014/2015 is denied exactly
        when its ASCII form is and is never allowed; a case flip of a pwsh option name keeps
        the decision; a '' or "" splice of a denied command is never allowed;
  (vi)  a command naming a credential token or -ec/-EncodedCommand/Invoke-Expression/iex,
        also behind a '' / "" / backslash-newline splice, is never allowed.

Generators: (a) random strings with non-ASCII, (b) mutations of every row in
lis-guard_test.py, (c) PS_RO_SPEC-shaped payloads with one corruption, (d) cd / -wd /
option-prefix / script-target combinations in a fake repo root with an outside dir and a
junction into it, then UNC targets on random hosts and credential tokens behind a splice in
allow-shaped commands and script bodies (their own rng, so the earlier streams are unchanged).
(a)-(c) run with the repo root as cwd and (d) under a temp path named by seed and a fixed-width
pid (parallel runs never share it; the pid feeds no generator), so a seed gives the same counts
from any cwd.

Run from the repo root: python -I scripts/hooks/tests/lis-guard_property_test.py
Options: --seed N (default 45), --cases N (default 20000), --hook PATH (another hook file,
for red-before-green runs).
"""
import importlib.util
import os
import random
import re
import shutil
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.stdout.reconfigure(errors='backslashreplace')
HERE = os.path.dirname(os.path.abspath(__file__))


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


SEED = int(arg('--seed', '45'))
CASES = int(arg('--cases', '20000'))
HOOK = arg('--hook', os.path.join(HERE, '..', 'lis-guard.py'))
spec = importlib.util.spec_from_file_location('lis_guard_prop', HOOK)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

# The non-PowerShell verbs the hook allows (seg_readonly), pinned here: a verb added to the
# hook's allow path fails this test until it is listed.
ALLOW_VERBS = frozenset({
    'ls', 'cat', 'head', 'tail', 'grep', 'wc', 'df', 'du', 'uptime', 'echo', 'printf', 'which', 'type',
    'stat', 'uname', 'free', 'systeminfo', 'whoami', 'id', 'pwd', 'tr', 'cut', 'true', 'false',
    'netstat', 'tasklist', 'nproc', 'continue', 'break', ':', 'cd', 'jq', 'column', 'basename',
    'dirname', 'realpath', 'readlink', 'sha256sum', 'md5sum', 'diff', 'cmp',
    'date', 'file', 'uniq', 'sort', 'tree', 'find', 'nvidia-smi', 'rg', 'wmic', 'hostname',
    'node', 'npm', 'pnpm', 'python', 'py', 'uv', 'claude', 'pip',
    'git', 'docker', 'curl', 'wsl'})
# git subcommands the hook allows (git_ok); GIT_PROBE pins git_ok against them below
FROZEN_GIT_SUBS = frozenset({'status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', '--version', 'remote',
                             'branch', 'config'})
GIT_PROBE = {s: True for s in FROZEN_GIT_SUBS - {'config'}} | {
    s: False for s in ('add', 'commit', 'stash', 'checkout', 'fetch', 'pull', 'clean', 'tag', 'grep', 'blame',
                       'gc', 'worktree', 'apply', 'am', 'config', 'reset', 'restore', 'switch', 'rm', 'mv')}
# literal copies of the hook's PS_RO_SPEC and PS_RO_PROPS (ruling 45 audit A12 W3): (ii) re-parses
# against these, and tables_match() fails the run when the hook's tables drift from them
FROZEN_PS_RO_SPEC = {
    'convertto-json': {'compress': 'none', 'depth': 'depth'},
    'format-list': {'': 'prop', 'property': 'prop'},
    'format-table': {
        '': 'prop', 'autosize': 'none', 'hidetableheaders': 'none', 'property': 'prop', 'wrap': 'none'},
    'get-childitem': {
        '': 'repo_path', 'depth': 'depth', 'directory': 'none', 'erroraction': 'erroraction', 'exclude':
        'glob', 'file': 'none', 'filter': 'glob', 'force': 'none', 'include': 'glob', 'literalpath':
        'repo_path', 'name': 'none', 'path': 'repo_path', 'recurse': 'none'},
    'get-ciminstance': {'': 'class', 'classname': 'class', 'erroraction': 'erroraction'},
    'get-command': {'': 'cmdname', 'name': 'cmdname'},
    'get-computerinfo': {'': 'prop', 'property': 'prop'},
    'get-date': {'format': 'word'},
    'get-item': {
        '': 'repo_path', 'erroraction': 'erroraction', 'force': 'none', 'literalpath': 'repo_path', 'path':
        'repo_path'},
    'get-process': {'': 'word', 'erroraction': 'erroraction', 'id': 'int', 'name': 'word'},
    'get-psdrive': {'': 'word', 'name': 'word', 'psprovider': 'filesystem'},
    'get-service': {'': 'word', 'erroraction': 'erroraction', 'name': 'word'},
    'get-volume': {'': 'word', 'driveletter': 'word'},
    'measure-object': {
        '': 'prop', 'average': 'none', 'maximum': 'none', 'minimum': 'none', 'property': 'prop', 'sum':
        'none'},
    'select-object': {
        '': 'prop', 'expandproperty': 'propone', 'first': 'int', 'last': 'int', 'property': 'prop', 'skip':
        'int', 'unique': 'none'},
    'sort-object': {'': 'prop', 'descending': 'none', 'property': 'prop', 'unique': 'none'},
    'test-path': {'': 'repo_path', 'literalpath': 'repo_path', 'path': 'repo_path', 'pathtype': 'word'},
    'where-object': {'': 'filter', 'filterscript': 'filter'},
    'write-output': {'': 'text'},
}
FROZEN_PS_RO_PROPS = {
    'get-childitem': {'Extension', 'FullName', 'LastWriteTime', 'Length', 'Mode', 'Name', 'PSIsContainer'},
    'get-command': {'CommandType', 'Name', 'Path', 'Source', 'Version'},
    'get-computerinfo': {
        'CsNumberOfLogicalProcessors', 'CsTotalPhysicalMemory', 'OsArchitecture', 'OsFreePhysicalMemory',
        'OsName', 'OsTotalVisibleMemorySize', 'OsVersion', 'WindowsVersion'},
    'get-date': {'DateTime', 'Day', 'Month', 'Ticks', 'Year'},
    'get-item': {'Extension', 'FullName', 'LastWriteTime', 'Length', 'Mode', 'Name', 'PSIsContainer'},
    'get-process': {
        'CPU', 'Handles', 'Id', 'NPM', 'Name', 'PM', 'Path', 'PriorityClass', 'ProcessName', 'Responding',
        'StartTime', 'VM', 'WS', 'WorkingSet64'},
    'get-psdrive': {'Free', 'Name', 'Root', 'Used'},
    'get-service': {'DisplayName', 'Name', 'StartType', 'Status'},
    'get-volume': {'DriveLetter', 'DriveType', 'FileSystemLabel', 'HealthStatus', 'Size', 'SizeRemaining'},
    'test-path': set(),
    'win32_bios': {'Manufacturer', 'Name', 'ReleaseDate', 'SMBIOSBIOSVersion'},
    'win32_computersystem': {
        'Manufacturer', 'Model', 'NumberOfLogicalProcessors', 'NumberOfProcessors', 'TotalPhysicalMemory'},
    'win32_diskdrive': {'InterfaceType', 'MediaType', 'Model', 'Size'},
    'win32_logicaldisk': {'DeviceID', 'DriveType', 'FileSystem', 'FreeSpace', 'Size'},
    'win32_operatingsystem': {
        'BuildNumber', 'Caption', 'FreePhysicalMemory', 'InstallDate', 'LastBootUpTime', 'OSArchitecture',
        'TotalVisibleMemorySize', 'Version'},
    'win32_physicalmemory': {'Capacity', 'Manufacturer', 'PartNumber', 'Speed'},
    'win32_processor': {
        'L2CacheSize', 'L3CacheSize', 'MaxClockSpeed', 'Name', 'NumberOfCores',
        'NumberOfEnabledLogicalProcessors', 'NumberOfLogicalProcessors'},
    'win32_videocontroller': {'AdapterRAM', 'DriverVersion', 'Name', 'VideoProcessor'},
    'write-output': set(),
}
DASHES = '\u2013\u2014\u2015'
CRED = re.compile(r'(?i)id_rsa|\.ssh[\\/]|\.aws[\\/]|credentials|api-key|hf_|\.env|(?<![\w-])-ec\b'
                  r'|-encodedcommand|invoke-expression|(?<![\w-])iex\b')


def cred(s):
    """A (vi) token in s as written or with splices removed (quotes, escapes, continuations)."""
    return CRED.search(s) or CRED.search(re.sub(r'[\'"`\\]', '', re.sub(r'[`\\]\r?\n', '', s)))


UNC_RX = re.compile(r'(?:-{1,2}[\w-]*=?|[\w.-]*=|@)?[\\/]{2}')


def unc_word(seg, toks):
    """Why, when a word of seg (a token, or a raw word with its quotes removed) names a UNC
    or device path, other than a //Switch to pwsh/powershell/tasklist; else None."""
    t2 = g.strip_env(list(toks), False) or toks
    native = g.exe(t2[0]) in ('pwsh', 'powershell', 'tasklist')
    for w in list(toks) + [x.replace('"', '').replace("'", '') for x in seg.split()]:
        if UNC_RX.match(w) and not (native and re.fullmatch(r'//[A-Za-z]+', w)):
            return f'UNC word {w!r}'
    return None


PS_VERB = re.compile(r'(?i)(?<![\w-])((?:get|set|new|remove|invoke|start|stop|out|export|import|copy|move|add|'
                     r'clear|write|read|test|select|where|sort|measure|format|convertto|convertfrom|rename|'
                     r'enable|disable|register|unregister|update|install|uninstall|send|receive|push|pop|'
                     r'join|split|resolve|expand|compress|restart|suspend|resume|wait|use|enter|exit|mount|'
                     r'save|restore|grant|revoke|protect|unprotect|find|show|trace|compare|group|tee|'
                     r'foreach)-\w+)(?![\w-])')
CMD_POS = re.compile(r'(?:^|[|;({&\n])\s*' + PS_VERB.pattern[4:], re.I)   # a cmdlet in command position
CONSUMER_LISTS = ('select-object', 'format-table', 'format-list', 'sort-object', 'measure-object')
PROPS_ALL = {k: {p.lower() for p in v} for k, v in FROZEN_PS_RO_PROPS.items()}
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
MEASURE = {'count', 'sum', 'average', 'maximum', 'minimum'}


# ---- invariant helpers -------------------------------------------------------------------

def producer_key(stmt):
    m = PS_VERB.search(stmt)
    if not m:
        return None
    name = m.group(1).lower()
    if name == 'get-ciminstance':
        c = re.search(r'(?i)(?<![\w-])(win32_\w+)', stmt)
        return c.group(1).lower() if c else name
    return name


def split_top(code):
    """code split at ; and newlines outside braces, brackets and parentheses."""
    out, depth, cur = [], 0, ''
    for c in code:
        depth += c in '{[(' and 1 or (-1 if c in '}])' else 0)
        if c in ';\n' and depth <= 0:
            out.append(cur)
            cur = ''
        else:
            cur += c
    return out + [cur]


def payload_props_ok(payload):
    """Independent of ps_readonly: every cmdlet is in PS_RO_SPEC and every property named
    after a consumer, in $_.X or in (...).X is in the statement producer's PS_RO_PROPS."""
    for m in CMD_POS.finditer(payload):
        if m.group(1).lower() not in FROZEN_PS_RO_SPEC:
            return f'cmdlet {m.group(1)} not in FROZEN_PS_RO_SPEC'
    for stmt in split_top(payload):
        key = producer_key(stmt)
        if key is None:
            continue
        ok = PROPS_ALL.get(key, set()) | MEASURE
        names = re.findall(r'\$_\.(\w+)', stmt) + re.findall(r'\)\.(\w+)', stmt)
        flat = re.sub(r'@\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', ' ', stmt)
        for part in flat.split('|'):
            words = part.replace(',', ' ').split()
            if words and words[0].lower() in CONSUMER_LISTS:
                names += [w.strip('\'"') for w in words[1:] if re.fullmatch(r'[\'"]?[A-Za-z]\w*[\'"]?', w)]
        for n in names:
            if n.lower() not in ok and not (n.lower() == 'tostring' and 'psversion' in stmt.lower()):
                return f'property {n} not listed for {key}'
    return None


def is_path_payload(payload):
    return any(c in payload.lower() for c in g.PS_RO_PATH_CMDLETS)


def grammar(cmd, cwd, depth=0):
    """None when every segment of an allowed cmd re-parses through the grammar, else why;
    also returns the script targets and whether a path-sensitive form was used."""
    scripts, pathy = [], False
    if depth > 6:
        return 'nesting', scripts, pathy
    for seg in g.split_segments(cmd):
        toks = g.tokens(seg)
        if not toks:
            continue
        why = unc_word(seg, toks)                           # (ii), before any file is opened
        if why:
            return why, scripts, pathy
        if all(re.match(r'^[A-Za-z_]\w*=', t) for t in toks):
            if not all(t.split('=', 1)[0] in g.ENV_SAFE for t in toks):
                return f'env assignment {seg!r}', scripts, pathy
            continue
        toks = g.strip_env(toks, False)
        if not toks:
            return f'env prefix {seg!r}', scripts, pathy
        v = g.exe(toks[0])
        st = g.script_target(toks)
        if st:
            full = g.resolve(st[0], cwd)
            try:
                with open(full, 'rb') as f:
                    data = f.read()
            except OSError:
                return f'script {st[0]} unreadable', scripts, pathy
            if not data.isascii() or b'\x00' in data:
                return f'script {st[0]} is not ASCII or has a NUL', scripts, pathy
            if cred(data.decode('ascii')):
                return f'script {st[0]} names a credential or eval token', scripts, pathy
            scripts.append(full)
            pathy = True
            continue
        if v in g.PS_EXES:
            payload = g.ps_payload(toks)[0]
            g._RO_CWD[0] = cwd
            if not payload or not g.ps_readonly(payload):
                return f'payload {payload!r} not ps_readonly', scripts, pathy
            why = payload_props_ok(payload)
            if why:
                return why, scripts, pathy
            pathy = pathy or is_path_payload(payload)
            continue
        if v in ('bash', 'sh') and toks[1:2] == ['-c'] and len(toks) > 2:
            why, s2, p2 = grammar(toks[2], cwd, depth + 1)
            if why:
                return why, scripts, pathy
            scripts += s2
            pathy = pathy or p2
            continue
        if v == 'git':
            a = toks[1:]
            while a and (a[0] == '-C' and len(a) > 1 or a[0] == '--no-pager'):
                a = a[2:] if a[0] == '-C' else a[1:]
            if not a or a[0] not in FROZEN_GIT_SUBS or (a[0] == 'remote' and a[1:] not in ([], ['-v'])):
                return f'git {a[:2]} not in FROZEN_GIT_SUBS', scripts, pathy
            continue
        if v not in ALLOW_VERBS:
            return f'verb {v!r} not in ALLOW_VERBS', scripts, pathy
    return None, scripts, pathy


def timed(cmd, cwd):
    t0 = time.perf_counter()
    d = g.decide(cmd, cwd)
    return d, time.perf_counter() - t0


def kind(d):
    return d[0] if d else None


def dash_variant(rng, cmd):
    """The first-found ASCII pwsh option dash at a token start replaced by a Unicode dash."""
    ms = [m.start() for m in re.finditer(r'(?<=\s)-(?=[A-Za-z])', cmd)]
    if not ms or not re.search(r'(?i)pwsh|powershell', cmd):
        return None
    i = rng.choice(ms)
    return cmd[:i] + rng.choice(DASHES) + cmd[i + 1:]


PS_OPTS = ('noprofile', 'nologo', 'noninteractive', 'command', 'c', 'file', 'f', 'wd', 'workingdirectory',
           'ec', 'encodedcommand', 'executionpolicy', 'settingsfile')


def case_variant(rng, cmd):
    """A pwsh option name (before -Command/-File, in a command that starts with pwsh) with
    its case flipped."""
    toks = cmd.split(' ')
    if len(toks) < 2 or toks[0].lower() not in ('pwsh', 'powershell', 'pwsh.exe', 'powershell.exe'):
        return None
    for i, t in enumerate(toks[1:], 1):
        if not re.fullmatch(r'-[A-Za-z]+', t) or t[1:].lower() not in PS_OPTS:
            return None
        if t[1:].lower() in ('command', 'c', 'file', 'f', 'ec', 'encodedcommand'):
            break
    i = rng.randint(1, i)
    toks[i] = toks[i].swapcase()
    return ' '.join(toks)


def splice_variant(rng, cmd):
    ws = [m for m in re.finditer(r'(?<![\w\'"$-])[A-Za-z]{3,}', cmd)]
    if not ws:
        return None
    m = rng.choice(ws)
    k = rng.randint(m.start() + 1, m.end() - 1)
    return cmd[:k] + rng.choice(("''", '""')) + cmd[k:]


class Checker:
    def __init__(self):
        self.n = self.fails = 0
        self.max_t = self.unc_max = 0.0
        self.counts = {'allow': 0, 'deny': 0, None: 0}

    def fail(self, why, cmd, d):
        self.fails += 1
        if self.fails <= 40:
            print(f'FAIL {why}: {cmd!r}\n     decision={d!r}')

    def check(self, cmd, cwd, rng):
        self.n += 1
        if len(cmd) > g.MAX_INPUT:
            return
        try:
            d, dt = timed(cmd, cwd)
            d2, dt2 = timed(cmd, cwd)
        except Exception as e:                                  # (i)
            self.fail(f'decide raised {e!r}', cmd, None)
            return
        self.max_t = max(self.max_t, dt, dt2)
        if dt > 3 or dt2 > 3:
            self.fail(f'decide took {max(dt, dt2):.2f}s', cmd, d)
        if not (d is None or (isinstance(d, tuple) and len(d) == 2 and d[0] in ('allow', 'deny'))):
            self.fail('decision shape', cmd, d)
            return
        self.counts[kind(d)] += 1
        if d != d2:                                             # (v) idempotence
            self.fail('decide(x) != decide(x)', cmd, (d, d2))
        if kind(d) == 'deny' and not (isinstance(d[1], str) and d[1].strip()):     # (iv)
            self.fail('deny without a reason', cmd, d)
        if kind(d) == 'allow':
            if not cmd.isascii() or '\x00' in cmd:             # (ii)
                self.fail('allow of a non-ASCII or NUL command', cmd, d)
            why, scripts, pathy = grammar(cmd, cwd)
            if why:
                self.fail(f'allow outside the grammar ({why})', cmd, d)
            if pathy:                                           # (iii)
                g._RO_CWD[0] = cwd
                if g.cwd_moves(cmd, cwd):
                    self.fail('allow of a path-sensitive command after a cwd move', cmd, d)
                if any(not g.in_repo(s) for s in scripts):
                    self.fail('allow of a script outside the repo', cmd, d)
            if cred(cmd):                                       # (vi)
                self.fail('allow of a credential or encoded/eval token', cmd, d)
        for make in (dash_variant, case_variant, splice_variant):    # (v) variants
            v = make(rng, cmd)
            if v is None or v == cmd or len(v) > g.MAX_INPUT:
                continue
            try:
                dv, dtv = timed(v, cwd)
            except Exception as e:
                self.fail(f'decide raised {e!r} on a variant', v, None)
                continue
            self.max_t = max(self.max_t, dtv)
            if make is dash_variant:
                if kind(dv) == 'allow':
                    self.fail('allow of a Unicode-dash variant', v, dv)
                if (kind(dv) == 'deny') != (kind(d) == 'deny'):
                    self.fail(f'dash variant deny differs from ASCII ({kind(d)})', v, dv)
            elif make is case_variant:
                if kind(dv) != kind(d):
                    self.fail(f'case flip of a pwsh option changed the decision ({kind(d)})', v, dv)
            elif kind(d) == 'deny' and kind(dv) == 'allow':
                self.fail('allow of a splice of a denied command', v, dv)


# ---- generators --------------------------------------------------------------------------

ALPHA = ('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
         ' \t\n-_./\\:;|&<>()[]{}$`\'"*?~!#%=+,@^')
UNI = ['\u00e9', '\u2013', '\u2014', '\u2015', '\u2212', '\u200b', '\ufeff', '\uff0d', '\u0430',
       '\u0435', '\u03bf', '\u2044', '\u2215', '\uff0f', '\u00a0', '\ufffd', '\x00', '\x07', '\x1b']
WORDS = ['ls', 'cat', 'git', 'status', 'push', 'pwsh', 'powershell', '-NoProfile', '-Command', '-c',
         '-File', '-wd', 'cd', '..', '~/.ssh/id_rsa', 'config/claude-settings.json', 'Get-ChildItem',
         'Get-Process', 'Select-Object', 'Name', 'Set-Content', 'Remove-Item', 'rm', '-rf', 'bash',
         '-ec', 'iex', '.env', 'models', 'docs', 'echo', 'curl', 'http://127.0.0.1:8080', '|', '&&', ';',
         'add', 'stash', 'log']
CONFUSE = {'-': DASHES + '\u2212\uff0d', '/': '\u2215\u2044\uff0f', 'a': '\u0430', 'e': '\u0435',
           'o': '\u03bf', ' ': '\u00a0\u200b'}


def gen_random(rng):
    if rng.random() < 0.5:
        return ''.join(rng.choice(ALPHA) if rng.random() < 0.9 else rng.choice(UNI)
                       for _ in range(rng.randint(1, 120)))
    return ' '.join(rng.choice(WORDS) if rng.random() < 0.85 else rng.choice(UNI)
                    for _ in range(rng.randint(1, 12)))


def mutate(rng, s):
    if not s:
        return rng.choice(WORDS)
    op = rng.randrange(10)
    i = rng.randrange(len(s))
    if op == 0:
        return s[:i] + rng.choice(ALPHA) + s[i:]
    if op == 1:
        return s[:i] + s[i + 1:]
    if op == 2 and len(s) > 1:
        j = min(i + 1, len(s) - 1)
        return s[:i] + s[j] + s[i] + s[j + 1:]
    if op == 3:
        hits = [k for k, c in enumerate(s) if c in CONFUSE]
        if hits:
            k = rng.choice(hits)
            return s[:k] + rng.choice(CONFUSE[s[k]]) + s[k + 1:]
    if op == 4:
        k = rng.choice([k for k, c in enumerate(s) if c == '-'] or [i])
        return s[:k] + rng.choice(['--', '/', '//', rng.choice(DASHES)]) + s[k + 1:]
    if op == 5:
        return s[:i] + rng.choice(["''", '""', '\\']) + s[i:]
    if op == 6:
        return ''.join(c.swapcase() if rng.random() < 0.3 else c for c in s)
    if op == 7:
        return re.sub(r' ', lambda m: rng.choice([' ', '  ', '\t', ' \\\n ']), s, count=rng.randint(1, 3))
    if op == 8:
        return s[:i] + rng.choice(['"', "'", '`', '$', ';', '|', '&']) + s[i:]
    return s[:i] + ' ' + rng.choice(WORDS) + ' ' + s[i:]


def corpus():
    """Every command string in lis-guard_test.py's module-level case lists."""
    tspec = importlib.util.spec_from_file_location('lis_guard_test_corpus', os.path.join(HERE, 'lis-guard_test.py'))
    t = importlib.util.module_from_spec(tspec)
    tspec.loader.exec_module(t)
    rows = []
    for name, val in vars(t).items():
        if name.isupper() and isinstance(val, (list, tuple)):
            for r in val:
                c = r[0] if isinstance(r, tuple) and r and isinstance(r[0], str) else r
                if isinstance(c, str) and c.strip():
                    rows.append(c)
    return sorted(set(rows))


VALUES = {'word': ['pwsh', 'C', 'svchost', 'x1', 'FileSystem'], 'int': ['1', '5', '1234'],
          'class': sorted(g.PS_RO_CLASSES), 'repo_path': ['models', 'docs', 'scripts', '.', 'docs/SETUP.md'],
          'glob': ['*.ps1', '*.md'], 'depth': ['1', '2', '3'], 'cmdname': ['git', 'pwsh'],
          'text': ['hello', 'ok'], 'filesystem': ['FileSystem'], 'erroraction': ['SilentlyContinue'],
          'format': ['yyyy']}
CORRUPT = ['; Remove-Item x', ' | Set-Content config/claude-settings.json', ' CommandLine', ' $(whoami)',
           ' env:PATH', ' | iex', '; Invoke-Expression x', ' -ec', ' ..', ' ~/.ssh', ' C:/', ' \\\\srv\\s',
           ' [Environment]::X', ' -Comp x', '; Get-Content ~/.aws/credentials', ' | Out-File x', ' `',
           ' -Path ..', ' -Recurse -Name']


def gen_spec(rng):
    p = rng.choice(sorted(g.PS_RO_PRODUCERS))
    params = g.PS_RO_SPEC[p]
    key = p
    parts = [p.title()]
    for name in rng.sample(sorted(params), min(len(params), rng.randint(0, 2))):
        cls = params[name]
        if cls in ('filter', 'none'):
            if cls == 'none':
                parts.append('-' + name.title())
            continue
        if cls in ('prop', 'propone'):
            props = sorted(g.PS_RO_PROPS.get(key, set())) or ['Name']
            val = ','.join(rng.sample(props, min(len(props), rng.randint(1, 2))))
        else:
            val = rng.choice(VALUES.get(cls, ['x']))
            if cls == 'class':
                key = val
        parts += ([('-' + name.title())] if name else []) + [val]
    pay = ' '.join(parts)
    props = sorted(g.PS_RO_PROPS.get(key, set()))
    if props and rng.random() < 0.7:
        pay += ' | ' + rng.choice(['Select-Object', 'Format-Table', 'Sort-Object']) + ' ' + \
            ','.join(rng.sample(props, min(len(props), rng.randint(1, 3))))
    if rng.random() < 0.8:
        k = rng.randrange(len(pay) + 1)
        c = rng.choice(CORRUPT) if rng.random() < 0.6 else mutate(rng, pay)[k:k + 3]
        pay = pay[:k] + c + pay[k:] if rng.random() < 0.7 else mutate(rng, pay)
    exe = rng.choice(['pwsh', 'powershell', 'pwsh.exe'])
    opt = rng.choice(['-NoProfile', '-NoProfile', '--NoProfile', '/NoProfile', '-NoLogo', ''])
    q = rng.choice(['"', "'"])
    return f'{exe} {opt} -Command {q}{pay}{q}'.replace('  ', ' ')


def gen_combo(rng, root, up, out):
    lead = rng.choice(['', '', '', 'cd .. && ', 'cd models && ', 'pushd .. ; ', 'cd ' + up + ' && ',
                       'cd ' + out + ' ; ', 'X=1 ', 'LANG=C ', '(cd ..) ; ', 'echo x | cd .. ; '])
    target = rng.choice(['e.ps1', './e.ps1', root + '/e.ps1', 'scripts/x.ps1', 'u.ps1', out + '/e.ps1',
                         '../' + os.path.basename(out) + '/e.ps1', 'C:e.ps1', 'scripts\\x.ps1', 'missing.ps1',
                         'lnk.ps1', 'r.ps1', out + '/r.ps1', 'jn/r.ps1', 'jn/e.ps1',
                         'scripts/../../' + os.path.basename(out) + '/r.ps1', 'k1.ps1', 'n2.ps1'])
    sh = target.replace('.ps1', '.sh')
    wd = rng.choice(['', '', '-wd .', '-wd ..', '--wd ..', '/wd ..', '//wd ..', '-w ..', '-wd:..',
                     rng.choice(DASHES) + 'wd ..', '-WorkingDirectory ' + up, '-wd ' + root])
    nop = rng.choice(['-NoProfile', '-NoProfile', '--NoProfile', '/NoProfile', rng.choice(DASHES) + 'NoProfile',
                      '', '-NoLogo', '-NoProfile -SettingsFile x.json'])
    form = rng.choice([
        f'pwsh {nop} {wd} -File {target}', f'pwsh {wd} {nop} -File {target}', f'pwsh {nop} {target}',
        f'powershell {nop} -File {target}', f'bash {sh}', f'sh {sh}', f'source {sh}', f'. {sh}',
        f'bash -l {sh}', f'pwsh {nop} {wd} -Command "Get-ChildItem"', f'pwsh {nop} -Command "Get-Date"',
        f'pwsh {nop} {wd} -Command "Get-Item docs"', f"bash -c 'pwsh {nop} -File {target}'",
        f'pwsh {nop} -Command "Test-Path models"'])
    cmd = (lead + form).replace('  ', ' ').strip()
    return mutate(rng, cmd) if rng.random() < 0.25 else cmd


UNC_SEPS = ('//', '\\\\', '////', '/\\', '\\/', '//?/UNC/', '\\\\?\\UNC\\', '//./', '\\\\.\\')
UNC_FORMS = ('cat {p}', 'ls {p}', 'head -n 1 {p}', 'wc -l {p}', 'grep x {p}', 'git diff --no-index {p} b',
             'git -C {p} status', 'find {p} -name x', 'stat {p}', 'file {p}', 'diff a {p}', 'grep -f{p} x',
             'grep --file={p} x', 'rg -f {p} x', 'sort {p}', 'bash {p}.sh', 'sh {p}.sh', 'source {p}.sh',
             'python {p}.py', 'node {p}.js', 'pwsh -NoProfile -File {p}.ps1', 'pwsh -NoProfile {p}.ps1',
             'pwsh //NoProfile //File {p}.ps1', 'pwsh -NoProfile -wd {p} -File e.ps1', 'git apply {p}.diff',
             'patch -i {p}.diff', 'cmd /c {p}.bat', 'pwsh -NoProfile -Command "Get-Content {p}"',
             "pwsh -NoProfile -Command 'Get-ChildItem -Path {p}'", 'bash r.sh {p}', 'bash -c "cat {p}"')


def gen_unc(rng):
    """A read verb, script run, -wd or patch file aimed at a UNC path on a random host."""
    host = 'q' + ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(11))
    tail = rng.choice(['/s/x', '\\s\\x', '/c/x', '/s'])
    q = rng.choice(['', '', "'", '"'])
    form = rng.choice(UNC_FORMS)
    p = rng.choice(UNC_SEPS) + host + tail
    if '{p}.' in form:                                  # the extension goes inside the quotes
        ext = form.split('{p}', 1)[1].split()[0].rstrip('"\'')
        form = form.replace('{p}' + ext, '{p}')
        p += ext
    return form.replace('{p}', q + p + q)


SPLICED = ('logs/a""pi-key', "logs/api''-key", 'logs/api\\\n-key', '.e\\\nnv', "cred''entials",
           'i""d_rsa', '~/.s""sh/config', "h''f_tok", '.a""ws/config', 'logs/ap""i-k""ey')
SPLICE_FORMS = ('cat {t}', 'ls {t}', 'head -n 1 {t}', 'wc -l {t}', 'grep -n x {t}', 'git log -- {t}',
                'git diff -- {t}', 'stat {t}', 'cat docs/x {t}')


def gen_splice(rng):
    """An allow-shaped command or script run naming a credential token behind a splice."""
    if rng.random() < 0.3:
        k = rng.randrange(len(SPLICED))
        return rng.choice([f'bash sp{k}.sh', f'source sp{k}.sh', f'pwsh -NoProfile -File sp{k}.ps1'])
    return rng.choice(SPLICE_FORMS).replace('{t}', rng.choice(SPLICED))


def write(d, name, body):
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)


def unlink_link(p):
    """Remove a symlink or junction itself, never what it points to."""
    if os.path.islink(p):
        os.unlink(p)
    elif getattr(os.path, 'isjunction', lambda x: False)(p):
        os.rmdir(p)


def clear(base):
    if os.path.lexists(base):
        for n in ('jn', 'lnk.ps1'):
            unlink_link(os.path.join(base, 'repo', n))
        shutil.rmtree(base)


def tables_match(ck):
    """The hook's tables equal the frozen copies, and git_ok agrees with GIT_PROBE."""
    for name, mine, theirs in (('PS_RO_SPEC', FROZEN_PS_RO_SPEC, g.PS_RO_SPEC),
                               ('PS_RO_PROPS', FROZEN_PS_RO_PROPS, g.PS_RO_PROPS)):
        ck.n += 1
        if mine != theirs:
            diff = {k for k in set(mine) | set(theirs) if mine.get(k) != theirs.get(k)}
            ck.fail(f'hook {name} differs from the frozen copy at {sorted(diff)}', name, None)
    for sub, want in sorted(GIT_PROBE.items()):
        ck.n += 1
        if bool(g.git_ok([sub])) != want:
            ck.fail(f'git_ok([{sub!r}]) is not {want}', 'git ' + sub, None)


def main():
    rng = random.Random(SEED)
    ck = Checker()
    t0 = time.perf_counter()
    tables_match(ck)
    rows = corpus()
    n_a, n_c = CASES // 5, CASES // 5
    n_d = CASES // 5
    n_b = CASES - n_a - n_c - n_d
    for _ in range(n_a):                                        # (a)
        ck.check(gen_random(rng), REPO, rng)
    for k in range(n_b):                                        # (b): every row, then more
        s = rows[k % len(rows)]
        for _ in range(rng.randint(1, 3)):
            s = mutate(rng, s)
        ck.check(s, REPO, rng)
    for _ in range(n_c):                                        # (c)
        ck.check(gen_spec(rng), REPO, rng)
    # (d): seed and fixed-width pid, so parallel runs never share it and paths keep one length
    base = os.path.join(tempfile.gettempdir(), f'lis-guard-property-{SEED}-{os.getpid():010d}')
    t, o = os.path.join(base, 'repo'), os.path.join(base, 'out')
    old_root = g.REPO_ROOT
    clear(base)
    try:
        g.REPO_ROOT = os.path.normcase(os.path.realpath(t))
        for d in (t, o):
            write(d, 'r.ps1', 'Get-Date\n')                  # read-only: outside the repo in o
            write(d, 'r.sh', 'ls\n')
            write(d, 'k1.ps1', 'Test-Path logs/api-key\n')   # an ALLOW_STOP token in the text
            write(d, 'k1.sh', 'cat logs/api-key\n')
            write(d, 'n2.ps1', 'Get-Date\x00\n')              # a NUL in the text
            write(d, 'n2.sh', 'ls docs\x00\n')
            write(d, 'e.ps1', 'Get-ChildItem -Recurse -Force\n')
            write(d, 'e.sh', "pwsh -NoProfile -Command 'Get-ChildItem -Recurse -Force'\n")
            write(d, 'scripts/x.ps1', 'Get-ChildItem\n')
            write(d, 'scripts/x.sh', 'ls\n')
            write(d, 'u.ps1', '# caf\u00e9\nGet-ChildItem\n')
            write(d, 'u.sh', 'ls # caf\u00e9\n')
        for k, tok in enumerate(SPLICED):                   # script bodies with a spliced token
            write(t, f'sp{k}.sh', f'cat {tok}\n')
            write(t, f'sp{k}.ps1', f'Get-Content {tok}\n')
        os.makedirs(os.path.join(t, 'models'))
        try:
            os.symlink(os.path.join(o, 'e.ps1'), os.path.join(t, 'lnk.ps1'))
        except OSError:
            pass
        try:                                                # a junction from the repo to o
            import _winapi
            _winapi.CreateJunction(o, os.path.join(t, 'jn'))
        except (ImportError, OSError):
            os.symlink(o, os.path.join(t, 'jn'), target_is_directory=True)
        root, up, out = t.replace('\\', '/'), os.path.dirname(t).replace('\\', '/'), o.replace('\\', '/')
        for _ in range(n_d):
            ck.check(gen_combo(rng, root, up, out), t, rng)
        rng2 = random.Random(SEED * 1000 + 13)              # its own stream: (a)-(d) unchanged
        slow = 0
        for _ in range(CASES // 20):                        # UNC targets: never allowed or looked up
            cmd = gen_unc(rng2)
            d, dt = timed(cmd, t)
            ck.unc_max = max(ck.unc_max, dt)
            if dt >= 1.0:
                ck.fail(f'a UNC path took {dt:.2f}s (the hook looked it up)', cmd, d)
                slow += 1
                if slow >= 3:
                    break                                   # every further case would wait as long
                continue
            ck.check(cmd, t, rng2)
        for _ in range(CASES // 20):                        # spliced credential tokens: (vi)
            ck.check(gen_splice(rng2), t, rng2)
    finally:
        g.REPO_ROOT = old_root
        clear(base)
    el = time.perf_counter() - t0
    print(f'seed {SEED}: {ck.n} cases ({len(rows)} corpus rows) in {el:.1f}s = {ck.n / el:.0f}/s; '
          f'max decide {ck.max_t:.3f}s (UNC {ck.unc_max:.3f}s); allow {ck.counts["allow"]} deny {ck.counts["deny"]} '
          f'none {ck.counts[None]}')
    print(f'{ck.n - ck.fails}/{ck.n} passed' if not ck.fails else f'{ck.fails} invariant failures')
    return 1 if ck.fails else 0


if __name__ == '__main__':
    sys.exit(main())
