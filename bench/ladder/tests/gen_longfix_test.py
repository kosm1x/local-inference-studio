"""Unit tests for bench/ladder/gen_longfix.py. Run: python -I bench/ladder/tests/gen_longfix_test.py

Generates the fixture into temp dirs (no session, no server). When node is on PATH, also
runs the generated suite: before = every bug test fails and every guard test passes; with
the generator's solve=True test aid every test passes. The prompt's test command uses the
fixture's reporter (longfix/reporter.mjs): one line per module with its failing tests' exact
names, then '# pass N' and '# fail N'. The before run must stay within 9,500 chars (run.ps1
$shownTotal: Claude Code shows a longer tool result as its first and last 5,000 chars), and
run.ps1's -Modules cap is the largest N whose before run fits 9,000. Run it under each node
the model may get (pwsh and Git Bash can resolve different ones). Exit 0 = all pass.
"""
import contextlib
import hashlib
import importlib.util
import io
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
# run.ps1 $longCmd
TEST_CMD = ['node', '--test', '--test-reporter=./longfix/reporter.mjs', 'longfix/test/all.test.js']
FORBIDDEN = re.compile(r'(?i)pass|fail|ok|[|#\'"]')
with open(os.path.join(HERE, '..', 'run.ps1'), encoding='ascii') as _f:
    RUN_PS1 = _f.read()
SHOWN_TOTAL = int(re.search(r'(?m)^\$shownTotal = (\d+)$', RUN_PS1)[1])  # a run seen whole
# This test's own margin: run.ps1's -Modules cap must give a before run of at most
# SHOWN_TOTAL - CAP_MARGIN chars, and cap + 1 more than that.
CAP_MARGIN = 500
MODULE_LINE = re.compile(r'(m\d\d|\?) (ok|FAIL) (\d+)/(\d+)(?:: (.+))?')


def node_version():
    return subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()


