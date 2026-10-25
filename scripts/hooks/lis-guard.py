"""lis-guard: PreToolUse hook (matcher Bash) for local Claude Code sessions, ruling 15.

Decision order for one Bash command:
  (a) a critical write or delete anywhere in it, including inside powershell/pwsh
      -Command, bash/sh -c, wsl ... -- and ssh payloads            -> deny
  (b) a script run (bash|sh <file>, powershell|pwsh -File <file>, python|py|node
      <file>): a critical write on any line -> deny quoting that line; every line
      read-only -> allow; unreadable, or a line that is neither -> no decision
  (c) every segment passes the read-only grammar                   -> allow
  (d) anything else: no output, exit 0, so the rules and the classifier decide.

This scanner is the judge of record for script execution and interpreter payloads
(operator ruling, 2026-10-25): the auto-mode classifier never sees a script's content
or a tool's output, so it cannot review them.

Static text analysis only: it never runs the command or the script. Stdlib only;
run with `python -I`. Over-matching is deliberate: a critical verb inside a quoted
string (a commit message saying "rm -rf") is denied too.
"""
import json
import os
import re
import shlex
import sys

NOT_RETRYABLE = 'critical write; not retryable; report it to the operator instead'

# (a) critical verbs, searched over the raw command text so nested payloads are covered.
_GIT = r'(?<![\w-])git(?:\s+(?:-C|-c)\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+'
CRITICAL_VERBS = [
    (r'(?i)\bRemove-Item\b', 'Remove-Item'),
    (r'(?<![\w-])rm\s+(?:-\w*[rRf]\w*|--recursive|--force)', 'rm -r/-f'),
    (r'(?i)(?<![\w-])(?:del|erase)\s+(?:/\w+\s+)*/s\b', 'del /s'),
    (r'(?i)(?<![\w-])(?:rmdir|rd)\s+(?:/\w+\s+)*/s\b', 'rmdir /s'),
    (r'(?i)\b(?:Set|New|Remove)-ItemProperty\b[^;|]*\bHK(?:LM|CU|EY_)', 'registry write'),
    (r'(?i)(?<![\w-])reg(?:\.exe)?\s+(?:add|delete|import|load|restore)\b', 'reg add/delete'),
    (r'(?i)\b(?:Stop|Set|Restart)-Service\b', 'Stop-/Set-Service'),
    (r'(?i)(?<![\w.-])sc(?:\.exe)?\s+(?:stop|start|delete|config|create|failure)\b', 'sc'),
    (r'(?i)\b(?:Register|Unregister)-ScheduledTask\b', 'Register-/Unregister-ScheduledTask'),
    (r'(?i)(?<![\w-])schtasks(?:\.exe)?\s+[^;|]*/(?:create|delete|change|end)\b', 'schtasks /create|/delete'),
    (r'(?i)(?<![\w-])format(?:\.com)?\s+[a-z]:', 'format'),
    (r'(?i)(?<![\w-])diskpart\b', 'diskpart'),
    (r'(?i)\b(?:Clear-Disk|Remove-Partition|Format-Volume|Initialize-Disk)\b', 'disk cmdlet'),
    (r'(?<![\w-])mkfs(?:\.\w+)?\b', 'mkfs'),
    (r'(?<![\w-])dd\s+[^;|]*\bof=', 'dd'),
    (r'(?i)(?<![\w-])wsl(?:\.exe)?\s+[^;|]*--(?:unregister|import)\b', 'wsl --unregister|--import'),
    (r'(?<![\w-])docker\s+(?:(?:container|image|volume|network|system|builder)\s+)?(?:rm|rmi|prune)\b', 'docker rm/rmi/prune'),
    (_GIT + r'push\b[^;|&]*?(?:\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S)', 'git push --force'),
    (_GIT + r'reset\b[^;|&]*--hard\b', 'git reset --hard'),
    (_GIT + r'clean\b', 'git clean'),
    (_GIT + r'rebase\b', 'git rebase'),
    (_GIT + r'branch\b[^;|&]*\s-D\b', 'git branch -D'),
    (_GIT + r'checkout\s+--\s', 'git checkout --'),
]
CRITICAL_VERBS = [(re.compile(p), n) for p, n in CRITICAL_VERBS]

