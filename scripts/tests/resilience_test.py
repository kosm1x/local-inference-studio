"""Tests for scripts/serve.ps1 (restart loop, fixed flags, per-start key), scripts/stop.ps1
(stop marker), scripts/watchdog.ps1 (poll and restart decisions), the server preflight
and key fallback of scripts/claude-local.ps1, its absolute path rules (-LisPrintArgs), and the logs/api-key resolver lines shared by
the smoke scripts and the benches.
Stop files are port-scoped: logs/.stop-requested-<port>.
Run: python -I scripts/tests/resilience_test.py

Everything runs on copies of the scripts in a temp "repo" whose bin/llama-server.exe is a
stub compiled from STUB_CS with the .NET Framework csc.exe (those cases are skipped when it
is missing). The stub never binds 8080 and ends on its own (exit plan or exit file); the
one process a case stops is that stub, by stop.ps1 on the stub's free port (test_stop_stub).
HTTP endpoints are a Python stub on a free loopback port. The live
server, the scheduled tasks and claude are never touched. Exit 0 = all pass.
The session supervisor of claude-local.ps1 runs against a stub claude compiled from
STUB_CLAUDE_CS (LIS_CLAUDE_EXE; skipped without csc.exe). Optional argument: a wrapper
file to test instead of scripts/claude-local.ps1 (for wrapper mutants).
Ledger S-B3, S-B5, W-5: -LisPrintArgs per profile (PowerShell and Playwright denies, hook
commands on the per-run read-only copies, the -LisFull web refusal) and a stub run whose
hook copies are checked on disk; lis-guard.py run from a copy with --hooks-dir.
Ledger S-O3: --setting-sources project,local in every mode but -LisFull (-LisUserScope drops
it), the banner line, and LIS_SESSION_START in the settings env and the launched env.
"""
import http.server
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
PWSH = shutil.which('pwsh')
CSC = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), r'Microsoft.NET\Framework64\v4.0.30319\csc.exe')

STUB_CS = r'''
using System; using System.Collections; using System.Collections.Generic; using System.IO; using System.Net; using System.Net.Sockets; using System.Text; using System.Threading;
class Stub {
  static int Main(string[] a) {
    string dir = AppDomain.CurrentDomain.BaseDirectory;
    File.AppendAllText(Path.Combine(dir, "stub-args.log"), string.Join(" ", a) + Environment.NewLine);
    foreach (DictionaryEntry e in Environment.GetEnvironmentVariables())
      if (((string)e.Key).StartsWith("LLAMA_")) File.AppendAllText(Path.Combine(dir, "stub-env.log"), e.Key + "=" + e.Value + Environment.NewLine);
    string mode = "serve", plan = Path.Combine(dir, "stub-plan.txt");
    if (File.Exists(plan)) {
      var lines = new List<string>(File.ReadAllLines(plan));
      if (lines.Count > 0) { mode = lines[0].Trim(); lines.RemoveAt(0); File.WriteAllLines(plan, lines.ToArray()); }
    }
    int port = 0;
    for (int i = 0; i + 1 < a.Length; i++) if (a[i] == "--port") port = int.Parse(a[i + 1]);
    if (port == 8080 || port == 0) return 2;
    if (mode.StartsWith("exit:")) return int.Parse(mode.Substring(5));
    var l = new TcpListener(IPAddress.Loopback, port); l.Start();
    File.WriteAllText(Path.Combine(dir, "stub-serving.txt"), "1");
    string exitFile = Path.Combine(dir, "stub-exit.txt");
    for (int t = 0; t < 600; t++) {
      if (File.Exists(exitFile)) { int c = int.Parse(File.ReadAllText(exitFile).Trim()); File.Delete(exitFile); return c; }
      Thread.Sleep(100);
    }
    return 9;
  }
}
'''


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def pwsh(script, timeout=120):
    r = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def make_repo(tmp, stub_exe=None):
    """A temp repo with copies of the scripts; a stub exe and a dummy model when given."""
    root = os.path.join(tmp, 'repo')
    for d in ('scripts', 'bin', 'logs', 'config/chat-templates', 'models/qwen3.8-27b-uncensored'):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    for f in ('serve.ps1', 'stop.ps1', 'watchdog.ps1'):
        shutil.copy(os.path.join(REPO, 'scripts', f), os.path.join(root, 'scripts', f))
    shutil.copy(os.path.join(REPO, 'config/chat-templates/qwen3.8-27b.jinja'),
                os.path.join(root, 'config/chat-templates'))
    open(os.path.join(root, 'models/qwen3.8-27b-uncensored/Qwen3.8-27B-OrcaRouter-GSQ-RCO-IQ3_XXS-v2.1.gguf'), 'w').close()
    # serve.ps1's binary pin check (S-O1) reads the pins from install.ps1 (refusing
    # without it); a release with no pin warns and goes on; the empty model has no
    # manifest here, so its hash check warns too (S-O2)
    shutil.copy(os.path.join(REPO, 'scripts', 'install.ps1'), os.path.join(root, 'scripts'))
    with open(os.path.join(root, 'bin', 'llama-release.txt'), 'w') as f:
        f.write('test-stub\n')
    if stub_exe:
        shutil.copy(stub_exe, os.path.join(root, 'bin', 'llama-server.exe'))
    return root


class Stub(http.server.BaseHTTPRequestHandler):
    """/health -> health_status; /slots -> 401 unless the bearer matches, else slots JSON."""
    health_status = 200
    hits = 0
    key = 'local'
    slots = [{'id': 0, 'is_processing': False}]

    def do_GET(self):
        if self.path == '/health':
            Stub.hits += 1
            code, body = Stub.health_status, {'status': 'ok' if Stub.health_status == 200 else 'loading'}
        elif self.path == '/slots':
            ok = self.headers.get('Authorization') == f'Bearer {Stub.key}'
            code, body = (200, Stub.slots) if ok else (401, {'error': 'Invalid API Key'})
        else:
            code, body = 404, {}
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


FAILS = []


def check(name, cond, detail=''):
    print(('ok    ' if cond else 'FAIL  ') + name + ('' if cond else f'  -- {detail[:600]}'))
    if not cond:
        FAILS.append(name)


def test_wrapper(port):
    """claude-local.ps1's own Get-LisApiKey / Test-LisServer, taken from the file by AST."""
    wrapper = os.path.join(REPO, 'scripts', 'claude-local.ps1').replace("'", "''")
    load = ("$ast = [Management.Automation.Language.Parser]::ParseFile('" + wrapper + "', [ref]$null, [ref]$null); "
            "$ast.FindAll({ $args[0] -is [Management.Automation.Language.FunctionDefinitionAst] -and "
            "$args[0].Name -in 'Get-LisApiKey', 'Test-LisServer' }, $false) | "
            "ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }; ")
    base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory() as tmp:
        key = os.path.join(tmp, 'api-key')
        _, out, _ = pwsh(load + f"'K=' + (Get-LisApiKey '{key}')")
        check('wrapper: no key file -> local', 'K=local' in out, out)
        with open(key, 'w') as f:
            f.write('\n')
        _, out, _ = pwsh(load + f"'K=' + (Get-LisApiKey '{key}')")
        check('wrapper: empty key file -> local', 'K=local' in out, out)
        with open(key, 'w') as f:
            f.write('ab12cd\n')
        _, out, _ = pwsh(load + f"'K=' + (Get-LisApiKey '{key}')")
        check('wrapper: key file -> its first line', 'K=ab12cd' in out, out)

    def run(api_key, strict):
        return pwsh(load + f"try {{ Test-LisServer '{base}' '{api_key}' ${'true' if strict else 'false'}; 'PASSED' }} "
                    "catch { 'THREW: ' + $_.Exception.Message }")

    Stub.key, Stub.health_status, Stub.slots = 'k1', 200, [{'id': 0, 'is_processing': False}]
    _, out, err = run('k1', False)
    check('preflight: health ok, slot idle -> passes', 'PASSED' in out and 'warning' not in err, out + err)
    _, out, _ = run('local', False)
    check('preflight: wrong key -> throws naming logs/api-key', 'THREW' in out and 'logs/api-key' in out, out)
    Stub.slots = [{'id': 0, 'is_processing': True}]
    _, out, err = run('k1', False)
    check('preflight: busy slot -> warning, continues', 'PASSED' in out and 'slot 0 is processing' in err, out + err)
    _, out, _ = run('k1', True)
    check('preflight: busy slot + -LisStrictSlot -> throws', 'THREW' in out and 'LisStrictSlot' in out, out)
    Stub.health_status = 503
    _, out, _ = run('k1', False)
    check('preflight: /health 503 -> throws with the start command', 'THREW' in out and 'Start-ScheduledTask' in out, out)
    Stub.health_status, Stub.slots = 200, [{'id': 0, 'is_processing': False}]
    dead = free_port()
    _, out, _ = pwsh(load + f"try {{ Test-LisServer 'http://127.0.0.1:{dead}' 'k1' $false; 'PASSED' }} "
                     "catch { 'THREW: ' + $_.Exception.Message }")
    check('preflight: nothing listening -> throws', 'THREW' in out and '/health' in out, out)


RESOLVER = [
    "$keyFile = Join-Path $repo 'logs\\api-key'",
    '$apiKey = if (Test-Path -LiteralPath $keyFile -PathType Leaf) { "$(Get-Content -LiteralPath $keyFile -TotalCount 1)".Trim() }',
    "if (-not $apiKey) { $apiKey = 'local' }",
]
RESOLVER_USERS = ['scripts/smoke.ps1', 'scripts/web-smoke.ps1', 'bench/run.ps1', 'bench/loop/run.ps1',
                  'bench/perm/run.ps1', 'bench/compact/run.ps1', 'bench/ladder/run.ps1']


