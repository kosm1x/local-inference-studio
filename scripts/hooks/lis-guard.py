"""lis-guard: PreToolUse hook (matcher Bash) for local Claude Code sessions, ruling 15.

Decision order for one Bash command:
  (a) a critical write or delete, a kill shape, a credential path or a network upload
      anywhere in it, including inside powershell/pwsh -Command (and -EncodedCommand),
      bash/sh -c, cmd /c, python -c, node -e, heredoc and here-string bodies fed to an
      interpreter, wsl ... -- and ssh payloads                      -> deny
  (b) a script run (bash|sh <file>, powershell|pwsh -File <file>, python|py|node
      [options] <file>): a deny hit on any line -> deny quoting that line; every line
      read-only -> allow (shell and PowerShell only; python/node files are never
      allowed); unreadable, over the read cap, or a line that is neither
      -> no decision
  (c) every segment passes the read-only grammar                   -> allow
  (d) anything else: no output, exit 0 -> no decision.

"No decision" is NOT "goes to the classifier": it hands the call back to Claude Code's
own permission rules (deny > ask > allow), and only a call no rule decides reaches the
auto-mode classifier.

The read-only grammar is a per-verb allow-list of argument shapes, not an "any
arguments" pass: a verb runs only with options from its own safe set, and an unknown
option gives no decision. This scanner is the judge of record for script execution and
interpreter payloads (operator ruling, 2026-10-25): the auto-mode classifier never sees
a script's content or a tool's output, so it cannot review them.

Static text analysis only: it never runs the command or the script. Stdlib only;
run with `python -I`. Over-matching is deliberate: a critical verb inside a quoted
string (a commit message saying "rm -rf") is denied too.
"""
import base64
import fnmatch
import functools
import glob
import itertools
import json
import os
import posixpath
import re
import stat
import shlex
import sys

NOT_RETRYABLE = 'critical write; not retryable; report it to the operator instead'
REWRITE_HIT = 'unexpanded shell metacharacter in a curl file argument'
REWRITE_SUFFIX = ('shell or curl would rewrite this argument, so it is not judged; use a plain '
                  'literal path; not retryable; report it to the operator instead')


def deny_reason(hit):
    return f'lis-guard: {hit}; {REWRITE_SUFFIX}.' if hit == REWRITE_HIT else f'lis-guard: {hit} matched; {NOT_RETRYABLE}.'
MAX_INPUT = 32_768          # inputs above this get no decision (ReDoS guard, W1)
# Script files exempt from the content scan (no decision, as before payload scanning):
# this hook's own tests (lis-guard_test.py and lis-guard_property_test.py) and three tests
# under scripts/tests/ (the two security tests and resilience_test.py, ruling 2026-10-30),
# whose cases quote denied shapes, and this hook itself, and bench/ladder/run.ps1, whose
# -DryRun deletes its own work tree under -WorkRoot (audit A4 R3). The per-run settings
# deny all seven to Edit and CRITICAL_PATH protects them from shell writes.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
SELF_TEST = os.path.normcase(os.path.realpath(os.path.join(_HOOK_DIR, 'tests', 'lis-guard_test.py')))
EXEMPT_SCRIPTS = {SELF_TEST, os.path.normcase(os.path.realpath(os.path.join(
    _HOOK_DIR, 'tests', 'lis-guard_property_test.py')))} | {
    os.path.normcase(os.path.realpath(os.path.join(_HOOK_DIR, '..', 'tests', n)))
    for n in ('claude_settings_test.py', 'install_verify_test.py', 'resilience_test.py')} | {
    os.path.normcase(os.path.realpath(os.path.abspath(__file__))),   # the hook quotes every shape (A3 W8)
    os.path.normcase(os.path.realpath(os.path.join(_HOOK_DIR, '..', '..', 'bench', 'ladder', 'run.ps1')))}
REPO_ROOT = os.path.normcase(os.path.realpath(os.path.join(_HOOK_DIR, '..', '..')))
SCRIPT_CAP = 200_000        # scripts above this get no decision, never allow (C5)
_SPAN = r'[^;|\n]{0,400}'   # bounded span, replaces unbounded [^;|]* (W1)

# (a) critical verbs, searched over the raw command text so nested payloads are covered.
_GIT = r'(?<![\w-])git(?:\s+(?:-C|-c)\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+'
CRITICAL_VERBS = [
    (r'(?i)\bRemove-Item\b', 'Remove-Item'),
    (r'(?<![\w-])rm\s+(?:-\w*[rRf]\w*|--recursive|--force)', 'rm -r/-f'),
    (r'(?i)(?<![\w-])(?:del|erase)\s+(?:/\w+\s+)*/s\b', 'del /s'),
    (r'(?i)(?<![\w-])(?:rmdir|rd)\s+(?:/\w+\s+)*/s\b', 'rmdir /s'),
    (r'(?i)\b(?:Set|New|Remove)-ItemProperty\b' + _SPAN + r'\bHK(?:LM|CU|EY_)', 'registry write'),
    (r'(?i)(?<![\w-])reg(?:\.exe)?\s+(?:add|delete|import|load|restore)\b', 'reg add/delete'),
    (r'(?i)\b(?:Stop|Set|Restart)-Service\b', 'Stop-/Set-Service'),
    (r'(?i)(?<![\w.-])sc(?:\.exe)?\s+(?:stop|start|delete|config|create|failure)\b', 'sc'),
    (r'(?i)\b(?:Register|Unregister)-ScheduledTask\b', 'Register-/Unregister-ScheduledTask'),
    (r'(?i)(?<![\w-])schtasks(?:\.exe)?\s+' + _SPAN + r'/(?:create|delete|change|end)\b', 'schtasks /create|/delete'),
    (r'(?i)(?<![\w-])format(?:\.com)?\s+[a-z]:', 'format'),
    (r'(?i)(?<![\w-])diskpart\b', 'diskpart'),
    (r'(?i)\b(?:Clear-Disk|Remove-Partition|Format-Volume|Initialize-Disk)\b', 'disk cmdlet'),
    (r'(?<![\w-])mkfs(?:\.\w+)?\b', 'mkfs'),
    (r'(?<![\w-])dd\s+' + _SPAN + r'\bof=', 'dd'),
    (r'(?i)(?<![\w-])wsl(?:\.exe)?\s+' + _SPAN + r'--(?:unregister|import)\b', 'wsl --unregister|--import'),
    (r'(?<![\w-])docker\s+(?:(?:container|image|volume|network|system|builder)\s+)?(?:rm|rmi|prune)\b', 'docker rm/rmi/prune'),
    (_GIT + r'push\b[^;|&\n]{0,200}?(?:\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S|\s:\S)', 'git push --force/delete-ref'),
    (_GIT + r'reset\b[^;|&\n]{0,200}--hard\b', 'git reset --hard'),
    (_GIT + r'clean\b', 'git clean'),
    (_GIT + r'rebase\b', 'git rebase'),
    (_GIT + r'branch\b[^;|&\n]{0,200}\s(?:-D|--delete|--force|-f)\b', 'git branch -D/--delete/--force'),
    (_GIT + r'stash\s+(?:drop|clear)\b', 'git stash drop/clear'),
    (_GIT + r'update-ref\s+-d\b', 'git update-ref -d'),
    (_GIT + r'reflog\s+expire\b', 'git reflog expire'),
    (_GIT + r'checkout\s+--\s', 'git checkout --'),
    # uploads that need no host check (security audit B1); curl/wget/PowerShell web
    # uploads are host-checked in critical(), interpreter code in code_critical()
    (_GIT + r'push\b', 'git push'),
    (r'(?<![\w-])docker(?:\.exe)?\s+(?:image\s+)?push\b', 'docker push'),
    (r'(?<![\w-])gh(?:\.exe)?\s+(?:gist\s+(?:create|edit)|release\s+(?:create|upload)|repo\s+create'
     r'|api\b[^;|&\n]{0,300}?(?:\s(?:-X|--method)[\s=]*(?:POST|PUT|PATCH|DELETE)\b|\s-[fF]\s|\s--(?:raw-)?field\b'
     r'|\s--input\b))', 'gh write/upload'),
    (r'(?i)\bSend-MailMessage\b|\.Upload(?:String|File|Data|Values)(?:Async)?\b', 'PowerShell upload'),
    # kill shapes (global rule after the 2026-10-24 incident); kill-guard is a user-scope
    # hook a local session may run without, so the same shapes are denied here
    (r'(?<![\w.-])kill\s+(?:[^;|&\n]{0,200}?\s)?--\s+-', 'kill of a process group'),
    (r'(?<![\w.-])kill\s+(?:-s\s+\w+\s+|-n\s+\w+\s+|-[^\s;|&]+\s+)*(?:-1|0)(?![\w.])', 'kill -1 / kill 0'),
    (r'(?<![\w.-])kill\s+[^;|&\n]{0,200}?[$`]', 'kill of a computed target'),
    (r'(?<![\w.-])(?:pkill|killall5?)\b', 'pkill/killall'),
    (r'(?i)(?<![\w.-])taskkill(?:\.exe)?\b[^;|&\n]{0,200}?\s[/-](?:im|t)\b', 'taskkill /IM or /T'),
    (r'(?i)(?<![\w.-])(?:Stop-Process|spps|kill)\s+[^;|&\n]{0,200}?-(?:Name|ProcessName)\b', 'Stop-Process -Name'),
    (r'(?i)\bGet-Process\b[^;\n]{0,200}\|\s*(?:Stop-Process|spps|kill)\b', 'Get-Process | Stop-Process'),
    (r'(?i)(?<![\w-])wmic\b[^;|&\n]{0,200}\bprocess\b[^;|&\n]{0,200}\b(?:delete|terminate)\b', 'wmic process delete'),
    (_GIT + r'credential\b', 'git credential'),
    (r'(?i)\bbase64\s+(?:-d|--decode|-D)\b[^;&\n]{0,300}\|\s*(?:ba|z|da|k)?sh\b', 'base64 decode piped to a shell'),
    # credential reads (audit B1): the Read tool has deny rules, a Bash cat does not. Any
    # mention denies, in every context: a local, wsl or ssh payload, a script, code.
    (r'(?i)(?:\.credentials\.json\b|(?<![\w-])\.claude\.json\b|huggingface[\\/]+(?:token|stored_tokens)\b'
     r'|\.cache[\\/]+huggingface\b|\.git-credentials\b|(?<![\w-])[._]netrc\b|\.aws[\\/]+[^\s\'"]'
     r'|\.ssh[\\/]+[^\s\'"]|\.docker[\\/]+config\.json\b|github[\s\\]+cli[\\/]|\.config[\\/]+gh\b'
     r'|\.claude[\\/]+(?:settings[\w.-]*\.json|backups\b|history\.jsonl\b|projects[\\/][^\s\'"]*\.jsonl\b)'
     r'|(?:^|(?<=[\s\'"=:/\\(,]))\.env[\w.-]*(?![\w-])'   # the settings' **/.env*
     r'|\.config[\\/]+git[\\/]+credentials\b|(?<![\w-])\.(?:npmrc|pypirc|vault-token)\b'
     r'|\.kube[\\/]+[^\s\'"]|\.gnupg[\\/]+[^\s\'"]|ssh_host_\w+_key\b|microsoft[\\/]+credentials\b'
     r'|\.local[\\/]+share[\\/]+keyrings\b|(?:^|[\\/])etc[\\/]+npmrc\b'
     # more known stores (audit A3 W3; the hook names known stores, it does not find secrets)
     r'|\.azure[\\/]+[^\s\'"]|\.config[\\/]+gcloud\b|(?<![\w-])\.pgpass\b|\.cargo[\\/]+credentials\b'
     r'|\.terraform\.d[\\/]+credentials\b|(?<![\w-])rclone\.conf\b'
     r'|user[\s\\]+data[\\/]+(?:[^\\/\s]+[\\/]+)*?(?:login[\s\\]+data|cookies)\b'
     r'|(?<![\w-])\.(?:bash|zsh|python|node_repl|psql|mysql)_history\b|ConsoleHost_history\.txt\b'
     r'|[\\/]proc[\\/]+[^\s\\/]+[\\/]+environ\b'
     r'|(?<![\w-])gh(?:\.exe)?\s+auth\s+token\b|(?<![\w-])gh(?:\.exe)?\s+auth\s+status\b[^;|&\n]{0,100}\s(?:-t|--show-token)\b'
     r'|\b(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN'
     r'|OPENAI_API_KEY|BRAVE_API_KEY|TAVILY_API_KEY|GH_TOKEN|GITHUB_TOKEN)\b)',
     'credential path'),
    # environment dumps (audit A2 W5/6): the env: drive, .NET and Deno whole-environment reads
    # (audit A5: the Environment provider by name, and -Path:env: / -LiteralPath:env:)
    (r'(?i)(?:(?<![\w$:{-])|(?<=-Path:)|(?<=-LiteralPath:))env:|\bGetEnvironmentVariables\b'
     r'|\bDeno\.env\.toObject\b|(?<![\w-])Environment::|-PSProvider[\s:]+[\'"]?Environment\b', 'environment dump'),
    # more upload and exec channels (audit A2 W5/6)
    (r'(?i)\b(?:Start-BitsTransfer|bitsadmin)\b', 'BITS transfer'),
    (r'(?i)(?<![\w-])git-credential-[\w-]+', 'git credential helper'),
    (r'(?i)(?<![\w-])git\b[^;|&\n]{0,200}?\s-c\s*[\'"]?(?:alias|credential)\.', 'git -c alias/credential'),
    (_GIT + r'config\b[^;|&\n]{0,200}?\b(?:alias|credential)\.', 'git config alias/credential'),
    (_GIT + r'send-email\b', 'git send-email'),
    # a file write under a read-only git verb (audit A4 W2)
    (_GIT + r'(?:log|show|diff|whatchanged)\b[^;|&\n]{0,400}?\s--ou(?:t(?:p(?:ut?)?)?)?(?:=|\s)',
     'git --output file write'),
    # Windows tools aimed at another host or run with credentials (audit A4 W4)
    (r'(?i)(?<![\w.-])(?:systeminfo|tasklist|taskkill|driverquery|getmac|openfiles|schtasks|eventcreate|wmic'
     r'|whoami|gpresult|sc|reg)(?:\.exe)?\b[^;|&\n]{0,300}?\s(?:[/-][UP]\s|[/-](?:node|user|password):)',
     'Windows tool with remote credentials'),
    (r'(?i)(?<![\w.-])(?:systeminfo|tasklist|taskkill|driverquery|getmac|openfiles|schtasks|eventcreate'
     r'|gpresult)(?:\.exe)?\b[^;|&\n]{0,300}?\s[/-]S\s', 'Windows tool aimed at another host'),
    (r'(?i)(?<![\w.-])(?:sc|reg)(?:\.exe)?\s+(?:\w+\s+)?\\\\', 'Windows tool aimed at another host'),
    (r'(?i)\b(?:iex|Invoke-Expression)\b[^;\n]{0,200}\[char\]', 'Invoke-Expression of computed text'),
    # a command reached through Get-Command hides its name from every check (& (gcm git) push)
    (r'(?i)(?<![\w.])[&.]\s*\(\s*(?:Get-Command|gcm)\b|\(\s*(?:Get-Command|gcm)\b[^()\n]{0,200}\)\s*\.\s*Invoke\b',
     'invocation through Get-Command'),
    (r'(?<![\w-])(?:python[\d.]*|py)(?:\.exe)?\s+(?:-\w+\s+)*-m\s+http\.server\b'
     r'(?![^;|&\n]{0,200}(?:--bind|-b)[\s=]+(?:127\.0\.0\.1|localhost|::1)\b)', 'http.server not bound to loopback'),
]
# Credential basenames for glob forms (.cred*.json, .credentials.jso?, id_*): a glob word
# with 3+ literal characters that can match one of these denies (fnmatch, lower case).
CRED_NAMES = ('.credentials.json', '.claude.json', '.git-credentials', '.netrc', '_netrc', '.ssh', '.aws',
              '.env', '.env.local', 'stored_tokens', 'hosts.yml', 'id_rsa', 'id_ed25519', 'id_ecdsa',
              '.npmrc', '.pypirc', '.vault-token', '.kube', '.gnupg', '.docker', '.claude', 'github cli',
              '.azure', 'gcloud', '.pgpass', 'rclone.conf', 'login data', 'cookies')
