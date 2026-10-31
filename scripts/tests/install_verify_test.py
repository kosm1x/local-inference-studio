"""Tests for the supply-chain pins: models/manifest.json and the llama.cpp zip digests
pinned in scripts/install.ps1. Run from the repo root:
  python -I scripts/tests/install_verify_test.py           (size checks, no hashing of GGUFs)
  python -I scripts/tests/install_verify_test.py --full    (also hashes the default GGUF)
  python -I scripts/tests/install_verify_test.py --root DIR (check another tree's files)

No network. The one pwsh run (install.ps1 -SkipVerify -WhatIf, no -SkipVerifyAck) must
throw before anything is fetched. A file that is not on disk is reported as SKIP.
Exit 0 = all pass.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


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

    print(f'{n - fails}/{n} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