def test_key_resolvers():
    """The same three resolver lines in every caller; evaluated with no, an empty and a
    real logs/api-key under a temp repo root. bench/compact's lines for its tree's wrapper
    are taken from its -DryRun output and evaluated the same way."""
    for rel in RESOLVER_USERS:
        with open(os.path.join(REPO, rel), encoding='utf-8') as f:
            lines = [l.strip() for l in f.read().splitlines()]
        found = any(lines[i:i + 3] == RESOLVER for i in range(len(lines)))
        check(f'resolver: {rel} has the three lines verbatim', found)

    def resolve(lines, repo):
        body = '; '.join(l.replace("$repo", f"'{repo}'", 1) if l.startswith("$keyFile") else l for l in lines)
        _, out, err = pwsh("$set = @{}; " + body + "; 'K=' + $apiKey + ' T=' + $set['ANTHROPIC_AUTH_TOKEN']")
        return out.strip() + err

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 'logs'))
        key = os.path.join(tmp, 'logs', 'api-key')
        check('resolver: no key file -> local', resolve(RESOLVER, tmp).startswith('K=local'))
        open(key, 'w').close()
        check('resolver: empty key file -> local', resolve(RESOLVER, tmp).startswith('K=local'))
        with open(key, 'w') as f:
            f.write('9f8e7d\n')
        check('resolver: key file -> its first line', resolve(RESOLVER, tmp).startswith('K=9f8e7d'))

        r = subprocess.run([PWSH, '-NoProfile', '-File', os.path.join(REPO, 'bench', 'compact', 'run.ps1'),
                            '-Case', 'baseline', '-DryRun'], capture_output=True, text=True, timeout=120)
        out = r.stdout.splitlines()
        start = next((i for i, l in enumerate(out) if 'insert before the $unset line' in l), None)
        tree = []
        if start is not None:
            for l in out[start + 1:]:
                if not l.startswith('    '):
                    break
                tree.append(l.strip())
        tree = [l for l in tree if not l.startswith("$set['ANTHROPIC_BASE_URL']")]
        check('resolver: compact tree lines = $repo of this repo + the three lines + AUTH_TOKEN',
              len(tree) == 5 and tree[0] == f"$repo = '{REPO}'" and tree[1:4] == RESOLVER
              and tree[4] == "$set['ANTHROPIC_AUTH_TOKEN'] = $apiKey", '\n'.join(out))
        if len(tree) == 5:
            got = resolve([f"$repo = '{tmp}'"] + tree[1:], tmp)
            check('resolver: compact tree lines set AUTH_TOKEN from the repo key file', 'T=9f8e7d' in got, got)


def test_wrapper_rules():
    """-LisPrintArgs (claude is not started): ~/ path rules rewritten to the absolute home
    form, and Edit denies on this repo's guard files by absolute repo path."""
    r = subprocess.run([PWSH, '-NoProfile', '-File', os.path.join(REPO, 'scripts', 'claude-local.ps1'), '-LisPrintArgs'],
                       capture_output=True, text=True, timeout=120)
    marker = 'settings JSON (the --settings file):'
    try:
        rules = json.loads(r.stdout[r.stdout.index(marker) + len(marker):])['permissions']
    except ValueError as e:
        check('rules: -LisPrintArgs prints the settings JSON', False, f'{e} {r.stdout}{r.stderr}')
        return
    home = os.path.expanduser('~').replace(os.sep, '/')
    home = '//' + home[0].lower() + home[2:]
    repo = '//' + REPO[0].lower() + REPO[2:].replace(os.sep, '/')
    every = [x for k in ('allow', 'ask', 'deny') for x in rules.get(k, [])]
    check('rules: no ~/ rule left', not [x for x in every if '(~/' in x], [x for x in every if '(~/' in x])
    check('rules: Read(~/.claude/.credentials.json) deny -> absolute home form',
          f'Read({home}/.claude/.credentials.json)' in rules['deny'])
    check('rules: Edit(~/.claude/**) -> absolute home form', f'Edit({home}/.claude/**)' in every)
    guards = ['scripts/hooks/**', 'scripts/verify-doc.py', 'scripts/serve.ps1', 'scripts/stop.ps1',
              'scripts/claude-local.ps1', 'scripts/register-task.ps1', 'scripts/watchdog.ps1',
              'scripts/register-watchdog.ps1', 'config/**', 'bin/**', '.gitignore', '.gitattributes', 'logs/api-key',
              'logs/.stop-requested*', 'scripts/tests/resilience_test.py', 'scripts/tests/claude_settings_test.py',
              'scripts/tests/install_verify_test.py']
    missing = [g for g in guards if f'Edit({repo}/{g})' not in rules['deny']]
    check(f'rules: Edit deny by absolute repo path for {len(guards)} guard paths', not missing, missing)


# Every profile's per-run settings deny the PowerShell tool (ledger S-B5) and path C's three
# riskiest Playwright tools (W-5); the hooks run from a per-run read-only copy (S-B3).
WEB_DENIES = ['PowerShell', 'mcp__playwright__browser_evaluate',
              'mcp__playwright__browser_run_code_unsafe', 'mcp__playwright__browser_file_upload',
              # any server's tools of those names, plugin servers included (audit W1)
              'mcp__*__browser_evaluate', 'mcp__*__browser_run_code_unsafe',
              'mcp__*__browser_file_upload']
GUARD_HOOKS = ['lis-guard.py', 'loop-guard.py', 'verify-doc.py']
PROFILE_HOOKS = [([], GUARD_HOOKS), (['-LisTask', 'review'], GUARD_HOOKS),
                 (['-LisTask', 'edit'], GUARD_HOOKS),
                 (['-LisTask', 'longrun'], GUARD_HOOKS + ['facts-inject.py']),
                 (['-LisFull'], GUARD_HOOKS),
                 (['-LisNoLoopGuard'], ['lis-guard.py', 'verify-doc.py']),
                 (['-LisNoGuard'], []),
                 # path C (docs/web-access.md): the lean set with the example MCP config
                 (['--mcp-config', 'scripts/web-access.example.mcp.json'], GUARD_HOOKS)]
# -LisFull with a web flag is refused before anything runs (S-B5); a prompt is not a flag.
WEB_REFUSED = [['-LisFull', '-LisWeb'], ['-LisWeb', '-LisFull'],
               ['-LisFull', '--mcp-config', 'scripts/web-access.example.mcp.json'],
               ['--mcp-config=x.json', '-LisFull'],
               ['-LisFull', '--allowedTools', 'Bash(git status)', 'WebFetch(domain:example.com)'],
               ['-LisFull', '--allowed-tools=mcp__playwright__browser_navigate'],
               ['-LisFull', '--allowedTools', 'WebSearch', '-p', 'x']]
# Every profile refuses a caller's settings, setting sources, plugin dir and permission
# bypass (S-B5 audit W2): the launcher owns settings and hooks; a prompt is not checked.
OWNED_REFUSED = [['--settings', '{"disableAllHooks":true}'], ['--settings={}'],
                 ['--setting-sources', 'user'], ['--plugin-dir', 'x'],
                 ['--dangerously-skip-permissions'], ['--allow-dangerously-skip-permissions'],
                 ['--permission-mode', 'bypassPermissions'],
                 ['--permission-mode=bypassPermissions'],
                 ['-LisFull', '--settings', 'x.json'], ['-LisNoGuard', '--plugin-dir', 'x'],
                 ['--mcp-config', 'scripts/web-access.example.mcp.json', '--settings', 'x.json']]
OWNED_KEPT = [['-p', 'what does --settings do here?'], ['--permission-mode', 'acceptEdits']]
WEB_KEPT = [['-LisFull', '-p', 'Why are WebFetch and mcp__playwright tools denied here?'],
            ['-LisFull', '--allowedTools', 'Bash(git status)', '-p', 'WebFetch'],
            ['-LisFull', '--disallowedTools', 'WebFetch']]


def abs_rule(path):
    """A Windows path in the //c/... rule form the wrapper writes."""
    p = path.replace(os.sep, '/')
    return '//' + p[0].lower() + p[2:]