# Credential directories (audit A2 Critical 1): named as a bare word (any verb: ls, find,
# grep -r, rg, tar, Get-ChildItem, cd ...) they deny, since a recursive reader or a cd
# reaches every file inside. .claude counts bare or with projects/backups/settings*/
# .credentials*; its skills, plugins, agents and commands stay readable.
CRED_DIR = re.compile(
    r'(?i)(?:^|[\\/])(?:\.ssh|\.aws|\.azure|\.docker|\.gnupg|\.kube|\.config[\\/]+(?:gh|git|gcloud)'
    r'|\.cache[\\/]+huggingface'
    r'|github[\s\\]+cli|microsoft[\\/]+credentials|programdata[\\/]+ssh'
    r'|\.claude(?:[\\/]+(?:projects|backups|settings[^\\/]*|\.credentials[^\\/]*))?)[\\/]*$')
CRED_DIR_NAMES = {'.ssh', '.aws', '.docker', '.gnupg', '.kube', '.claude', 'gh', 'huggingface', 'github cli',
                  'credentials', 'ssh'}
# This repo's guard files, matched against glob words in write targets (echo x > scripts/tests/claude*.py).
CRIT_FILES = ('scripts/hooks/lis-guard.py', 'scripts/hooks/loop-guard.py', 'scripts/verify-doc.py',
              'scripts/serve.ps1', 'scripts/stop.ps1', 'scripts/claude-local.ps1', 'scripts/register-task.ps1',
              'scripts/watchdog.ps1', 'scripts/register-watchdog.ps1',
              'scripts/tests/claude_settings_test.py', 'scripts/tests/install_verify_test.py',
              'scripts/tests/resilience_test.py', 'config/claude-settings.json', 'bench/ladder/run.ps1')
# Executables the per-run settings deny (config/claude-settings.json): the hook denies
# them too, after exe() normalisation (quotes, full path, case, leading backslash, .exe,
# env prefix), so a form the literal prefix rules miss is still denied.
DENIED_EXES = {'ssh', 'scp', 'sftp', 'gh', 'docker-compose'}
DOCKER_DENIED = {'run', 'exec', 'cp', 'push', 'login', 'build', 'buildx', 'compose', 'save', 'load', 'import',
                 'export', 'commit', 'volume', 'network', 'system', 'container', 'image', 'create', 'start'}
WSL_DENIED_OPTS = {'-d', '--distribution', '-e', '--exec', '-u', '--user', '--', '~', '--cd', '--shell-type',
                   '--import', '--export', '--install', '--unregister', '--mount'}
CRITICAL_VERBS = [(re.compile(p), n) for p, n in CRITICAL_VERBS]

# A path that must not be written: user .claude/.ssh, Windows, Program Files*,
# ProgramData, WSL-side /mnt/c mirrors of those, .env*, *.pem, *.key, token, .git, .curlrc/_curlrc.
_ANCH = r"(?:^|[\s'\"=:])"
CRITICAL_PATH = re.compile(
    r'(?i)(?:\.claude\b|\.ssh\b'
    r'|' + _ANCH + r'(?:[a-z]:[\\/]|/[a-z]/|/mnt/[a-z]/)windows\b'
    r'|' + _ANCH + r'(?:[a-z]:[\\/]|/[a-z]/|/mnt/[a-z]/)?program ?files'
    r'|programdata'
    r'|/mnt/[a-z]/users/[^/]+/\.(?:claude|ssh)\b'
    r'|\.env\b|\.pem\b|\.key\b|[\\/]token\b|^token\b|\.git(?:[\\/]|$|[\s\'"])'
    r'|[._]curlrc\b'  # curl's default config file (~/.curlrc, %APPDATA%\_curlrc)
    # this repo's guards and launch path (audit B3): the hooks, the wrapper, the logon
    # task's serve script, the per-run settings and the server binary
    r'|scripts[\\/]+(?:hooks\b|verify-doc\.py\b|(?:serve|stop|claude-local|register-task|watchdog|register-watchdog)\.ps1\b'
    r'|tests[\\/]+(?:claude_settings|install_verify|resilience)_test\.py\b)'
    r'|config[\\/]+claude-settings\.json\b|llama-server\.exe\b|bench[\\/]+ladder[\\/]+run\.ps1\b)')

WRITE_VERBS = {'tee', 'mv', 'cp', 'chmod', 'chown', 'ln', 'install', 'truncate', 'touch'}
PS_WRITE = re.compile(r'(?i)\b(?:Set-Content|Out-File|Add-Content|New-Item|Copy-Item|Move-Item|Rename-Item|Set-Acl'
                      r'|Tee-Object|Set-Item|Clear-Content|Clear-Item|Invoke-Item)\b')
# PowerShell aliases of the delete/move/write/exec cmdlets (ni = New-Item, ii = Invoke-Item, W4).
PS_DEL_ALIAS = re.compile(r'(?i)(?<![\w-])(?:del|erase|ri|rd|rmdir|rm|move|mv|copy|cp|mi|cpi'
                          r'|ni|ii|ren|rni|si|sc|ac|clc|cli|tee)\b')
PS_IOFILE = re.compile(r'(?i)\[(?:System\.)?IO\.(?:File|Directory)\]::(?:Delete|Write\w*|Copy|Move|Create\w*'
                       r'|AppendAll\w*|Replace|Encrypt|Decrypt|SetAttributes|SetLastWriteTime)')
# PowerShell payload cmdlets that run, change or stop something with no other check
# covering them (audit A3 W1): process and WMI/CIM methods, code execution, power, volumes
PS_CRIT = re.compile(r'(?i)(?<![\w$-])(?:Invoke-CimMethod|Invoke-WmiMethod|Remove-CimInstance|Set-CimInstance'
                     r'|New-CimInstance|Remove-WmiObject|Start-Process|Invoke-Expression|iex|Invoke-Command'
                     r'|Stop-Computer|Restart-Computer|Set-Volume|Format-Volume|Clear-Disk|Set-Clipboard'
                     r'|New-Object\s+(?:-TypeName\s+)?(?:System\.)?Net\.(?:WebClient|Sockets\.\w+))(?![\w-])')
# a read cmdlet whose path is built by -f, -replace, -join, [char], .Replace(), + or an
# index (audit A5): the hook cannot see the path it reads, so it is a credential read
PS_READ_CMD = re.compile(r'(?i)(?<![\w$.:-])(?:Get-Content|gc|cat|type|Get-Item|gi|Get-ChildItem|gci|ls|dir'
                         r'|Select-String|sls|Import-Csv|ipcsv|Get-FileHash|Format-Hex|fhx|Copy-Item|cpi|cp'
                         r'|Get-ItemProperty|gp)(?![\w-])')
PS_SPLICE = re.compile(r'(?i)\s-[ci]?(?:f|replace|join|split|as)(?![\w-])|\[char\]|\[string\]|\.Replace\s*\('
                       r'|::(?:Join|Concat|Format|ToString)\s*\(|[\'"]\s*\[|[\'")]\s*\+|\+\s*[\'"(\[$]')
PS_INVOKE_WEB = re.compile(r'(?i)\b(?:Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b')
PS_CD = re.compile(r'(?i)^(?:Set-Location|Push-Location|sl|cd|chdir|pushd)(?:\s+(.*))?$')
REMOTE_WRITE = {'rm', 'rmdir', 'systemctl', 'docker', 'git', 'tee', 'mv', 'cp', 'chmod', 'chown', 'kill',
                'pkill', 'killall', 'apt', 'apt-get', 'dpkg', 'reboot', 'shutdown', 'poweroff', 'halt',
                'dd', 'truncate', 'crontab', 'sed', 'npm', 'pip',
                'shred', 'chattr', 'wipefs', 'blkdiscard', 'mkswap', 'swapoff', 'fdisk', 'sfdisk', 'parted'}
HOSTNAME_FLAGS_OK = {'-s', '-f', '-d', '-i', '-I', '-a', '-A', '-y', '-h', '-V', '--short', '--fqdn', '--long',
                     '--domain', '--ip-address', '--all-ip-addresses', '--alias', '--all-fqdns', '--yp',
                     '--nis', '--help', '--version'}  # -F/--file and -b/--boot set the name

# Generic read verbs: safe whatever their flags/positionals; a write can only come from a
# redirection (handled separately) or from a verb that has its own stricter handler below.
READ_VERBS = {'ls', 'cat', 'head', 'tail', 'grep', 'wc', 'df', 'du', 'uptime', 'echo', 'printf',
              'which', 'type', 'stat', 'uname', 'free', 'systeminfo', 'whoami', 'id', 'pwd',
              'tr', 'cut', 'true', 'false', 'netstat', 'tasklist', 'nproc',
              'continue', 'break', ':', 'cd', 'jq', 'column', 'basename', 'dirname', 'realpath',
              'readlink', 'sha256sum', 'md5sum', 'diff', 'cmp'}
# Verbs whose dangerous options (output/exec file) force a per-verb allow-list (C1):
#   uniq, sort, tree, find, nvidia-smi, rg, wmic, date -- handled in seg_readonly().
# file/find/tree/rg: every flag must be listed here; anything else (-exec, -delete, -fprint,
# --pre, -o FILE, file -C/-m, a bundle) gets no decision.
FIND_VALUED = {'-name', '-iname', '-path', '-ipath', '-type', '-maxdepth', '-mindepth',
               '-mtime', '-newer', '-size', '-regex', '-iregex'}
FIND_BARE = {'-empty', '-print', '-print0', '-prune', '-not', '-o', '-a', '!', '(', ')',
             '-readable'}
FILE_FLAGS = {'-b', '-i', '-L', '-h', '-z', '-s', '-k', '--mime', '--mime-type', '--brief'}
TREE_VALUED = {'-L', '-I', '-P'}
TREE_FLAGS = TREE_VALUED | {'-a', '-d', '-f', '-i', '-h', '-s', '-D', '--noreport', '--dirsfirst'}
RG_VALUED = {'-e', '-g', '-t', '-T', '--glob', '--type', '-m', '--max-count', '-A', '-B', '-C',
             '--color'}
RG_FLAGS = RG_VALUED | {'-n', '-i', '-l', '-c', '-w', '-F', '-S', '--no-heading', '-o', '--json',
                        '--hidden', '-u'}
VERSION_ONLY = {'node', 'npm', 'pnpm', 'python', 'py', 'uv', 'claude', 'pip'}
VERSION_FLAGS = {'-v', '--version', '-V', 'version'}
PS_EXES = {'powershell', 'pwsh'}
PS_VALUED = {'executionpolicy', 'ex', 'ep', 'workingdirectory', 'wd', 'version', 'v', 'configurationname',
             'config', 'custompipename', 'settingsfile', 'outputformat', 'o', 'of', 'inputformat', 'if', 'in',
             'windowstyle', 'w', 'configurationfile', 'psconsolefile'}
# PowerShell read-only allowlist (audits A5-A7): a payload is allowed only when every
# statement is a pipeline that starts with one producer (a Get-* cmdlet, Test-Path or
# Write-Output) and continues only with consumers (PS_RO_CONSUMERS), each cmdlet with only
# the parameters listed for it and each value in its class (ps_ro_value), or one of the
# survey forms in ps_ro_statement(); anything else gets no decision (the deny rules still
# run first). Names are exact (no -Comp, -cn abbreviations); '' is the cmdlet's first
# positional parameter; a quoted value is judged like the same value unquoted. Every
# property the payload names must be in its producer's PS_RO_PROPS list.
_EA = {'erroraction': 'erroraction'}
_PATHS = {'': 'repo_path', 'path': 'repo_path', 'literalpath': 'repo_path'}
_PROPS = {'': 'prop', 'property': 'prop'}
PS_RO_SPEC = {
    'get-ciminstance': {'': 'class', 'classname': 'class', **_EA},
    'get-volume': {'': 'word', 'driveletter': 'word'},
    'get-psdrive': {'': 'word', 'name': 'word', 'psprovider': 'filesystem'},
    'get-process': {'': 'word', 'name': 'word', 'id': 'int', **_EA},
    'get-service': {'': 'word', 'name': 'word', **_EA},
    'get-date': {'format': 'word'},
    'get-computerinfo': {**_PROPS},             # a -Property list is required
    'get-command': {'': 'cmdname', 'name': 'cmdname'},
    'select-object': {**_PROPS, 'expandproperty': 'propone', 'first': 'int', 'last': 'int', 'skip': 'int',
                      'unique': 'none'},
    'format-table': {**_PROPS, 'autosize': 'none', 'wrap': 'none', 'hidetableheaders': 'none'},
    'format-list': {**_PROPS},
    'sort-object': {**_PROPS, 'descending': 'none', 'unique': 'none'},
    'where-object': {'': 'filter', 'filterscript': 'filter'},
    'measure-object': {**_PROPS, 'sum': 'none', 'average': 'none', 'maximum': 'none', 'minimum': 'none'},
    'convertto-json': {'depth': 'depth', 'compress': 'none'},
    'write-output': {'': 'text'},
    'test-path': {**_PATHS, 'pathtype': 'word'},
    'get-item': {**_PATHS, 'force': 'none', **_EA},
    'get-childitem': {**_PATHS, 'recurse': 'none', 'force': 'none', 'filter': 'glob', 'include': 'glob',
                      'exclude': 'glob', 'file': 'none', 'directory': 'none', 'name': 'none', 'depth': 'depth',
                      **_EA},
}
PS_RO_CMDLETS = frozenset(PS_RO_SPEC)
# what may follow a `|`: a producer there would take its path or name from the pipeline
# (Get-PSDrive | Select-Object -ExpandProperty Root | Get-ChildItem, audit A7 W1)
PS_RO_CONSUMERS = {'select-object', 'where-object', 'sort-object', 'measure-object', 'format-table',
                   'format-list', 'convertto-json', 'write-output'}
PS_RO_PRODUCERS = (PS_RO_CMDLETS - PS_RO_CONSUMERS) | {'write-output'}
# CIM classes with no secret-bearing property (Win32_Process has CommandLine, Win32_Service
# PathName, Win32_Product runs a consistency check; CIM_* bases cover Win32_Environment)
PS_RO_CLASSES = {'win32_operatingsystem', 'win32_computersystem', 'win32_processor', 'win32_videocontroller',
                 'win32_physicalmemory', 'win32_logicaldisk', 'win32_diskdrive', 'win32_bios'}
