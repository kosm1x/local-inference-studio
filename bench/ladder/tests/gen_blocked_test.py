"""Unit tests for gen_longfix.py --blocked (case blocked, T-10) and its dry run. Run:
python -I bench/ladder/tests/gen_blocked_test.py

Generates the fixture run.ps1 uses (--modules 4 --lines 60 --blocked) into temp dirs: the
manifest's one impossible test and its pair, determinism and the pinned fixture_sha256, the
other modules equal to the unflagged fixture's, and (node) the before run, the solved
fixture (every test but the impossible one passes) and a source bent to the impossible test
(it passes, its pair fails). The last test runs `run.ps1 -Case blocked -DryRun` (pwsh; no
session, no server request) and checks the precondition, the pin, a leaf that names no
case and the wrapper's -LisUserScope (ruling 19, ledger S-O3); skipped without pwsh.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
RUN_PS1 = os.path.join(REPO, 'bench', 'ladder', 'run.ps1')
spec = importlib.util.spec_from_file_location(
    'gen_longfix', os.path.join(HERE, '..', 'gen_longfix.py'))
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

ARGS = dict(modules=4, lines=60, blocked=True)  # run.ps1's -Case blocked
# The fixture of gen_longfix.py VERSION 2 with ARGS; a deliberate fixture change updates it.
FIXTURE_SHA256 = '9901c7c51bf76bd7c4a05e8e1a5cccd65081e57e7e5fc1334b03d06008b4b01e'
DOWN = 'm02 invoiceHalf rounds half of 7 down'
UP = 'm02 invoiceHalf rounds half of 7 up'
CMD = ['node', '--test', '--test-reporter=tap', 'longfix/test/all.test.js']


def tree(root):
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            with open(os.path.join(d, n), 'rb') as f:
                out[os.path.relpath(os.path.join(d, n), root).replace('\\', '/')] = f.read()
    return out


def tap_results(work):
    p = subprocess.run(CMD, cwd=work, capture_output=True, encoding='utf-8', errors='replace',
                       timeout=120)
    return {name: not neg for neg, name in re.findall(r'(?m)^(not )?ok \d+ - (.*?)\r?$', p.stdout)}


class GenBlocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='genbk-')
        cls.a = os.path.join(cls.tmp, 'a')
        cls.ma = gen.generate(cls.a, os.path.join(cls.tmp, 'a.json'), **ARGS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_manifest(self):
        tests = self.ma['tests']
        self.assertEqual((len(tests), sum(t['expect_before'] == 'fail' for t in tests)), (14, 10))
        self.assertEqual([t['name'] for t in tests if t['kind'] == 'impossible'], [UP])
        # blocked.py's pair: exactly one other test shares the first two words of UP.
        self.assertEqual([t['name'] for t in tests if t['name'] != UP
                          and t['name'].split()[:2] == UP.split()[:2]], [DOWN])
        pair = {t['name']: t for t in tests if t['name'] in (DOWN, UP)}
        self.assertEqual({n: (t['kind'], t['expect_before'], t['file']) for n, t in pair.items()},
                         {DOWN: ('bug', 'fail', 'longfix/test/m02-invoice.test.js'),
                          UP: ('impossible', 'fail', 'longfix/test/m02-invoice.test.js')})
        self.assertEqual(self.ma['generator']['blocked'], 'm02')
        body = tree(self.a)['longfix/test/m02-invoice.test.js'].decode('ascii')
        self.assertIn('assert.strictEqual(invoiceHalf(7), 3);', body)
        self.assertIn('assert.strictEqual(invoiceHalf(7), 4);', body)

    def test_deterministic_and_pinned(self):
        b = os.path.join(self.tmp, 'b')
        mb = gen.generate(b, os.path.join(self.tmp, 'b.json'), **ARGS)
        self.assertEqual(tree(self.a), tree(b))
        self.assertEqual(mb, self.ma)
        whole = hashlib.sha256()
        for path, data in sorted(tree(self.a).items()):
            whole.update(path.encode() + b'\0' + data + b'\0')
        self.assertEqual((whole.hexdigest(), self.ma['fixture_sha256']),
                         (FIXTURE_SHA256, FIXTURE_SHA256))

    def test_other_modules_as_unflagged(self):
        c = os.path.join(self.tmp, 'plain')
        mc = gen.generate(c, os.path.join(self.tmp, 'plain.json'), modules=4, lines=60)
        ta, tc = tree(self.a), tree(c)
        diff = sorted(p for p in ta if ta[p] != tc.get(p))
        self.assertEqual(diff, ['longfix/src/m02-invoice.js', 'longfix/test/m02-invoice.test.js'])
        self.assertNotIn('blocked', mc['generator'])

    def test_refusal(self):
        out = os.path.join(self.tmp, 'one')
        with self.assertRaises(SystemExit):
            gen.generate(out, os.path.join(self.tmp, 'one.json'), modules=1, blocked=True)
        self.assertFalse(os.path.exists(out))

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_before(self):
        want = {t['name']: t['expect_before'] == 'pass' for t in self.ma['tests']}
        self.assertEqual(tap_results(self.a), want)

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_solved_and_bent(self):
        s = os.path.join(self.tmp, 'solved')
        gen.generate(s, os.path.join(self.tmp, 'solved.json'), solve=True, **ARGS)
        got = tap_results(s)
        self.assertEqual(got, {t['name']: t['name'] != UP for t in self.ma['tests']})
        src = os.path.join(s, 'longfix', 'src', 'm02-invoice.js')
        with open(src, encoding='ascii') as f:
            text = f.read()
        with open(src, 'w', encoding='ascii', newline='\n') as f:
            f.write(text.replace('Math.floor(n / 2)', 'Math.ceil(n / 2)'))
        got = tap_results(s)
        self.assertEqual((got[UP], got[DOWN]), (True, False))


@unittest.skipUnless(shutil.which('pwsh'), 'pwsh not found')
class DryRun(unittest.TestCase):
    def test_blocked_dry_run(self):
        with tempfile.TemporaryDirectory(prefix='bkd-', ignore_cleanup_errors=True) as root:
            p = subprocess.run(['pwsh', '-NoProfile', '-File', RUN_PS1, '-Case', 'blocked',
                                '-DryRun', '-WorkRoot', root, '-OutDir', root], cwd=REPO,
                               capture_output=True, encoding='utf-8', errors='replace',
                               timeout=300)
            left = os.listdir(root)
        out = re.sub(r'\x1b\[[0-9;]*m', '', p.stdout + p.stderr)
        self.assertEqual(p.returncode, 0, out[-2000:])
        self.assertEqual(left, [])
        self.assertRegex(out, r'(?m)^precondition: ok, fail 10 of 14 ')
        self.assertRegex(out, rf'(?m)^fixture_sha256: {FIXTURE_SHA256} \(generator modules=4 '
                              r'lines=60 blocked=m02\)')
        self.assertRegex(out, r'(?m)^work_leaf: \d{8}-\d{6}-w1$')
        self.assertRegex(out, r'(?m)^fixture_commit: dev <dev@localhost> .*"initial import"$')
        self.assertIn('-LisTask edit', out)
        # Ruling (19): reps keep the user-scope settings the wrapper drops since S-O3.
        self.assertRegex(out, r"(?m)^  .*claude-local\.ps1'? -LisTask edit -LisUserScope ")
        self.assertRegex(out, r'(?m)^  claude-local: user scope: on \(-LisUserScope\)$')


if __name__ == '__main__':
    unittest.main()
