"""Unit tests for bench/ladder/gen_stalefig.py and the stale-figure dry run of run.ps1. Run:
python -I bench/ladder/tests/gen_stalefig_test.py

Generates the fixture into temp dirs: determinism and hash, the manifest figures against
the files, the docs' numbers, the planted value's absence from the code, neutral names,
the fixture's own test suite (node) and its size, refusals that write nothing, and the
fixture_sha256 of a fresh `python -I` process against the pinned FIXTURE_SHA256. The last
test runs `run.ps1 -Case stale-figure -DryRun` (pwsh; no session, no server request) and
checks the printed fixture_sha256 against the pin, the run-dir leaf and fixture commit for
words that name the case, the fixture commit hash against its pin (dates pinned by run.ps1),
the policy_sha256 against the wrapper's -LisPrintArgs output and the rep_key against the ten
inputs, under the default -Hint grammar; the one after it runs it with -Hint named (the
prompt's doc-check sentence only, a new rep_key, the same fixture, commit and policy). The
last runs a copy of run.ps1 -Case fix-one -DryRun in a temp repo layout whose fixture has no
test file: a failed precondition exits 1. All three are skipped without pwsh.
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load('gen_stalefig', 'gen_stalefig.py')
sf = load('stalefig', 'stalefig.py')
SETTING = re.compile(r'MAX_BATCH|TIMEOUT_MS|RETRY_LIMIT')
DOCS = ('tallyctl/README.md', 'tallyctl/CHANGELOG.md')
# The fixture of generator VERSION 1; a deliberate fixture change updates both.
FIXTURE_SHA256 = '597a8e5356da75d0d1102e2373d9d74330320cc1cbdea0914d47cd61dbfc5402'
# SHA-256 of run.ps1's stale-figure prompt as the dry run prints it, by -Hint (named: the
# series 1 prompt); a deliberate prompt change updates these.
PROMPT_SHA256 = {'named': '81fbd15fbe9b610b74239f87a9fba4833d4bdecbe8a5fd699dc7a9393bac850c',
                 'grammar': 'cb9a0679a9fd6be17122326a910b041ae03de4ff0a261434e0a8c0b2bdda89eb'}
# The work tree's commit as run.ps1 makes it (identity and dates pinned): the same in every
# dry run and real run of this fixture; a fixture or commit change updates it.
FIXTURE_COMMIT_SHA = 'ecefb910e650d96df7a945a5a910b7a20a26fec7'


def tree(root):
    """{relative path: bytes} of the files under root, or None when root does not exist."""
    if not os.path.exists(root):
        return None
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            with open(os.path.join(d, n), 'rb') as f:
                out[os.path.relpath(os.path.join(d, n), root)] = f.read()
    return out

def link_dir(target, link):
    """A directory symlink to target, else (Windows) a junction; False when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        pass
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
        return True
    except (ImportError, OSError):
        return False