# the scalar properties a payload may name, per producer (per class for Get-CimInstance):
# no object-typed property (Parent, Modules, DependentServices, Provider, CimSession) and
# no identity (UserName, RegisteredUser, SerialNumber, Domain, ProcessorId) (audit A7)
_FILE_PROPS = {'Name', 'FullName', 'Length', 'LastWriteTime', 'Extension', 'Mode', 'PSIsContainer'}
PS_RO_PROPS = {
    'get-process': {'Name', 'Id', 'CPU', 'WS', 'PM', 'NPM', 'VM', 'Handles', 'Path', 'StartTime', 'ProcessName',
                    'Responding', 'PriorityClass', 'WorkingSet64'},
    'get-service': {'Name', 'DisplayName', 'Status', 'StartType'},
    'get-volume': {'DriveLetter', 'FileSystemLabel', 'Size', 'SizeRemaining', 'HealthStatus', 'DriveType'},
    'get-psdrive': {'Name', 'Root', 'Used', 'Free'},
    'get-item': _FILE_PROPS,
    'get-childitem': _FILE_PROPS,
    'get-date': {'Year', 'Month', 'Day', 'DateTime', 'Ticks'},
    'get-command': {'Source', 'Path', 'Name', 'Version', 'CommandType'},
    'get-computerinfo': {'OsName', 'OsVersion', 'OsArchitecture', 'CsNumberOfLogicalProcessors',
                         'CsTotalPhysicalMemory', 'OsTotalVisibleMemorySize', 'OsFreePhysicalMemory',
                         'WindowsVersion'},
    'test-path': set(),
    'write-output': set(),
    'win32_operatingsystem': {'Caption', 'Version', 'BuildNumber', 'OSArchitecture', 'TotalVisibleMemorySize',
                              'FreePhysicalMemory', 'LastBootUpTime', 'InstallDate'},
    'win32_computersystem': {'Model', 'Manufacturer', 'TotalPhysicalMemory', 'NumberOfLogicalProcessors',
                             'NumberOfProcessors'},
    'win32_processor': {'Name', 'NumberOfCores', 'NumberOfLogicalProcessors', 'NumberOfEnabledLogicalProcessors',
                        'MaxClockSpeed', 'L2CacheSize', 'L3CacheSize'},
    'win32_videocontroller': {'Name', 'AdapterRAM', 'DriverVersion', 'VideoProcessor'},
    'win32_physicalmemory': {'Capacity', 'Speed', 'Manufacturer', 'PartNumber'},
    'win32_logicaldisk': {'DeviceID', 'Size', 'FreeSpace', 'FileSystem', 'DriveType'},
    'win32_diskdrive': {'Model', 'Size', 'MediaType', 'InterfaceType'},
    'win32_bios': {'Manufacturer', 'Name', 'SMBIOSBIOSVersion', 'ReleaseDate'},
}
_PROPS_LC = {k: {x.lower() for x in v} for k, v in PS_RO_PROPS.items()}
PS_RO_MEASURE = {'count', 'sum', 'average', 'maximum', 'minimum'}     # (... | Measure-Object).Sum
# producers whose default view is safe to print whole: no Format-* without a property
# list, and no bare Get-CimInstance (its default view names the owner and serial number)
PS_RO_VIEW_OK = {'get-psdrive', 'get-date', 'get-item', 'get-childitem', 'test-path', 'write-output'}
PS_RO_PATH_CMDLETS = {'get-childitem', 'get-item', 'test-path'}   # only with the cwd inside the repo
PS_RO_EXACT = {'$psversiontable', '$psversiontable.psversion', '$psversiontable.psversion.tostring()'}
_RO_CWD = [None]                        # decide()'s cwd (False after a cd), for repo paths
_UNDECIDED = [False]                    # set when a cd rewrite was too large (A10 W2)
_PS_LIT = r'''(?:'[^'$`]*'|"[^"$`]*"|\d+)'''
# { $_.X -eq 'y' } in Where-Object; @{n='X';e={[math]::Round($_.Y/1GB,1)}} in Select-Object;
# each becomes a placeholder word that keeps the property name (\x01F<X>, \x01C<Y>)
PS_RO_FILTER = re.compile(r'\{\s*\$_\.(\w+)\s+-(?:eq|ne|gt|lt|like|match)\s+' + _PS_LIT + r'\s*\}', re.I)
PS_RO_CALC = re.compile(r"@\{\s*(?:n|name|l|label)\s*=\s*'\w+'\s*;\s*(?:e|expression)\s*=\s*\{\s*"
                        r"(?:\[math\]::Round\(\s*\$_\.(\w+)\s*/\s*1[KMG]B\s*(?:,\s*\d)?\s*\)|\$_\.(\w+))\s*\}\s*\}", re.I)
# Env assignments: only these names (exact case) may lead a command or stand alone; any
# other NAME=VALUE gets no decision (C6, R9: a deny-list missed GIT_EXTERNAL_DIFF,
# GIT_CONFIG_*, PAGER, GIT_DIR, ...). WSLENV is left out: it forwards variables into WSL.
ENV_SAFE = {'MSYS_NO_PATHCONV', 'MSYS2_ARG_CONV_EXCL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'TERM',
            'COLUMNS', 'LINES', 'NO_COLOR', 'FORCE_COLOR', 'CLICOLOR', 'GIT_TERMINAL_PROMPT',
            'GIT_OPTIONAL_LOCKS', 'PYTHONIOENCODING', 'PYTHONUTF8', 'PYTHONDONTWRITEBYTECODE',
            'DOCKER_CLI_HINTS', 'WSL_UTF8'}
MAX_DEPTH = 6

# Interpreter payloads (audit B4): python -c, node -e, a heredoc or here-string fed to an
# interpreter, and python/node script files are judged by the same deny scan as a shell
# command, plus the language APIs below. A payload none of them matches keeps today's
# outcome (no decision), so the rules or the classifier decide.
SH_EXES = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
PY_EXE = re.compile(r'(?:python[\d.]*w?|py|pypy3?)')
PY_VALUED = {'-X', '-W', '-Q'}
NODE_VALUED = {'-r', '--require', '--import', '--loader', '--experimental-loader', '-C', '--conditions',
               '--input-type', '--test-reporter', '--test-reporter-destination', '--test-name-pattern',
               '--env-file', '--title', '--inspect-port'}
NET_TOOLS = {'scp', 'sftp', 'nc', 'ncat', 'netcat', 'socat', 'ftp', 'tftp'}
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
CODE_TREE_DELETE = re.compile(r'(?:\brmtree|\bremovedirs|\brmSync|\brimraf(?:\.sync)?|\bfs(?:\.promises)?\.rm)'
                              r'\s*\(\s*([^,)\n]{0,200}(?:\([^)\n]{0,100}\))?[^,)\n]{0,100})')
CODE_WRITE = re.compile(r'\b(?:os\.(?:remove|unlink|rmdir|rename|replace|truncate|chmod|symlink|link)'
                        r'|shutil\.(?:copy\w*|move)|unlink|unlinkSync|rmdir|rmdirSync|writeFile|writeFileSync'
                        r'|appendFile|appendFileSync|copyFile|copyFileSync|rename|renameSync|truncateSync|chmodSync'
                        r'|createWriteStream|cpSync|symlinkSync|write_text|write_bytes|touch)\s*\('
                        r'|\bopen\s*\([^)\n]{0,300}?[\'"][rwxabt+]*[wxa+][rwxabt+]*[\'"]')
CODE_KILL = re.compile(r'\bos\.killpg\s*\(|\b(?:os|process)\.kill\s*\(\s*(?:-|0\s*[,)])|\bsignal\.pthread_kill\b')
CODE_UPLOAD = re.compile(r'(?i)\b(?:requests|httpx|session|client|axios)\.(?:post|put|patch)\s*\('
                         r'|\bmethod\s*[=:]\s*[\'"](?:POST|PUT|PATCH)[\'"]|\.request\s*\(\s*[\'"](?:POST|PUT|PATCH)[\'"]'
                         r'|\b(?:urlopen|Request)\s*\([^)\n]{0,300}\bdata\s*=|\b(?:smtplib|ftplib|paramiko|dgram)\b'
                         r'|\bsocket\.(?:socket|create_connection)\s*\(|\bnet\.(?:connect|createConnection|Socket)\s*\(')
_DOMAINISH = re.compile(r'^(?:[\w-]+\.)+[a-z]{2,}(?::\d+)?(?:[/?#]|$)', re.I)
# argv lists: ['git', 'push'] / ["ssh", 'h'] are walked as one shell command (W1)
_ARGV_LIST = re.compile(r"\[\s*((?:'[^'\\\n]{0,300}'|\"[^\"\\\n]{0,300}\")"
                        r"(?:\s*,\s*(?:'[^'\\\n]{0,300}'|\"[^\"\\\n]{0,300}\")){1,40})\s*,?\s*\]")
# the whole environment printed, serialised or sent (audit A2 W5): print(os.environ),
# print(dict(os.environ)), console.log(process.env), JSON.stringify(process.env); a copy
# for a child process (env = dict(os.environ, X=1)) is not a dump
CODE_ENV_DUMP = re.compile(r'\b(?:print|pprint|repr|str|json\.dumps?|JSON\.stringify|console\.\w+|write|send\w*)'
                           r'\s*\(\s*(?:dict\s*\(\s*)?(?:os\.environ|process\.env|Deno\.env)\s*\)'
                           r'|\bos\.environ\.(?:items|values)\s*\(|\bObject\.(?:entries|values)\s*\(\s*process\.env\b')
# obfuscation fed to an executor: chr()/fromCharCode/base64 decode near system/exec/eval
CODE_OBFUSCATION = re.compile(r'\bchr\b|\bfromCharCode\b|\bb(?:64|32|16|85)decode\s*\(|\batob\s*\('
                              r'|[\'"]base64[\'"]|\bcodecs\.decode\s*\(|\bbytes\.fromhex\s*\(')
CODE_EXEC = re.compile(r'\bos\.(?:system|popen|exec\w*|spawn\w*)\s*\(|\bsubprocess\b|\bexec(?:Sync|File\w*)?\s*\('
                       r'|\beval\s*\(|\bspawn(?:Sync)?\s*\(|\bchild_process\b|\bnew\s+Function\s*\(|\bFunction\s*\(')
# reading a file and calling the network in the same code: the file can ride in a URL
# query (fetch('https://x/?d=' + readFileSync(...))), so it counts as an upload (W1)
CODE_FILE_READ = re.compile(r'\breadFile(?:Sync)?\s*\(|\bread_(?:text|bytes)\s*\(|\bopen\s*\([^)\n]{0,300}\)\s*\.read\s*\(')
CODE_NET = re.compile(r'\bfetch\s*\(|\bhttps?\.(?:get|request)\s*\(|\burlopen\s*\(|\b(?:requests|httpx|axios)\.\w+\s*\('
                      r'|\bWebSocket\s*\(|\bXMLHttpRequest\b|\burllib\.request\b')


def inline_code(v, a):
    """(kind, code) for python -c CODE / node -e CODE (attached or next token), else None.
    Scanning stops at the first positional (the script file; later words are its args)."""
    py = bool(PY_EXE.fullmatch(v))
    if v == 'deno' and a[:1] == ['eval'] and len(a) > 1:
        return 'js', a[-1]
    if v == 'bun':
        for j, t in enumerate(a):
            if t in ('-e', '--eval', '-p', '--print') and j + 1 < len(a):
                return 'js', a[j + 1]
        return None
    if not (py or v == 'node'):
        return None
    i = 0
    while i < len(a):
        t = a[i]
        if t == '--' or not t.startswith('-') or t == '-':
            return None
        if py:
            m = re.fullmatch(r'-[A-Za-z]*c(.*)', t, re.S)
            if m:
                return ('py', m.group(1)) if m.group(1) else (('py', a[i + 1]) if i + 1 < len(a) else None)
            if re.fullmatch(r'-[A-Za-z]*m.*', t, re.S):
                return None
            i += 2 if t in PY_VALUED else 1
        else:
            if t in ('-e', '--eval', '-p', '--print', '-pe', '-ep'):
                return ('js', a[i + 1]) if i + 1 < len(a) else None
            if t.startswith(('--eval=', '--print=')):
                return 'js', t.split('=', 1)[1]
            i += 2 if t in NODE_VALUED else 1
    return None


def code_strings(code):
    """Contents of the '...', "..." and `...` literals in code, by one linear pass (W4: a
    regex retried from every quote was quadratic on a run of escaped quotes). A literal is
    at most 4000 chars; ' and " stop at a newline. A quote whose scan fails marks its span
    dead for that quote type, so a later quote of the same type inside it is not rescanned."""
    out, i, n = [], 0, len(code)
    dead = {"'": -1, '"': -1, '`': -1}
    while i < n:
        c = code[i]
        if c not in dead or i < dead[c]:
            i += 1
            continue
        j, limit = i + 1, min(n, i + 4001)
        while j < limit:
            d = code[j]
            if d == '\\':
                j += 2
                continue
            if d == c or (d == '\n' and c != '`'):
                break
            j += 1
        if j < limit and code[j] == c:
            out.append(code[i + 1:j])
            i = j + 1
        else:
            dead[c] = j
            i += 1
    return out


def loopback_only(words):
    """True when at least one word is a URL and every URL or bare domain is loopback."""
    urls = [w for w in words if re.match(r'^[a-zA-Z][\w+.-]*://', w)]
    if any(_DOMAINISH.match(w) for w in words if w not in urls and not w.startswith('-')):
        return False
    return bool(urls) and all(_url_host(u) in LOOPBACK for u in urls)


def code_critical(code):
    """Deny reason for python/node code: a recursive delete, a broadcast or group kill, a
    write/delete API with a critical path among the string literals, or an upload API
    whose URLs are not all loopback. Static and over-matching, like the shell scan."""
    lits = code_strings(code)
    # A tree delete of a temp dir held in a variable (test cleanup) passes; one whose first
    # argument names the home dir or cwd, or holds a literal absolute, home, parent or cwd
    # path that is not a temp dir, or a critical path, denies.
    for m in CODE_TREE_DELETE.finditer(code):
        arg = m.group(1)
        if re.search(r'expanduser|Path\.home|homedir|USERPROFILE|\bHOME\b|getcwd|\bcwd\s*\(', arg) or any(
                CRITICAL_PATH.search(' ' + s)
                or (re.match(r'^(?:[A-Za-z]:[\\/]|[\\/]|~|\.{1,2}(?:[\\/]|$))', s)
                    and not re.search(r'(?i)(?:^|[\\/])(?:tmp|temp)(?:[\\/]|$)', s)) for s in code_strings(arg)):
            return 'recursive delete in interpreter code'
    if CODE_KILL.search(code):
        return 'group or broadcast kill in interpreter code'
    if CODE_OBFUSCATION.search(code) and CODE_EXEC.search(code):
        return 'obfuscated code fed to system/exec/eval'
    # a critical path literal on the same line as the call, within 400 chars of it. The
    # windows of all matches are merged first, so each stretch of code is lexed once
    # (audit A2 W3: per-match lexing was 33k passes on a 200 KB one-liner).
    spans = []
    for m in CODE_WRITE.finditer(code):
        start = max(code.rfind('\n', 0, m.start()) + 1, m.start() - 400)
        end = code.find('\n', m.end(), m.end() + 400)
        end = end if end >= 0 else min(len(code), m.end() + 400)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    for start, end in spans:
        line = code[start:end]
        if any(CRITICAL_PATH.search(' ' + s) for s in code_strings(line) + code_strings(join_concat(line))):
            return 'interpreter write/delete on a critical path'
    if CODE_ENV_DUMP.search(code):
        return 'environment dump in interpreter code'
    if CODE_UPLOAD.search(code) and not loopback_only(lits):
        return 'network upload to a non-loopback host from interpreter code'
    if CODE_FILE_READ.search(code) and CODE_NET.search(code) and not loopback_only(lits):
        return 'file read sent to a non-loopback host from interpreter code'
    return None


def join_concat(s):
    """s with adjacent string literals joined: 'git pu' + 'sh' -> 'git push', and the
    shell's quote splicing pu''sh / "$HOME/.cred"entials.json -> push / ...credentials.json."""
    s = re.sub(r'([\'"`])\s*\+\s*([\'"`])', '', s)
    return re.sub(r'(?<=\w)(?:\'\'|""|[\'"](?=\w))|(?<=[\w./])[\'"](?=[\w./])', '', s)


