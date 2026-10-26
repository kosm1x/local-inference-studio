"""Unit tests for bench/ladder/gen_longfix.py. Run: python -I bench/ladder/tests/gen_longfix_test.py

Generates the fixture into temp dirs (no session, no server). When node is on PATH, also
runs the generated suite: before = every bug test fails and every guard test passes; with
the generator's solve=True test aid every test passes. The before-run output budget depends
on the node major on PATH: Node >= 23 prints spec (< 25,000 chars), Node 22 off a TTY
prints TAP (< 35,000; ~29.5K). Run it under each node the model may get (pwsh and Git
Bash can resolve different ones). Exit 0 = all pass.
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


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load('gen_longfix')
TEST_CMD = ['node', '--test', 'longfix/test/all.test.js']
FORBIDDEN = re.compile(r'(?i)pass|fail|ok|[|#\'"]')
SPEC_BUDGET = 25000
TAP_BUDGET = 35000  # Node 22: TAP off a TTY, ~29.5K for the before run


class GenLongfix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='genlf-')
        # Mimic the run.ps1 work path length (<LOCALAPPDATA>\lis-ladder\<stamp>-<case>\work):
        # the spec reporter's output size depends on it.
        cls.a = os.path.join(cls.tmp, '20261026-120000-long-fix', 'work')
        cls.ma = gen.generate(cls.a, os.path.join(cls.tmp, 'a.manifest.json'))
        cls.b = os.path.join(cls.tmp, 'b')
        cls.mb = gen.generate(cls.b, os.path.join(cls.tmp, 'b.manifest.json'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tree(self, root):
        out = {}
        for d, _, names in os.walk(root):
            for n in names:
                p = os.path.join(d, n)
                with open(p, 'rb') as f:
                    out[os.path.relpath(p, root).replace('\\', '/')] = f.read()
        return out

    def test_deterministic(self):
        ta, tb = self.tree(self.a), self.tree(self.b)
        self.assertEqual(ta, tb)
        with open(os.path.join(self.tmp, 'a.manifest.json'), 'rb') as fa, \
                open(os.path.join(self.tmp, 'b.manifest.json'), 'rb') as fb:
            self.assertEqual(fa.read(), fb.read())
        whole = hashlib.sha256()
        for path in sorted(ta):
            whole.update(path.encode() + b'\0' + ta[path] + b'\0')
        self.assertEqual(whole.hexdigest(), self.ma['fixture_sha256'])
        self.assertEqual(sorted(ta), [f['path'] for f in self.ma['files']])
        self.assertFalse(any(p.endswith('package.json') for p in ta))
        for data in ta.values():
            data.decode('ascii')
            self.assertNotIn(b'\r', data)

    def test_lines(self):
        src = [f for f in self.ma['files'] if f['path'].startswith('longfix/src/')]
        self.assertEqual(len(src), 24)
        for f in src:
            self.assertLessEqual(f['lines'], 290, f['path'])
            self.assertLessEqual(abs(f['lines'] - 220), 5, f['path'])

    def test_names_and_counts(self):
        tests = self.ma['tests']
        names = [t['name'] for t in tests]
        self.assertEqual(len(names), 72)
        self.assertEqual(len(set(names)), 72)
        self.assertEqual(sum(t['expect_before'] == 'fail' for t in tests), 48)
        self.assertEqual({t['kind'] for t in tests if t['expect_before'] == 'fail'}, {'bug'})
        for t in tests:
            self.assertRegex(t['name'], rf"^{t['module']} \w+ [A-Za-z0-9 -]+$")
            self.assertIsNone(FORBIDDEN.search(t['name']), t['name'])
        self.assertEqual(self.ma['generator']['modules'], 24)

    def test_small(self):
        out = os.path.join(self.tmp, 'small')
        m = gen.generate(out, os.path.join(self.tmp, 's.json'), modules=4, lines=120)
        self.assertEqual((len(m['tests']), len(m['files'])), (12, 9))
        for f in m['files']:
            if f['path'].startswith('longfix/src/'):
                self.assertLessEqual(abs(f['lines'] - 120), 5, f['path'])

    def test_refusals(self):
        with self.assertRaises(SystemExit):
            gen.generate(self.b, os.path.join(self.tmp, 'again.json'))
        with self.assertRaises(SystemExit):
            gen.generate(os.path.join(self.tmp, 'big'), os.path.join(self.tmp, 'x.json'), lines=291)

    def run_node(self, cwd, *extra):
        r = subprocess.run(TEST_CMD[:2] + list(extra) + TEST_CMD[2:], cwd=cwd, capture_output=True,
                           encoding='utf-8', errors='replace', timeout=300)
        return r.returncode, r.stdout + r.stderr

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_before(self):
        rc, out = self.run_node(self.a)  # exactly the prompt's test command
        ver = subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()
        major = int(re.match(r'v(\d+)', ver).group(1))
        kind, budget = ('TAP', TAP_BUDGET) if major < 23 else ('spec', SPEC_BUDGET)
        print(f'\nnode {ver}; before-run output (default reporter, {kind}) {len(out)} chars',
              file=sys.stderr)
        self.assertNotEqual(rc, 0)
        if major < 23:
            self.assertTrue(out.startswith('TAP version'), out[:200])
        self.assertLess(len(out), budget, f'node {ver}: the {kind} before-run output is '
                        f'{len(out)} chars, over the {kind} budget of {budget}')
        self.assertNotRegex(out, r'SyntaxError|ReferenceError')
        rc, tap = self.run_node(self.a, '--test-reporter=tap')
        got = load('grade').tap(tap)
        self.assertEqual((got['pass'], got['fail']), (24, 48))
        want = {t['name']: t['expect_before'] == 'pass' for t in self.ma['tests']}
        self.assertEqual(got['tests'], want)

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_solved(self):
        out = os.path.join(self.tmp, 'solved')
        m = gen.generate(out, os.path.join(self.tmp, 'solved.json'), solve=True)
        rc, tap = self.run_node(out, '--test-reporter=tap')
        got = load('grade').tap(tap)
        self.assertEqual(rc, 0, tap[-2000:])
        self.assertEqual(got['tests'], {t['name']: True for t in m['tests']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