def print_args(args, wrapper=None):
    """-LisPrintArgs: rc, the claude argument list, the settings dict (None when absent),
    stdout and stderr."""
    r = subprocess.run([PWSH, '-NoProfile', '-File', wrapper or WRAPPER, '-LisPrintArgs'] + args,
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    a, b = 'claude arguments (JSON array, in order):', 'settings JSON (the --settings file):'
    try:
        argv = json.loads(r.stdout[r.stdout.index(a) + len(a):r.stdout.index(b)])
        cfg = json.loads(r.stdout[r.stdout.index(b) + len(b):])
    except ValueError:
        argv, cfg = None, None
    return r.returncode, argv, cfg, r.stdout, r.stderr


def hook_scripts(cfg):
    """(event, script path, the rest of the command) for every registered hook."""
    out = []
    for ev, groups in (cfg.get('hooks') or {}).items():
        for g in groups:
            for h in g['hooks']:
                m = re.match(r'python -I "([^"]+)"(.*)$', h['command'])
                out.append((ev, m.group(1) if m else h['command'], m.group(2) if m else ''))
    return out


def check_hook_settings(name, cfg, want, err):
    """The hook commands name one per-run lis-hooks-<stamp>-<pid> directory under %TEMP%, not
    the repo; lis-guard gets --hooks-dir <repo>/scripts/hooks; Edit of that directory is
    denied (an Edit rule covers Write); the banner names it. Returns the directory (None
    without hooks)."""
    deny = cfg['permissions']['deny']
    hooks = hook_scripts(cfg)
    dirs = {os.path.dirname(p) for _, p, _ in hooks}
    temp = os.environ['TEMP'].replace(os.sep, '/')
    named = sorted({os.path.basename(p) for _, p, _ in hooks})
    if not want:
        check(f'hook copies {name}: no hook, no copy directory, no banner line',
              not hooks and 'hook copies:' not in err
              and not [x for x in deny if 'lis-hooks-' in x],
              f'{hooks} {err}')
        return None
    d = dirs.pop() if len(dirs) == 1 else ''
    repo = REPO.replace(os.sep, '/').lower()
    check(f'hook copies {name}: every hook command runs a copy in one %TEMP%\\lis-hooks-* dir',
          not dirs and d.startswith(temp + '/lis-hooks-') and named == sorted(want)
          and not [p for _, p, _ in hooks if p.lower().startswith(repo)],
          f'{hooks}')
    guard = [rest for _, p, rest in hooks if p.endswith('/lis-guard.py')]
    check(f'hook copies {name}: lis-guard gets --hooks-dir <repo>/scripts/hooks',
          guard == [f' --hooks-dir "{REPO.replace(os.sep, "/")}/scripts/hooks"'], f'{guard}')
    vd = [rest for _, p, rest in hooks if p.endswith('/verify-doc.py')]
    check(f'hook copies {name}: verify-doc gets --script <repo>/scripts/verify-doc.py (audit C1)',
          vd == [f' --hook --script "{REPO.replace(os.sep, "/")}/scripts/verify-doc.py"'], f'{vd}')
    rules = ([f'Edit({abs_rule(d)}/**)'] if d else []) + ['Edit(//**/lis-hooks-*/**)']
    check(f'hook copies {name}: Edit of the copies denied',
          d and all(x in deny for x in rules), [x for x in rules if x not in deny])
    check(f'hook copies {name}: the banner names the directory',
          f'claude-local: hook copies: {d.replace("/", os.sep)} ' in err, err)
    return d


# -LisUserScope opts user scope back in, with or without a profile (ledger S-O3).
USER_SCOPE_CASES = [(['-LisUserScope'], '-LisUserScope'),
                    (['-LisUserScope:true'], '-LisUserScope'),
                    (['-LisUserScope:false'], None),
                    (['-LisTask', 'review', '-LisUserScope'], '-LisUserScope'),
                    (['-LisTask', 'longrun', '-LisUserScope'], '-LisUserScope'),
                    (['-LisNoGuard', '-LisUserScope'], '-LisUserScope'),
                    (['--mcp-config', 'scripts/web-access.example.mcp.json', '-LisUserScope'],
                     '-LisUserScope'),
                    (['-LisFull', '-LisUserScope'], '-LisFull')]
# LIS_SESSION_START: round-trip ('o') UTC, 7 fraction digits, so a file born in the
# launch second before the start does not count as session-written (S-B4).
SESSION_START = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z\Z')


def check_user_scope(name, argv, cfg, err, on):
    """User scope off: --setting-sources project,local once, before the forwarded
    arguments, and the banner says off; on (-LisFull or -LisUserScope): no flag, the banner
    names the switch. Either way the per-run settings env carries LIS_SESSION_START, the
    reads the user scope denied on the audit machine (.env, ~/.ssh, ~/.aws) stay denied, and
    Edit of the work tree's .claude/settings*.json is denied (S-O3 audit W4). No Write(path)
    rule is emitted: Claude Code 2.1.318 does not match one in its file permission checks
    (an Edit rule covers every file-editing tool, Write included) and warns at startup."""
    argv = argv or []
    n = argv.count('--setting-sources')
    i = argv.index('--setting-sources') if n else -1
    if on:
        check(f'user scope {name}: on ({on}), no --setting-sources',
              n == 0 and f'claude-local: user scope: on ({on})' in err, f'{argv} {err}')
    else:
        check(f'user scope {name}: off, --setting-sources project,local in front',
              n == 1 and argv[i + 1] == 'project,local' and i == 2
              and 'claude-local: user scope: off (S-O3)' in err, f'{argv} {err}')
    start = (cfg.get('env') or {}).get('LIS_SESSION_START', '')
    check(f'user scope {name}: settings env LIS_SESSION_START is ISO UTC',
          bool(SESSION_START.match(start)), repr(start))
    home = abs_rule(os.path.expanduser('~'))
    deny = cfg['permissions']['deny']
    reads = ['Read(**/.env*)', f'Read({home}/.ssh/**)', f'Read({home}/.aws/**)']
    check(f'user scope {name}: the .env, ~/.ssh and ~/.aws read denies are per-run',
          all(x in deny for x in reads), [x for x in reads if x not in deny])
    check(f'user scope {name}: Edit of .claude/settings*.json denied per run',
          'Edit(**/.claude/settings*.json)' in deny, deny)
    writes = [x for x in deny if x.startswith('Write(')]
    check(f'user scope {name}: no Write(path) deny rule emitted (inert on 2.1.318)',
          not writes, writes)


def test_wrapper_web_and_hooks():
    """-LisPrintArgs per profile: the PowerShell and Playwright denies, the hook commands on
    the per-run copies (nothing written: the directory does not exist), and the -LisFull
    web refusal (S-B5), which exits before the banner or any output."""
    for args, want in PROFILE_HOOKS:
        name = ' '.join(args) or 'no profile'
        rc, argv, cfg, out, err = print_args(args)
        if cfg is None:
            check(f'web/hooks {name}: -LisPrintArgs prints the settings', False, f'{rc} {out}{err}')
            continue
        deny = cfg['permissions']['deny']
        check(f'web/hooks {name}: PowerShell and the three Playwright tools denied',
              rc == 0 and all(x in deny for x in WEB_DENIES),
              [x for x in WEB_DENIES if x not in deny])
        # serve.ps1's pin sources (ledger S-B3): Edit denied by absolute path.
        pins = [f'Edit({abs_rule(REPO)}/{f})'
                for f in ('scripts/install.ps1', 'models/manifest.json')]
        check(f'web/hooks {name}: Edit of install.ps1 and models/manifest.json denied',
              not [x for x in pins if x not in deny], [x for x in pins if x not in deny])
        if 'longrun' in args:               # the facts-inject log (batch E audit W2)
            facts = [f'Edit({abs_rule(os.environ["TEMP"])}/lis-facts-inject-*)',
                     'Edit(//**/lis-facts-inject-*)']
            check(f'web/hooks {name}: Edit of lis-facts-inject-* denied',
                  all(x in deny for x in facts), [x for x in facts if x not in deny])
        d = check_hook_settings(name, cfg, want, err)
        if d:
            check(f'hook copies {name}: -LisPrintArgs writes no copy', not os.path.exists(d), d)
        check_user_scope(name, argv, cfg, err, on='-LisFull' if '-LisFull' in args else None)
    for args, on in USER_SCOPE_CASES:
        rc, argv, cfg, out, err = print_args(args)
        check_user_scope(' '.join(args), argv, cfg, err, on) if cfg is not None else \
            check(f'user scope {" ".join(args)}: -LisPrintArgs prints the settings', False,
                  f'{rc} {out}{err}')
    for args in WEB_REFUSED:
        rc, argv, cfg, out, err = print_args(args)
        check(f'web/-LisFull refused: {" ".join(args)}',
              rc != 0 and cfg is None and '-LisFull cannot be combined with web access' in err
              and 'claude-local:' not in err, f'{rc} {out}{err}')
    for args in WEB_KEPT:
        rc, argv, cfg, out, err = print_args(args)
        check(f'web/-LisFull kept (no web flag): {" ".join(args)}',
              rc == 0 and cfg is not None, f'{rc} {err}')
    for args in OWNED_REFUSED:
        rc, argv, cfg, out, err = print_args(args)
        check(f'owned/refused in every profile: {" ".join(args)}',
              rc != 0 and cfg is None and "would replace the launcher's settings" in err
              and 'claude-local:' not in err, f'{rc} {out}{err}')
    for args in OWNED_KEPT:
        rc, argv, cfg, out, err = print_args(args)
        check(f'owned/kept: {" ".join(args)}', rc == 0 and cfg is not None, f'{rc} {err}')
    # -LisFull keeps --strict-mcp-config and the empty per-run MCP config (audit C2), so
    # no .mcp.json server loads; it still drops --tools and the policy
    rc, argv, cfg, out, err = print_args(['-LisFull'])
    temp = os.environ['TEMP'].replace(os.sep, '/').lower()
    i = argv.index('--mcp-config') if argv and '--mcp-config' in argv else -1
    check('mcp/-LisFull: --strict-mcp-config and the empty per-run --mcp-config, no --tools',
          rc == 0 and '--strict-mcp-config' in argv and i >= 0
          and os.path.basename(argv[i + 1]).startswith('lis-mcp-')
          and argv[i + 1].replace(os.sep, '/').lower().startswith(temp)
          and '--tools' not in argv and '--append-system-prompt' not in argv, f'{rc} {argv}')


def test_guard_copy():
    """lis-guard.py copied out of the repo (the wrapper's per-run copy, S-B3) and run with
    --hooks-dir <repo>/scripts/hooks decides as the repo file does; without it the copy
    loses the repo anchor (its exemptions and repo root), so the argument is needed."""
    src = os.path.join(REPO, 'scripts', 'hooks', 'lis-guard.py')
    cmds = ['python -I scripts/hooks/tests/lis-guard_test.py',
            'python -I scripts/tests/resilience_test.py',
            'python -I scripts/hooks/lis-guard.py', 'pwsh -NoProfile -File scripts/web-smoke.ps1',
            'cat README.md', 'git push origin main']
    with tempfile.TemporaryDirectory() as t:
        cp = shutil.copy(src, t)

        def run(script, extra):
            out = []
            for c in cmds:
                r = subprocess.run([sys.executable, '-I', script] + extra, capture_output=True,
                                   text=True, timeout=60,
                                   input=json.dumps({'tool_name': 'Bash', 'cwd': REPO,
                                                     'tool_input': {'command': c}}))
                d = json.loads(r.stdout)['hookSpecificOutput'] if r.stdout.strip() else {}
                out.append(d.get('permissionDecision'))
            return out
        want = run(src, [])
        got = run(cp, ['--hooks-dir', os.path.join(REPO, 'scripts', 'hooks').replace(os.sep, '/')])
        bare = run(cp, [])
    check('guard copy: with --hooks-dir the copy decides as the repo file', got == want,
          f'{got} vs {want}')
    check('guard copy: without --hooks-dir the copy decides otherwise (the anchor is needed)',
          bare != want, f'{bare} vs {want}')


FIXED_FLAGS = ['--host', '--port', '--api-key', '--api-key-file', '--connect', '--connect-code', '--tools', '--agent',
               '--reuse-port', '--webui', '--ui', '--mcp-servers-config', '--mcp-servers-json', '--ui-mcp-proxy',
               '--webui-mcp-proxy', '--path', '-ag', '--media-path', '--hf-token', '-hft', '--slot-save-path',
               '--log-prompts-dir', '--props', '--models-dir', '--models-preset']


def test_fixed_flags():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)  # no bin/llama-server.exe: a missed refusal throws "not found"
        serve = os.path.join(root, 'scripts', 'serve.ps1')

        def line(text):
            r = subprocess.run([PWSH, '-NoProfile', '-File', serve, '-Port', str(free_port()), '-ExtraArgLine', text],
                               capture_output=True, text=True, timeout=60)
            return r.returncode, r.stdout + r.stderr

        for flag in FIXED_FLAGS:
            res = [line(t) for t in (f'-lv 4 {flag} x', f'{flag}=x')]
            check(f'serve: -ExtraArgLine {flag} x and {flag}=x refused',
                  all(rc != 0 and 'may not set' in out for rc, out in res), '\n'.join(o for _, o in res))
        r = subprocess.run([PWSH, '-NoProfile', '-Command',
                            f"& '{serve}' -Port {free_port()} -ExtraArgs '--temp','0.7','--host','::'"],
                           capture_output=True, text=True, timeout=60)
        check('serve: -ExtraArgs --host refused', 'may not set' in r.stdout + r.stderr, r.stdout + r.stderr)
        for text in ('-lv 4', '-lv 4 --cors-origins x', '--no-webui'):
            rc, out = line(text)
            check(f'serve: harmless -ExtraArgLine {text!r} passes the check', 'llama-server.exe not found' in out, out)


