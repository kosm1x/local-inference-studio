"""Tests for scripts/serve.ps1 (restart loop, fixed flags, per-start key), scripts/stop.ps1
(stop marker), scripts/watchdog.ps1 (poll and restart decisions), the server preflight
and key fallback of scripts/claude-local.ps1, its absolute path rules (-LisPrintArgs), and the logs/api-key resolver lines shared by
the smoke scripts and the benches.
Stop files are port-scoped: logs/.stop-requested-<port>.
Run: python -I scripts/tests/resilience_test.py

Everything runs on copies of the scripts in a temp "repo" whose bin/llama-server.exe is a
stub compiled from STUB_CS with the .NET Framework csc.exe (those cases are skipped when it
is missing). The stub never binds 8080 and ends on its own (exit plan or exit file); no
case stops a process. HTTP endpoints are a Python stub on a free loopback port. The live
server, the scheduled tasks and claude are never touched. Exit 0 = all pass.
"""
import http.server
import json
import os
import shutil
import socket
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
    open(os.path.join(root, 'models/qwen3.8-27b-uncensored/Qwen3.8-27B-Uncensored-IQ3_XXS.gguf'), 'w').close()
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
        test_key_resolvers()
        test_fixed_flags()
        test_restart_window()
        test_stop_marker()
        test_watchdog(port)
        if os.path.exists(CSC):
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, 'stub.cs')
                with open(src, 'w') as f:
                    f.write(STUB_CS)
                exe = os.path.join(tmp, 'llama-server.exe')
                subprocess.run([CSC, '-nologo', '-out:' + exe, src], check=True, capture_output=True, cwd=tmp)
                test_serve_loop(exe)
        else:
            print(f'skip  serve restart-loop cases: {CSC} not found')
    finally:
        srv.shutdown()
    print(f'{len(FAILS)} failed' if FAILS else 'all passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