# A path that must not be written: user .claude/.ssh, Windows, Program Files*,
# ProgramData, .env*, *.pem, *.key, token, .git internals.
CRITICAL_PATH = re.compile(
    r'(?i)(?:\.claude\b|\.ssh\b|(?:^|[\s\'"=])(?:[a-z]:[\\/]|/[a-z]/)windows\b|program ?files'
    r'|programdata|\.env\b|\.pem\b|\.key\b|[\\/]token\b|^token\b|\.git(?:[\\/]|$|[\s\'"]))')
WRITE_VERBS = {'tee', 'mv', 'cp', 'chmod', 'chown', 'ln', 'install', 'truncate', 'touch'}
PS_WRITE = re.compile(r'(?i)\b(?:Set-Content|Out-File|Add-Content|New-Item|Copy-Item|Move-Item|Rename-Item|Set-Acl)\b')
REMOTE_WRITE = {'rm', 'rmdir', 'systemctl', 'docker', 'git', 'tee', 'mv', 'cp', 'chmod', 'chown', 'kill',
                'pkill', 'killall', 'apt', 'apt-get', 'dpkg', 'reboot', 'shutdown', 'poweroff', 'halt',
                'dd', 'truncate', 'crontab', 'sed', 'npm', 'pip'}
REMOTE_READ = {'uptime', 'df', 'free', 'cat', 'tail', 'head', 'ls', 'docker', 'systemctl', 'journalctl',
               'who', 'hostname', 'uname', 'grep', 'wc', 'echo', 'date', 'ps', 'du'}

READ_VERBS = {'ls', 'cat', 'head', 'tail', 'grep', 'wc', 'df', 'du', 'uptime', 'date', 'echo', 'printf',
              'which', 'type', 'file', 'stat', 'uname', 'free', 'nvidia-smi', 'wmic', 'systeminfo',
              'whoami', 'id', 'pwd', 'tr', 'cut', 'test', '[', '[[', 'true', 'false', 'netstat',
              'tasklist', 'nproc', 'continue', 'break', ':', 'cd', 'jq', 'uniq', 'column', 'basename',
              'dirname', 'realpath', 'readlink', 'sha256sum', 'md5sum', 'diff', 'cmp', 'tree', 'rg'}
PS_METHODS_OK = {'tostring', 'substring', 'trim', 'trimstart', 'trimend', 'replace', 'split', 'tolower',
                 'toupper', 'contains', 'startswith', 'endswith', 'gettype', 'padleft', 'padright', 'round',
                 'indexof', 'join', 'equals', 'compareto'}
VERSION_ONLY = {'node', 'npm', 'pnpm', 'python', 'py', 'uv', 'claude', 'pip'}
VERSION_FLAGS = {'-v', '--version', '-V', 'version'}
PS_EXES = {'powershell', 'pwsh'}
PS_OK_EXACT = {'measure-object', 'select-object', 'where-object', 'sort-object', 'out-string',
               'convertto-json', 'foreach-object', 'test-path', 'resolve-path', 'get-content'}
PS_ALIASES = {'select', 'where', 'sort', 'ft', 'fl', 'measure', 'foreach', 'if', 'else', 'elseif', 'in'}
SSH_ARG_OPTS = set('bcDEeFIiJLlmOopQRSWw')
ENV_PREFIX_OK = {'MSYS_NO_PATHCONV'}
MAX_DEPTH = 6