def test_restart_window():
    """The restart-window prune, taken from serve.ps1 by AST and fed restarts of 120, 59
    and 10 s ago."""
    serve = os.path.join(REPO, 'scripts', 'serve.ps1')
    load = ("$ast = [Management.Automation.Language.Parser]::ParseFile('" + serve.replace("'", "''") + "', [ref]$null, [ref]$null); "
            "$ast.FindAll({ $args[0] -is [Management.Automation.Language.FunctionDefinitionAst] -and "
            "$args[0].Name -eq 'Get-RecentRestarts' }, $false) | "
            "ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }; ")
    _, out, err = pwsh(load + "$now = Get-Date; $t = @($now.AddSeconds(-120), $now.AddSeconds(-59), $now.AddSeconds(-10)); "
                       "'N1=' + @(Get-RecentRestarts $t $now 1).Count + ' N60=' + @(Get-RecentRestarts $t $now 60).Count + "
                       "' N0=' + @(Get-RecentRestarts @() $now 1).Count")
    check('serve: -RestartWindowMin 1 keeps the 2 restarts younger than 60 s, 60 keeps all 3',
          'N1=2 N60=3 N0=0' in out, out + err)
    with open(serve, encoding='utf-8') as f:
        check('serve: the restart loop prunes with Get-RecentRestarts',
              '$restarts = @(Get-RecentRestarts $restarts $now $RestartWindowMin)' in f.read())


VRAM_VALUE = r'\d+ MiB(, \d+ MiB)*|unavailable'


def test_vram_free():
    """Get-VramFree, taken from serve.ps1 by AST, against fake nvidia-smi.cmd files on PATH,
    an empty PATH, and the real nvidia-smi query on this host."""
    serve = os.path.join(REPO, 'scripts', 'serve.ps1')
    load = ("$ast = [Management.Automation.Language.Parser]::ParseFile('"
            + serve.replace("'", "''") + "', [ref]$null, [ref]$null); "
            "$ast.FindAll({ $args[0] -is "
            "[Management.Automation.Language.FunctionDefinitionAst] -and "
            "$args[0].Name -eq 'Get-VramFree' }, $false) | "
            "ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }; ")
    with open(serve, encoding='utf-8') as f:
        text = f.read()
    check('serve: the loop logs Get-VramFree before each start',
          'while ($true) {\n        Write-ServeLog "serve.ps1: vram free: $(Get-VramFree)"' in text)
    slow = '@%SystemRoot%\\System32\\ping.exe -n 3 127.0.0.1 >nul\r\n@echo 1\r\n'  # about 2 s
    fakes = [('two', '@echo 1234\r\n@echo  567 \r\n', 10000, '1234 MiB, 567 MiB'),
             ('fail', '@echo 1234\r\n@exit /b 9\r\n', 10000, 'unavailable'),
             ('text', '@echo No devices were found\r\n', 10000, 'unavailable'),
             ('slow-in-time', slow, 10000, '1 MiB'),
             ('slow-past-timeout', slow, 500, 'unavailable')]
    with tempfile.TemporaryDirectory() as tmp:
        for name, body, timeout, want in fakes:
            d = os.path.join(tmp, name)
            os.makedirs(d)
            with open(os.path.join(d, 'nvidia-smi.cmd'), 'w', newline='') as f:
                f.write(body)
            _, out, err = pwsh(load + f"$env:PATH = '{d};' + $env:SystemRoot; "
                               f"'V=' + (Get-VramFree {timeout})")
            check(f'serve: Get-VramFree with a fake nvidia-smi ({name}, {timeout} ms) -> {want}',
                  f'V={want}' in out.splitlines(), out + err)
    _, out, err = pwsh(load + "$env:PATH = ''; 'V=' + (Get-VramFree)")
    check('serve: Get-VramFree with no nvidia-smi on PATH -> unavailable',
          'V=unavailable' in out.splitlines(), out + err)
    _, out, err = pwsh(load + "'V=' + (Get-VramFree)")
    value = next((ln[2:] for ln in out.splitlines() if ln.startswith('V=')), '')
    print(f'info  this host: vram free: {value}')
    host_ok = (re.fullmatch(r'\d+ MiB(, \d+ MiB)*', value) if shutil.which('nvidia-smi')
               else value == 'unavailable')
    check('serve: Get-VramFree on this host -> MiB values (unavailable without nvidia-smi)',
          bool(host_ok), out + err)


def run_serve(root, port, extra=(), timeout=60, env=None):
    serve = os.path.join(root, 'scripts', 'serve.ps1')
    log = os.path.join(root, 'logs', 'llama-server.log')
    try:
        code = subprocess.run([PWSH, '-NoProfile', '-File', serve, '-Port', str(port), '-LogFile', log,
                               '-RestartDelaySec', '0'] + list(extra), capture_output=True, text=True,
                              timeout=timeout, env=env).returncode
    except subprocess.TimeoutExpired:
        code = 'timeout'
    with open(log, encoding='utf-8', errors='replace') as f:
        text = f.read()
    with open(os.path.join(root, 'bin', 'stub-args.log')) as f:
        starts = len(f.read().splitlines())
    return code, text, starts


