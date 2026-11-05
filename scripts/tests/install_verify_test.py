"""Tests for the supply-chain pins: models/manifest.json and the llama.cpp zip digests
pinned in scripts/install.ps1; serve.ps1's start checks over them (binary pins, the
once-per-boot GGUF hash) and its -Web log level (S-O1, S-O2, S-L1). Run from the repo root:
  python -I scripts/tests/install_verify_test.py           (size checks, no hashing of GGUFs)
  python -I scripts/tests/install_verify_test.py --full    (also hashes the default GGUF)
  python -I scripts/tests/install_verify_test.py --root DIR (check another tree's files)

No network. install.ps1 runs only as -SkipVerify -WhatIf (no -SkipVerifyAck: must throw
before anything is fetched) and -VerifyZip; serve.ps1 runs only as -VerifyOnly or
-PrintArgs (or is refused before either), in temp trees with fake binaries, so no server
starts and no key file is written. A file that is not on disk is reported as SKIP.
Exit 0 = all pass.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def pwsh_file(script, *args):
    r = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', script] + list(args),
                       capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


def q(s):
    return "'" + s.replace("'", "''") + "'"


GGUF = b'GGUF fake model for the serve.ps1 hash check\n' * 64
LLAMA_ZIP = 'llama-b11868-bin-win-cuda-13.4-x64.zip'
FAKES = {'llama-server.exe': b'fake llama-server.exe\n',
         'llama-server-impl.dll': b'fake impl dll\n'}


def serve_tree(tmp, root, tag=None, fake_pins=False, entry=True, sha=None, size=None):
    """A temp tree: serve.ps1, install.ps1 (its server pins replaced by the fakes' when
    fake_pins), fake bin/llama-server.exe and -impl.dll, a fake GGUF and a scratch
    manifest listing it (entry=False: listing another file)."""
    t = os.path.join(tmp, 'repo')
    for d in ('scripts', 'bin', 'logs', 'models/test'):
        os.makedirs(os.path.join(t, d), exist_ok=True)
    shutil.copy(os.path.join(root, 'scripts', 'serve.ps1'), os.path.join(t, 'scripts'))
    with open(os.path.join(root, 'scripts', 'install.ps1'), encoding='utf-8', newline='') as f:
        inst = f.read()
    for name, data in FAKES.items():
        with open(os.path.join(t, 'bin', name), 'wb') as f:
            f.write(data)
        if fake_pins:
            digest = hashlib.sha256(data).hexdigest()
            inst = re.sub(r"('" + re.escape(name) + r"'\s*=\s*')[0-9a-f]{64}'",
                          lambda m: m.group(1) + digest + "'", inst)
    with open(os.path.join(t, 'scripts', 'install.ps1'), 'w', encoding='utf-8', newline='') as f:
        f.write(inst)
    if tag:
        with open(os.path.join(t, 'bin', 'llama-release.txt'), 'w') as f:
            f.write(tag + '\n')
    with open(os.path.join(t, 'models', 'test', 'fake.gguf'), 'wb') as f:
        f.write(GGUF)
    e = {'path': 'models/test/fake.gguf' if entry else 'models/test/other.gguf',
         'size': size if size is not None else len(GGUF),
         'sha256': sha or hashlib.sha256(GGUF).hexdigest()}
    with open(os.path.join(t, 'models', 'test-manifest.json'), 'w') as f:
        json.dump({'files': [e]}, f)
    return t


def serve(t, *extra):
    return pwsh_file(os.path.join(t, 'scripts', 'serve.ps1'), '-Port', str(free_port()),
                     '-Model', 'models/test/fake.gguf',
                     '-ModelManifest', 'models/test-manifest.json', *extra)


def probe(sp, fn, body):
    """Run body in pwsh after dot-sourcing function fn extracted from serve.ps1 sp."""
    script = ("$ast = [Management.Automation.Language.Parser]::ParseFile(" + q(sp)
              + ", [ref]$null, [ref]$null); "
              "$ast.FindAll({ $args[0] -is "
              "[Management.Automation.Language.FunctionDefinitionAst] -and "
              f"$args[0].Name -eq '{fn}' }}, $true) | "
              "ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }; " + body)
    r = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def serve_checks(root, check):
    """S-O1, S-O2 and S-L1 over serve.ps1 and install.ps1 from root."""
    def want(cond, msg, rc, out):
        check(cond, f'{msg}: rc={rc} {out}')

    def no_key(t, what):
        check(not os.path.exists(os.path.join(t, 'logs', 'api-key')), f'{what} wrote the key file')

    inst_path = os.path.join(root, 'scripts', 'install.ps1')
    with open(inst_path, encoding='utf-8') as f:
        inst = f.read()
    pins = dict(re.findall(r"'(llama-server(?:-impl)?\.(?:exe|dll))'\s*=\s*'([0-9a-f]{64})'", inst))
    check(set(pins) == set(FAKES), f'install.ps1 server pins: {pins}')
    pin_exe = pins.get('llama-server.exe', '?')
    for name, pin in pins.items():
        b = os.path.join(root, 'bin', name)
        if os.path.isfile(b):
            check(sha256(b) == pin, f'bin/{name} differs from its pin')
        else:
            print(f'SKIP bin/{name}: not on disk')
    z = os.path.join(root, 'bin', '.download', LLAMA_ZIP)
    if os.path.isfile(z):
        with zipfile.ZipFile(z) as zf:
            for name, pin in pins.items():
                check(hashlib.sha256(zf.read(name)).hexdigest() == pin,
                      f'{name} in {LLAMA_ZIP} differs from its pin')

    # install.ps1 -VerifyZip: the install's own check, offline
    with tempfile.TemporaryDirectory() as tmp:
        bad = os.path.join(tmp, LLAMA_ZIP)
        with open(bad, 'wb') as f:
            f.write(b'not the release zip')
        rc, out = pwsh_file(inst_path, '-VerifyZip', bad)
        want(rc != 0 and 'SHA256 mismatch' in out and '6b39772ceb8668e8' in out
             and hashlib.sha256(b'not the release zip').hexdigest() in out,
             '-VerifyZip on a wrong zip must throw with both hashes', rc, out)
        other = os.path.join(tmp, 'unpinned.zip')
        shutil.copy(bad, other)
        rc, out = pwsh_file(inst_path, '-VerifyZip', other)
        want(rc != 0 and 'No pinned SHA256' in out, '-VerifyZip on an unpinned name must throw',
             rc, out)
    if os.path.isfile(z):
        rc, out = pwsh_file(inst_path, '-VerifyZip', z)
        want(rc == 0 and 'SHA256 OK (pinned)' in out, '-VerifyZip on the real zip', rc, out)
    else:
        print(f'SKIP -VerifyZip {LLAMA_ZIP}: not on disk')

    # S-O1: serve.ps1 checks llama-server.exe and -impl.dll against those pins
    fake_exe = hashlib.sha256(FAKES['llama-server.exe']).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:  # no tag, exe matches no pin
        t = serve_tree(tmp, root)
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and 'matches no release pinned' in out and fake_exe in out and pin_exe in out,
             'serve: unpinned exe without a tag must refuse with both hashes', rc, out)
        no_key(t, 'serve -VerifyOnly')
    with tempfile.TemporaryDirectory() as tmp:  # tag b11868, exe differs from its pin
        t = serve_tree(tmp, root, tag='b11868')
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and 'refusing to start' in out
             and f'llama-server.exe sha256 {fake_exe}, pinned for b11868 {pin_exe}' in out,
             'serve: exe pin mismatch must refuse', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # a release with no pin warns and goes on
        t = serve_tree(tmp, root, tag='b99999')
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'WARNING no llama-server.exe pin for release b99999' in out
             and fake_exe in out, 'serve: a missing pin must warn and go on', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # pins equal the binaries; then the dll differs
        t = serve_tree(tmp, root, fake_pins=True)
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'binaries match the b11868 pins (llama-server.exe, '
             'llama-server-impl.dll)' in out, 'serve: pinned binaries must pass', rc, out)
        with open(os.path.join(t, 'bin', 'llama-server-impl.dll'), 'ab') as f:
            f.write(b'x')
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and 'llama-server-impl.dll sha256' in out,
             'serve: a dll pin mismatch must refuse', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # the release is pinned, the dll is not
        t = serve_tree(tmp, root, fake_pins=True)
        ip = os.path.join(t, 'scripts', 'install.ps1')
        with open(ip, encoding='utf-8', newline='') as f:
            inst_t = f.read()
        with open(ip, 'w', encoding='utf-8', newline='') as f:
            f.write(re.sub(r"\r?\n\s*'llama-server-impl\.dll'\s*=\s*'[0-9a-f]{64}'", '', inst_t))
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'WARNING llama-server binaries match the b11868 pins (llama-server.exe); '
             'no b11868 pin for llama-server-impl.dll (sha256 '
             + hashlib.sha256(FAKES['llama-server-impl.dll']).hexdigest() in out,
             'serve: a pinned release with no dll pin must warn and go on', rc, out)
        # install.ps1 unreadable as pins: refuse, never pass unchecked
        for what, head, msg in (('no $pinned', '$pinnedX = @{', 'no $pinned table'),
                                ('a string', "$pinned = 'x'\n$u = @{", 'no $pinned table'),
                                ('not constant', '$pinned = @{ x = (Get-Date) }\n$u = @{',
                                 'check failed')):
            with open(ip, 'w', encoding='utf-8', newline='') as f:
                f.write(inst_t.replace('$pinned = @{', head, 1))
            rc, out = serve(t, '-VerifyOnly')
            want(rc != 0 and 'refusing to start' in out and msg in out,
                 f'serve: install.ps1 with {what} must refuse', rc, out)
        os.remove(ip)
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and 'install.ps1 not found' in out, 'serve: a missing install.ps1 must refuse',
             rc, out)

    # S-O2: the GGUF hash, at most once per boot
    good = hashlib.sha256(GGUF).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:  # hash, marker, no rehash, another boot rehashes
        t = serve_tree(tmp, root, fake_pins=True)
        marker = os.path.join(t, 'logs', 'model-verify.json')
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'model sha256 matches' in out and os.path.isfile(marker),
             'serve: a matching GGUF must pass and write the marker', rc, out)
        no_key(t, 'serve -VerifyOnly')
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'verified earlier this boot' in out,
             'serve: the second run must take the marker', rc, out)
        gguf = os.path.join(t, 'models', 'test', 'fake.gguf')
        st = os.stat(gguf)
        os.utime(gguf, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 10))
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'model sha256 matches' in out,
             'serve: a new mtime must rehash, not take the marker', rc, out)
        st = os.stat(gguf)
        with open(gguf, 'r+b') as f:  # same size, same mtime: only a rehash would see it
            f.write(b'X')
        os.utime(gguf, ns=(st.st_atime_ns, st.st_mtime_ns))
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'verified earlier this boot' in out,
             'serve: the marker must skip the hash', rc, out)
        with open(marker, encoding='utf-8-sig') as f:
            m = json.load(f)
        m['boot'] = 0
        with open(marker, 'w') as f:
            json.dump(m, f)
        bad = hashlib.sha256(b'X' + GGUF[1:]).hexdigest()
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and f'sha256 {bad},' in out and f'says {good}' in out,
             'serve: another boot must rehash and refuse with both hashes', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # wrong sha256
        t = serve_tree(tmp, root, fake_pins=True, sha='0' * 64)
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and f'sha256 {good},' in out and 'says ' + '0' * 64 in out
             and not os.path.exists(os.path.join(t, 'logs', 'model-verify.json')),
             'serve: a GGUF hash mismatch must refuse with both hashes, no marker', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # wrong size
        t = serve_tree(tmp, root, fake_pins=True, size=len(GGUF) + 1)
        rc, out = serve(t, '-VerifyOnly')
        want(rc != 0 and f'is {len(GGUF)} bytes' in out,
             'serve: a GGUF size mismatch must refuse', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # not in the manifest; -SkipModelVerify
        t = serve_tree(tmp, root, fake_pins=True, entry=False)
        rc, out = serve(t, '-VerifyOnly')
        want(rc == 0 and 'WARNING no entry for' in out,
             'serve: an unlisted GGUF must warn and go on', rc, out)
        t2 = serve_tree(os.path.join(tmp, 'b'), root, fake_pins=True, sha='0' * 64)
        rc, out = serve(t2, '-VerifyOnly', '-SkipModelVerify')
        want(rc == 0 and 'WARNING model hash check skipped (-SkipModelVerify)' in out,
             'serve: -SkipModelVerify must skip and log', rc, out)

    # S-O2: the extracted Test-ModelHash, called twice in one process with the file
    # changed between (same size and mtime): the second call takes the marker, no hash
    sp = os.path.join(root, 'scripts', 'serve.ps1')
    with open(sp, encoding='utf-8') as f:
        text = f.read()
    with tempfile.TemporaryDirectory() as tmp:
        t = serve_tree(tmp, root)
        g = q(os.path.join(t, 'models', 'test', 'fake.gguf'))
        mk = os.path.join(t, 'logs', 'model-verify.json')
        call = (f"Test-ModelHash {g} {q(os.path.join(t, 'models', 'test-manifest.json'))} "
                f"{q(t)} {q(mk)}")
        rc, out = probe(sp, 'Test-ModelHash',
                        f"$a = {call}; $i = Get-Item -LiteralPath {g}; $w = $i.LastWriteTimeUtc; "
                        f"$b = [IO.File]::ReadAllBytes({g}); $b[0] = 88; "
                        f"[IO.File]::WriteAllBytes({g}, $b); $i.LastWriteTimeUtc = $w; "
                        f"$c = {call}; 'FIRST=' + $a[0]; 'SECOND=' + $c[0]")
        want('FIRST=ok' in out and 'SECOND=marker' in out,
             'Test-ModelHash: a valid marker must skip the hash', rc, out)
    with tempfile.TemporaryDirectory() as tmp:  # boot time unreadable: hash, no marker
        t = serve_tree(tmp, root)
        mk = os.path.join(t, 'logs', 'model-verify.json')
        call = (f"Test-ModelHash {q(os.path.join(t, 'models', 'test', 'fake.gguf'))} "
                f"{q(os.path.join(t, 'models', 'test-manifest.json'))} {q(t)} {q(mk)}")
        rc, out = probe(sp, 'Test-ModelHash',
                        "function Get-CimInstance { throw 'CIM unavailable' }; "
                        f"$a = {call}; $c = {call}; 'FIRST=' + $a[0]; 'SECOND=' + $c[0]; $c[1]")
        want('FIRST=ok' in out and 'SECOND=ok' in out and 'no marker written' in out
             and not os.path.exists(mk),
             'Test-ModelHash: an unreadable boot time must hash every time, no marker', rc, out)
    loop = text.find('while ($true) {')
    pat = r'Confirm-Check \{ Test-(ModelHash|ServerBinary) '
    calls = [m.start() for m in re.finditer(pat, text)]
    check(len(calls) == 2 and loop > 0 and all(c < loop for c in calls),
          'serve.ps1: the binary and model checks must run once, before the restart loop')
    # W2: a dry run never takes the port mutex
    seg = text[text.find('$dryRun = '):text.find('$listener = ')]
    gate = seg.find('if (-not $dryRun) {')
    check(0 <= gate < seg.find('WaitOne(0)') and seg.count('WaitOne(') == 1,
          'serve.ps1: WaitOne must run only under if (-not $dryRun)')
    # W3: the stop request is deleted once, before the checks; none after the key write
    key = text.find('WriteAllText($keyFile')
    dels = [m.start() for m in re.finditer(r'Remove-Item -LiteralPath \$stopFile', text)]
    check(key > 0 and calls and len(dels) == 1 and dels[0] < calls[0] < key,
          'serve.ps1: the stop file must be deleted only before the checks, never after the key')
    # M13: -Web clears LLAMA_ARG_LOG_VERBOSITY, a run without -Web keeps it
    seg = text[text.find('$envOverrides = @('):text.find('if ($cleared)')]
    r = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
                        "$env:LLAMA_ARG_LOG_VERBOSITY = '5'; $Web = $true; " + seg
                        + "; 'WEB=' + (Test-Path Env:LLAMA_ARG_LOG_VERBOSITY); "
                        "$env:LLAMA_ARG_LOG_VERBOSITY = '5'; $Web = $false; " + seg
                        + "; 'NOWEB=' + (Test-Path Env:LLAMA_ARG_LOG_VERBOSITY)"],
                       capture_output=True, text=True, timeout=60)
    want('WEB=False' in r.stdout and 'NOWEB=True' in r.stdout,
         'serve -Web: LLAMA_ARG_LOG_VERBOSITY must be cleared', r.returncode, r.stdout + r.stderr)
    # W4: dry runs leave -LogFile alone (no rotation, no append); -PrintArgs writes nothing
    with tempfile.TemporaryDirectory() as tmp:
        t = serve_tree(tmp, root, fake_pins=True)
        log = os.path.join(tmp, 'big.log')
        size = 50 * 2 ** 20 + 1
        with open(log, 'wb') as f:
            f.truncate(size)

        def untouched():
            return (os.path.isfile(log) and os.path.getsize(log) == size
                    and not os.path.exists(log + '.1'))
        rc, out = serve(t, '-VerifyOnly', '-LogFile', log)
        want(rc == 0 and 'binaries match' in out and untouched(),
             'serve -VerifyOnly: -LogFile must not be rotated or appended', rc, out)
        shutil.rmtree(os.path.join(t, 'logs'))
        rc, out = serve(t, '-PrintArgs', '-LogFile', log)
        want(rc == 0 and untouched() and not os.path.exists(os.path.join(t, 'logs')),
             'serve -PrintArgs: must write nothing', rc, out)
    # W6: a check that throws refuses through -LogFile (a real run: refused before any start)
    with tempfile.TemporaryDirectory() as tmp:
        t = serve_tree(tmp, root, fake_pins=True)
        with open(os.path.join(t, 'models', 'test-manifest.json'), 'w') as f:
            f.write('{ not json')
        log = os.path.join(t, 'logs', 'serve.log')
        rc, out = serve(t, '-LogFile', log)
        with open(log, encoding='utf-8-sig') as f:
            logged = f.read()
        want(rc != 0 and 'refusing to start: check failed: ' in logged, 'serve: a check that '
             'throws must refuse through -LogFile', rc, out + logged)
        no_key(t, 'a refused serve')
    # W3: a stop request written while the model is hashed stops the start
    with tempfile.TemporaryDirectory() as tmp:
        t = serve_tree(tmp, root, fake_pins=True)
        n = 1 << 30  # about 0.5 s or more of hashing: the window for the stop request
        with open(os.path.join(t, 'models', 'test', 'fake.gguf'), 'wb') as f:
            f.truncate(n)
        h, zero = hashlib.sha256(), bytes(1 << 24)
        for _ in range(n >> 24):
            h.update(zero)
        with open(os.path.join(t, 'models', 'test-manifest.json'), 'w') as f:
            json.dump({'files': [{'path': 'models/test/fake.gguf', 'size': n,
                                  'sha256': h.hexdigest()}]}, f)
        port = free_port()
        log = os.path.join(t, 'logs', 'serve.log')
        stop = os.path.join(t, 'logs', f'.stop-requested-{port}')
        p = subprocess.Popen(['pwsh', '-NoProfile', '-NonInteractive', '-File',
                              os.path.join(t, 'scripts', 'serve.ps1'), '-Port', str(port),
                              '-Model', 'models/test/fake.gguf',
                              '-ModelManifest', 'models/test-manifest.json', '-LogFile', log],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        seen = ''
        for _ in range(3000):
            if p.poll() is not None:
                break
            if os.path.exists(log):
                with open(log, encoding='utf-8-sig') as f:
                    seen = f.read()
                if 'binaries match' in seen:
                    with open(stop, 'w') as f:
                        f.write('[stop.ps1] stop requested during the checks\n')
                    break
            time.sleep(0.01)
        try:
            out = p.communicate(timeout=120)[0]
        except subprocess.TimeoutExpired:
            p.kill()
            out = p.communicate()[0] + ' (timed out, killed)'
        with open(log, encoding='utf-8-sig') as f:
            logged = f.read()
        want(p.returncode == 0 and 'model sha256 matches' in logged
             and 'not starting: [stop.ps1] stop requested during the checks' in logged
             and 'llama-server.exe -m ' not in logged,
             'serve: a stop request during the checks must stop the start', p.returncode,
             out + logged)
        no_key(t, 'a serve stopped during the checks')

    # S-L1: -Web passes -lv 3 and refuses a louder log
    with tempfile.TemporaryDirectory() as tmp:
        t = serve_tree(tmp, root)
        rc, out = serve(t, '-Web', '-PrintArgs')
        line = next((ln for ln in out.splitlines() if 'llama-server.exe -m ' in ln), '')
        want(rc == 0 and ' -lv 3' in line and line.count(' -lv ') == 1,
             'serve -Web: the args must hold -lv 3', rc, out)
        no_key(t, 'serve -PrintArgs')
        rc, out = serve(t, '-PrintArgs')
        want(rc == 0 and 'llama-server.exe -m ' in out and ' -lv ' not in out,
             'serve: no -lv without -Web', rc, out)
        rc, out = serve(t, '-PrintArgs', '-ExtraArgLine', '-lv 4')
        want(rc == 0 and ' -lv 4' in out, 'serve: -lv 4 stays allowed without -Web', rc, out)
        rc, out = serve(t, '-Web', '-PrintArgs', '-ExtraArgLine', '-lv 2')
        want(rc == 0 and ' -lv 3 ' in out and out.rstrip().endswith('-lv 2'),
             'serve -Web: -lv 2 allowed', rc, out)
        for loud in ('-lv 4', '-lv', '-lv x', '--temp 0.7 -v', '--temp 0.7 --verbose',
                     '--log-verbose', '--verbosity=5', '--log-verbosity 9', '--temp 0.7 -lv 5'):
            rc, out = serve(t, '-Web', '-PrintArgs', '-ExtraArgLine', loud)
            want(rc != 0 and '-Web keeps the server log at -lv 3 or lower' in out,
                 f'serve -Web: {loud!r} must be refused', rc, out)
        r = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
                            f"& {q(os.path.join(t, 'scripts', 'serve.ps1'))} -Port {free_port()} "
                            "-Model models/test/fake.gguf -Web -PrintArgs "
                            "-ExtraArgs '--temp','0.7','-lv','5'"],
                           capture_output=True, text=True, timeout=60)
        want(r.returncode != 0 and '-Web keeps the server log' in r.stdout + r.stderr,
             'serve -Web: -ExtraArgs -lv 5 must be refused', r.returncode, r.stdout + r.stderr)


def main():
    args = sys.argv[1:]
    full = '--full' in args
    root = args[args.index('--root') + 1] if '--root' in args else os.path.join(HERE, '..', '..')
    fails, n = 0, 0

    def check(ok, msg):
        nonlocal fails, n
        n += 1
        if not ok:
            fails += 1
            print('FAIL ' + msg)

    # models/manifest.json
    mpath = os.path.join(root, 'models', 'manifest.json')
    check(os.path.isfile(mpath), 'models/manifest.json missing')
    entries = []
    if os.path.isfile(mpath):
        raw = open(mpath, 'rb').read()
        check(b'\r' not in raw, 'manifest has CR line endings (LF expected)')
        entries = json.loads(raw.decode('utf-8'))['files']
    check(len(entries) >= 1, 'manifest lists no files')
    for e in entries:
        tag = e.get('path', '?')
        check(set(e) >= {'path', 'repo', 'revision', 'file', 'size', 'sha256'}, f'{tag}: missing keys')
        check(re.fullmatch(r'[0-9a-f]{64}', e.get('sha256', '')) is not None, f'{tag}: sha256 not 64 lowercase hex')
        check(re.fullmatch(r'[0-9a-f]{40}', e.get('revision', '')) is not None, f'{tag}: revision not a 40-hex commit')
        check(isinstance(e.get('size'), int) and e['size'] > 0, f'{tag}: size not a positive integer')
        check(tag.startswith('models/') and tag.endswith('/' + e.get('file', '')), f'{tag}: path/file disagree')
        p = os.path.join(root, tag)
        if not os.path.isfile(p):
            print(f'SKIP {tag}: not on disk')
            continue
        check(os.path.getsize(p) == e['size'], f'{tag}: size {os.path.getsize(p)} != manifest {e["size"]}')
        d, f = tag.split('/')[1], e['file']
        meta = os.path.join(root, 'models', d, '.cache', 'huggingface', 'download', f + '.metadata')
        if os.path.isfile(meta):  # hf download's record: line 1 commit, line 2 LFS sha256 etag
            lines = open(meta, encoding='utf-8').read().split()
            check(lines[:2] == [e['revision'], e['sha256']], f'{tag}: manifest differs from hf download metadata')
    defaults = [e for e in entries if e.get('default')]
    check(len(defaults) == 1, f'expected exactly one default entry, got {len(defaults)}')
    serve = open(os.path.join(root, 'scripts', 'serve.ps1'), encoding='utf-8').read()
    m = re.search(r"\[string\]\$Model\s*=\s*'([^']+)'", serve)
    if defaults and m:
        check(defaults[0]['path'] == m.group(1).replace('\\', '/'),
              f'default entry {defaults[0]["path"]} is not serve.ps1 default {m.group(1)}')
        p = os.path.join(root, defaults[0]['path'])
        if full and os.path.isfile(p):
            check(sha256(p) == defaults[0]['sha256'], 'default GGUF sha256 differs from the manifest')

    # scripts/install.ps1 pins
    inst_path = os.path.join(root, 'scripts', 'install.ps1')
    inst = open(inst_path, encoding='utf-8').read()
    pins = dict(re.findall(r"'([\w.-]+\.zip)'\s*=\s*'([0-9a-f]{64})'", inst))
    for name in ('llama-b11868-bin-win-cuda-13.4-x64.zip', 'cudart-llama-bin-win-cuda-13.4-x64.zip'):
        check(name in pins, f'install.ps1 has no pinned SHA256 for {name}')
        z = os.path.join(root, 'bin', '.download', name)
        if name in pins and os.path.isfile(z):
            check(sha256(z) == pins[name], f'{name} on disk differs from the pin')
        elif name in pins:
            print(f'SKIP {name}: not on disk')
    check('$api256 -ne $pin256' in inst, 'install.ps1 does not require the API digest to equal the pin')
    r = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', inst_path, '-SkipVerify', '-WhatIf'],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode != 0 and 'SkipVerifyAck' in (r.stdout + r.stderr),
          f'-SkipVerify without -SkipVerifyAck must throw (rc={r.returncode})')
    serve_checks(root, check)

    print(f'{n - fails}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