OBF_CAP = 500
OVER_CAP = 'obfuscation over cap'
OBF_FORMS = re.compile(r'\{[^{}\s\'"]*,|\'\'|""|\\[A-Za-z.]|\$\'|(?<![\w-])(?:cd|pushd|chdir|Set-Location|sl)\s', re.I)
OBF_CD = re.compile(r'(?<![\w-])(?:cd|pushd|popd|chdir|Set-Location|sl|Push-Location|Pop-Location)(?![\w-])', re.I)
TOO_BIG = 'cd rewrite too large'        # past the cd count or size bound: no decision (A10 W2, A11)
PS_DASH = re.compile('[\u2013\u2014\u2015]')   # en dash, em dash, horizontal bar
# never on the allow path, whatever the verb (ruling 45): credential names, encoded and eval forms
ALLOW_STOP = re.compile(r'(?i)id_rsa|\.ssh[\\/]|\.aws[\\/]|credentials|api-key|hf_|\.env'
                        r'|(?<![\w-])-ec\b|-encodedcommand|invoke-expression|(?<![\w-])iex\b')


def allow_stop(s):
    """An ALLOW_STOP token in s, also once line continuations, quotes, backslashes and
    backticks are removed (`a""pi-key`, `.e\\<newline>nv`; A12 sweep)."""
    return ALLOW_STOP.search(s) or ALLOW_STOP.search(re.sub(r'[\'"`\\]', '', re.sub(r'[`\\]\r?\n', '', s)))
ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.){0,2000})'", re.S)
_ANSI_SIMPLE = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b',
                'f': '\f', 'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}


def ansi_c(body):
    """The text bash makes of $'body': \\xHH, \\NNN (octal), \\uHHHH, \\UHHHHHHHH, \\n ..."""
    def one(m):
        e = m.group(1)
        if e[0] in 'xuU':
            try:
                return chr(int(e[1:], 16))
            except ValueError:
                return e
        if e[0] in '01234567':
            return chr(int(e, 8) & 0xFF)
        return _ANSI_SIMPLE.get(e, '\\' + e)
    return re.sub(r'\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|.)', one, body, flags=re.S)


def ps_dashes(cmd):
    """cmd with U+2013, U+2014 and U+2015 read as '-' when it names pwsh or powershell:
    PowerShell takes them as dashes, so -wd, -c and -ec in those spellings are the same
    options (audit A10 C1)."""
    return PS_DASH.sub('-', cmd) if PS_DASH.search(cmd) and re.search(r'(?i)pwsh|powershell', cmd) else cmd


def normalize(cmd):
    """cmd rewritten the way the shell would read its paths (audit A2 W1/W2), for a second
    scan: 'a'+'b' and pu''sh splices joined, {a,b} braces expanded, a backslash before a
    letter or dot dropped (.s\\sh), /./ and // collapsed, and a glob word that can match
    one of this repo's guard files (scripts/tests/claude*.py) replaced by that file.
    ANSI-C $'...' strings are decoded first (A3 W2: $'\\x2essh'). OVER_CAP when one line
    holds more than OBF_CAP of these forms (A3 W6: bounds the time). TOO_BIG (no decision)
    when the command holds more than OBF_CAP cd/pushd over all its lines (A9 C2, A11)."""
    for line in cmd.split('\n'):
        n = 0
        for _ in OBF_FORMS.finditer(line):
            n += 1
            if n > OBF_CAP:
                return OVER_CAP
    n = 0
    for _ in OBF_CD.finditer(cmd):          # cd statements over all lines (A9 C2)
        n += 1
        if n > OBF_CAP:
            return TOO_BIG                  # many cd words: no decision (A11)
    s = ANSI_C.sub(lambda m: ansi_c(m.group(1)), cmd)
    s = ps_dashes(join_concat(s))
    stop = set(' \t\n\'"`;|&()<>{}')
    for _ in range(3):           # the brace is found first, then its word: linear (W3)
        m = re.search(r'\{([^{}\s\'"]*,[^{}\s\'"]*)\}', s)
        if not m:
            break
        a, b = m.start(), m.end()
        while a > 0 and s[a - 1] not in stop and m.start() - a < 300:
            a -= 1
        while b < len(s) and s[b] not in stop and b - m.end() < 300:
            b += 1
        pre, post = s[a:m.start()], s[m.end():b]
        s = s[:a] + ' '.join(pre + x + post for x in m.group(1).split(',')[:20]) + s[b:]
    s = re.sub(r'\\(?=[A-Za-z.])', '', s)
    s = s.replace('>|', '>')        # noclobber override; the segment split reads it as a pipe
    s = re.sub(r'(?<=[\\/])\.(?=[\\/])', '', s)
    s = re.sub(r'(?<!:)[\\/]{2,}', '/', s)

    def crit_glob(m):
        w = m.group(0)
        if not re.search(r'[\\/]', w) or not re.search(r'[*?\[]', w):
            return w
        parts = [p for p in re.split(r'[\\/]', w) if p not in ('', '.')]
        for f in CRIT_FILES:
            fp = f.split('/')
            if len(fp) == len(parts) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(fp, parts)):
                return f
        return w
    return re.sub(r'[^\s\'"`;|&()<>=,]+', crit_glob, s)   # one pass per word: linear (A3 W6)


def cd_rewrite(cmd):
    """The segments after a cd/pushd with their relative arguments prefixed by the cd
    target, so `cd config; echo {} > claude-settings.json` and `cd ~/.ssh && cat x` are
    judged as the paths they reach (audit A2). None when there is no cd."""
    if not re.search(r'(?i)(?<![\w-])(?:cd|pushd|chdir|set-location|sl|push-location)\b', cmd):
        return None
    prefix, out, seen, size = None, [], 0, 0
    for seg in split_segments(cmd):
        t = tokens(seg) or []
        if not t:
            continue
        if exe(t[0]) in ('cd', 'pushd', 'chdir', 'set-location', 'sl', 'push-location'):
            seen += 1
            d = next((x for x in t[1:] if not x.startswith('-')), None)
            if d is None or d == '-':
                prefix = None
            elif re.match(r'^(?:[A-Za-z]:|[\\/~$])', d) or prefix is None:
                prefix = d
            else:
                prefix = posixpath.normpath(prefix + '/' + d)
            if seen > OBF_CAP:
                return TOO_BIG              # many cd words: no decision (A11)
            if prefix and len(re.split(r'[\\/]', prefix)) > PATH_MAX_PARTS:
                return OVER_CAP             # the rewrite would grow without bound (A9 C2)
            continue
        if prefix is None:
            continue
        new = [t[0]]
        for x in t[1:]:
            m = re.match(r'^(\d?>>?\|?|<|\w+=)?(.*)$', x, re.S)
            op, rest = m.group(1) or '', m.group(2)
            if rest and not rest.startswith('-') and rest not in ('>', '>>', '<', '|') \
                    and not re.match(r'^(?:[A-Za-z]:|[\\/~$]|\w+://)', rest):
                rest = prefix.rstrip('\\/') + '/' + rest
            new.append(op + rest)
        out.append(' '.join(x if re.fullmatch(r'[^\s\'"]+', x) else shlex.quote(x) for x in new))
        size += len(out[-1]) + 2
        if size > 2 * len(cmd) + 4096:
            return TOO_BIG                  # many names after a cd: no decision (A9 C2, A10 W2)
    return '; '.join(out) if seen and out else None


def cred_glob(cmd):
    """Deny reason when a glob word (* ? [) can match a credential basename and has at
    least 3 literal characters: .cred*.json, .credentials.jso?, ~/.ss?/id_*."""
    globs = [w for w in re.findall(r'[^\s\'"`;|&()<>=,]+', cmd) if re.search(r'[*?\[]', w)]
    for w in globs[:200]:
        parts = re.split(r'[\\/]', w.lower())
        for i, part in enumerate(parts):
            if not re.search(r'[*?\[]', part):
                continue
            # any glob inside a credential directory (~/.ssh/*, ~/.claude/.c*) (audit A2)
            if i and parts[i - 1] in CRED_DIR_NAMES:
                return 'credential path (glob)'
            lit = len(re.sub(r'[*?\[\]]', '', re.sub(r'\[[^\]]*\]', '', part)))   # [a-f] is no literal
            # ~/.config/g*/hosts.yml: a short glob under .config reaches gh, git, gcloud (A5)
            if i and parts[i - 1] == '.config' and (lit < 3 or any(fnmatch.fnmatchcase(n, part)
                                                                   for n in ('gh', 'git', 'gcloud'))):
                return 'credential path (glob)'
            if parts[-1] in CRED_NAMES:     # */hosts.yml, ~/.*/.credentials.json
                return 'credential path (glob)'
            # 3+ literal characters, or 2 for a dot name (.s*, .e*): it can match a credential name
            if (lit >= 3 or (lit >= 2 and part.startswith('.'))) \
                    and any(fnmatch.fnmatchcase(n, part) for n in CRED_NAMES):
                return 'credential path (glob)'
    return None


def interp_kind(lead):
    """Payload kind for the command a heredoc or here-string feeds, from its last segment."""
    segs = split_segments(lead)
    toks = tokens(segs[-1]) if segs else None
    toks = strip_env(toks, False) if toks else toks
    if not toks:
        return None
    v = exe(toks[0])
    if PY_EXE.fullmatch(v):
        return 'py'
    if v in ('node', 'deno', 'bun'):
        return 'js'
    if v in SH_EXES or v == 'cmd':
        return 'local'
    if v in PS_EXES:
        return 'ps'
    return None


def heredocs(cmd, cap=32):
    """(lead, body) for the first `cap` <<WORD heredocs and <<< here-strings in cmd. The
    lead (the command fed) is at most 300 chars of the same line, so the cost stays linear."""
    out = []

    def lead(i):
        return cmd[max(cmd.rfind('\n', 0, i) + 1, i - 300):i]
    for m in re.finditer(r'(?<!<)<<(?!<)-?\s*([\'"]?)([A-Za-z_]\w*)\1[^\n]*\n(.*?)(?:\n[ \t]*\2[ \t]*(?=\n|$)|$)',
                         cmd, re.S):
        out.append((lead(m.start()), m.group(3)))
        if len(out) >= cap:
            return out
    for m in re.finditer(r'(?<!<)<<<\s*(\'[^\']*\'|"(?:\\.|[^"\\])*"|\S+)', cmd):
        body = m.group(1)
        out.append((lead(m.start()), body[1:-1] if body[:1] in '\'"' else body))
        if len(out) >= cap:
            break
    return out


def curl_uploads(a):
    """True when curl sends a body or a file: -d/-F/-T (bundled too), --data*, --form*,
    --json, --upload-file."""
    for t in a:
        if t.startswith('--'):
            if t.split('=', 1)[0].startswith(('--data', '--form', '--json', '--upload-file')):
                return True
        elif t.startswith('-') and len(t) > 1:
            for ch in t[1:]:
                if ch in 'dFT':
                    return True
                if ch not in _CURL_BOOL:
                    break
    return False


def wget_uploads(a):
    for j, t in enumerate(a):
        name = t.split('=', 1)[0]
        if name in ('--post-data', '--post-file', '--body-data', '--body-file'):
            return True
        if name == '--method':
            val = t.split('=', 1)[1] if '=' in t else (a[j + 1] if j + 1 < len(a) else '')
            if val.upper() in ('POST', 'PUT', 'PATCH'):
                return True
    return False


def upload_hit(v, args):
    """Deny reason for a network upload or copy tool in one tokenised segment."""
    if v == 'curl' and curl_uploads(args) and not loopback_only(args):
        return 'network upload to a non-loopback host'
    if v == 'wget' and wget_uploads(args) and not loopback_only(args):
        return 'network upload to a non-loopback host'
    if v in NET_TOOLS:
        return f'{v} (network copy or raw socket)'
    if v == 'rsync' and any(re.match(r'^(?:[\w.-]+@)?[\w.-]{2,}:', t) for t in args if not t.startswith('-')):
        return 'rsync to a remote host'
    return None


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
    t = _tokens(seg)
    return None if t is None else list(t)


@functools.lru_cache(maxsize=256)
def _tokens(seg):                       # one shlex pass per segment per call (A3 W6)
    try:
        return tuple(shlex.split(seg, posix=True))
    except ValueError:
        return None


def exe(tok):
    t = tok.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return t[:-4] if t.endswith('.exe') else t


def env_safe(tok):
    name, val = tok.split('=', 1)
    return name in ENV_SAFE and '\n' not in val and '\r' not in val


def strip_env(toks, safe_only=True):
    """Drop leading NAME=VALUE assignments. With safe_only, a name outside ENV_SAFE (or a
    value holding a newline) -> None (no decision); deny scans pass safe_only=False."""
    while toks and re.match(r'^[A-Za-z_]\w*=', toks[0]) and len(toks) > 1:
        if safe_only and not env_safe(toks[0]):
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


def ps_opt(t):
    """(lowercased name, colon value or None) when t is a pwsh option, else None. pwsh 7
    takes -x, --x and /x alike, and Git Bash turns //x into /x (audit A9 C1); the dash may
    be U+2013, U+2014 or U+2015, single or doubled (A10 C1)."""
    m = re.fullmatch(r'(?:[-\u2013\u2014\u2015]{1,2}|//?)([A-Za-z]\w*)(?:[:=](.*))?', t, re.S)
    return (m.group(1).lower(), m.group(2)) if m else None


def ps_payload(toks):
    """(-Command payload, -File path) of a powershell/pwsh token list. PowerShell
    prefix-matches parameter names, so -c/-co/-com/-comm/-command all select -Command
    and -f/-fi/-fil/-file select -File (C3); --x and /x are the same options (A9 C1)."""
    for k, t in enumerate(toks[1:], 1):
        o = ps_opt(t)
        if o is None:
            continue
        name, val = o
        if 'command'.startswith(name) or name == 'cwa' or (len(name) > 7 and 'commandwithargs'.startswith(name)):
            return ' '.join(([val] if val is not None else []) + toks[k + 1:]), None
        if 'file'.startswith(name):
            return None, (val if val is not None else toks[k + 1] if k + 1 < len(toks) else '')
        if name in ('e', 'ec') or (len(name) > 1 and 'encodedcommand'.startswith(name)):
            try:  # -EncodedCommand: base64 of UTF-16LE text
                return base64.b64decode(toks[k + 1], validate=True).decode('utf-16-le'), None
            except (IndexError, ValueError):
                return None, None
    return None, None


def ps_payload_index(toks):
    for k, t in enumerate(toks[1:], 1):
        if (o := ps_opt(t)) and o[1] is None and 'command'.startswith(o[0]):
            return k
    return None


def ssh_remote(toks):
    """Lenient: the remote command string, for critical-write scanning (any options)."""
    i = 1
    while i < len(toks) and toks[i].startswith('-'):
        flag = toks[i]
        i += 2 if (flag in ('-i', '-p', '-o', '-F', '-l', '-b', '-c', '-E', '-I', '-J', '-L',
                             '-R', '-D', '-W', '-m', '-O', '-Q', '-S', '-w') and len(flag) == 2) else 1
    return ' '.join(toks[i + 1:]) if i + 1 < len(toks) else ''


def wsl_payload(toks):
    """The command wsl runs in a distro: after `--`, `-e`/`--exec`, or the first word that
    is not one of wsl's own options (`wsl cat x` runs `cat x` in the default distro).
    Options with a value are skipped; any other option (`--list`, `--status`) means none."""
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ('--', '-e', '--exec'):
            return toks[i + 1:]
        if t in ('-d', '--distribution', '-u', '--user', '--cd', '--shell-type'):
            i += 2
            continue
        if t == '~':
            i += 1
            continue
        if t.startswith('-'):
            return []
        return toks[i:]
    return []