def test_serve_loop(stub_exe):
    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        plan = os.path.join(root, 'bin', 'stub-plan.txt')
        with open(plan, 'w') as f:
            f.write('exit:1\n' * 6)
        code, log, starts = run_serve(root, port)
        check('serve: 6 failures -> gives up, exit 1', code == 1 and starts == 6 and 'giving up' in log
              and log.count('serve.ps1: restart ') == 5, f'{code} {starts}\n{log}')
        key_path = os.path.join(root, 'logs', 'api-key')
        with open(key_path) as f:
            key = f.read().strip()
        check('serve: key file holds 64 hex chars', len(key) == 64 and all(c in '0123456789abcdef' for c in key), key)
        check('serve: launch line has --api-key-file and --no-webui, not the key',
              f'--api-key-file {key_path}' in log and '--no-webui' in log and key not in log and '--api-key local' not in log,
              log[:800])
        vram = re.findall(r'serve\.ps1: vram free: (.*)', log)
        check('serve: one "vram free: <N> MiB" or "unavailable" line before each of the 6 starts',
              len(vram) == starts and all(re.fullmatch(VRAM_VALUE, v.strip()) for v in vram),
              log[:800])
        launches = [ln for ln in log.splitlines() if 'llama-server.exe -m ' in ln]
        check('serve: every launch line has --metrics',
              len(launches) == starts and all(' --metrics ' in ln for ln in launches), log[:800])
        rc, out, _ = pwsh(f"$a = Get-Acl -LiteralPath '{key_path}'; "
                          "\"$($a.AreAccessRulesProtected) $(@($a.Access).Count) $(@($a.Access)[0].IdentityReference) "
                          "$([Security.Principal.WindowsIdentity]::GetCurrent().Name)\"")
        parts = out.split()
        check('serve: key file ACL = current user only, no inheritance',
              len(parts) == 4 and parts[0] == 'True' and parts[1] == '1' and parts[2] == parts[3], out)

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        with open(os.path.join(root, 'logs', f'.stop-requested-{port}'), 'w') as f:
            f.write('stale\n')
        with open(os.path.join(root, 'bin', 'stub-plan.txt'), 'w') as f:
            f.write('exit:3\nexit:0\n' + 'exit:1\n' * 6)  # bounded even if exit 0 were restarted
        code, log, starts = run_serve(root, port)
        check('serve: stale stop file cleared at start; exit 3 restarted; exit 0 not restarted',
              code == 0 and starts == 2 and 'restart 1 of 5 in 0 s: llama-server exited 3' in log, f'{code} {starts}\n{log}')

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        serve = os.path.join(root, 'scripts', 'serve.ps1')
        log_path = os.path.join(root, 'logs', 'llama-server.log')
        p = subprocess.Popen([PWSH, '-NoProfile', '-File', serve, '-Port', str(port), '-LogFile', log_path,
                              '-RestartDelaySec', '0'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        serving = os.path.join(root, 'bin', 'stub-serving.txt')
        for _ in range(300):
            if os.path.exists(serving):
                break
            time.sleep(0.1)
        key_path = os.path.join(root, 'logs', 'api-key')
        with open(key_path) as f:
            key_a = f.read()
        r = subprocess.run([PWSH, '-NoProfile', '-File', serve, '-Port', str(port), '-RestartDelaySec', '0'],
                           capture_output=True, text=True, timeout=60)
        with open(key_path) as f:
            key_b = f.read()
        check('serve: second instance on the same port -> exit 1 on the mutex, key file untouched',
              r.returncode == 1 and f'another serve.ps1 holds port {port}' in r.stdout + r.stderr and key_a == key_b,
              f'{r.returncode} {r.stdout}{r.stderr}')
        # What stop.ps1 leaves before it stops the server, then the "kill" as an exit code.
        with open(os.path.join(root, 'logs', f'.stop-requested-{port}'), 'w') as f:
            f.write('[stop.ps1] stop requested 2026-01-01T00:00:00\n')
        with open(os.path.join(root, 'bin', 'stub-exit.txt'), 'w') as f:
            f.write('5')
        code = p.wait(timeout=60)
        with open(log_path, encoding='utf-8', errors='replace') as f:
            log = f.read()
        check('serve: stop file present at exit -> not restarted, marker logged',
              code == 5 and 'serve.ps1: not restarting: [stop.ps1] stop requested 2026-01-01T00:00:00' in log
              and 'restart 1' not in log, f'{code}\n{log}')

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        with open(os.path.join(root, 'bin', 'stub-plan.txt'), 'w') as f:
            f.write('exit:0\n' + 'exit:1\n' * 10)
        code, log, starts = run_serve(root, port, timeout=30)
        check('serve: stub exits 0 -> serve exits 0, no restart', code == 0 and starts == 1
              and 'serve.ps1: restart' not in log, f'{code} {starts}\n{log}')

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        serve = os.path.join(root, 'scripts', 'serve.ps1')
        log_path = os.path.join(root, 'logs', 'llama-server.log')
        with open(os.path.join(root, 'bin', 'stub-plan.txt'), 'w') as f:
            f.write('exit:1\nexit:0\n')
        p = subprocess.Popen([PWSH, '-NoProfile', '-File', serve, '-Port', str(port), '-LogFile', log_path,
                              '-RestartDelaySec', '5'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log, deadline = '', time.time() + 60
        while time.time() < deadline and 'serve.ps1: restart 1 of' not in log:
            time.sleep(0.1)
            if os.path.exists(log_path):
                with open(log_path, encoding='utf-8', errors='replace') as f:
                    log = f.read()
        time.sleep(1)
        with open(os.path.join(root, 'logs', f'.stop-requested-{port}'), 'w') as f:
            f.write('[stop.ps1] stop requested 2026-01-01T00:00:01\n')
        t0 = time.time()
        code = p.wait(timeout=30)
        elapsed = time.time() - t0
        with open(log_path, encoding='utf-8', errors='replace') as f:
            log = f.read()
        with open(os.path.join(root, 'bin', 'stub-args.log')) as f:
            starts = len(f.read().splitlines())
        check('serve: stop file 1 s into a 5 s restart wait -> no restart, marker within 3 s',
              elapsed < 3 and starts == 1
              and 'not restarting (during the restart wait): [stop.ps1] stop requested 2026-01-01T00:00:01' in log,
              f'{code} {elapsed:.1f}s {starts}\n{log}')

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        with open(os.path.join(root, 'bin', 'stub-plan.txt'), 'w') as f:
            f.write('exit:0\n')
        env = dict(os.environ, LLAMA_ARG_TOOLS='all', LLAMA_ARG_HOST='0.0.0.0', LLAMA_ARG_THREADS='4')
        code, log, starts = run_serve(root, port, env=env)
        with open(os.path.join(root, 'bin', 'stub-env.log')) as f:
            seen = f.read()
        check('serve: LLAMA_ARG_TOOLS/HOST removed before launch (LLAMA_ARG_THREADS kept), one log line',
              code == 0 and 'LLAMA_ARG_TOOLS' not in seen and 'LLAMA_ARG_HOST' not in seen
              and 'LLAMA_ARG_THREADS=4' in seen and log.count('serve.ps1: cleared 2 llama-server env overrides') == 1,
              f'{code}\n{seen}\n{log}')

    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        serve = os.path.join(root, 'scripts', 'serve.ps1')
        log_path = os.path.join(root, 'logs', 'llama-server.log')
        with open(os.path.join(root, 'bin', 'stub-plan.txt'), 'w') as f:
            f.write('exit:0\nexit:0\n')
        # The first run is in-process (&); the child, started from the same pwsh after it
        # returns, gets the port's mutex only if the first run released it.
        rc, out, err = pwsh(f"& '{serve}' -Port {port} -LogFile '{log_path}' -RestartDelaySec 0; \"FIRST=$LASTEXITCODE\"; "
                            f"& '{PWSH}' -NoProfile -File '{serve}' -Port {port} -LogFile '{log_path}' "
                            "-RestartDelaySec 0; \"SECOND=$LASTEXITCODE\"")
        check('serve: in-process run releases the port mutex; a child on the same port then starts',
              'FIRST=0' in out and 'SECOND=0' in out and 'another serve.ps1' not in out + err, out + err)


def test_stop_marker():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        stop = os.path.join(root, 'scripts', 'stop.ps1')
        sport = free_port()
        r = subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(sport), '-Reason', 'test'],
                           capture_output=True, text=True, timeout=60)
        with open(os.path.join(root, 'logs', 'llama-server.log')) as f:
            log = f.read()
        with open(os.path.join(root, 'logs', f'.stop-requested-{sport}')) as f:
            sentinel = f.read()
        check('stop: nothing listening -> marker in log and stop file',
              r.returncode == 0 and log.startswith('[stop.ps1] stop requested ') and '(test)' in log
              and sentinel == log, r.stdout + r.stderr + log + sentinel)
        r = subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(free_port()), '-WhatIf'],
                           capture_output=True, text=True, timeout=60)
        with open(os.path.join(root, 'logs', 'llama-server.log')) as f:
            check('stop: -WhatIf writes nothing', f.read() == log, r.stdout)
        r = subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(sport), '-Reason',
                            'line one\nline two\x07 three\x85four \r\n'],
                           capture_output=True, text=True, timeout=60)
        with open(os.path.join(root, 'logs', 'llama-server.log')) as f:
            added = f.read()[len(log):]
        with open(os.path.join(root, 'logs', f'.stop-requested-{sport}')) as f:
            sentinel = f.read()
        check('stop: -Reason with a newline -> one marker line in log and stop file',
              added.count('\n') == 1 and added.rstrip('\n').endswith('(line one line two three four)')
              and sentinel == added, repr(added) + repr(sentinel) + r.stdout + r.stderr)
        for reason in ('watchdog: spoof', ' Watchdog: spoof'):
            r = subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(sport), '-Reason', reason],
                               capture_output=True, text=True, timeout=60)
            with open(os.path.join(root, 'logs', f'.stop-requested-{sport}')) as f:
                after = f.read()
            check(f'stop: -Reason {reason!r} without -FromWatchdog refused, nothing written',
                  r.returncode != 0 and 'may not start with' in r.stdout + r.stderr and after == sentinel,
                  r.stdout + r.stderr + after)


