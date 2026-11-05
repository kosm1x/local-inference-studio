"""Unit tests for scripts/hooks/facts-inject.py. Run:
python -I scripts/hooks/tests/facts-inject_test.py [hook]

Exit 0 = all pass. The optional argument is a hook file to test instead of the default
(used to prove that file mutants go red). Every case runs the hook as Claude Code does
(stdin JSON, python -I) in a throwaway directory, with LIS_FACTS_FILE and
LIS_FACTS_INJECT_LOG set or unset per case, so no session file is touched; cap() is also
checked directly.
"""
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
HOOK = os.path.abspath(sys.argv.pop(1)) if len(sys.argv) > 1 \
    else os.path.join(HERE, '..', 'facts-inject.py')
spec = importlib.util.spec_from_file_location('facts_inject', HOOK)
fi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fi)
NAME = 'lis-facts-20261104-120000.md'
LINES = ['BEFORE pass 1 fail 2', 'CHECK pass 2 fail 1', 'FIXED m01 a | longfix/src/m01-a.js',
         'NEXT m02']
LOG_RE = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00 source=(\S+) facts=(\S+) '
                    r'injected=(?:yes lines=(\d+) bytes=(\d+) truncated=(yes|no)'
                    r'|no reason=(input|unset|missing|empty|oversize|error))$')
SMILE = '\U0001F600'  # outside the BMP: 1 character, 2 UTF-16 units


def units(s):
    return len(s.encode('utf-16-le')) // 2


