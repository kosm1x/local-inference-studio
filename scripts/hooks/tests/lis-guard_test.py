"""Unit tests for scripts/hooks/lis-guard.py. Run: python -I scripts/hooks/tests/lis-guard_test.py

Static analysis only: no candidate command is ever executed. Exit 0 = all pass.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # no __pycache__ next to the hook
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, '..', 'lis-guard.py')
spec = importlib.util.spec_from_file_location('lis_guard', HOOK)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

VPS = 'root@203.0.113.7'
WSL_SSH = "wsl -d Ubuntu -- bash -c 'ssh -i $HOME/.ssh/k -o BatchMode=yes " + VPS + ' "{}"\''

CASES = [
    # (a) critical write/delete -> deny
    ('rm -rf /z/repos/x', 'deny'),
    ('rm -f notes.txt', 'deny'),
    ('ls; rm -r build', 'deny'),
    ('powershell -NoProfile -Command "Get-Date; Remove-Item x"', 'deny'),  # V5 payload case
    ("pwsh -NoProfile -Command 'Get-ChildItem C:/tmp | Remove-Item -Recurse'", 'deny'),
    ("bash -c 'cd /tmp && rm -rf cache'", 'deny'),
    ('cmd /c del /s /q C:\\tmp\\x', 'deny'),
    ('cmd /c rmdir /s /q C:\\tmp\\x', 'deny'),
    ('reg add HKCU\\Software\\X /v a /d b', 'deny'),
    ('powershell -NoProfile -Command "Set-ItemProperty HKLM:\\Software\\X -Name a -Value 1"', 'deny'),
    ('powershell -NoProfile -Command "Stop-Service llama"', 'deny'),
    ('sc stop wuauserv', 'deny'),
    ('schtasks /create /tn x /tr y /sc onlogon', 'deny'),
    ('powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName x"', 'deny'),
    ('format D: /q', 'deny'),
    ('diskpart /s plan.txt', 'deny'),
    ('wsl --unregister Ubuntu', 'deny'),
    ('wsl.exe --import Old C:/wsl old.tar', 'deny'),
    ('docker rm -f web', 'deny'),
    ('docker system prune -a', 'deny'),
    ('docker volume rm data', 'deny'),
    ('git push --force origin main', 'deny'),
    ('git -C /z/repos/x push -f', 'deny'),
    ('git reset --hard HEAD~1', 'deny'),
    ('git clean -fdx', 'deny'),
    ('git rebase -i main', 'deny'),
    ('git branch -D old', 'deny'),
    ('echo x > ~/.claude/settings.json', 'deny'),
    ('echo k >> /c/Users/me/.ssh/authorized_keys', 'deny'),
    ('cat new | tee .env', 'deny'),
    ('cp key.pem /z/repos/x/.git/hooks/pre-commit', 'deny'),
    ('mv cfg.json "/c/Program Files/App/cfg.json"', 'deny'),
    ('chmod 600 server.key', 'deny'),
    ('powershell -NoProfile -Command "Set-Content -Path C:/Windows/x.txt -Value 1"', 'deny'),
    ('powershell -NoProfile -Command "New-Item -Force C:/ProgramData/x"', 'deny'),
    ('dd if=/dev/zero of=/dev/sdb bs=1M', 'deny'),
    (WSL_SSH.format('rm /root/x'), 'deny'),
    (WSL_SSH.format('systemctl restart caddy'), 'deny'),
    (WSL_SSH.format('docker restart web'), 'deny'),
    ('ssh ' + VPS + " 'uptime > /tmp/u'", 'deny'),
    ('ssh ' + VPS + " 'kill 1234'", 'deny'),
    ('ssh ' + VPS + " 'cd /srv/app && git push origin main'", 'deny'),
    ('ssh ' + VPS + " 'apt-get install -y jq'", 'deny'),
    ('ssh ' + VPS + ' reboot', 'deny'),
    ('git commit -m "drop the rm -rf step"', 'deny'),  # deliberate over-match, documented
    ('ls 2>~/.claude/err.txt', 'deny'),
    # (c) read-only grammar -> allow
    ('ls -la /z/repos', 'allow'),
    ('ls /c/Users/me/.ssh/', 'allow'),
    ('hostname; uptime; date', 'allow'),
    ('systeminfo | grep -Ei "OS Name|Total Physical Memory"', 'allow'),
    ('nvidia-smi --query-gpu=name,memory.used --format=csv', 'allow'),
    ('node -v; pnpm -v 2>&1; python --version 2>/dev/null; uv --version', 'allow'),
    ('git status --porcelain && git log --oneline -5 && git branch --show-current', 'allow'),
    ('git -C /z/repos/x status --porcelain 2>/dev/null | wc -l', 'allow'),
    ('git config --global user.name', 'allow'),
    ('git remote -v', 'allow'),
    ("docker ps --format '{{.Names}}\\t{{.State}}' 2>&1", 'allow'),
    ('docker version --format server={{.Server.Version}}', 'allow'),
    ('docker context ls 2>&1 | head -5', 'allow'),
    ('wsl --list --verbose 2>&1', 'allow'),
    ('wsl.exe -l -v', 'allow'),
    ("wsl -d Ubuntu -- sh -c 'uname -r; cat /etc/os-release | head -2'", 'allow'),
    ('gh auth status 2>&1 | head -8', 'allow'),
    ('curl -s -H "Authorization: Bearer local" http://127.0.0.1:8080/v1/models', 'allow'),
    ('powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version"', 'allow'),
    ("pwsh -NoProfile -Command '(Get-CimInstance Win32_Processor | Measure-Object -Sum NumberOfEnabledLogicalProcessors).Sum'", 'allow'),
    ('powershell -NoProfile -Command "[math]::Round((Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum).Sum/1GB,1)"', 'allow'),
    # the $_ cases: bash expands an unescaped $_ inside double quotes, which breaks
    # the PowerShell call but writes nothing; read-only either way
    ('powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | Where-Object {$_.Free -ne $null} | Select-Object Name, @{N=\'FreeGB\';E={[math]::Round($_.Free/1GB,1)}}"', 'allow'),
    ('powershell -NoProfile -Command "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name, @{n=\'MB\';e={[math]::Round(\\$_.WorkingSet64/1MB)}} | Format-Table -AutoSize"', 'allow'),
    ("pwsh -NoProfile -Command 'Get-Volume | Where-Object { $_.DriveType -eq \"Fixed\" } | Select-Object DriveLetter'", 'allow'),
    (WSL_SSH.format('uptime; docker ps | wc -l'), 'allow'),
    ('MSYS_NO_PATHCONV=1 ' + WSL_SSH.format('df -h; free -m; systemctl status caddy --no-pager | head -5'), 'allow'),
    ('ssh -o ConnectTimeout=8 ' + VPS + " 'journalctl -u caddy -n 20; tail -5 /var/log/syslog'", 'allow'),
    ('cd /z/repos/x && git status --porcelain', 'allow'),
    ("pwsh -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'", 'allow'),
    # (d) passthrough -> no decision, the rules/classifier judge
    ('mkdir -p out && echo hi > out/x.txt', None),
    ('npm install', None),
    ('python -c "print(1)"', None),
    ('curl -s https://example.com', None),
    ('curl -s -X POST http://127.0.0.1:8080/slots', None),
    ('powershell -NoProfile -Command "$env:PATH = \'x\'"', None),
    ('powershell -NoProfile -Command "Get-Date > C:/tmp/d.txt"', None),
    ('powershell -NoProfile -Command "[IO.File]::WriteAllText(\'a\', \'b\')"', None),
    ('powershell -NoProfile -Command "Invoke-WebRequest https://example.com"', None),
    ('git commit -m "msg"', None),
    ('git config --global user.name x', None),
    ('find . -name "*.tmp" -delete', None),
    ('ssh ' + VPS, None),
    ('for d in /z/repos/*/; do echo $d; done', None),
    ('node -e "1"', None),
    ("pwsh -NoProfile -Command 'Get-ChildItem C:/tmp/x | ForEach-Object { $_.Delete() }'", None),
    ("pwsh -NoProfile -Command '(Get-Process -Id 4242).Kill()'", None),
    ('curl -s --json \'{"a":1}\' http://127.0.0.1:8080/x', None),
    ('ssh ' + VPS + " 'sqlite3 /srv/app/data.db \"select 1\"'", None),
    ('', None),
]


def write(dirpath, name, body):
    p = os.path.join(dirpath, name)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    return p


def main():
    fails = 0
    n = 0
    for cmd, want in CASES:
        n += 1
        d = g.decide(cmd)
        got = d[0] if d else None
        if got != want:
            fails += 1
            print(f'FAIL want={want} got={got}: {cmd}\n     reason={d[1] if d else ""}')
    with tempfile.TemporaryDirectory() as t:
        write(t, 'hello.sh', '#!/bin/bash\n# probe\necho "hello-from-script"\n')
        write(t, 'sweep.sh', '#!/usr/bin/env bash\nset -u\nfor d in /z/repos/a/*/ /z/repos/b/*/; do\n'
              '  [ -d "$d.git" ] || continue\n  b=$(git -C "$d" branch --show-current 2>/dev/null)\n'
              '  n=$(git -C "$d" status --porcelain 2>/dev/null | wc -l)\n  echo "$d branch=$b dirty=$n"\ndone\n'
              'powershell -NoProfile -Command "Test-Path \'C:/Program Files/Docker/Docker.exe\'"\n')
        write(t, 'probe.sh', '#!/usr/bin/env bash\nset -u\n'
              "wsl -d Ubuntu -- bash -c 'test -f \"$HOME/.ssh/k\" && echo key-present || echo key-missing'\n"
              + WSL_SSH.format('uptime; docker ps | wc -l') + ' 2>&1\n')
        write(t, 'wipe.sh', '#!/bin/bash\necho start\nrm -rf old\necho done\n')
        write(t, 'rm1.sh', '#!/bin/bash\nrm old.log\n')
        write(t, 'crit.ps1', 'Get-Date\nRemove-Item C:/tmp/x -Recurse\n')
        write(t, 'evil.py', 'import os\nos.system("rm -rf /tmp/x")\n')
        write(t, 'push.sh', '#!/bin/bash\ngit status\ngit push --force\n')
        write(t, 'mk.sh', '#!/bin/bash\nmkdir -p out\n')
        write(t, 'q.ps1', 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption\nGet-Date\n')
        write(t, 'w.ps1', 'Get-Date\nSet-Content -Path out.txt -Value 1\n')
        write(t, 'tool.py', 'import os\nprint(os.getcwd())\n')
        scripts = [
            ('bash hello.sh', 'allow'), ('bash ./sweep.sh 2>&1', 'allow'), ('sh probe.sh', 'allow'),
            ('bash wipe.sh', 'deny'), ('bash push.sh', 'deny'), ('bash mk.sh', None), ('bash rm1.sh', None),
            ('pwsh -NoProfile -File q.ps1', 'allow'), ('powershell -NoProfile -File w.ps1', None),
            ('pwsh -File crit.ps1', 'deny'), ('python evil.py', 'deny'),
            ('python tool.py', None), ('bash missing.sh', None),
            ('echo start; bash hello.sh', 'allow'), ('bash hello.sh; npm install', None),
        ]
        for cmd, want in scripts:
            n += 1
            d = g.decide(cmd, t)
            got = d[0] if d else None
            if got != want:
                fails += 1
                print(f'FAIL want={want} got={got}: {cmd}\n     reason={d[1] if d else ""}')
        d = g.decide('bash wipe.sh', t)
        n += 1
        if not (d and "'rm -rf old'" in d[1] and 'line 3' in d[1] and 'echo done' not in d[1]
                and 'not retryable' in d[1]):
            fails += 1
            print(f'FAIL script reason must quote only the first offending line: {d}')
        # end to end through stdin/stdout, as Claude Code calls it
        for cmd, want in [('git reset --hard', 'deny'), ('uptime', 'allow'), ('npm install', None)]:
            n += 1
            inp = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': t})
            r = subprocess.run([sys.executable, '-I', HOOK], input=inp, capture_output=True, text=True, timeout=20)
            out = json.loads(r.stdout)['hookSpecificOutput']['permissionDecision'] if r.stdout.strip() else None
            if r.returncode != 0 or out != want:
                fails += 1
                print(f'FAIL e2e want={want} got={out} rc={r.returncode}: {cmd} {r.stderr[:200]}')
        n += 1
        r = subprocess.run([sys.executable, '-I', HOOK], input='not json', capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or r.stdout.strip():
            fails += 1
            print('FAIL e2e: bad stdin must give exit 0 and no output')
    d = g.decide('git push --force')
    n += 1
    if not (d and 'not retryable' in d[1] and 'report it to the operator' in d[1]):
        fails += 1
        print(f'FAIL deny reason wording: {d}')
    print(f'{n - fails}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