def test_stop_stub(stub_exe):
    """stop.ps1 against the stub llama-server on a free port (never 8080): the log keeps what
    was in it, carries the "stop requested" marker when nothing held it, and ALWAYS ends with
    "[stop.ps1] stopped PID <pid> (llama-server) <timestamp> (<reason>)", written after the
    stub exited. The second case gives the stub the log as its stdout, as serve.ps1's
    redirect does; on this machine that handle does not block an append (measured
    2026-11-05), so the held case is checked for the last line only."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, stub_exe)
        exe = os.path.join(root, 'bin', 'llama-server.exe')
        stop = os.path.join(root, 'scripts', 'stop.ps1')
        log = os.path.join(root, 'logs', 'llama-server.log')
        serving = os.path.join(root, 'bin', 'stub-serving.txt')
        for held in (False, True):
            name = 'log held as the stub stdout' if held else 'nothing holds the log'
            port = free_port()
            while port == 8080:
                port = free_port()
            with open(log, 'w') as f:
                f.write('stub output line\n')
            if os.path.exists(serving):
                os.remove(serving)
            out = open(log, 'a') if held else subprocess.DEVNULL
            p = subprocess.Popen([exe, '--port', str(port)], stdout=out, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if os.path.exists(serving) or p.poll() is not None:
                        break
                    time.sleep(0.1)
                r = subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(port),
                                    '-Reason', 'test'], capture_output=True, text=True, timeout=90)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                with open(log) as f:
                    lines = f.read().splitlines()
                last = re.fullmatch(rf'\[stop\.ps1\] stopped PID {p.pid} \(llama-server\) '
                                    r'\d{4}-\d\d-\d\dT\S+ \(test\)', lines[-1] if lines else '')
                marker = [i for i, x in enumerate(lines)
                          if x.startswith('[stop.ps1] stop requested ')]
                check(f'stop: stub stopped ({name}) -> "stopped PID" is the last log line',
                      r.returncode == 0 and p.poll() is not None
                      and lines[:1] == ['stub output line'] and bool(last)
                      and (held or marker == [len(lines) - 2]),
                      f'{r.stdout}{r.stderr}{lines}')
            finally:
                if p.poll() is None:            # stop.ps1 failed: the stub's own exit file
                    with open(os.path.join(root, 'bin', 'stub-exit.txt'), 'w') as f:
                        f.write('0')
                    p.wait(timeout=10)
                if held:
                    out.close()


def test_watchdog(port):
    """Health from the Python stub (503 = failing). stop.ps1 refuses the stub's port owner
    (python, not llama-server), so no process is stopped."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        wd = os.path.join(root, 'scripts', 'watchdog.ps1')
        wlog = os.path.join(root, 'logs', 'watchdog.log')
        sentinel = os.path.join(root, 'logs', f'.stop-requested-{port}')
        fake = "{ param($n) \"fake start $n\" }"

        def run(polls):
            if os.path.exists(wlog):
                os.remove(wlog)
            rc, out, err = pwsh(f"& '{wd}' -Port {port} -IntervalSec 0 -TimeoutSec 5 -MaxPolls {polls} "
                                f"-TaskName 'LIS-test-no-such-task' -StartCommand {fake}", timeout=180)
            with open(wlog) as f:
                return rc, f.read(), out + err

        Stub.health_status = 200
        rc, log, out = run(3)
        check('watchdog: healthy -> no failure, no restart',
              rc == 0 and 'health failed' not in log and 'restart 1 of' not in log and log.count('\n') == 1, log + out)
        Stub.health_status = 503
        rc, log, out = run(13)
        check('watchdog: 3 failures -> restart; 3 per hour, then refuses once',
              log.count('fake start LIS-test-no-such-task') == 3 and 'restart 3 of 3' in log
              and log.count('health failed (1 of 3)') == 4
              and log.count('not restarting: 3 restarts in the last hour') == 1, log + out)
        check('watchdog: restart runs stop.ps1 (refused here: not llama-server)',
              'stop.ps1 failed:' in log and 'not llama-server' in log, log)
        with open(sentinel, 'w') as f:
            f.write('[stop.ps1] stop requested\n')
        rc, log, out = run(6)
        check('watchdog: stop file present -> paused, no polls, no restart',
              log.count('paused:') == 1 and 'health failed' not in log and 'fake start' not in log, log + out)
        Stub.health_status = 200

    # Its own stop requests: on a port with no listener stop.ps1 writes one each restart.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        wd = os.path.join(root, 'scripts', 'watchdog.ps1')
        wlog = os.path.join(root, 'logs', 'watchdog.log')
        dead = free_port()
        own = os.path.join(root, 'logs', f'.stop-requested-{dead}')

        def run_dead(start):
            rc, out, err = pwsh(f"& '{wd}' -Port {dead} -IntervalSec 0 -TimeoutSec 2 -FailThreshold 1 -MaxPolls 3 "
                                f"-MaxRestartsPerHour 5 -TaskName 'LIS-test-no-such-task' -StartCommand {start}",
                                timeout=180)
            with open(wlog) as f:
                log = f.read()
            os.remove(wlog)
            return log, out + err

        log, out = run_dead("{ param($n) throw 'fake start failure' }")
        check('watchdog: start throws -> own stop request cleared, next polls run, budget counted',
              not os.path.exists(own) and log.count('start failed, clearing own stop request') == 3
              and 'restart 3 of 5' in log and 'paused' not in log, log + out)
        log, out = run_dead(fake)
        mark = ''
        if os.path.exists(own):
            with open(own) as f:
                mark = f.read()
        check('watchdog: own stop request (start ok, serve not up) never pauses it',
              '(watchdog: 1 failed health polls)' in mark and 'restart 3 of 5' in log and 'paused' not in log
              and 'clearing own' not in log, mark + log + out)
        # An operator's stop.ps1 whose reason only mentions the watchdog is not its own.
        stop = os.path.join(root, 'scripts', 'stop.ps1')
        subprocess.run([PWSH, '-NoProfile', '-File', stop, '-Port', str(dead), '-Reason', 'manual, watchdog: spoof'],
                       capture_output=True, text=True, timeout=60)
        log, out = run_dead(fake)
        check('watchdog: operator stop request mentioning "watchdog:" -> paused, no restart',
              log.count('paused:') == 1 and 'restart 1 of' not in log and 'health failed' not in log, log + out)

    # A log write that fails (the start command turns the log into a directory) ends a
    # poll, never the watchdog: the stub sees all 4 health polls.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        wd = os.path.join(root, 'scripts', 'watchdog.ps1')
        wlog = os.path.join(root, 'logs', 'watchdog.log')
        flip = ("{ param($n) Remove-Item -LiteralPath '" + wlog + "'; New-Item -ItemType Directory -Path '"
                + wlog + "' | Out-Null }")
        Stub.health_status, Stub.hits = 503, 0
        rc, out, err = pwsh(f"& '{wd}' -Port {port} -IntervalSec 0 -TimeoutSec 5 -FailThreshold 1 -MaxPolls 4 "
                            f"-MaxRestartsPerHour 5 -TaskName 'LIS-test-no-such-task' -StartCommand {flip}", timeout=180)
        check('watchdog: failed log write -> poll error on stderr, all 4 polls run',
              rc == 0 and Stub.hits == 4 and 'watchdog: poll ' in err, f'{rc} {Stub.hits}\n{out}{err}')
        Stub.health_status = 200


# The session supervisor of scripts/claude-local.ps1 (ledger R-W2, T-5) against a stub
# claude: LIS_CLAUDE_EXE names it (the wrapper refuses a path outside %TEMP%). The stub
# counts its calls in calls.txt, records each call's arguments and LIS_* env, prints a
# stream-json init line and exits as plan.txt says for that call: 'exit:RC', 'thrash:RC'
# (the thrash message in a stdout result record, as the live run of 2026-11-04 printed it),
# 'thrash-err:RC' (the message on stderr), 'quote:RC' (the message only in a tool result
# line on stdout), 'maxturns:RC' (a result record with subtype error_max_turns) or
# 'badmax:RC' (that record cut short, so it does not parse) or 'casekeys:RC' (subtype
# success, permission_denials holding a tool_input with keys Path and path and a nested
# "subtype":"error_max_turns": only a parse reads success). The result record keeps
# Claude Code's key order, "type" near the end. It talks to no server. An optional argument
# is a wrapper file to test instead (used to prove that wrapper mutants go red).
WRAPPER = os.path.abspath(sys.argv.pop(1)) if len(sys.argv) > 1 \
    else os.path.join(REPO, 'scripts', 'claude-local.ps1')
THRASH = ('Autocompact is thrashing: the context refilled to the limit within 3 turns of the '
          'previous compact, 3 times in a row. Try reading in smaller chunks, or use /clear to '
          'start fresh.')