class FactsInject(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='facts-inject-')
        self.work = os.path.join(self.root, 'work')
        self.other = os.path.join(self.root, 'other')
        os.makedirs(self.work)
        os.makedirs(self.other)
        self.log = os.path.join(self.root, 'inject.log')

    def tearDown(self):
        shutil.rmtree(self.root)

    def facts(self, body, d=None):
        with open(os.path.join(d or self.work, NAME), 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)

    def run_hook(self, stdin=None, name=NAME, log=True, cwd=None):
        """Run the hook; stdin None sends a compact SessionStart event naming self.work."""
        env = dict(os.environ)  # a copy for the child (lis-guard: not an environment dump)
        env.pop('LIS_FACTS_FILE', None)
        env.pop('LIS_FACTS_INJECT_LOG', None)
        if name is not None:
            env['LIS_FACTS_FILE'] = name
        if log:
            env['LIS_FACTS_INJECT_LOG'] = self.log
        if stdin is None:
            stdin = json.dumps({'session_id': 'abc', 'hook_event_name': 'SessionStart',
                                'source': 'compact', 'cwd': self.work})
        p = subprocess.run([sys.executable, '-I', HOOK], input=stdin.encode('utf-8'),
                           capture_output=True, env=env, cwd=cwd or self.other, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.decode('utf-8')

    def log_lines(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding='utf-8', newline='') as f:
            return f.read().splitlines(keepends=True)

    def logged(self):
        """The log lines as match objects (each must match the format)."""
        m = [LOG_RE.match(x.rstrip('\n')) for x in self.log_lines()]
        self.assertTrue(all(m), self.log_lines())
        return m

    def ctx(self, out):
        o = json.loads(out)
        self.assertEqual(list(o), ['hookSpecificOutput'])
        self.assertEqual(o['hookSpecificOutput']['hookEventName'], 'SessionStart')
        return o['hookSpecificOutput']['additionalContext']

    def test_injects_the_facts_file_from_stdin_cwd(self):
        body = '\n'.join(LINES) + '\n'
        self.facts(body)
        c = self.ctx(self.run_hook())
        head, rest = c.split('\n', 1)
        self.assertIn(NAME, head)
        self.assertIn(f'(4 lines, {len(body)} bytes)', head)
        self.assertNotIn('Only its last', head)
        self.assertEqual(rest, body)

    def test_log_line_format(self):
        body = '\n'.join(LINES) + '\n'
        self.facts(body)
        self.run_hook()
        self.run_hook(stdin=json.dumps({'trigger': 'auto', 'cwd': self.work}))
        logs = self.log_lines()
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(x.endswith('\n') and not x.endswith('\r\n') for x in logs))
        m = self.logged()
        self.assertEqual(m[0].groups()[:5], ('compact', NAME, '4', str(len(body)), 'no'))
        self.assertEqual(m[1].group(1), 'auto')

    def test_odd_source_is_sanitised(self):
        self.facts('BEFORE pass 1 fail 2\n')
        self.run_hook(stdin=json.dumps({'source': 'a b\nc', 'cwd': self.work}))
        self.run_hook(stdin=json.dumps({'cwd': self.work}))
        self.assertEqual([x.group(1) for x in self.logged()], ['a_b_c', 'unknown'])

    def test_no_log_without_env(self):
        self.facts('BEFORE pass 1 fail 2\n')
        self.assertTrue(self.ctx(self.run_hook(log=False)))
        self.assertEqual(self.run_hook(name=None, log=False), '')
        self.assertFalse(os.path.exists(self.log))

    def test_every_run_logs_a_line_with_its_reason(self):
        # One line per compaction, injected or not, so the k-th line is the k-th boundary.
        self.assertEqual(self.run_hook(name=None), '')
        self.assertEqual(self.run_hook(), '')  # no file yet
        self.facts('')
        self.assertEqual(self.run_hook(), '')
        self.facts('\n\n  \n')
        self.assertEqual(self.run_hook(), '')
        self.facts('BEFORE pass 1 fail 2\n')
        self.assertTrue(self.ctx(self.run_hook()))
        m = self.logged()
        self.assertEqual([(x.group(2), x.group(6)) for x in m],
                         [('-', 'unset'), (NAME, 'missing'), (NAME, 'empty'), (NAME, 'empty'),
                          (NAME, None)])
        self.assertEqual(m[-1].group(5), 'no')

    def test_process_cwd_without_stdin_cwd(self):
        self.facts('BEFORE pass 1 fail 2\n', d=self.other)
        c = self.ctx(self.run_hook(stdin=json.dumps({'source': 'compact'})))
        self.assertTrue(c.endswith('BEFORE pass 1 fail 2\n'))

    def test_process_cwd_when_stdin_cwd_lacks_the_file(self):
        # The session cd'd into a subdirectory: the hook's own cwd still finds the file.
        self.facts('BEFORE pass 1 fail 2\n', d=self.other)
        self.assertTrue(self.ctx(self.run_hook()))

    def test_truncation_keeps_the_last_lines_under_the_cap(self):
        lines = [f'FIXED m{i:02d} test number {i} | longfix/src/m{i:02d}-x.js' for i in range(400)]
        body = '\n'.join(lines + ['NEXT none']) + '\n'
        self.assertGreater(len(body), 10_000)
        self.facts(body)
        c = self.ctx(self.run_hook())
        self.assertLess(units(c), 10_000)  # Claude Code spills a longer string to a file
        head, rest = c.split('\n', 1)
        self.assertIn('Only its last', head)
        self.assertTrue(rest.endswith('NEXT none\n'))
        self.assertTrue(body.endswith(rest))
        self.assertIn(rest.split('\n', 1)[0], lines)  # cut at a line boundary
        self.assertEqual(self.logged()[0].groups()[2:5], ('401', str(len(body)), 'yes'))

    def test_at_the_cap_is_not_truncated(self):
        body = ('x' * 99 + '\n') * 90  # exactly 9,000 units
        self.facts(body)
        c = self.ctx(self.run_hook())
        self.assertNotIn('Only its last', c.split('\n', 1)[0])
        self.assertTrue(c.endswith(body))

    def test_cap_keeps_a_whole_line_that_fits(self):
        # The cut lands exactly on a line start: that line fits and is kept.
        tail = 'b' * 8999 + '\n'
        self.assertEqual(fi.cap('a\n' + tail), (tail, True))
        self.assertEqual(fi.cap('a\n' + 'b' * 9000 + '\n'), ('', True))

    def test_cap_counts_utf16_units(self):
        # 100 lines of 49 non-BMP characters: 5,000 characters but 9,900 UTF-16 units.
        line = SMILE * 49 + '\n'
        body = line * 100
        self.assertLess(len(body), fi.CAP_UNITS)
        kept, cut = fi.cap(body)
        self.assertTrue(cut)
        self.assertEqual(kept, line * 90)  # 90 x 99 = 8,910 units; 91 lines would be 9,009
        self.facts(body)
        c = self.ctx(self.run_hook())
        self.assertLess(units(c), 10_000)
        self.assertIn('Only its last 90 lines', c.split('\n', 1)[0])

    def test_oversize_last_line_gives_nothing(self):
        self.facts('BEFORE pass 1 fail 2\n' + 'x' * 9001 + '\n')
        self.assertEqual(self.run_hook(), '')
        self.assertEqual(self.logged()[0].group(6), 'oversize')

    def test_malformed_stdin_exits_0_with_no_output(self):
        self.facts('BEFORE pass 1 fail 2\n')
        bad = ('', 'not json', '[1, 2]', '"x"', '{"cwd": ', '\x00\xff')
        for stdin in bad:
            self.assertEqual(self.run_hook(stdin=stdin), '', repr(stdin))
        m = self.logged()
        self.assertEqual([(x.group(1), x.group(2), x.group(6)) for x in m],
                         [('unknown', '-', 'input')] * len(bad))

    def test_bad_log_path_still_injects(self):
        self.facts('BEFORE pass 1 fail 2\n')
        self.log = os.path.join(self.root, 'no-such-dir', 'inject.log')
        self.assertTrue(self.ctx(self.run_hook()))


if __name__ == '__main__':
    unittest.main(verbosity=1)