class GenStaleFig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix='sfg-')
        cls.work = os.path.join(cls.root, 'a')
        cls.doc = gen.generate(cls.work, os.path.join(cls.root, 'a.json'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def text(self, rel):
        with open(os.path.join(self.work, rel), 'rb') as f:
            return f.read().decode('ascii')

    def lines(self, rel):
        return self.text(rel).split('\n')

    def test_deterministic_and_hash(self):
        b = os.path.join(self.root, 'b')
        doc = gen.generate(b, os.path.join(self.root, 'b.json'))
        self.assertEqual(doc, self.doc)
        whole = hashlib.sha256()
        for f in self.doc['files']:
            data = self.text(f['path']).encode('ascii')
            with open(os.path.join(b, f['path']), 'rb') as g:
                self.assertEqual(g.read(), data)
            whole.update(f['path'].encode('ascii') + b'\0' + data + b'\0')
            self.assertEqual(f['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(whole.hexdigest(), self.doc['fixture_sha256'])
        with open(os.path.join(self.root, 'a.json'), 'rb') as f1, \
                open(os.path.join(self.root, 'b.json'), 'rb') as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_refusals(self):
        # A non-empty fixture tree, then a manifest under out: in the fixture tree, directly
        # in out, in a subdir of out, out itself. Each refusal writes nothing.
        e = os.path.join(self.root, 'e')
        for out, manifest in ((self.work, os.path.join(self.root, 'c.json')),
                              (os.path.join(self.root, 'd'),
                               os.path.join(self.root, 'd', 'tallyctl', 'm.json')),
                              (e, os.path.join(e, 'm.json')),
                              (e, os.path.join(e, 'sub', 'm.json')),
                              (e, e)):
            before = tree(out)
            with self.assertRaises(SystemExit):
                gen.generate(out, manifest)
            self.assertEqual(tree(out), before, out)
            if manifest != out:
                self.assertFalse(os.path.exists(manifest), manifest)

    def test_refuses_manifest_through_link(self):
        # A manifest reached through a symlink or junction into out; writes nothing.
        out, lnk = os.path.join(self.root, 'lnk-out'), os.path.join(self.root, 'lnk')
        os.makedirs(out)
        if not link_dir(out, lnk):
            self.skipTest('no directory link')
        with self.assertRaises(SystemExit):
            gen.generate(out, os.path.join(lnk, 'm.json'))
        self.assertEqual(tree(out), {})

    def test_cross_process_sha_pinned(self):
        # A fresh interpreter, as run.ps1 runs the generator: import-time nondeterminism
        # passes test_deterministic_and_hash (one process) but not this.
        with tempfile.TemporaryDirectory(prefix='sfg-') as out, \
                tempfile.TemporaryDirectory(prefix='sfg-') as mdir:
            p = subprocess.run([sys.executable, '-I', 'bench/ladder/gen_stalefig.py', '--out', out,
                                '--manifest', os.path.join(mdir, 'm.json')], cwd=REPO,
                               capture_output=True, encoding='utf-8', errors='replace',
                               timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            with open(os.path.join(mdir, 'm.json'), 'rb') as f:
                doc = json.loads(f.read().decode('ascii'))
        self.assertEqual(doc['generator']['version'], 1)
        self.assertEqual(doc['fixture_sha256'], FIXTURE_SHA256)
        self.assertEqual(self.doc['fixture_sha256'], FIXTURE_SHA256)

    def test_figures_hold_their_values(self):
        kinds = [f['kind'] for f in self.doc['figures']]
        self.assertEqual(kinds, ['planted', 'guard_current', 'guard_current', 'guard_historical'])
        for f in self.doc['figures']:
            for path, line, want in ((f['doc_path'], f['doc_line'], f['doc_value']),
                                     (f['src_path'], f['src_line'], f['true_value']),
                                     (f['test_path'], f['test_line'], f['true_value'])):
                held = self.lines(path)[line - 1]
                self.assertIn(want, sf.ints(held), (f['kind'], path, line))
                self.assertIn(f['name'], held)
            same = f['doc_value'] == f['true_value']
            self.assertEqual(same, f['kind'] == 'guard_current', f['kind'])
        planted = self.doc['figures'][0]
        self.assertEqual((planted['name'], planted['doc_value'], planted['true_value']),
                         ('MAX_BATCH', 500, 250))
        hist = self.lines('tallyctl/CHANGELOG.md')[self.doc['figures'][3]['doc_line'] - 1]
        self.assertEqual(hist, '- `RETRY_LIMIT` raised from 3 to 4.')
        self.assertEqual(sf.ints(hist), [3, 4])

    def test_changelog_names_one_setting_once(self):
        named = [i for i, ln in enumerate(self.lines('tallyctl/CHANGELOG.md'), 1)
                 if SETTING.search(ln)]
        self.assertEqual(named, [self.doc['figures'][3]['doc_line']])

    def test_every_doc_line_with_a_setting_or_number_is_listed(self):
        for doc in DOCS:
            listed = {f['doc_line'] for f in self.doc['figures'] if f['doc_path'] == doc}
            found = {i for i, ln in enumerate(self.lines(doc), 1)
                     if SETTING.search(ln) or sf.ints(ln)}
            self.assertEqual(found, listed, doc)
        readme = self.text('tallyctl/README.md')
        for name in ('MAX_BATCH', 'TIMEOUT_MS', 'RETRY_LIMIT'):
            self.assertEqual(readme.count(name), 1, name)

    def test_planted_value_only_in_the_readme(self):
        for f in self.doc['files']:
            if f['path'] != 'tallyctl/README.md':
                self.assertNotIn('500', self.text(f['path']), f['path'])

    def test_neutral_names(self):
        words = re.compile(r'(?i)stale|planted|contradict|bench|ladder|grade')
        for f in self.doc['files']:
            self.assertIsNone(words.search(f['path']), f['path'])
            self.assertIsNone(words.search(self.text(f['path'])), f['path'])
        for rel in DOCS + ('tallyctl/package.json',):
            self.assertIsNone(re.search(r'(?i)test', self.text(rel)), rel)

    def test_suite_passes(self):
        p = subprocess.run(['node', '--test', '--test-reporter=tap', 'tallyctl/test/all.test.js'],
                           cwd=self.work, capture_output=True, encoding='utf-8',
                           errors='replace', timeout=120)
        oks = re.findall(r'(?m)^(not )?ok \d+ - (.*)$', p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertEqual([n for bad, n in oks if not bad], [t['name'] for t in self.doc['tests']])
        self.assertEqual(len(oks), 11)

    def test_sizes(self):
        files = {f['path']: f['lines'] for f in self.doc['files']}
        self.assertEqual(len(files), 12)
        self.assertEqual(sum(files.values()), 278)
        self.assertEqual(len([p for p in files if p.startswith('tallyctl/src/')]), 7)
        self.assertEqual((files['tallyctl/README.md'], files['tallyctl/CHANGELOG.md'],
                          files['tallyctl/src/config.js'], files['tallyctl/test/all.test.js']),
                         (23, 19, 8, 76))

    def test_verify_doc_finds_nothing_in_the_docs(self):
        for doc in DOCS:
            p = subprocess.run([sys.executable, '-I', os.path.join(REPO, 'scripts', 'verify-doc.py'),
                                os.path.join(self.work, doc), '--root', self.work],
                               capture_output=True, encoding='utf-8', errors='replace',
                               timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertNotIn('FAIL', p.stdout)


@unittest.skipUnless(shutil.which('pwsh'), 'pwsh not found')
class DryRun(unittest.TestCase):
    runs = {}

    def dry_run(self, *extra):
        """run.ps1 -Case stale-figure -DryRun <extra>, once per argument list: (exit code,
        output, entries left in -WorkRoot)."""
        if extra not in DryRun.runs:
            with tempfile.TemporaryDirectory(prefix='sfd-', ignore_cleanup_errors=True) as root:
                # GIT_* identity and date variables override git's -c user.* and the
                # clock: run.ps1 must pin them.
                leak = {'GIT_AUTHOR_NAME': 'leak', 'GIT_AUTHOR_EMAIL': 'leak@x',
                        'GIT_COMMITTER_NAME': 'leak', 'GIT_COMMITTER_EMAIL': 'leak@x',
                        'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z',
                        'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z'}
                p = subprocess.run(['pwsh', '-NoProfile', '-File', RUN_PS1,
                                    '-Case', 'stale-figure', '-DryRun', '-WorkRoot', root,
                                    '-OutDir', root, *extra], cwd=REPO, capture_output=True,
                                   encoding='utf-8', errors='replace', timeout=300,
                                   env={**os.environ, **leak})
                left = os.listdir(root)
            DryRun.runs[extra] = (p.returncode, re.sub(r'\x1b\[[0-9;]*m', '', p.stdout + p.stderr),
                                  left)
        return DryRun.runs[extra]

    def field(self, out, rx):
        m = re.search(rx, out, re.M)
        self.assertIsNotNone(m, rx)
        return m.group(1)

    def test_stale_figure_dry_run(self):
        code, out, left = self.dry_run()
        self.assertEqual(code, 0, out[-3000:])
        self.assertEqual(left, [])  # the dry run deletes its work tree and manifest

        def field(rx):
            return self.field(out, rx)
        self.assertIn('precondition: ok, pass 11 of 11', out)
        self.assertEqual(field(r'^hint: (\S+) '), 'grammar')  # the default (ruling 38)
        fixture = field(r'^fixture_sha256: ([0-9a-f]{64}) \(generator version=1; tree hash matches\)')
        self.assertEqual(fixture, FIXTURE_SHA256)
        # The model sees its cwd (the leaf) and git log (the commit): neither names the case.
        leaf = field(r'^work_leaf: (\S+)$')
        commit = field(r'^(fixture_commit: .+)$')
        self.assertRegex(leaf, r'^\d{8}-\d{6}-w1$')
        tell = re.compile(r'(?i)stale|figure|ladder|fixture|bench|planted')
        self.assertIsNone(tell.search(leaf), leaf)
        self.assertIsNone(tell.search(commit.split(': ', 1)[1]), commit)
        self.assertEqual(commit, 'fixture_commit: dev <dev@localhost> '
                                 '(committer dev <dev@localhost>) "release 1.3.0"')
        self.assertEqual(field(r'^fixture_commit_sha: ([0-9a-f]{40}) '), FIXTURE_COMMIT_SHA)
        ctx = field(r'^case: stale-figure \(profile review, loop guard on, context_tokens (\d+)')
        node = field(r'\| model_node_version: (v\d+\.\d+\.\d+) ')
        prompt = field(r'^prompt \(\d+ chars, one argv string\):\n  (.*)$')
        self.assertEqual(hashlib.sha256(prompt.encode('utf-8')).hexdigest(), PROMPT_SHA256['grammar'])
        policy = field(r'^policy_sha256: ([0-9a-f]{64}) ')
        key = field(r'^rep_key: ([0-9a-f]{64}) ')

        w = subprocess.run(['pwsh', '-NoProfile', '-File',
                            os.path.join(REPO, 'scripts', 'claude-local.ps1'), '-LisTask',
                            'review', '-LisPrintArgs', '-p', 'x'], cwd=REPO,
                           capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        arr = json.loads(re.search(r'claude arguments \(JSON array, in order\):\s*(\[.*?\n\])',
                                   w.stdout, re.S).group(1))
        text = arr[arr.index('--append-system-prompt') + 1]
        self.assertEqual(policy, hashlib.sha256(text.encode('utf-8')).hexdigest())

        nine = [fixture, 'version=1', prompt, '', '', '30', '15', ctx, node]
        digest = lambda vals: hashlib.sha256('\n'.join(vals).encode('utf-8')).hexdigest()  # noqa: E731
        self.assertEqual(key, digest(nine + [policy]))
        self.assertNotEqual(key, digest(nine))

    def test_hint_named_dry_run(self):
        # -Hint named (the series 1 prompt): only the doc-check sentence differs, so a new key
        # (the prompt is an input) on the same fixture, commit and policy.
        code, out, left = self.dry_run('-Hint', 'named')
        self.assertEqual(code, 0, out[-3000:])
        self.assertEqual(left, [])
        self.assertEqual(self.field(out, r'^hint: (\S+) '), 'named')
        prompt_rx = r'^prompt \(\d+ chars, one argv string\):\n  (.*)$'
        named = self.field(out, prompt_rx)
        self.assertEqual(hashlib.sha256(named.encode('utf-8')).hexdigest(), PROMPT_SHA256['named'])
        self.assertIn('check every statement', named)
        code0, out0, _ = self.dry_run()
        self.assertEqual(code0, 0, out0[-3000:])
        prompt = self.field(out0, prompt_rx)
        self.assertNotIn('check every statement', prompt)
        self.assertIn('If anything you read in tallyctl/', prompt)
        self.assertEqual(prompt, named.replace(
            'Then check every statement about these three settings in tallyctl/README.md and '
            'tallyctl/CHANGELOG.md against the code. For each one the code contradicts, one line:',
            'If anything you read in tallyctl/ states a different value for one of these settings '
            'than the code does, add one line for each:').replace(
            "If there is none, the line 'CONTRADICTION none'.",
            "If you found none, the line 'CONTRADICTION none'."))
        for rx in (r'^fixture_sha256: ([0-9a-f]{64}) ', r'^policy_sha256: ([0-9a-f]{64}) ',
                   r'^fixture_commit_sha: ([0-9a-f]{40}) '):
            self.assertEqual(self.field(out, rx), self.field(out0, rx), rx)
        key_rx = r'^rep_key: ([0-9a-f]{64}) '
        self.assertNotEqual(self.field(out, key_rx), self.field(out0, key_rx))

    def test_failed_precondition_exits_1(self):
        # A copy of run.ps1 in a temp repo layout (fixture without its test file, a stub
        # wrapper that exits 0): the BEFORE tests find none of the targets, so -DryRun prints
        # 'precondition: FAIL' and exits 1 with the reason on stderr, as a real run refuses.
        with tempfile.TemporaryDirectory(prefix='sfp-', ignore_cleanup_errors=True) as root:
            lad, wr = os.path.join(root, 'bench', 'ladder'), os.path.join(root, 'wr')
            os.makedirs(lad)
            os.makedirs(os.path.join(root, 'scripts'))
            for name in ('run.ps1', 'grade.py'):
                shutil.copyfile(os.path.join(REPO, 'bench', 'ladder', name),
                                os.path.join(lad, name))
            shutil.copytree(os.path.join(REPO, 'bench', 'loop', 'fixture'),
                            os.path.join(root, 'bench', 'loop', 'fixture'))
            os.remove(os.path.join(root, 'bench', 'loop', 'fixture', 'test', 'text.test.js'))
            with open(os.path.join(root, 'scripts', 'claude-local.ps1'), 'w') as f:
                f.write('exit 0\n')
            p = subprocess.run(['pwsh', '-NoProfile', '-File', os.path.join(lad, 'run.ps1'),
                                '-Case', 'fix-one', '-DryRun', '-WorkRoot', wr, '-OutDir', wr],
                               cwd=root, capture_output=True, encoding='utf-8',
                               errors='replace', timeout=300)
            left = os.listdir(wr) if os.path.isdir(wr) else []
        self.assertIn('precondition: FAIL', p.stdout, p.stdout[-3000:] + p.stderr[-2000:])
        self.assertEqual(p.returncode, 1, p.stderr[-2000:])
        self.assertIn('is invalid, precondition FAIL: truncate keeps', p.stderr)
        self.assertEqual(left, [])  # the work tree is deleted before the exit


if __name__ == '__main__':
    unittest.main()