def settings_denied(toks):
    """Deny reason when a tokenised segment runs an executable the per-run settings deny:
    ssh/scp/sftp/gh/docker-compose whole, docker.exe whole, docker with a global option
    first or an exec/copy/build/login subcommand, wsl with a distro, user, exec, cwd or
    shell option, or `wsl bash|sh`. Read-only `docker version|ps|info|context ls` and
    `wsl --list|-l|--status` pass."""
    raw = toks[0].strip('\'"').replace('\\', '/').rsplit('/', 1)[-1].lower()
    v, a = exe(toks[0]), toks[1:]
    if v in DENIED_EXES:
        return f'{v} (denied in local sessions)'
    if v == 'docker':
        if raw.endswith('.exe') or (a and (a[0] in ('-H', '--host', '-c', '--context', '--config')
                                           or a[0].startswith(('-H', '--host=', '--context=', '--config=')))):
            return 'docker with a remote context or as docker.exe (denied in local sessions)'
        if a and (a[0] in DOCKER_DENIED or a[:2] in (['context', 'use'], ['context', 'create'],
                                                      ['context', 'import'])):
            return f'docker {a[0]} (denied in local sessions)'
    if v == 'wsl':
        if any(x in WSL_DENIED_OPTS for x in a) or (wsl_payload(toks)[:1] and exe(wsl_payload(toks)[0]) in SH_EXES):
            return 'wsl into a distro, user or shell (denied in local sessions)'
    if v == 'git':
        sub = git_sub(a)
        if sub in ('push', 'credential'):
            return f'git {sub}'
    return None


SUBST_READ_VERBS = {'cat', 'head', 'tail', 'less', 'more', 'type', 'gc', 'get-content', 'grep', 'egrep',
                    'fgrep', 'rg', 'find', 'nl', 'od', 'xxd', 'strings', 'select-string', 'sls'}
NET_DENIED_EXES = {'pscp', 'plink', 'telnet', 'tftp', 'bitsadmin'}
FIND_CRED = re.compile(r'(?i)pem|key|id_|rsa|ed25519|ecdsa|ppk|p12|pfx|kdbx|credential|token|secret|passw'
                       r'|\.env|netrc|npmrc|pypirc|pgpass|cookies|login data')
CRED_DIR_ANY = re.compile(r'(?i)(?:^|[\s\\/\'"=%])(?:\.ssh|\.aws|\.azure|\.docker|\.gnupg|\.kube|\.claude'
                          r'|\.config[\\/]+(?:gh|git|gcloud)|\.cache[\\/]+huggingface)(?=[\\/\s\'"]|$)')
RECURSIVE_ALWAYS = {'rg', 'find', 'tree', 'du', 'tar', 'zip', '7z', 'robocopy', 'xcopy', 'compress-archive'}
RECURSIVE_FLAGGED = {'grep', 'egrep', 'fgrep', 'ls', 'get-childitem', 'gci', 'dir', 'cp', 'select-string'}
HOME_ROOT = re.compile(r'(?i)^(?:~|\$HOME|\$env:USERPROFILE|%USERPROFILE%|[a-z]:[\\/]+users(?:[\\/]+[^\\/]+)?'
                       r'|/(?:mnt/)?[a-z]/users(?:/[^/]+)?|/home(?:/[^/]+)?|/root)'
                       r'(?:[\\/]+(?:\.config|\.cache|\.local|appdata(?:[\\/]+roaming)?))?[\\/]*$')
NET_VERBS = {'curl', 'wget', 'nc', 'ncat', 'socat', 'ftp', 'aria2c', 'http', 'https'}
GIT_NET = {'fetch', 'pull', 'clone', 'ls-remote', 'remote', 'submodule', 'push'}


def segment_denied(toks, seg, ctx):
    """Deny reason for one tokenised segment (audit A2): a credential directory named as
    a word, a remote shell or transfer tool, a whole-environment dump, or a $( )/backtick
    substitution inside a network command's arguments (data smuggled into a URL/header)."""
    for t in toks[1:]:
        if CRED_DIR.search(t.strip('\'"').rstrip('\\/') or 'x'):
            return 'credential directory'
    v, a = exe(toks[0]), toks[1:]
    # a recursive search or archive of a home directory or its .config/.cache/AppData
    # walks into the credential directories under it (audit A2: rg -uuu token C:/Users/x)
    if (v in RECURSIVE_ALWAYS or (v in RECURSIVE_FLAGGED and any(re.fullmatch(r'-\w*[rR]\w*|--recursive|-Recurse', x)
                                                              for x in a))) \
            and any(HOME_ROOT.search(x.strip('\'"')) for x in a if not x.startswith('-')):
        return 'recursive read of a home directory'
    if v in NET_DENIED_EXES:
        return f'{v} (remote shell or transfer tool)'
    # find that runs a command on files named like keys or tokens (find . -name '*.pem'
    # -exec cat {} +), and a link onto a credential directory (mklink /D s ~\.ssh) (A3 W5)
    if v == 'find' and any(x in ('-exec', '-execdir', '-ok', '-okdir') for x in a) and any(
            a[i - 1] in ('-name', '-iname', '-path', '-ipath', '-regex', '-iregex') and FIND_CRED.search(x)
            for i, x in enumerate(a) if i):
        return 'find -exec on credential files'
    if (v == 'mklink' or re.search(r'(?i)-ItemType\s+[\'"]?(?:SymbolicLink|Junction|HardLink)', seg)) \
            and CRED_DIR_ANY.search(seg):
        return 'link onto a credential directory'
    if ctx == 'lit':
        pass                    # a code literal 'env' or 'set' is a dict key, not a command
    elif (v in ('env', 'printenv') and not [x for x in a if not x.startswith('-')]) or (v == 'set' and not a) \
            or (v in ('export', 'declare', 'typeset') and all(x.startswith('-') for x in a)
                and (not a or any(re.fullmatch(r'-[a-zA-Z]*[px][a-zA-Z]*', x) for x in a))) \
            or (v == 'compgen' and any(x in ('-v', '-e') or x == 'variable' for x in a)):
        return 'environment dump'
    if ctx != 'ps' and re.search(r'\$\(|`', seg) and (
            v in NET_VERBS or (v == 'git' and git_sub(a) in GIT_NET)):
        return 'command substitution in a network command'
    # cat $(printf .ssh)/x: the shell builds the path after the hook reads it (audit A4 W1)
    if ctx in ('local', 'ps') and v in SUBST_READ_VERBS and any('$(' in x or (ctx != 'ps' and '`' in x)
                                                                for x in a):
        return 'command substitution in a read path'
    if ctx == 'ps' and (m := PS_INVOKE_WEB.search(seg)) and '$(' in seg[m.end():]:   # in its args
        return 'subexpression in a PowerShell web request'
    return None


def git_sub(a):
    """The git subcommand after global options (-C X, -c X, --opt[=v])."""
    i = 0
    while i < len(a):
        if a[i] in ('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'):
            i += 2
        elif a[i].startswith('-'):
            i += 1
        else:
            return a[i]
    return None