class GenLongfix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='genlf-')
        # Mimic the run.ps1 work path (<LOCALAPPDATA>\lis-ladder\<stamp>-<case>\work); the
        # reporter's output names no path, so its size does not depend on it.
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
        self.assertEqual(ta['longfix/reporter.mjs'], gen.REPORTER.encode('ascii'))
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
        self.assertEqual((len(m['tests']), len(m['files'])), (12, 10))
        for f in m['files']:
            if f['path'].startswith('longfix/src/'):
                self.assertLessEqual(abs(f['lines'] - 120), 5, f['path'])

    def test_refusals(self):
        with self.assertRaises(SystemExit):
            gen.generate(self.b, os.path.join(self.tmp, 'again.json'))
        with self.assertRaises(SystemExit):
            gen.generate(os.path.join(self.tmp, 'big'), os.path.join(self.tmp, 'x.json'), lines=291)

    def run_node(self, cwd):
        r = subprocess.run(TEST_CMD, cwd=cwd, capture_output=True,
                           encoding='utf-8', errors='replace', timeout=300)
        return r.returncode, r.stdout + r.stderr

    def read_compact(self, out):
        # The reporter's output: {module: (passed, total, failing names)}, pass, fail.
        *body, sum_pass, sum_fail, end = out.split('\n')
        self.assertEqual(end, '', out[-200:])
        self.assertRegex(sum_pass, r'^# pass \d+$')
        self.assertRegex(sum_fail, r'^# fail \d+$')
        rows = {}
        for line in body:
            m = MODULE_LINE.fullmatch(line)
            self.assertIsNotNone(m, line)
            names = m[5].split('; ') if m[5] else []
            self.assertEqual((m[2], int(m[4]) - int(m[3])), ('FAIL' if names else 'ok', len(names)))
            self.assertNotIn(m[1], rows, line)
            rows[m[1]] = (int(m[3]), int(m[4]), names)
        return rows, int(sum_pass.split()[2]), int(sum_fail.split()[2])

    def expect(self, tests, passing=()):
        # What the reporter must print for a manifest's tests; passing: names fixed since.
        rows = {}
        for t in tests:
            p, n, failed = rows.get(t['module'], (0, 0, []))
            ok = t['expect_before'] == 'pass' or t['name'] in passing
            rows[t['module']] = (p + ok, n + 1, failed if ok else failed + [t['name']])
        return rows

    def check_run(self, out, tests, passing=()):
        rows, n_pass, n_fail = self.read_compact(out)
        want = self.expect(tests, passing)
        self.assertEqual(list(rows), list(want))
        self.assertEqual(rows, want)
        self.assertEqual((n_pass, n_fail), (sum(r[0] for r in want.values()),
                                            sum(r[1] - r[0] for r in want.values())))
        self.assertLessEqual(len(out), SHOWN_TOTAL)
        return n_pass, n_fail

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_before(self):
        rc, out = self.run_node(self.a)  # exactly the prompt's test command
        print(f'\nnode {node_version()}; before-run output {len(out)} chars', file=sys.stderr)
        self.assertNotEqual(rc, 0)
        self.assertNotRegex(out, r'SyntaxError|ReferenceError')
        self.assertEqual(self.check_run(out, self.ma['tests']), (24, 48))

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_node_solved(self):
        out = os.path.join(self.tmp, 'solved')
        m = gen.generate(out, os.path.join(self.tmp, 'solved.json'), solve=True)
        rc, run = self.run_node(out)
        self.assertEqual(rc, 0, run[-2000:])
        names = {t['name'] for t in m['tests']}
        self.assertEqual(self.check_run(run, m['tests'], names), (72, 0))

    def test_modules_48(self):
        # The CLI path run.ps1 -Modules 48 takes: --modules 48, twice, byte-identical.
        roots, docs = [], []
        for tag in ('m48a', 'm48b'):
            out, man = os.path.join(self.tmp, tag), os.path.join(self.tmp, tag + '.json')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gen.main(['--out', out, '--manifest', man, '--modules', '48']), 0)
            with open(man, encoding='ascii') as f:
                docs.append(json.load(f))
            roots.append(out)
        m = docs[0]
        self.assertEqual(self.tree(roots[0]), self.tree(roots[1]))
        self.assertEqual(m['fixture_sha256'], docs[1]['fixture_sha256'])
        self.assertNotEqual(m['fixture_sha256'], self.ma['fixture_sha256'])
        self.assertEqual(m['generator']['modules'], 48)
        src = [f['path'] for f in m['files'] if f['path'].startswith('longfix/src/')]
        self.assertEqual([p.split('/')[-1][:4] for p in src],
                         [f'm{i:02d}-' for i in range(1, 49)])
        tests = m['tests']
        self.assertEqual(len(tests), 144)
        self.assertEqual(len({t['name'] for t in tests}), 144)
        self.assertEqual(sum(t['expect_before'] == 'fail' for t in tests), 96)
        # Bug pair of module i: K[(2i-2) % 14] and K[(2i-1) % 14], so it repeats every 7.
        pairs = {}
        for t in tests:
            if t['kind'] == 'bug':
                pairs.setdefault(int(t['module'][1:]), []).append(t['name'].split(' ', 2)[2])
        for i in range(1, 49):
            k = len(gen.K)
            self.assertEqual(pairs[i], [gen.K[(2 * i - 2) % k]['does'],
                                        gen.K[(2 * i - 1) % k]['does']], i)
            if i > 7:
                self.assertEqual(pairs[i], pairs[i - 7], i)
        if shutil.which('node'):
            rc, out = self.run_node(roots[0])  # the prompt's command
            self.assertNotEqual(rc, 0)
            self.assertEqual(self.check_run(out, tests), (48, 96))
            print(f'\nnode {node_version()}; 48 modules: before-run output {len(out)} chars',
                  file=sys.stderr)

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_partial_solve(self):
        # 48 modules with m01..m24 fixed (the solve=True sources): the mid-task view.
        out, sol = os.path.join(self.tmp, 'half'), os.path.join(self.tmp, 'half-solved')
        m = gen.generate(out, out + '.json', modules=48)
        gen.generate(sol, sol + '.json', modules=48, solve=True)
        for f in m['files']:
            if re.match(r'longfix/src/m(0\d|1\d|2[0-4])-', f['path']):
                shutil.copyfile(os.path.join(sol, f['path']), os.path.join(out, f['path']))
        fixed = {t['name'] for t in m['tests'] if int(t['module'][1:]) <= 24}
        rc, run = self.run_node(out)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.check_run(run, m['tests'], fixed), (96, 48))
        rows = self.read_compact(run)[0]
        self.assertEqual({k: v[:2] for k, v in rows.items()},
                         {f'm{i:02d}': (3, 3) if i <= 24 else (1, 3) for i in range(1, 49)})
        print(f'\nnode {node_version()}; 48 modules, m01..m24 fixed: {len(run)} chars',
              file=sys.stderr)

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_load_error(self):
        # A module that fails to load stops all.test.js: one '?' test (the entry file) and no
        # mNN line. The test:fail event only says 'test failed' and there is no stack, so
        # all.test.js's load() names the module on stderr, which the reporter passes on.
        # The thrown message names no module, so only load() can name it.
        for case, edit, line in (
                ('throw', lambda t: t + "\nthrow new Error('top-level failure');\n",
                 'Error: top-level failure'),
                ('syntax', lambda t: t.replace('\nfunction ', '\nfunction (', 1),
                 'SyntaxError: Function statements require a function name')):
            with self.subTest(case):
                out = os.path.join(self.tmp, 'loaderr-' + case)
                m = gen.generate(out, out + '.json', modules=8)
                src = next(f['path'] for f in m['files']
                           if f['path'].startswith('longfix/src/m07-'))
                with open(os.path.join(out, src), encoding='ascii') as f:
                    text = edit(f.read())
                with open(os.path.join(out, src), 'w', encoding='ascii', newline='\n') as f:
                    f.write(text)
                rc, run = self.run_node(out)
                self.assertEqual(rc, 1, run)
                self.assertRegex(run, rf'(?m)^load error in {src}: {line}$')
                self.assertRegex(run, r'\n\? FAIL 0/1: longfix[\\/]test[\\/]all\.test\.js\n'
                                      r'# pass 0\n# fail 1\n$')
                self.assertNotRegex(run, r'(?m)^m\d\d ')
                if case == 'syntax':  # node's own report, with the path, still follows
                    self.assertRegex(run, r'longfix[\\/]src[\\/]m07-\w+\.js:\d+\n')

    @unittest.skipUnless(shutil.which('node'), 'node not on PATH')
    def test_module_cap(self):
        # run.ps1's -Modules cap is the largest N whose before run fits SHOWN_TOTAL less
        # CAP_MARGIN; the generator's own cap (99) is printed for the record.
        cap = int(re.search(r'ValidateRange\(7, (\d+)\)\]\[int\]\$Modules', RUN_PS1)[1])
        sizes = {}
        for n in sorted({cap, min(cap + 1, 99), 99}):
            out = os.path.join(self.tmp, f'cap{n}')
            m = gen.generate(out, out + '.json', modules=n)
            rc, run = self.run_node(out)
            self.assertNotEqual(rc, 0)
            rows, n_pass, n_fail = self.read_compact(run)
            self.assertEqual((len(rows), n_pass, n_fail), (n, n, 2 * n))
            self.assertEqual(rows, self.expect(m['tests']))
            sizes[n] = len(run)
        self.assertLessEqual(sizes[cap], SHOWN_TOTAL - CAP_MARGIN)
        if cap < 99:
            self.assertGreater(sizes[cap + 1], SHOWN_TOTAL - CAP_MARGIN)
        print(f'\nnode {node_version()}; before-run chars by modules: {sizes} (cap {cap})',
              file=sys.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