def split_segments(s, bs_escape=True):
    """Split on unquoted ; && || | & and newlines; $( ... ) stays whole."""
    segs, cur, q, depth, i = [], [], None, 0, 0
    while i < len(s):
        c = s[i]
        if q:
            cur.append(c)
            if c == '\\' and q == '"' and bs_escape and i + 1 < len(s):
                cur.append(s[i + 1]); i += 2; continue
            if c == q:
                q = None
        elif c in '"\'':
            q = c; cur.append(c)
        elif c == '\\' and bs_escape and i + 1 < len(s):
            cur.append(s[i:i + 2]); i += 2; continue
        elif s.startswith('$(', i):
            depth += 1; cur.append('$('); i += 2; continue
        elif depth and c == '(':
            depth += 1; cur.append(c)
        elif depth and c == ')':
            depth -= 1; cur.append(c)
        elif depth:
            cur.append(c)
        elif s.startswith('&&', i) or s.startswith('||', i):
            segs.append(''.join(cur)); cur = []; i += 2; continue
        elif c in ';|\n' or (c == '&' and not (cur and cur[-1] == '>') and not s.startswith('&>', i)):
            segs.append(''.join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    segs.append(''.join(cur))
    return [x.strip() for x in segs if x.strip()]


def tokens(seg):
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return None


def exe(tok):
    t = tok.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return t[:-4] if t.endswith('.exe') else t


def strip_env(toks):
    while toks and re.match(r'^[A-Za-z_]\w*=', toks[0]) and len(toks) > 1:
        if toks[0].split('=', 1)[0] not in ENV_PREFIX_OK:
            return None
        toks = toks[1:]
    return toks


def subst(seg):
    """Inner text of every top-level $( ... ) in seg."""
    out, i = [], 0
    while True:
        i = seg.find('$(', i)
        if i < 0:
            return out
        depth, j = 1, i + 2
        while j < len(seg) and depth:
            depth += {'(': 1, ')': -1}.get(seg[j], 0)
            j += 1
        out.append(seg[i + 2:j - 1])
        i = j


def ps_payload(toks):
    """(-Command payload, -File path) of a powershell/pwsh token list."""
    for k, t in enumerate(toks[1:], 1):
        tl = t.lower()
        if tl in ('-command', '-c'):
            return ' '.join(toks[k + 1:]), None
        if tl in ('-file', '-f'):
            return None, (toks[k + 1] if k + 1 < len(toks) else '')
    return None, None


def ssh_remote(toks):
    i = 1
    while i < len(toks) and toks[i].startswith('-'):
        flag = toks[i]
        i += 2 if (len(flag) == 2 and flag[1] in SSH_ARG_OPTS) else 1
    return ' '.join(toks[i + 1:]) if i + 1 < len(toks) else ''


def walk(cmd, ctx='local', depth=0):
    """Yield (ctx, segment) for every segment at every nesting level."""
    if depth > MAX_DEPTH:
        return
    for seg in split_segments(cmd, bs_escape=(ctx != 'ps')):
        yield ctx, seg
        for inner in subst(seg):
            yield from walk(inner, ctx, depth + 1)
        if ctx == 'ps':
            continue
        toks = tokens(seg)
        toks = strip_env(toks) if toks else toks
        if not toks:
            continue
        v = exe(toks[0])
        if v in ('bash', 'sh') and '-c' in toks[1:]:
            k = toks.index('-c')
            if k + 1 < len(toks):
                yield from walk(toks[k + 1], ctx, depth + 1)
        elif v in PS_EXES:
            payload, _ = ps_payload(toks)
            if payload:
                yield from walk(payload, 'ps', depth + 1)
        elif v == 'wsl' and '--' in toks:
            rest = toks[toks.index('--') + 1:]
            if rest:
                yield from walk(shlex.join(rest), 'remote' if ctx == 'remote' else 'wsl', depth + 1)
        elif v == 'ssh':
            remote = ssh_remote(toks)
            if remote:
                yield from walk(remote, 'remote', depth + 1)


def remote_write(seg):
    toks = tokens(seg) or seg.split()
    if not toks:
        return None
    v = exe(toks[0])
    if v == 'sudo' and len(toks) > 1:
        v, toks = exe(toks[1]), toks[1:]
    if v == 'systemctl' and len(toks) > 1 and toks[1] in ('status', 'is-active', 'is-enabled', 'list-units', 'show', 'cat'):
        return None
    if v == 'docker' and len(toks) > 1 and toks[1] in ('ps', 'images', 'version', 'info', 'logs', 'inspect', 'stats'):
        return None
    if v == 'git' and len(toks) > 1 and toks[1] in ('status', 'log', 'diff', 'show', 'branch', 'rev-parse'):
        return None
    if v == 'sed' and not any(t.startswith('-i') or t == '--in-place' for t in toks[1:]):
        return None
    if v in REMOTE_WRITE:
        return v
    if re.search(r'(?<![\d&])>(?!&)|\d>(?!&|\s*/dev/null)', strip_quoted(seg)):
        return '>'
    return None


def strip_quoted(s):
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", '""', s)


def critical_verb(cmd):
    for rx, name in CRITICAL_VERBS:
        if rx.search(cmd):
            return name
    return None


def critical(cmd, ctx0='local'):
    """Name of the critical write/delete in cmd, or None."""
    hit = critical_verb(cmd)
    if hit:
        return hit
    for ctx, seg in walk(cmd, ctx0):
        if ctx == 'remote':
            w = remote_write(seg)
            if w:
                return f'VPS-side {w}'
            continue
        if ctx == 'ps':
            if PS_WRITE.search(seg) and CRITICAL_PATH.search(seg):
                return 'PowerShell write to a critical path'
            for m in re.finditer(r'>>?\s*([^\s;|]+)', seg):
                if CRITICAL_PATH.search(m.group(1)):
                    return 'redirect into a critical path'
            continue
        for m in re.finditer(r'>>?\s*([^\s;|&]+)', seg):
            if CRITICAL_PATH.search(m.group(1).strip('\'"')):
                return 'redirect into a critical path'
        toks = tokens(seg)
        if not toks:
            continue
        toks = strip_env(toks) or toks
        v = exe(toks[0])
        args = [t for t in toks[1:] if not t.startswith('-')]
        if v in WRITE_VERBS and args:
            targets = args if v in ('tee', 'chmod', 'chown', 'touch', 'truncate') else args[-1:]
            if any(CRITICAL_PATH.search(t) for t in targets):
                return f'{v} into a critical path'
    return None


def ps_readonly(payload):
    code = re.sub(r"'(?:[^']|'')*'", "''", payload)
    code = re.sub(r'"(?:`.|[^"`])*"', lambda m: m.group(0) if '$(' in m.group(0) else '""', code)
    code = re.sub(r'2>\s*\$null|2>&1|>\s*\$null', '', code, flags=re.I)
    if '>' in code:
        return False
    if re.search(r'(?i)\$env:\w+\s*=(?!=)', code):
        return False
    if re.search(r'(?<![\w.])&\s*[\'"$\w]', code):
        return False
    for m in re.finditer(r'\[([\w.]+)\]::', code):
        if m.group(1).lower() != 'math':
            return False
    for m in re.finditer(r'\.\s*([A-Za-z_]\w*)\s*\(', code):  # $_.Delete(), .Kill(), ... are writes
        if m.group(1).lower() not in PS_METHODS_OK:
            return False
    for m in re.finditer(r'(?<![\w$.-])([A-Za-z]+-[A-Za-z]+)\b', code):
        w = m.group(1).lower()
        if not (w.startswith('get-') or w.startswith('format-') or w in PS_OK_EXACT):
            return False
    for stmt in re.split(r'[;|{}(\n]', code):
        s = stmt.strip()
        m = re.match(r'^([A-Za-z][\w.]*)(.?)', s)
        if not m or '-' in s.split()[0]:
            continue
        word, nxt = m.group(1).lower(), s[len(m.group(1)):].lstrip()[:1]
        if word in PS_ALIASES or nxt == '=':
            continue
        return False
    return True


def curl_ok(args):
    skip = False
    for t in args:
        if skip:
            skip = False; continue
        if t in ('-H', '--header', '-m', '--max-time', '--connect-timeout', '-w', '--write-out', '-A', '--user-agent'):
            skip = True; continue
        if t.startswith('--'):
            if t.startswith(('--data', '--output', '--upload', '--form', '--request', '--config', '--remote-name', '--json')):
                return False
            continue
        if t.startswith('-'):
            if set(t[1:]) & set('oOdTFXK'):
                return False
            continue
        if not re.match(r'^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|$)', t):
            return False
    return True


def seg_readonly(seg, ctx, depth):
    if ctx == 'ps':
        return ps_readonly(seg)
    bare = strip_quoted(seg)
    if '`' in bare or '<(' in bare:
        return False
    bare = re.sub(r'\d?>&\d|&>\s*/dev/null|\d?>\s*/dev/null', '', bare)
    if '>' in bare or '<' in bare:
        return False
    for inner in subst(seg):
        if not readonly(inner, ctx, depth + 1):
            return False
    masked = seg
    for inner in subst(seg):  # already checked above; mask so shlex sees one word
        masked = masked.replace('$(' + inner + ')', 'SUBST', 1)
    toks = tokens(re.sub(r'\s\d?>&\d|\s&>\s*/dev/null|\s\d?>\s*/dev/null', ' ', masked))
    if not toks:
        return False
    if all(re.match(r'^[A-Za-z_]\w*=', t) for t in toks):
        return True
    toks = strip_env(toks)
    if not toks:
        return False
    v, a = exe(toks[0]), toks[1:]
    if ctx == 'remote':
        if v not in REMOTE_READ or remote_write(seg):
            return False
        return v not in ('docker', 'systemctl') or bool(a)
    if v in READ_VERBS:
        if v == 'date' and any(x in ('-s', '--set') for x in a):
            return False
        return True
    if v == 'hostname':
        return all(x.startswith('-') for x in a)
    if v == 'find':
        return not any(x in ('-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprintf', '-fls') for x in a)
    if v == 'sort':
        return not any(x == '-o' or x.startswith('--output') for x in a)
    if v in ('env', 'printenv'):
        return v == 'printenv' or not a
    if v in VERSION_ONLY:
        return len(a) == 1 and a[0] in VERSION_FLAGS
    if v == 'git':
        return git_ok(a)
    if v == 'docker':
        return bool(a) and (a[0] in ('version', 'ps', 'images', 'info', '--version') or a[:2] == ['context', 'ls'])
    if v == 'gh':
        return a[:2] in (['auth', 'status'], ['repo', 'view']) or a == ['--version']
    if v == 'curl':
        return curl_ok(a)
    if v == 'wsl':
        if a[:1] in (['-d'], ['--distribution']) and len(a) > 2:
            rest = a[2:]
            if rest[0] in ('--', '-e', '--exec'):
                rest = rest[1:]
            return bool(rest) and readonly(shlex.join(rest), 'wsl', depth + 1)
        return bool(a) and all(x in ('--list', '-l', '--verbose', '-v', '--status', '--version',
                                    '--running', '--quiet', '-q', '--online', '-o', '--all') for x in a)
    if v in ('bash', 'sh'):
        if a[:1] == ['-c'] and len(a) > 1:
            return readonly(a[1], ctx, depth + 1)
        return False
    if v in PS_EXES:
        payload, _ = ps_payload(toks)
        if payload is None:
            return False
        k = next(i for i, x in enumerate(a) if x.lower() in ('-command', '-c'))
        return all(f.lower() in ('-noprofile', '-nologo', '-noninteractive') for f in a[:k]) and ps_readonly(payload)
    if v == 'ssh':
        remote = ssh_remote(toks)
        return bool(remote) and readonly(remote, 'remote', depth + 1)
    return False


def git_ok(a):
    while a and (a[0] in ('-C',) and len(a) > 1 or a[0] in ('--no-pager',)):
        a = a[2:] if a[0] == '-C' else a[1:]
    if not a:
        return False
    sub, rest = a[0], a[1:]
    if sub in ('status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', '--version'):
        return not any(x.startswith('--output') for x in rest)
    if sub == 'remote':
        return rest in ([], ['-v'])
    if sub == 'branch':
        return all(x in ('--show-current', '-a', '-r', '-v', '-vv', '--list', '--all', '--remotes') for x in rest)
    if sub == 'config':
        flags = [x for x in rest if x.startswith('-')]
        keys = [x for x in rest if not x.startswith('-')]
        return len(keys) <= 1 and all(f in ('--global', '--system', '--local', '--show-origin', '--get',
                                            '--get-all', '--list', '-l') for f in flags) and bool(keys or flags)
    return False


def readonly(cmd, ctx='local', depth=0):
    if depth > MAX_DEPTH:
        return False
    segs = split_segments(cmd, bs_escape=(ctx != 'ps'))
    return bool(segs) and all(seg_readonly(s, ctx, depth) for s in segs)


SCRIPT_KEYWORDS = {'do', 'done', 'then', 'fi', 'else', 'esac', '{', '}', 'continue', 'break', 'true', ':'}


def script_line_ok(line, kind):
    if kind == 'ps':
        return ps_readonly(line)
    if kind != 'sh':
        return False
    s = re.sub(r';\s*(?:do|then)$', '', line).strip()
    if s in SCRIPT_KEYWORDS or re.match(r'^set(\s+[-+][a-zA-Z]+|\s+-o\s+\w+)+$', s):
        return True
    m = re.match(r'^for\s+\w+\s+in\s+(.*)$', s)
    if m:
        return '$(' not in m.group(1) and '`' not in m.group(1)
    m = re.match(r'^(?:if|elif|while|until)\s+(.*)$', s)
    return readonly(m.group(1) if m else s)


def script_target(toks):
    """(path, kind) when the segment runs a script file, else None."""
    v, a = exe(toks[0]), toks[1:]
    if v in ('bash', 'sh') and a and not a[0].startswith('-'):
        return a[0], 'sh'
    if v in PS_EXES:
        _, f = ps_payload(toks)
        if f is not None:
            return f, 'ps'
    if v in ('python', 'py', 'node') and a and not a[0].startswith('-'):
        return a[0], v
    return None


def resolve(path, cwd):
    p = os.path.expanduser(path)
    m = re.match(r'^/([a-zA-Z])/(.*)$', p)
    if m:
        p = f'{m.group(1).upper()}:/{m.group(2)}'
    return p if os.path.isabs(p) else os.path.join(cwd or os.getcwd(), p)


def check_script(path, kind, cwd):
    """'allow' when every line is read-only, ('deny', reason) for the first critical
    line, None (no decision) when the file is unreadable or a line is neither."""
    try:
        with open(resolve(path, cwd), encoding='utf-8', errors='replace') as f:
            text = f.read(200_000)
    except OSError:
        return None
    lines = re.sub(r'\\\r?\n', ' ', text).splitlines()
    all_readonly = True
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if kind in ('sh', 'ps'):
            hit = critical(line, 'ps' if kind == 'ps' else 'local')
        else:
            hit = critical_verb(line)
        if hit:
            return 'deny', f'lis-guard: script {path} line {n} is a critical write ({hit}): {line[:160]!r}; {NOT_RETRYABLE}.'
        if all_readonly and not script_line_ok(line, kind):
            all_readonly = False
    return 'allow' if all_readonly else None


def decide(cmd, cwd=None):
    """('deny'|'allow', reason) or None for no decision."""
    if not cmd.strip():
        return None
    hit = critical(cmd)
    if hit:
        return 'deny', f'lis-guard: {hit} matched; {NOT_RETRYABLE}.'
    scripts, others = [], []
    for seg in split_segments(cmd):
        toks = tokens(seg)
        toks = strip_env(toks) if toks else toks
        st = script_target(toks) if toks else None
        (scripts if st else others).append(st or seg)
    scripts_ok = True
    for path, kind in scripts:
        r = check_script(path, kind, cwd)
        if isinstance(r, tuple):
            return r
        scripts_ok = scripts_ok and r == 'allow'
    if scripts_ok and all(seg_readonly(s, 'local', 0) for s in others):
        return 'allow', 'lis-guard: read-only command'
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get('tool_name', 'Bash') != 'Bash':
        return 0
    cmd = (data.get('tool_input') or {}).get('command') or ''
    try:
        d = decide(cmd, data.get('cwd'))
    except Exception:  # an analysis bug must not block the session; the classifier still judges
        hit = critical_verb(cmd)
        d = ('deny', f'lis-guard: {hit} matched; {NOT_RETRYABLE}.') if hit else None
    if d:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                                 'permissionDecision': d[0],
                                                 'permissionDecisionReason': d[1]}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