STUB_CLAUDE_CS = r'''
using System; using System.IO; using System.Text;
class Claude {
  static int Main(string[] a) {
    string dir = AppDomain.CurrentDomain.BaseDirectory, cf = Path.Combine(dir, "calls.txt");
    int n = File.Exists(cf) ? int.Parse(File.ReadAllText(cf).Trim()) + 1 : 1;
    File.WriteAllText(cf, n.ToString());
    File.WriteAllText(Path.Combine(dir, "args-" + n + ".txt"), string.Join("\0", a),
                      new UTF8Encoding(false));
    int si = Array.IndexOf(a, "--settings");
    if (si >= 0 && si + 1 < a.Length)
      File.Copy(a[si + 1], Path.Combine(dir, "settings-" + n + ".json"), true);
    string env = "";
    foreach (string k in new[] { "LIS_RELAUNCH", "LIS_RELAUNCH_RC", "LIS_FACTS_FILE",
                                 "LIS_SESSION_START" })
      env += k + "=" + Environment.GetEnvironmentVariable(k) + "\n";
    File.WriteAllText(Path.Combine(dir, "env-" + n + ".txt"), env);
    string[] plan = File.ReadAllLines(Path.Combine(dir, "plan.txt"));
    string mode = plan[Math.Min(n, plan.Length) - 1].Trim();
    int rc = int.Parse(mode.Substring(mode.IndexOf(':') + 1));
    var o = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
    var e = new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false));
    o.NewLine = e.NewLine = "\n"; o.AutoFlush = e.AutoFlush = true;
    o.WriteLine("{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"stub-" + n
                + "\",\"note\":\"\u26a0 caf\u00e9\"}");
    string msg = File.ReadAllText(Path.Combine(dir, "thrash.txt")).Trim();
    if (mode.StartsWith("thrash-err:")) e.WriteLine(msg);
    if (mode.StartsWith("quote:"))
      o.WriteLine("{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\","
                  + "\"content\":\"grep hit: " + msg + "\"}]}}");
    // The result record in Claude Code's key order (live 2026-11-04: duration_api_ms first,
    // type near the end), values shortened. badmax: the same record cut short (no closing
    // brace), so it does not parse.
    bool max = mode.StartsWith("maxturns:") || mode.StartsWith("badmax:");
    // casekeys: valid JSON a plain ConvertFrom-Json refuses (keys differing only by case); the
    // nested subtype key makes the substring fallback answer differently from a parse.
    string casekeys = "[{\"tool_name\":\"Bash\",\"tool_input\":{\"Path\":\"a\",\"path\":\"b\","
      + "\"subtype\":\"error_max_turns\"}}]";
    string res = "{\"duration_api_ms\":1,\"stop_reason\":\"stop_sequence\",\"session_id\":\"stub-"
      + n + "-r\",\"total_cost_usd\":0,\"usage\":{\"input_tokens\":1,\"output_tokens\":1},"
      + "\"permission_denials\":" + (mode.StartsWith("casekeys:") ? casekeys : "[]")
      + ",\"terminal_reason\":\"completed\",\"is_error\":false,"
      + "\"num_turns\":1,\"subtype\":\"" + (max ? "error_max_turns" : "success")
      + "\",\"api_error\":null,\"result\":\"" + (mode.StartsWith("thrash:") ? msg : "stub " + n)
      + "\",\"type\":\"result\",\"duration_ms\":1";
    o.WriteLine(mode.StartsWith("badmax:") ? res : res + "}");
    e.WriteLine("stub stderr " + n + " \u26a0");
    return rc;
  }
}
'''
PROMPT = 'Fix the failing tests; the facts file is your record.'


def relaunch_prefix(n, rc, facts):
    return (f'Relaunch {n} after the previous session exited (rc {rc}). The facts file {facts} '
            'in the working directory holds the progress so far: run the test command first and '
            'append a CHECK line before any edit, then continue from its last NEXT line.\n')


def remove_hook_copies(err):
    """The per-run hook copies the banner names (kept after exit by design), read-only."""
    for d in set(re.findall(r'(?m)^claude-local: hook copies: (\S+) ', err)):
        if os.path.isdir(d) and os.path.dirname(d) == os.path.normpath(os.environ['TEMP']) \
                and os.path.basename(d).startswith('lis-hooks-'):
            for f in os.listdir(d):
                os.chmod(os.path.join(d, f), stat.S_IWRITE)
            shutil.rmtree(d)


def run_supervised(stub_dir, args, plan, exe=None, keep=False):
    """The wrapper with LIS_CLAUDE_EXE set, from a scratch working directory. Returns rc,
    stdout bytes, stderr text, the calls made and per call its arguments and env lines.
    The hook copies the run made are removed unless keep (the caller removes them)."""
    for f in os.listdir(stub_dir):
        if f.startswith(('calls', 'args-', 'env-', 'settings-')):
            os.remove(os.path.join(stub_dir, f))
    with open(os.path.join(stub_dir, 'plan.txt'), 'w') as f:
        f.write('\n'.join(plan) + '\n')
    work = os.path.join(stub_dir, 'work')
    os.makedirs(work, exist_ok=True)
    env = dict(os.environ)  # a copy for the child
    env['LIS_CLAUDE_EXE'] = exe or os.path.join(stub_dir, 'claude-stub.exe')
    for k in ('LIS_RELAUNCH', 'LIS_RELAUNCH_RC'):
        env.pop(k, None)
    r = subprocess.run([PWSH, '-NoProfile', '-File', WRAPPER] + args, cwd=work, env=env,
                       capture_output=True, timeout=120)
    err = r.stderr.decode('utf-8', errors='replace')
    # The longrun banner names the facts-inject log the wrapper made in %TEMP%: remove it.
    for p in set(re.findall(r'facts inject log: (\S+\.log)', err)):
        if os.path.isfile(p) and os.path.dirname(p) == os.path.normpath(os.environ['TEMP']):
            os.remove(p)
    if not keep:
        remove_hook_copies(err)
    calls = []
    for n in range(1, 10):
        a = os.path.join(stub_dir, f'args-{n}.txt')
        if not os.path.exists(a):
            break
        with open(a, encoding='utf-8') as f:
            argv = f.read().split('\0')
        with open(os.path.join(stub_dir, f'env-{n}.txt')) as f:
            envs = dict(x.split('=', 1) for x in f.read().splitlines())
        calls.append((argv, envs))
    return r.returncode, r.stdout, err, calls