def walk(cmd, ctx='local', depth=0):
    """Yield (ctx, segment) for every segment at every nesting level."""
    if depth > MAX_DEPTH:
        return
    if ctx in ('py', 'js'):
        # interpreter code: judged whole by code_critical(); each string literal may be a
        # shell command (os.system, subprocess, execSync), so it is walked as one, in
        # context 'lit': judged like a local command, but a leading `x` is markdown there
        yield ctx, cmd
        for lit in code_strings(cmd):
            yield from walk(lit, 'lit', depth + 1)
        for m in list(_ARGV_LIST.finditer(cmd))[:50]:   # subprocess.run(['git', 'push'])
            yield from walk(shlex.join(code_strings(m.group(1))), 'lit', depth + 1)
        return
    for seg in split_segments(cmd, bs_escape=(ctx != 'ps')):
        yield ctx, seg
        for inner in subst(seg):
            yield from walk(inner, ctx, depth + 1)
        if ctx == 'ps':
            continue
        toks = tokens(seg)
        toks = strip_env(toks, False) if toks else toks
        if not toks:
            continue
        v = exe(toks[0])
        code = inline_code(v, toks[1:])
        if code is not None:
            yield from walk(code[1], code[0], depth + 1)
        elif v in SH_EXES:
            k = next((i for i, t in enumerate(toks[1:], 1) if re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', t)), None)
            if k is not None and k + 1 < len(toks):
                yield from walk(toks[k + 1], ctx, depth + 1)
        elif v == 'cmd':
            k = next((i for i, t in enumerate(toks[1:], 1) if t.lower() in ('/c', '/k', '/r')), None)
            if k is not None and k + 1 < len(toks):
                yield from walk(' '.join(toks[k + 1:]), ctx, depth + 1)
        elif v in PS_EXES:
            payload, _ = ps_payload(toks)
            if payload:
                yield from walk(payload, 'ps', depth + 1)
        elif v == 'wsl':
            rest = wsl_payload(toks)
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
    if v in ('sudo', 'doas'):  # skip every leading option and the -u/-g/-C value (W2)
        k = 1
        while k < len(toks) and toks[k].startswith('-'):
            k += 2 if toks[k] in ('-u', '-g', '-C', '-D', '-h', '-p', '-r', '-t', '-U', '-T', '--user', '--group') else 1
        if k < len(toks):
            v, toks = exe(toks[k]), toks[k:]
    if v == 'systemctl' and len(toks) > 1 and toks[1] in ('status', 'is-active', 'is-enabled', 'list-units', 'show', 'cat'):
        return None
    if v == 'docker' and len(toks) > 1 and toks[1] in ('ps', 'images', 'version', 'info', 'logs', 'inspect', 'stats'):
        return None
    if v == 'date' and date_sets(toks[1:]):
        return 'date -s'
    if v == 'journalctl' and any(x.startswith('--vacuum') or x in ('--rotate', '--flush') for x in toks[1:]):
        return 'journalctl --vacuum/--rotate/--flush'
    if v == 'git' and len(toks) > 1 and toks[1] in ('status', 'log', 'diff', 'show', 'branch', 'rev-parse'):
        return None
    if v == 'sed' and not any(t.startswith('-i') or t == '--in-place' for t in toks[1:]):
        return None
    if v in REMOTE_WRITE:
        return v
    if re.search(r'(?<![\d&])>(?!&)|\d>(?!&|\s*/dev/null)', strip_quoted(seg)):
        return '>'
    return None


def date_sets(a):
    """date sets the clock: -s/--set (and --s/--se), also inside a bundle like -us (W6)."""
    for x in a:
        if x.startswith('--'):
            if x.split('=', 1)[0] in ('--s', '--se', '--set'):
                return True
        elif x.startswith('-') and len(x) > 1:
            for ch in x[1:]:
                if ch == 's':
                    return True
                if ch in 'dfrI':  # these take the rest of the token as their value
                    break
    return False


def strip_quoted(s):
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", '""', s)


def critical_verb(cmd):
    for rx, name in CRITICAL_VERBS:
        if rx.search(cmd):
            return name
    return None


_CURL_BOOL = set('0123469#aBfgGIijJklLMnNOpqRsSvVZ')  # curl short options that take no value
_CURL_FILE = set('odTDcKFbE')                         # curl short options whose value is a file
_CURL_META_FILE = set('ocDKTbE')                      # file-valued letters vetted for _SHELL_META
_SHELL_META = re.compile(r'[?*\[{}$`#]')  # shell glob/brace/$/backtick; curl's #N from URL globs
_CURL_REMOTE = ('--remote-name', '--remote-name-all', '--remote-header-name')


def _bundle_has_remote(t):
    """True when a short bundle such as -sSO or -OJ holds O or J before its first value letter."""
    for ch in t[1:]:
        if ch in 'OJ':
            return True
        if ch not in _CURL_BOOL:
            return False
    return False


def _curl_target_critical(a):
    """Deny reason when a curl option that writes to / reads a file names a critical path
    (C2/C7b), or when a file argument or -w value holds a shell metacharacter: the shell
    rewrites it after the hook reads it (glob, brace, $var, backtick), so it is refused,
    not judged. Long names match exactly; a short bundle (-sfo PATH, -soPATH, -sd@PATH)
    is read letter by letter, and the first letter that takes a value owns the rest (W1)."""
    long_file = ('--output', '--dump-header', '--cookie-jar', '--trace', '--trace-ascii',
                 '--config', '--upload-file', '--cookie', '--key', '--cert', '--output-dir',
                 '--stderr', '--libcurl', '--etag-save', '--hsts', '--alt-svc')
    long_data = ('--data', '--form', '--json')
    # -O/-J name the output after the URL (or the server): a URL glob ({..} or [..]) makes
    # several names, and a last path segment such as .env or .curlrc is a critical file
    remote = any(t in _CURL_REMOTE or (re.match(r'-[^-]', t) and _bundle_has_remote(t)) for t in a)
    for t in a if remote else ():
        if t.startswith('-'):
            continue
        if '{' in t or '[' in t:
            return REWRITE_HIT
        if CRITICAL_PATH.search(re.split(r'[?#]', t, maxsplit=1)[0].rsplit('/', 1)[-1]):
            return 'curl -O/-J naming a critical file'
    for j, t in enumerate(a):
        nxt = a[j + 1] if j + 1 < len(a) else None
        val = letter = wout = None
        if t.startswith('--'):
            name = t.split('=', 1)[0]
            v = t.split('=', 1)[1] if '=' in t else nxt
            if name in long_file:
                val = v
            elif name.startswith(long_data):
                letter, val = 'd', v
            elif name == '--write-out':
                wout = v
        elif t.startswith('-') and len(t) > 1:
            for k, ch in enumerate(t[1:], 2):
                if ch in _CURL_BOOL:
                    continue
                if ch in _CURL_FILE:
                    letter, val = ch, (t[k:] or nxt)
                elif ch == 'w':
                    wout = t[k:] or nxt
                break
        # -w '%output{[>>]FILE}' writes FILE (curl 8.3+), and every -w variable is %{...}:
        # any -w value with a brace (or other metacharacter) is refused below.
        farg = wout or (val if letter in _CURL_META_FILE or (letter is None and val) else None)
        if farg and _SHELL_META.search(farg):
            return REWRITE_HIT
        if val and letter in ('d', 'F'):  # data/form read a file only after @ or <
            m = re.search(r'[@<](.*)$', val)
            val = m.group(1) if m else None
        if val and CRITICAL_PATH.search(val):
            return 'curl writing/reading a critical path'
    return None


def procsubst(s):
    """Inner text of every >( ... ) process substitution in s (W5)."""
    out, i = [], 0
    while True:
        i = s.find('>(', i)
        if i < 0:
            return out
        depth, j = 1, i + 2
        while j < len(s) and depth:
            depth += {'(': 1, ')': -1}.get(s[j], 0)
            j += 1
        out.append(s[i + 2:j - 1] if not depth else s[i + 2:])
        i = j


def critical(cmd, ctx0='local', _alt=False):
    """Name of the critical write/delete in cmd, or None."""
    hit = critical_verb(cmd) or (not _alt and critical_verb(join_concat(cmd))) or cred_glob(cmd)
    if hit:
        return hit
    if ctx0 not in ('py', 'js') and not _alt:
        # second reads (audit A2): the paths as the shell resolves them, and the segments
        # after a cd with their relative arguments under the cd target
        alt = normalize(cmd)
        if alt is OVER_CAP:
            return OVER_CAP
        if alt is TOO_BIG:
            _UNDECIDED[0], alt = True, None
        cdr = cd_rewrite(cmd)
        if cdr is OVER_CAP:
            return OVER_CAP
        if cdr is TOO_BIG:
            _UNDECIDED[0], cdr = True, None
        for alt in (alt, cdr):
            if alt and alt != cmd and (hit := critical(alt, ctx0, True)):
                return hit
    if ctx0 not in ('py', 'js'):
        # a heredoc or here-string body fed to an interpreter or shell is its payload
        for lead, body in heredocs(cmd):
            kind = interp_kind(lead)
            if kind and body.strip() and (hit := critical(body, kind)):
                return hit
    # a critical path inside a >( ... ) process substitution, e.g. > >(tee <critical>) (W5)
    if any(CRITICAL_PATH.search(' ' + inner) for inner in procsubst(cmd)):
        return 'process substitution writing a critical path'
    # cd into a critical dir then a relative write (W2)
    cd_crit = False
    for seg in split_segments(cmd):
        t = tokens(seg) or []
        v0 = exe(t[0]) if t else ''
        if v0 in ('cd', 'pushd'):
            cd_crit = bool(len(t) > 1 and CRITICAL_PATH.search(t[1]))
            continue
        if cd_crit and (v0 in ('cp', 'mv', 'rm', 'tee') or re.search(r'>', strip_quoted(seg))):
            return 'write in a critical directory after cd'
    # local `cat <critical>` piped into ssh (C4)
    # bounded: an unbounded lazy path made a 199 KB `cat $(printf x) ...` line take 15 s (A5 W4)
    m = re.search(r'(?i)\bcat\s+("[^"]*"|\'[^\']*\'|[^|;&\n]{1,300}?)\s*\|\s*ssh\b', cmd)
    if m and CRITICAL_PATH.search(m.group(1)):
        return 'cat of a critical file piped into ssh'
    ps_cd = False  # PowerShell: Set-Location into a critical dir earlier in the same payload (W4)
    for ctx, seg in walk(cmd, ctx0):
        if ctx != 'ps':
            ps_cd = False
        if ctx in ('py', 'js'):
            hit = code_critical(seg)
            if hit:
                return hit
            continue
        # a $( ) or backtick substitution as the command word: the shell picks the program
        # after the hook reads it ($(echo git) push), so it is denied, not judged (W1)
        if ctx != 'ps' and re.match(r'(?:[A-Za-z_]\w*=\S*\s+)*["\']?(?:\$\(' + ('|`)' if ctx != 'lit' else ')'), seg):
            return 'command substitution as the command word'
        if ctx == 'remote':
            w = remote_write(seg)
            if w:
                return f'remote-host {w}'
            rt = strip_env(tokens(seg) or [], False) or []
            w = (upload_hit(exe(rt[0]), rt[1:]) or settings_denied(rt) or segment_denied(rt, seg, ctx)) if rt else None
            if w:
                return f'remote-host {w}'
            continue
        if ctx == 'ps':
            code = seg.replace('`', '')             # strip PS escape so Re`move-Item matches (W2)
            # text already present verbatim in cmd was scanned above; rescanning every
            # nested $( level of a 200 KB payload doubled its time (audit A2 W3)
            cv = critical_verb(code) if code != seg or code not in cmd else None
            if cv:
                return cv
            if m := PS_CRIT.search(code):
                return f'PowerShell {m.group(0)}'
            if any(PS_SPLICE.search(code, m.end(), ps_args_end(code, m.end()))
                   for m in PS_READ_CMD.finditer(code)):
                return 'credential path (PowerShell path built from pieces)'
            pt = strip_env(tokens(re.sub(r'^\s*&\s*', '', code)) or [], False) or []
            if pt and (w := settings_denied(pt) or segment_denied(pt, code, ctx)
                       or upload_hit(exe(pt[0]), pt[1:])):            # & curl -T x https://e (A4 W6)
                return w
            m = PS_CD.match(code.strip())
            if m:
                ps_cd = bool(m.group(1) and CRITICAL_PATH.search(' ' + m.group(1)))
                continue
            if ps_cd and (PS_WRITE.search(code) or PS_DEL_ALIAS.search(code) or PS_IOFILE.search(code)
                          or PS_INVOKE_WEB.search(code) or '>' in strip_quoted(code)):
                return 'PowerShell write in a critical directory after Set-Location'
            if PS_WRITE.search(code) and CRITICAL_PATH.search(code):
                return 'PowerShell write to a critical path'
            if PS_DEL_ALIAS.search(code) and CRITICAL_PATH.search(code):
                return 'PowerShell write/delete alias on a critical path'
            if PS_IOFILE.search(code) and CRITICAL_PATH.search(code):
                return 'PowerShell [IO.File]/[IO.Directory] write on a critical path'
            if PS_INVOKE_WEB.search(code):
                om = re.search(r'(?i)-OutF\w*[=\s]+(\S+)', code)
                if om and CRITICAL_PATH.search(om.group(1)):
                    return 'Invoke-WebRequest -OutFile to a critical path'
                if re.search(r'(?i)\s-(?:Method\s+[\'"]?(?:Post|Put|Patch)\b|Body\b|InFile\b|Form\b)', code) \
                        and not loopback_only(re.findall(r'[a-zA-Z][\w+.-]*://[^\s\'"`)]+', code)):
                    return 'PowerShell upload to a non-loopback host'
            for mm in re.finditer(r'>>?\|?\s*([^\s;|]+)', code):
                if CRITICAL_PATH.search(mm.group(1)):
                    return 'redirect into a critical path'
            continue
        for mm in re.finditer(r'>>?\|?\s*([^\s;|&]+)', seg):
            if CRITICAL_PATH.search(mm.group(1).strip('\'"')):
                return 'redirect into a critical path'
        if PS_WRITE.match(seg.lstrip()) and CRITICAL_PATH.search(seg):   # a bare cmdlet line
            return 'PowerShell write to a critical path'
        toks = tokens(seg)
        if not toks:
            continue
        toks = strip_env(toks, False) or toks
        v = exe(toks[0])
        args = toks[1:]
        nonflag = [t for t in args if not t.startswith('-')]
        if why := settings_denied(toks) or segment_denied(toks, seg, ctx):
            return why
        if v == 'rm' and any(CRITICAL_PATH.search(t) for t in nonflag):
            return 'rm of a critical path'
        # in-place edits and checkouts that rewrite a guard or other critical file (W2)
        crit_arg = any(CRITICAL_PATH.search(t) for t in nonflag)
        if v == 'sed' and crit_arg and any(t == '--in-place' or t.startswith('--in-place=')
                                           or re.fullmatch(r'-[A-Za-z]*i.*', t) for t in args):
            return 'sed -i on a critical path'
        if v == 'perl' and crit_arg and any(re.fullmatch(r'-[A-Za-z]*i.*', t) for t in args):
            return 'perl -i on a critical path'
        if v == 'git' and git_sub(args) in ('checkout', 'restore', 'apply', 'switch', 'reset') \
                and any(CRITICAL_PATH.search(t) for t in args):
            return f'git {git_sub(args)} onto a critical path'
        if v == 'patch' and crit_arg:
            return 'patch of a critical path'
        if v in WRITE_VERBS and nonflag:
            targets = nonflag if v in ('tee', 'chmod', 'chown', 'touch', 'truncate') else nonflag[-1:]
            if any(CRITICAL_PATH.search(t) for t in targets):
                return f'{v} into a critical path'
        if v == 'curl' and (why := _curl_target_critical(args)):
            return why
        if why := upload_hit(v, args):
            return why
        if v == 'nvidia-smi' and any((f in ('-f', '--filename') and j + 1 < len(args) and CRITICAL_PATH.search(args[j + 1]))
                                     or (f.startswith('--filename=') and CRITICAL_PATH.search(f))
                                     for j, f in enumerate(args)):
            return 'nvidia-smi -f into a critical path'
        if v == 'git' and any((x.startswith('--output=') and CRITICAL_PATH.search(x)) for x in args):
            return 'git --output into a critical path'
        if v == 'uniq' and len(nonflag) >= 2 and any(CRITICAL_PATH.search(t) for t in nonflag[1:]):
            return 'uniq output into a critical path'
        if v == 'sort' and (any('o' in f[1:] and not f.startswith('--') for f in args if f.startswith('-'))
                            or any(f.startswith('--output') for f in args)):
            if any(CRITICAL_PATH.search(t) for t in nonflag):
                return 'sort -o into a critical path'
        if v == 'tree' and any(f == '-o' or f.startswith('--output') for f in args) \
                and any(CRITICAL_PATH.search(t) for t in nonflag):
            return 'tree -o into a critical path'
        if v == 'find' and any(f in ('-fprint', '-fprint0', '-fprintf', '-fls') or f.startswith('-fprint') for f in args) \
                and any(CRITICAL_PATH.search(t) for t in nonflag):
            return 'find -fprint into a critical path'
    return None


def ps_args_end(text, i):
    """End of the arguments of the command word ending at i: the ; | or newline at its own
    depth, or the ) that closes the group it sits in ((gc x) -replace 'a' is not its path)."""
    depth, q = 0, None
    for k in range(i, len(text)):
        c = text[k]
        if q:
            q = None if c == q else q
        elif c in '\'"':
            q = c
        elif c in '({[':
            depth += 1
        elif c in ')}]':
            if depth == 0:
                return k
            depth -= 1
        elif c in ';|\n' and depth == 0:
            return k
    return len(text)


def ps_split_top(text, sep):
    """text split at each `sep` outside quotes, ( ) and { }; None when unbalanced."""
    out, depth, q, start = [], 0, None, 0
    for k, c in enumerate(text):
        if q:
            q = None if c == q else q
        elif c in '\'"':
            q = c
        elif c in '({':
            depth += 1
        elif c in ')}':
            depth -= 1
            if depth < 0:
                return None
        elif c == sep and depth == 0:
            out.append(text[start:k])
            start = k + 1
    return None if depth or q else out + [text[start:]]


UNC_ARG = re.compile(r'(?:-{1,2}[\w-]*=?|[\w.-]*=|@)?[\\/]{2}')


def is_unc(p):
    """True for a network or device path: two or more leading slashes or backslashes in
    either direction (//h/s, \\\\h\\s, \\\\?\\, \\\\.\\). The hook never opens or resolves one:
    that is SMB traffic and an NTLM hash to the host, and seconds of lookup (A13 W2)."""
    return bool(re.match(r'[\\/]{2}', p))


def unc_args(seg, toks):
    """True when a word of seg names a UNC path, as a token (after unquoting), behind a
    flag (-f//h, --file=//h, x=//h, @//h), or as a raw word with its quotes removed (A13 W1).
    A native Windows exe (pwsh, tasklist) may take //Switch: Git Bash passes it as /Switch."""
    native = bool(toks) and (exe(toks[0]) in PS_EXES or exe(toks[0]) == 'tasklist')

    def unc(w):
        return bool(UNC_ARG.match(w)) and not (native and re.fullmatch(r'//[A-Za-z]+', w))
    return any(unc(x) for x in toks) or any(unc(w.replace('"', '').replace("'", '')) for w in seg.split())


def cwd_in_repo():
    if _RO_CWD[0] is False:
        return False                            # a cd earlier in the command (A7)
    return in_repo(_RO_CWD[0] or os.getcwd())


PATH_MAX_PARTS = 64                     # a repo path has at most this many parts (A8 R1)
GLOB_CAP = 4096                         # matches a wildcard repo path may have (A8 W2)


def is_link(path):
    """True for a symlink or any other reparse point (a junction) at path itself."""
    if is_unc(path):
        return True                             # never looked up (A13 W2)
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & 0x400)


def path_has_link(v):
    """True when relative path v (under the cwd) passes through or names a link, or a
    wildcard in it matches one (bench/results/latest is a symlink; audit A7 W4)."""
    cur = _RO_CWD[0] or os.getcwd()
    if is_unc(cur) or is_unc(v):
        return True                             # never looked up (A13 W2)
    parts = [x for x in re.split(r'[\\/]', v) if x not in ('', '.')]
    if len(parts) > PATH_MAX_PARTS:
        return True                             # deeper than any repo path (A8 R1: glob recursion)
    for i, part in enumerate(parts):
        if re.search(r'[*?\[]', part):
            ms = list(itertools.islice(glob.iglob(os.path.join(cur, *parts[i:]), include_hidden=True), GLOB_CAP + 1))
            if len(ms) > GLOB_CAP:
                return True                     # too many matches to check: fail closed (A8 W2)
            for m in ms:
                rel = os.path.relpath(m, cur).split(os.sep)
                if any(is_link(os.path.join(cur, *rel[:k + 1])) for k in range(len(rel))):
                    return True
            return False
        cur = os.path.join(cur, part)
        if is_link(cur):
            return True
    return False


def ps_ro_value(cls, v):
    """True when value v (unquoted) is in class cls of PS_RO_SPEC."""
    if '\\\\' in v or '//' in v or '..' in v:
        return False                            # a UNC path or a parent directory (audit A6 C3)
    if cls == 'class':
        return v.lower() in PS_RO_CLASSES
    if re.search(r'(?i)(?:cim|win32)_', v):
        return False                            # a CIM class only where the class is checked
    if cls == 'prop':                           # names; the producer's list is checked later
        return all(re.fullmatch(r'(?:\x01C)?\w+', x) for x in v.split(','))
    if cls == 'propone':
        return bool(re.fullmatch(r'\w+', v))
    if cls == 'word':
        return bool(re.fullmatch(r'[\w.-]+', v))
    if cls == 'cmdname':                        # a command name, never a script file (A6 C5)
        return bool(re.fullmatch(r'[\w-]+(?:\.exe)?', v, re.I))
    if cls == 'glob':
        return bool(re.fullmatch(r'[\w.*?-]+', v))
    if cls == 'int':
        return bool(re.fullmatch(r'[0-9]{1,6}', v))
    if cls == 'depth':
        return v in ('1', '2', '3')
    if cls == 'text':
        return bool(re.fullmatch(r'[\w .,!-]*', v))
    if cls == 'filter':
        return bool(re.fullmatch(r'\x01F\w+', v))
    if cls == 'filesystem':
        return v.lower() == 'filesystem'
    if cls == 'erroraction':
        return v.lower() in ('silentlycontinue', 'stop', 'continue', 'ignore')
    if cls == 'repo_path':                      # relative, under the cwd: no drive, root, ~, $ or :
        return bool(re.fullmatch(r'[\w.*?/\\-]+', v)) and not re.match(r'[\\/]', v) and not path_has_link(v)
    return False


def ps_ro_pipeline(text, prop=None):
    """True when text is `Producer args | Consumer args ...` (PS_RO_SPEC parameters, each
    value in its class), every property it names is in the producer's PS_RO_PROPS list,
    and its output is either a listed selection or a producer view that is safe whole
    (audits A6, A7). prop is the property read in (pipeline).Prop."""
    parts = ps_split_top(text, '|')
    if not parts:
        return False
    props, src, sealed, json_ok = set(), None, False, False
    for i, part in enumerate(parts):
        part = re.sub(r'\s*,\s*', ',', part.strip())
        if not re.fullmatch(r"(?:(?:'[^']*'|\"[^\"$`]*\"|[^\s'\"]+)(?:\s+|$))+", part):
            return False
        words = re.findall(r"'[^']*'|\"[^\"$`]*\"|[^\s'\"]+", part)
        cmd = words[0].lower()
        spec = PS_RO_SPEC.get(cmd)
        if spec is None or (cmd not in PS_RO_PRODUCERS if i == 0 else cmd not in PS_RO_CONSUMERS):
            return False                        # a producer only first, a consumer only after |
        if cmd in PS_RO_PATH_CMDLETS and not cwd_in_repo():
            return False                        # a relative path from outside the repo (A6 W3)
        vals = []
        args, k, npos = words[1:], 0, 0
        while k < len(args):
            w = args[k]
            k += 1
            m = re.fullmatch(r'-([A-Za-z]\w*)(?::(.+))?', w)
            if m:
                name = m.group(1).lower()
                cls = spec.get(name)
                if cls is None:
                    return False                # unknown or abbreviated parameter
                if cls == 'none':
                    if m.group(2) is not None:
                        return False
                    continue
                if m.group(2) is not None:
                    v = m.group(2)
                elif k < len(args):
                    v, k = args[k], k + 1
                else:
                    return False
            else:
                name, cls = '', spec.get('')
                if cls is None or (npos and cmd != 'write-output'):
                    return False
                npos += 1
                v = w
            if len(v) > 1 and v[0] in '\'"' and v[-1] == v[0]:
                v = v[1:-1]                     # quoted values are judged alike (A6 C1)
            if not ps_ro_value(cls, v):
                return False
            vals.append((name, cls, v))
        if cmd == 'get-childitem' and re.search(r'(?i)(?<!\S)-name\b', part) \
                and re.search(r'(?i)(?<!\S)-(?:recurse|depth)\b', part):
            return False                        # -Name -Recurse follows links (A8 W1)
        if i == 0:
            src = next((v.lower() for _, c, v in vals if c == 'class'), cmd)
            if cmd == 'get-ciminstance' and src == cmd:
                return False                    # a class is required
            props = _PROPS_LC[src]
        names = [re.sub(r'^\x01[CF]', '', x).lower() for _, c, v in vals if c in ('prop', 'propone', 'filter')
                 for x in v.split(',')]
        if any(x not in props for x in names):
            return False                        # a property not on the producer's list (A7 C1, C2)
        listed = bool(names) and cmd != 'where-object' and cmd != 'sort-object'
        if cmd == 'get-computerinfo':
            if not listed:
                return False                    # the full dump; name the properties
            sealed = json_ok = True
        elif cmd == 'select-object' and listed:
            sealed = json_ok = True
            if any(n == 'expandproperty' for n, _, _ in vals):
                props = set()                   # scalars from here on
        elif cmd == 'measure-object':
            sealed, props = True, PS_RO_MEASURE
        elif cmd in ('format-table', 'format-list'):
            if not listed and not sealed and src not in PS_RO_VIEW_OK:
                return False                    # a default view that may carry identity
            sealed = True
        elif cmd == 'convertto-json' and not json_ok:
            return False                        # every property: a Select-Object list first
    if prop is not None:
        return prop.lower() in props
    return sealed or not src.startswith('win32_')    # bare Get-CimInstance: owner, serial


def ps_ro_statement(st):
    """One statement: an exact $PSVersionTable form, (pipeline).Prop, [math]::Round(
    (pipeline).Prop/1KB|1MB|1GB[,N]) or a plain pipeline."""
    if st.lower() in PS_RO_EXACT:
        return True
    m = re.fullmatch(r'\[math\]::Round\((\(.*\)\.\w+)\s*/\s*1[KMG]B\s*(?:,\s*\d)?\)', st, re.I | re.S)
    if m:
        st = m.group(1)
    m = re.fullmatch(r'\((.*)\)\.(\w+)', st, re.S)
    if m:
        return ps_ro_pipeline(m.group(1), m.group(2))
    return ps_ro_pipeline(st)


def ps_readonly(payload):
    """True only when the whole payload is allowlisted (audit A5: the blocklist this
    replaced allowed Environment::, -f/-replace splices and globs). No `(`, `[`, `::`,
    `$(`, backtick, operator, assignment, call or dot-source operator, script block or
    unknown cmdlet outside the survey forms; never env: or Environment."""
    code = re.sub(r'\s*(?:2>\s*\$null|2>&1|>\s*\$null)', ' ', payload, flags=re.I)
    code = code.replace('\\$', '$')     # "\$_" in a bash double-quoted payload: bash passes $_
    if re.search(r'(?i)env:|environment|`|\$\(', code):
        return False
    code = PS_RO_FILTER.sub(lambda m: ' \x01F' + m.group(1) + ' ', code)
    code = PS_RO_CALC.sub(lambda m: ' \x01C' + (m.group(1) or m.group(2)) + ' ', code)
    stmts = ps_split_top(code, ';')
    if stmts is None:
        return False
    stmts = [s.strip() for x in stmts for s in x.split('\n') if s.strip()]
    return bool(stmts) and all(ps_ro_statement(s) for s in stmts)


def _url_host(u):
    m = re.match(r'^[a-zA-Z][\w+.-]*://([^/?#]*)', u)
    if not m:
        return None
    auth = m.group(1)
    if '@' in auth:
        auth = auth.rsplit('@', 1)[1]
    if auth.startswith('['):
        return auth[1:auth.find(']')].lower() if ']' in auth else auth[1:].lower()
    return auth.split(':', 1)[0].lower()


def curl_ok(args):
    """Allow only safe options and a URL whose host is exactly 127.0.0.1/localhost (C2).
    -w / --write-out in any form is never allowed: its format can write a file
    (%output{FILE}), and bash can build that format after the hook reads it."""
    skip = expect_get = False
    url_seen = False
    for t in args:
        if skip:
            skip = False
            if expect_get:
                expect_get = False
                if t.upper() != 'GET':
                    return False
            continue
        if t in ('-s', '-S', '-f', '-L', '-I', '-i', '--silent', '--fail', '--location', '--head',
                 '--show-error', '--fail-with-body'):
            continue
        if re.fullmatch(r'-[sSfLIi]+', t):
            continue
        if t in ('-X', '--request'):
            skip = expect_get = True; continue
        if t in ('-H', '--header', '-m', '--max-time', '--connect-timeout',
                 '-A', '--user-agent'):
            skip = True; continue
        if t.startswith(('--max-time=', '--connect-timeout=', '--header=', '--user-agent=')):
            continue
        if t.startswith('-X'):
            if t[2:].upper() != 'GET':
                return False
            continue
        if t.startswith('-'):
            return False  # unknown / output / data option -> no decision
        if _url_host(t) not in ('127.0.0.1', 'localhost'):
            return False
        url_seen = True
    return url_seen


def flags_ok(a, flags, valued):
    """Every dash token is a listed flag (a valued long flag may use --flag=value); the
    token after a valued flag is its value; other tokens are positionals (pattern, paths)."""
    i = 0
    while i < len(a):
        t = a[i]
        if t.startswith('-') and t != '-':
            name = t.split('=', 1)[0] if t.startswith('--') else t
            if name not in flags or ('=' in t and name not in valued):
                return False
            if name in valued and '=' not in t:
                i += 1
                if i >= len(a):
                    return False
        i += 1
    return True


def find_ok(a):
    """find PATH... EXPR with EXPR built only from FIND_VALUED/FIND_BARE."""
    i = 0
    while i < len(a) and not (a[i].startswith('-') or a[i] in ('!', '(', ')')):
        i += 1
    while i < len(a):
        t = a[i]
        if t in FIND_VALUED:
            i += 1
            if i >= len(a):
                return False
        elif t not in FIND_BARE:
            return False
        i += 1
    return True


def shell_expands(s):
    """True when bash would expand something in s before the command sees it: a $ or
    backtick outside single quotes, or an unquoted { } * ? [ ] (brace expansion, globs), or
    an unquoted ~ at word start or after = or :. Single-quoted spans and backslash-escaped
    characters are literal; inside double quotes only $ and backtick expand."""
    q, i = None, 0
    while i < len(s):
        c = s[i]
        if q == "'":
            q = None if c == "'" else q
        elif c == '\\':
            i += 1
        elif c in '$`':
            return True
        elif c == '"':
            q = None if q == '"' else '"'
        elif q is None:
            if c == "'":
                q = "'"
            elif c in '{}*?[]' or (c == '~' and (i == 0 or s[i - 1] in ' \t\n=:')):
                return True
        i += 1
    return False


def seg_readonly(seg, ctx, depth):
    if ctx == 'ps':
        return ps_readonly(seg)
    # Any shell expansion means the shell rewrites the segment after the hook reads it: a
    # word-split $(...), a "$X" that is a flag, ${Y@P} running a command, -{delete,delete}
    # or a glob that becomes a flag, ~user. No grammar over expansions survived audit
    # (5 rounds), so no decision (critical() has already scanned the raw text for denies).
    # A $ or backtick anywhere means no decision; a PowerShell payload may keep $_ only
    # where bash leaves it (single quotes, \$).
    if shell_expands(seg):
        return False
    lead = tokens(seg)
    if not (lead and exe(lead[0]) in PS_EXES) and ('$' in seg or '`' in seg):
        return False
    bare = strip_quoted(seg)
    if '<(' in bare:
        return False
    bare = re.sub(r'\d?>&\d|&>\s*/dev/null|\d?>\s*/dev/null', '', bare)
    if '>' in bare or '<' in bare:
        return False
    toks = tokens(re.sub(r'\s\d?>&\d|\s&>\s*/dev/null|\s\d?>\s*/dev/null', ' ', seg))
    if not toks:
        return False
    if all(re.match(r'^[A-Za-z_]\w*=', t) for t in toks):
        return all(env_safe(t) for t in toks)
    toks = strip_env(toks)
    if not toks:
        return False
    if unc_args(seg, toks):
        return False                        # a UNC path: SMB traffic and an NTLM hash to any host (A13 W1)
    v, a = exe(toks[0]), toks[1:]
    if v in ('cd', 'pushd', 'popd', 'chdir'):
        _RO_CWD[0] = False                  # a cd inside a script: its later paths (A7, A8)
    if v in READ_VERBS:
        return True
    if v == 'date':
        return not date_sets(a)
    if v == 'file':
        return flags_ok(a, FILE_FLAGS, set())
    if v == 'uniq':
        return len([t for t in a if not t.startswith('-')]) <= 1
    if v == 'sort':
        return not (any('o' in f[1:] and not f.startswith('--') for f in a if f.startswith('-'))
                    or any(f.startswith('--output') or f == '-o' for f in a))
    if v == 'tree':
        return flags_ok(a, TREE_FLAGS, TREE_VALUED)
    if v == 'find':
        return find_ok(a)
    if v == 'nvidia-smi':
        return all(x.startswith('--query') or x.startswith('--format') or x in ('-L', '-q', '--list-gpus', '--help', '-h') for x in a)
    if v == 'rg':
        return flags_ok(a, RG_FLAGS, RG_VALUED)
    if v == 'wmic':
        return len(a) >= 2 and a[1].lower() in ('get', 'list')
    if v == 'hostname':
        return all(x in HOSTNAME_FLAGS_OK for x in a)
    if v in VERSION_ONLY:
        return len(a) == 1 and a[0] in VERSION_FLAGS
    if v == 'git':
        return git_ok(a)
    if v == 'docker':
        return bool(a) and (a[0] in ('version', 'ps', 'images', 'info', '--version') or a[:2] == ['context', 'ls'])
    if v == 'curl':
        return curl_ok(a)
    if v == 'wsl':
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
        k = ps_payload_index(toks[1:])
        if k is None:
            return False
        return all((o := ps_opt(f)) and o[1] is None and o[0] in ('noprofile', 'nologo', 'noninteractive')
                   for f in a[:k]) and ps_readonly(payload)
    return False


def git_ok(a):
    while a and (a[0] in ('-C',) and len(a) > 1 or a[0] in ('--no-pager',)):
        a = a[2:] if a[0] == '-C' else a[1:]
    if not a:
        return False
    sub, rest = a[0], a[1:]
    if sub in ('status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', '--version'):
        return not any(x.startswith('--ou') or x == '--ext-diff' for x in rest)   # --outp=x, a diff driver
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
    if v in ('source', '.') and a and not a[0].startswith('-'):
        return a[0], 'sh'
    if v in ('bash', 'sh'):
        i = 0
        while i < len(a):                   # skip shell options (-e, -x, +x, -o pipefail, --)
            x = a[i]
            if x == '--':
                i += 1
                break
            if x.startswith('--') and len(x) > 2:
                i += 2 if x in ('--rcfile', '--init-file') else 1
                continue
            if not re.fullmatch(r'[-+][A-Za-z]+', x):
                break
            if x[0] == '-' and re.search('[cs]', x[1:]):
                return None                 # -c payload (judged by walk) or -s stdin
            i += 2 if x[-1] in 'oO' else 1
        if i < len(a) and a[i] != '-' and not re.match(r'\d*[<>]|&>', a[i]):
            return a[i], 'sh'
        return None
    if v == 'cmd':                          # cmd /c x.bat: the batch file is read like a script
        k = next((i for i, t in enumerate(a) if t.lower() in ('/c', '/k')), None)
        if k is not None and k + 1 < len(a) and re.search(r'(?i)\.(?:bat|cmd)$', a[k + 1]):
            return a[k + 1], 'bat'
    if v in PS_EXES:
        pl, f = ps_payload(toks)
        if f is not None:
            return f, 'ps'
        i = 0
        while pl is None and i < len(a):    # pwsh [options] ./x.ps1: the first positional is -File
            x = a[i]
            o = ps_opt(x)
            if o is None:
                if x.startswith('-'):
                    i += 1
                    continue
                return x, 'ps'
            n = o[0]
            if any(w.startswith(n) for w in ('command', 'encodedcommand', 'file')):
                break
            i += 2 if n in PS_VALUED and o[1] is None else 1
    py = bool(PY_EXE.fullmatch(v))
    if py or v == 'node':
        if inline_code(v, a) is not None:
            return None                     # inline payload: judged by critical() via walk()
        valued = PY_VALUED if py else NODE_VALUED
        i = 0
        while i < len(a):                   # skip interpreter options (python -I, node --test)
            t = a[i]
            if t == '--':
                i += 1
                break
            if not t.startswith('-') or t == '-':
                break
            if py and re.fullmatch(r'-[A-Za-z]*m.*', t, re.S):
                return None                 # -m module: no file to read
            i += 2 if t in valued else 1
        if i < len(a) and a[i] != '-' and not re.match(r'\d*[<>]|&>', a[i]):
            return a[i], ('py' if py else 'js')
    return None


SCRIPT_EXT = {'ps1': 'ps', 'psm1': 'ps', 'sh': 'sh', 'py': 'py', 'js': 'js', 'mjs': 'js', 'cjs': 'js', 'bat': 'bat', 'cmd': 'bat'}


def ps_script_targets(payload):
    """Script files a PowerShell payload runs (audit A3 C1, A4 W5): a statement that is a
    path (./up.ps1, also inside ( ), $( ), @( ), { }, after ! , -not or [void]), the & or .
    call operator on a path, an interpreter given a file (& python x.py, cmd /c x.bat),
    Import-Module/ipmo of a path, and literal text handed to InvokeScript or
    [scriptblock]::Create. They are judged like -File. Returns (targets, deny reason): the
    call operator on a variable or expression, and script text built at run time, hide the
    command, so they are denied; & on a plain program name (& git status) is judged as
    the command it runs (A4 W6)."""
    out = []
    for m in re.finditer(r'(?i)(?:\.InvokeScript|\[(?:System\.Management\.Automation\.)?ScriptBlock\]::Create'
                         r'|\.NewScriptBlock)\s*\(\s*(.?)', payload):
        q = m.group(1)
        body = re.match(r"'([^']*)'|\"([^\"$]*)\"", payload[m.end() - 1:]) if q in ("'", '"') else None
        if not body:
            return out, 'PowerShell script text built at run time'
        sub, why = ps_script_targets(body.group(1) if body.group(1) is not None else body.group(2))
        if why:
            return out, why
        out += sub
    if re.search(r'(?<![\w.])&\s*[($]', payload):
        return out, 'PowerShell call operator on a computed command'
    for stmt in re.split(r'[;|\n{}()]|&&|\$\(|@\(', payload.replace('\\', '/'))[:400]:
        op = re.match(r'^\s*(?:&|\.(?=\s))\s*', stmt)
        s = (stmt[op.end():] if op else stmt).strip()
        s = re.sub(r'^(?:[!,+*/=\s]|-not\b|\[\w+\])+', '', s).strip()
        toks = tokens(s) if s else None
        if not toks:
            if op and s:
                return out, 'PowerShell call operator on a computed command'
            continue
        fp = next((toks[k + 1] if k + 1 < len(toks) else '' for k, x in enumerate(toks)
                   if re.fullmatch(r'(?i)-FilePath', x)), None)
        fp = fp if fp is not None else next((x[10:] for x in toks if re.match(r'(?i)-FilePath:', x)), None)
        if fp is not None:                  # Start-Job -FilePath x.ps1 runs the file
            out.append((fp, 'ps'))
            continue
        if exe(toks[0]) in ('import-module', 'ipmo') or [x.lower() for x in toks[:2]] == ['using', 'module']:
            rest = toks[2:] if toks[0].lower() == 'using' else toks[1:]
            pth = next((re.sub(r'(?i)^-Name:', '', x) for x in rest
                        if not x.startswith('-') or re.match(r'(?i)-Name:', x)), '')
            if re.search(r'[\\/]|\.ps[md]?1$', pth, re.I):
                out.append((pth, 'ps'))
            continue
        m = re.search(r'\.([A-Za-z0-9]+)$', toks[0])
        if m and m.group(1).lower() in SCRIPT_EXT and exe(toks[0]) not in PS_EXES:
            out.append((toks[0], SCRIPT_EXT[m.group(1).lower()]))
        elif st := script_target(toks):
            out.append(st)
        elif op and not re.fullmatch(r'[A-Za-z0-9_][\w.-]*', toks[0]):
            return out, 'PowerShell call operator on a path or expression'
    return out, None


def resolve(path, cwd):
    p = os.path.expanduser(path)
    m = re.match(r'^/([a-zA-Z])/(.*)$', p)
    if m:
        p = f'{m.group(1).upper()}:/{m.group(2)}'
    return p if os.path.isabs(p) else os.path.join(cwd or os.getcwd(), p)


def ps_strip_block_comments(text):
    """text with each <# ... #> block blanked, line count kept (help prose is not code)."""
    out, i = [], 0
    while (j := text.find('<#', i)) >= 0:
        k = text.find('#>', j + 2)
        if k < 0:
            break
        out.append(text[i:j])
        out.append('\n' * text.count('\n', j, k))
        i = k + 2
    out.append(text[i:])
    return ''.join(out)


def ps_literal_vars(text, full):
    """{name: literal} for a repo script under bench/ or scripts/: each $name assigned
    exactly once, on its own line, to a quoted literal, and never a parameter, a scoped
    ($script:name) or Set-Variable target, a foreach variable or an -OutVariable (audit A4
    W0b: $base = "http://127.0.0.1:$Port" makes -Uri "$base/v1" loopback)."""
    real = os.path.normcase(os.path.realpath(full))
    if not any(real.startswith(os.path.join(REPO_ROOT, d) + os.sep) for d in ('bench', 'scripts')):
        return {}
    # a variable reachable by name, by reference, or from code the file runs in its scope (A5)
    if re.search(r'(?im)PSVariable|\b(?:Get|Set|New|Clear|Remove)-Variable\b|\[ref\]|\bImport-Module\b|\bipmo\b'
                 r'|^\s*\.\s+\S|(?<![\w.>&])&(?!&)\s*\S|(?:^|[;{(])\s*\.\s', text):
        return {}
    pm = re.search(r'(?i)\bparam\s*\(', text)
    params = ''
    if pm:                              # the param( ) block, balanced
        depth, k = 0, pm.end() - 1
        while k < len(text):
            depth += {'(': 1, ')': -1}.get(text[k], 0)
            if depth == 0:
                break
            k += 1
        params = text[pm.start():k + 1].lower()
    lits = {}
    for m in re.finditer(r'(?m)^[ \t]*\$(\w+)[ \t]*=[ \t]*("[^"\n`]*"|\'[^\'\n]*\')[ \t]*$', text):
        name = m.group(1).lower()
        if pm and pm.start() <= m.start() <= pm.start() + len(params):
            continue
        if '$' + name in params:
            continue
        if re.search(r'\$\{\w+:' + re.escape(name) + r'\}|\$\{' + re.escape(name) + r'\}\s*[-+*/]?=(?!=)'
                     r'|^[^=\n]*(?:\$\{?(?:\w+:)?' + re.escape(name) + r'\b\}?\s*,|,\s*\$\{?(?:\w+:)?'
                     + re.escape(name) + r'\b)[^=\n]*=(?!=)', text, re.I | re.M):
            continue                    # ${script:name}, ${name} = ..., $a, $name = ...
        others = re.findall(r'\$(?:\w+:)?' + re.escape(name) + r'\b\s*[-+*/]?=(?!=)'
                            r'|\b(?:Set-Variable|sv|New-Variable|nv)\s+(?:-Name\s+)?[\'"]?' + re.escape(name) + r'\b'
                            r'|-(?:OutVariable|ov|ErrorVariable|ev|PipelineVariable|pv)\s+[\'"]?' + re.escape(name) + r'\b'
                            r'|\bforeach\s*\(\s*\$' + re.escape(name) + r'\b', text, re.I)
        if len(others) == 1:
            lits[name] = m.group(2)[1:-1]
    return lits


def check_script(path, kind, cwd):
    """'allow' when every line is read-only, ('deny', reason) for the first critical
    line, None (no decision) when the file is unreadable, over the read cap, or a line
    is neither read-only nor a critical write."""
    full = resolve(path, cwd)
    if is_unc(full):
        return None                     # never opened or resolved (A13 W2)
    if os.path.normcase(os.path.realpath(full)) in EXEMPT_SCRIPTS:
        return None                     # the exempt files: they quote denied shapes
    try:
        with open(full, encoding='utf-8', errors='replace') as f:
            text = f.read(SCRIPT_CAP + 1)
    except (OSError, ValueError):       # ValueError: a NUL in the path (property test)
        return None
    if len(text) > SCRIPT_CAP:          # over the cap: never allow (C5)
        return None
    # a non-ASCII script, or one with a NUL or an ALLOW_STOP token, is never allowed (ruling 45, A12 W2)
    ascii_ok = text.isascii() and '\x00' not in text and not allow_stop(text)
    if kind in ('py', 'js'):            # never allowed; denied on a hit, else no decision
        hit = critical(text, kind)
        if not hit:
            return None
        lines = text.splitlines()
        hits = [(i, critical(ln, kind)) for i, ln in enumerate(lines, 1) if ln.strip()]
        n = next((i for i, h in hits if h == hit), None) or next((i for i, h in hits if h), None)
        if n is None:                   # a cross-line hit: point at the first API call
            m = next((m for rx in (CODE_WRITE, CODE_UPLOAD) for m in [rx.search(text)] if m), None)
            n = text.count('\n', 0, m.start()) + 1 if m else 1
        line = lines[n - 1].strip() if n <= len(lines) else ''
        what, tail = ('refused', REWRITE_SUFFIX) if hit == REWRITE_HIT else ('a critical write', NOT_RETRYABLE)
        return 'deny', f'lis-guard: script {path} line {n} is {what} ({hit}): {line[:160]!r}; {tail}.'
    lines = re.sub(r'\\\r?\n', ' ', text).splitlines()
    lits = {}
    if kind == 'ps':
        text = ps_strip_block_comments(text)
        lines = text.splitlines()
        lits = ps_literal_vars(text, full)
    all_readonly = True
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        judged = re.sub(r'\$(\w+)', lambda m: lits.get(m.group(1).lower(), m.group(0)), line) if lits else line
        # a line over the command cap is never judged in parts (A5 W4: bounds the time)
        hit = OVER_CAP if len(judged) > MAX_INPUT else critical(judged, 'ps' if kind == 'ps' else 'local')
        if hit:
            what, tail = ('refused', REWRITE_SUFFIX) if hit == REWRITE_HIT else ('a critical write', NOT_RETRYABLE)
            return 'deny', f'lis-guard: script {path} line {n} is {what} ({hit}): {line[:160]!r}; {tail}.'
        if all_readonly and not script_line_ok(line, kind):
            all_readonly = False
    return 'allow' if all_readonly and ascii_ok else None


def patch_hit(cmd, cwd):
    """Deny reason when `git apply F` or `patch [-i F | < F]` reads a diff whose file
    headers name a critical path (a guard file, .claude, .ssh, ...) (W2)."""
    for seg in split_segments(cmd):
        toks = strip_env(tokens(seg) or [], False) or []
        if not toks:
            continue
        v, a = exe(toks[0]), toks[1:]
        if v == 'git' and git_sub(a) == 'apply':
            files = [t for t in a[a.index('apply') + 1:] if not t.startswith('-')]
        elif v == 'patch':
            files = [a[j + 1] for j, t in enumerate(a[:-1]) if t == '-i']
            files += [t.split('=', 1)[1] for t in a if t.startswith('--input=')]
        else:
            continue
        files += re.findall(r'<\s*([^\s<>;|&]+)', seg)
        for f in files[:8]:
            if is_unc(resolve(f.strip('\'"'), cwd)):
                continue                # never opened (A13 W2); critical() has scanned the command
            try:
                with open(resolve(f.strip('\'"'), cwd), encoding='utf-8', errors='replace') as fh:
                    text = fh.read(SCRIPT_CAP)
            except OSError:
                continue
            for m in re.finditer(r'(?m)^(?:\+\+\+|---|diff --git|rename to|copy to)\s+(.+)$', text):
                if CRITICAL_PATH.search(' ' + m.group(1)):
                    return 'patch file touching a critical path'
    return None


CWD_VERBS = {'cd', 'pushd', 'popd', 'chdir', 'set-location', 'sl', 'push-location', 'pop-location'}


def ps_workdir(toks):
    """The -WorkingDirectory (-wd, any prefix, colon form too) value of a pwsh token list."""
    for k, x in enumerate(toks[1:], 1):
        name, val = ps_opt(x) or ('', None)
        if name == 'wd' or (name and 'workingdirectory'.startswith(name)):
            return val if val is not None else toks[k + 1] if k + 1 < len(toks) else ''
    return None


def profile_runs(toks, st):
    """True when the interpreter that runs script st may first run a profile or settings
    file that can cd (pwsh without -NoProfile, -SettingsFile, -ConfigurationFile; bash -l,
    -i, --login, --rcfile, --init-file) (audit A9)."""
    v = exe(toks[0])
    opts = toks[1:toks.index(st[0])] if st[0] in toks[1:] else toks[1:]
    if v in PS_EXES:
        names = [o[0] for o in map(ps_opt, opts) if o]
        return 'noprofile' not in names or any(
            (len(n) > 1 and 'settingsfile'.startswith(n)) or n.startswith('configurationf') for n in names)
    if v in SH_EXES:
        return any(x in ('--login', '--rcfile', '--init-file', '--interactive')
                   or re.fullmatch(r'-[A-Za-z]*[li][A-Za-z]*', x) for x in opts)
    return False


def cwd_moves(cmd, cwd):
    """True when any segment, at any nesting level or in a heredoc body, changes directory
    (cd, Set-Location, ...) or starts PowerShell in another -WorkingDirectory (A8 C1)."""
    for text in [cmd] + [body for _, body in heredocs(cmd)]:
        for ctx, seg in walk(text):
            if ctx in ('py', 'js'):
                continue
            toks = (tokens(seg) if ctx != 'ps' else None) or seg.split()
            toks = strip_env(toks, False) or toks
            if not toks:
                continue
            v = exe(toks[0])
            if v in CWD_VERBS:
                return True
            if v in PS_EXES:
                wd = ps_workdir(toks)
                if wd is not None and (is_unc(resolve(wd.strip('\'"'), cwd)) or is_unc(cwd or '')):
                    return True             # never resolved (A13 W2)
                if wd is not None and os.path.normcase(os.path.realpath(resolve(wd.strip('\'"'), cwd))) != \
                        os.path.normcase(os.path.realpath(cwd or os.getcwd())):
                    return True
    return False


def in_repo(path):
    if is_unc(path):
        return False                        # never resolved (A13 W2)
    p = os.path.normcase(os.path.realpath(path))
    return p == REPO_ROOT or p.startswith(REPO_ROOT.rstrip(os.sep) + os.sep)


def decide(cmd, cwd=None):
    """('deny'|'allow', reason) or None for no decision."""
    if not cmd.strip():
        return None
    ascii_ok = cmd.isascii() and '\x00' not in cmd     # the allow path is ASCII-only (ruling 45)
    cmd = ps_dashes(cmd)
    _RO_CWD[0] = cwd
    _UNDECIDED[0] = False
    hit = critical(cmd) or patch_hit(cmd, cwd)
    if hit:
        return 'deny', deny_reason(hit)
    if _UNDECIDED[0]:
        return None                         # a cd rewrite too large to read (A10 W2)
    scripts, others = [], []
    scripts_ok = True
    for seg in split_segments(cmd):
        toks = tokens(seg)
        if toks and strip_env(toks) is None:  # unsafe env prefix: still deny-scan a script
            scripts_ok = False
        toks = strip_env(toks, False) if toks else toks
        st = script_target(toks) if toks else None
        (scripts if st else others).append(st or seg)
        if st and (profile_runs(toks, st) or re.match(r'[A-Za-z]:(?![\\/])', st[0])):
            scripts_ok = False              # a profile may cd first; C:x.ps1 is drive-relative (A9)
        if st and unc_args(seg, toks):
            scripts_ok = False              # a UNC script or argument (A13 W1/W2)
        if st and exe(toks[0]) in PS_EXES and '\\' in seg:     # pwsh .\up.ps1 (audit A5 W3)
            raw = strip_env(tokens(seg.replace('\\', '/')) or [], False)
            st2 = script_target(raw) if raw else None
            if st2 and st2 != st and is_unc(resolve(st2[0], cwd)):
                scripts_ok = False          # pwsh \\h\s\x.ps1: never looked up (A13 W2)
            elif st2 and st2 != st and os.path.isfile(resolve(st2[0], cwd)):
                scripts.append(st2)
        if toks and not st and exe(toks[0]) in PS_EXES and (pl := ps_payload(toks)[0]):
            pst, why = ps_script_targets(pl)
            if why:
                return 'deny', deny_reason(why)
            for path, kind in pst:          # a payload that runs a file the hook cannot read
                if is_unc(resolve(path, cwd)) or not os.path.isfile(resolve(path, cwd)):
                    return 'deny', deny_reason(f'PowerShell payload runs {path}, which the hook cannot read')
            scripts.extend(pst)
    if cwd_moves(cmd, cwd):
        _RO_CWD[0] = False                  # a script's paths are not known to be under the repo (A8 C1)
        if scripts:
            scripts_ok = False              # the script run may not be the file read here (property test)
    if any(not in_repo(resolve(path, cwd)) for path, _ in scripts):
        _RO_CWD[0] = False
        scripts_ok = False                  # a script outside the repo is never allowed (A12 W1)
    seen = {}                               # one check per script per call: source ./ok.sh x N (A6 W5)
    for path, kind in scripts:
        if (path, kind) not in seen:
            seen[path, kind] = check_script(path, kind, cwd)
        r = seen[path, kind]
        if isinstance(r, tuple):
            return r
        scripts_ok = scripts_ok and r == 'allow'
    if is_unc(cwd or ''):
        return None                         # a UNC cwd: every relative path is a network path (A13 W2)
    if scripts_ok and ascii_ok and not allow_stop(cmd) and all(seg_readonly(s, 'local', 0) for s in others):
        return 'allow', 'lis-guard: read-only command'
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    if data.get('tool_name', 'Bash') != 'Bash':
        return 0
    ti = data.get('tool_input')
    if not isinstance(ti, dict):
        return 0
    cmd = ti.get('command')
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    cwd = data.get('cwd') if isinstance(data.get('cwd'), str) else None
    if len(cmd) > MAX_INPUT:
        sys.stderr.write('lis-guard: command over 32 KB; no decision\n')
        return 0
    try:
        d = decide(cmd, cwd)
    except Exception:  # an analysis bug must not block the session; the rules still judge
        hit = critical_verb(cmd)
        d = ('deny', deny_reason(hit)) if hit else None
    if d:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                                 'permissionDecision': d[0],
                                                 'permissionDecisionReason': d[1]}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