def test_relaunch():
    if not os.path.exists(CSC):
        print(f'skip  supervisor cases: {CSC} not found')
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'claude-stub.cs')
        with open(src, 'w') as f:
            f.write(STUB_CLAUDE_CS)
        subprocess.run([CSC, '-nologo', '-out:' + os.path.join(tmp, 'claude-stub.exe'), src],
                       check=True, capture_output=True, cwd=tmp)
        with open(os.path.join(tmp, 'thrash.txt'), 'w') as f:
            f.write(THRASH)
        longrun = ['-LisTask', 'longrun', '-p', PROMPT, '--output-format', 'stream-json']

        def lines(err):
            return re.findall(r'(?m)^claude-local: relaunch n=.*$', err.replace('\r', ''))

        dbg = ['--debug-file', 'run.debug.log']
        rc, out, err, calls = run_supervised(tmp, longrun + dbg, ['thrash:1', 'exit:0'])
        facts = (re.findall(r'lis-facts-\d{8}-\d{6}\.md', err) or ['?'])[0]
        check('supervisor: thrash rc 1 -> one relaunch, logged with reason=thrash, exit 0',
              rc == 0 and len(calls) == 2
              and lines(err) == ['claude-local: relaunch n=1 rc=1 reason=thrash'], err)
        check('supervisor: the stub ran instead of claude, no server preflight',
              'server preflight skipped' in err and 'claude-local: relaunch: max 1' in err, err)
        if len(calls) == 2:
            (a1, e1), (a2, e2) = calls
            i = a1.index(PROMPT) if PROMPT in a1 else -1
            check('supervisor: LIS_RELAUNCH unset in session 1, 1 and rc 1 in the relaunch',
                  e1['LIS_RELAUNCH'] == '' and e1['LIS_RELAUNCH_RC'] == ''
                  and e2['LIS_RELAUNCH'] == '1' and e2['LIS_RELAUNCH_RC'] == '1'
                  and e1['LIS_FACTS_FILE'] == e2['LIS_FACTS_FILE'] == facts, f'{e1} {e2}')
            check('supervisor: LIS_SESSION_START is ISO UTC and the relaunch keeps it',
                  bool(SESSION_START.match(e1['LIS_SESSION_START']))
                  and e1['LIS_SESSION_START'] == e2['LIS_SESSION_START'], f'{e1} {e2}')
            check('supervisor: both sessions launch with --setting-sources project,local',
                  all(a[a.index('--setting-sources') + 1] == 'project,local'
                      for a in (a1, a2) if '--setting-sources' in a)
                  and '--setting-sources' in a1 and '--setting-sources' in a2, f'{a1}')
            check('supervisor: the relaunch prompt is the prefix line plus the same prompt',
                  i >= 0 and a2[i] == relaunch_prefix(1, 1, facts) + PROMPT, repr(a2[i:i + 1]))
            d = a1.index('--debug-file') + 1 if '--debug-file' in a1 else -1
            check('supervisor: the relaunch gets its own debug file, base.debug.2.log',
                  d > 0 and a1[d] == 'run.debug.log' and a2[d] == 'run.debug.2.log',
                  f'{a1}\n{a2}')
            keep = [k for k in range(len(a1)) if k not in (i, d)]
            check('supervisor: the relaunch keeps every other argument; no --continue/--resume',
                  i >= 0 and len(a1) == len(a2) and [a1[k] for k in keep] == [a2[k] for k in keep]
                  and not {'--continue', '--resume', '-c', '-r'} & set(a2), f'{a1}\n{a2}')
        inits = re.findall(rb'"session_id":"(stub-\d)"', out)
        check('supervisor: stdout keeps both sessions in order, UTF-8 intact, LF ends',
              inits == [b'stub-1', b'stub-2'] and out.count('\u26a0 caf\u00e9'.encode()) == 2
              and b'\r\n' not in out and THRASH.encode() in out, repr(out[:400]))
        check('supervisor: stderr of both sessions passes through, UTF-8 intact',
              'stub stderr 1 \u26a0' in err and 'stub stderr 2 \u26a0' in err, err)

        rc, _, err, calls = run_supervised(tmp, longrun, ['exit:1', 'exit:3'])
        check('supervisor: rc 1 without the thrash message -> reason=exit; max 1 holds; '
              'exit = the last rc', rc == 3 and len(calls) == 2
              and lines(err) == ['claude-local: relaunch n=1 rc=1 reason=exit'], err)
        rc, _, err, calls = run_supervised(tmp, ['-LisRelaunchMax', '2'] + longrun,
                                           ['exit:1', 'thrash-err:2', 'exit:0'])
        check('supervisor: -LisRelaunchMax 2 -> two relaunches; thrash on stderr is a thrash',
              rc == 0 and len(calls) == 3 and lines(err) == [
                  'claude-local: relaunch n=1 rc=1 reason=exit',
                  'claude-local: relaunch n=2 rc=2 reason=thrash'], err)
        if len(calls) == 3:
            name = calls[2][1]['LIS_FACTS_FILE']  # each run has its own facts file stamp
            check('supervisor: the second relaunch prefixes the original prompt once',
                  relaunch_prefix(2, 2, name) + PROMPT in calls[2][0]
                  and calls[2][1]['LIS_RELAUNCH'] == '2', repr(calls[2][0][-3:]))
        rc, _, err, calls = run_supervised(tmp, longrun, ['quote:1', 'exit:0'])
        check('supervisor: the message only in a tool result on stdout -> reason=exit',
              rc == 0 and len(calls) == 2
              and lines(err) == ['claude-local: relaunch n=1 rc=1 reason=exit'], err)
        rc, _, err, calls = run_supervised(tmp, longrun, ['maxturns:1', 'exit:0'])
        check('supervisor: result subtype error_max_turns -> no relaunch, logged, rc 1',
              rc == 1 and len(calls) == 1 and not lines(err)
              and 'claude-local: relaunch skipped rc=1 reason=max_turns' in err, err)
        rc, _, err, calls = run_supervised(tmp, longrun, ['casekeys:1', 'exit:0'])
        check('supervisor: a record with keys differing by case parses (subtype success, '
              'not the fallback) -> relaunch reason=exit',
              rc == 0 and len(calls) == 2 and 'reason=max_turns' not in err
              and lines(err) == ['claude-local: relaunch n=1 rc=1 reason=exit'], err)
        rc, _, err, calls = run_supervised(tmp, longrun, ['badmax:1', 'exit:0'])
        check('supervisor: an unparsable error_max_turns record -> no relaunch, logged',
              rc == 1 and len(calls) == 1 and not lines(err)
              and 'claude-local: relaunch skipped rc=1 reason=max_turns' in err, err)
        rc, _, err, calls = run_supervised(tmp, ['-LisRelaunchMax', '0'] + longrun, ['thrash:1'])
        check('supervisor: -LisRelaunchMax 0 -> no relaunch, rc 1',
              rc == 1 and len(calls) == 1 and not lines(err)
              and 'relaunch: off (-LisRelaunchMax 0)' in err, err)
        # A timeout kill: run.ps1 kills the wrapper's whole tree (Kill($true)), so the wrapper
        # cannot relaunch; a claude killed alone exits -1 (TerminateProcess), simulated here.
        rc, _, err, calls = run_supervised(tmp, longrun, ['exit:-1', 'exit:0'])
        check('supervisor: a killed claude (rc -1) -> no relaunch',
              rc in (-1, 0xFFFFFFFF) and len(calls) == 1 and not lines(err), f'{rc} {err}')
        rc, _, err, calls = run_supervised(tmp, longrun, ['exit:0', 'exit:0'])
        check('supervisor: rc 0 -> no relaunch',
              rc == 0 and len(calls) == 1 and not lines(err), err)
        rc, _, err, calls = run_supervised(tmp, ['-p', PROMPT], ['exit:1', 'exit:0'])
        check('supervisor: no -LisTask -> off, no relaunch, rc 1',
              rc == 1 and len(calls) == 1 and not lines(err) and 'profile: none' in err, err)
        # The unsupervised launch line passes the flag too, and -LisUserScope drops it.
        start = calls[0][1].get('LIS_SESSION_START', '') if calls else ''
        check('user scope: an unsupervised launch gets --setting-sources project,local and '
              'LIS_SESSION_START', calls and '--setting-sources' in calls[0][0]
              and calls[0][0][calls[0][0].index('--setting-sources') + 1] == 'project,local'
              and bool(SESSION_START.match(start)), f'{calls} {err}')
        rc, _, err, calls = run_supervised(tmp, ['-LisUserScope', '-p', PROMPT], ['exit:0'])
        check('user scope: -LisUserScope launches without --setting-sources',
              rc == 0 and len(calls) == 1 and '--setting-sources' not in calls[0][0]
              and 'claude-local: user scope: on (-LisUserScope)' in err, f'{calls} {err}')
        rc, _, err, calls = run_supervised(tmp, ['-LisTask', 'longrun'], ['exit:1', 'exit:0'])
        check('supervisor: longrun without -p <prompt> -> off, no relaunch',
              rc == 1 and len(calls) == 1 and not lines(err)
              and 'relaunch: off (no -p <prompt> to relaunch)' in err, err)
        rc, _, err, calls = run_supervised(tmp, ['-LisRelaunchMax', '1', '-p', PROMPT], ['exit:1'])
        check('supervisor: -LisRelaunchMax 1 without longrun -> refused, nothing launched',
              rc != 0 and not calls and 'needs -LisTask longrun' in err, err)
        rc, _, err, calls = run_supervised(tmp, longrun, ['exit:1'],
                                           exe=os.path.join(REPO, 'README.md'))
        check('supervisor: LIS_CLAUDE_EXE outside %TEMP% -> refused, nothing launched',
              rc != 0 and not calls and 'is not a file under %TEMP%' in err, err)
        # S-B3: the hooks run from read-only copies in a per-run %TEMP% directory, kept after exit
        rc, _, err, calls = run_supervised(tmp, ['-LisRelaunchMax', '0'] + longrun, ['exit:0'],
                                           keep=True)
        try:
            with open(os.path.join(tmp, 'settings-1.json'), encoding='utf-8') as f:
                cfg = json.load(f)
            d = check_hook_settings('stub longrun', cfg, GUARD_HOOKS + ['facts-inject.py'], err)
            d = d and os.path.normpath(d)
            src = {n: 'scripts/hooks/' + n
                   for n in ('lis-guard.py', 'loop-guard.py', 'facts-inject.py')}
            src['verify-doc.py'] = 'scripts/verify-doc.py'
            names = sorted(os.listdir(d)) if d and os.path.isdir(d) else []
            check('hook copies: the four hook scripts copied, the directory kept after exit',
                  rc == 0 and len(calls) == 1 and names == sorted(src), f'{rc} {names} {err}')
            for n in names:
                fp = os.path.join(d, n)
                with open(fp, 'rb') as f, open(os.path.join(REPO, src[n]), 'rb') as g:
                    same = f.read() == g.read()
                ro = bool(os.stat(fp).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
                check(f'hook copies: {n} read-only and byte-identical to {src[n]}', ro and same,
                      f'{ro} {same}')
            # audit C1: the registered lis-guard (itself a copy) denies a literal command that
            # would unprotect or empty a copy; this asks for the decision, nothing is run
            guard = [(q, rest) for _, q, rest in hook_scripts(cfg) if q.endswith('/lis-guard.py')]
            hd = re.findall(r'"([^"]+)"', guard[0][1]) if guard else []
            for n in names if guard else []:
                fp = os.path.join(d, n).replace(os.sep, '/')
                got = []
                for c in (f'chmod +w "{fp}"', f'cp /dev/null "{fp}"', f'echo > "{fp}"'):
                    r = subprocess.run([sys.executable, '-I', guard[0][0], '--hooks-dir'] + hd,
                                       capture_output=True, text=True, timeout=60,
                                       input=json.dumps({'tool_name': 'Bash', 'cwd': REPO,
                                                         'tool_input': {'command': c}}))
                    h = json.loads(r.stdout)['hookSpecificOutput'] if r.stdout.strip() else {}
                    got.append(h.get('permissionDecision'))
                check(f'hook copies: the registered guard denies chmod +w, cp, echo > of {n}',
                      got == ['deny'] * 3, f'{got}')
        except (OSError, ValueError, KeyError) as e:
            check('hook copies: the stub saw the per-run settings', False, f'{e} {err}')
        finally:
            remove_hook_copies(err)
        rc, out, err, calls = run_supervised(tmp, longrun + ['-LisPrintArgs'], ['exit:1'])
        hooks = []
        try:
            text = out.decode('utf-8')
            marker = 'settings JSON (the --settings file):'
            hooks = json.loads(text[text.index(marker) + len(marker):])['hooks']['SessionStart']
        except (ValueError, KeyError) as e:
            err += f' {e}'
        check('supervisor: -LisPrintArgs launches nothing; facts-inject at compact and startup',
              rc == 0 and not calls and 'claude-local: relaunch: max 1' in err
              and [(h['matcher'], 'facts-inject.py' in h['hooks'][0]['command']) for h in hooks]
              == [('compact', True), ('startup', True)], f'{hooks} {err}')


def main():
    if not PWSH:
        print('FAIL  pwsh not found')
        return 1
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        test_wrapper(port)
        test_wrapper_rules()
        test_wrapper_web_and_hooks()
        test_guard_copy()
        test_key_resolvers()
        test_fixed_flags()
        test_restart_window()
        test_vram_free()
        test_stop_marker()
        test_watchdog(port)
        test_relaunch()
        if os.path.exists(CSC):
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, 'stub.cs')
                with open(src, 'w') as f:
                    f.write(STUB_CS)
                exe = os.path.join(tmp, 'llama-server.exe')
                subprocess.run([CSC, '-nologo', '-out:' + exe, src], check=True, capture_output=True, cwd=tmp)
                test_serve_loop(exe)
                test_stop_stub(exe)
        else:
            print(f'skip  serve restart-loop cases: {CSC} not found')
    finally:
        srv.shutdown()
    print(f'{len(FAILS)} failed' if FAILS else 'all passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
