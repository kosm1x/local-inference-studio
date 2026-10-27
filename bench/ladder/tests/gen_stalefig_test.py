"""Unit tests for bench/ladder/gen_stalefig.py and the stale-figure dry run of run.ps1. Run:
python -I bench/ladder/tests/gen_stalefig_test.py

Generates the fixture into temp dirs: determinism and hash, the manifest figures against
the files, the docs' numbers, the planted value's absence from the code, neutral names,
the fixture's own test suite (node) and its size. The last test runs
`run.ps1 -Case stale-figure -DryRun` (pwsh; no session, no server request) and checks the
printed policy_sha256 against the wrapper's -LisPrintArgs output and the rep_key against
the ten inputs; it is skipped without pwsh.
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load('gen_stalefig', 'gen_stalefig.py')
sf = load('stalefig', 'stalefig.py')
SETTING = re.compile(r'MAX_BATCH|TIMEOUT_MS|RETRY_LIMIT')
DOCS = ('tallyctl/README.md', 'tallyctl/CHANGELOG.md')


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
        with self.assertRaises(SystemExit):
            gen.generate(self.work, os.path.join(self.root, 'c.json'))
        with self.assertRaises(SystemExit):
            gen.generate(os.path.join(self.root, 'd'),
                         os.path.join(self.root, 'd', 'tallyctl', 'm.json'))

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
    def test_stale_figure_dry_run(self):
        root = tempfile.mkdtemp(prefix='sfd-')
        try:
            p = subprocess.run(['pwsh', '-NoProfile', '-File',
                                os.path.join(REPO, 'bench', 'ladder', 'run.ps1'),
                                '-Case', 'stale-figure', '-DryRun', '-WorkRoot', root,
                                '-OutDir', root], cwd=REPO, capture_output=True,
                               encoding='utf-8', errors='replace', timeout=300)
            left = os.listdir(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        out = re.sub(r'\x1b\[[0-9;]*m', '', p.stdout + p.stderr)
        self.assertEqual(p.returncode, 0, out[-3000:])
        self.assertEqual(left, [])  # the dry run deletes its work tree and manifest

        def field(rx):
            m = re.search(rx, out, re.M)
            self.assertIsNotNone(m, rx)
            return m.group(1)
        self.assertIn('precondition: ok, pass 11 of 11', out)
        fixture = field(r'^fixture_sha256: ([0-9a-f]{64}) \(generator version=1; tree hash matches\)')
        self.assertEqual(fixture, gen.generate(os.path.join(tempfile.mkdtemp(prefix='sfh-'), 'w'),
                                               os.path.join(tempfile.gettempdir(),
                                                            'sfh-manifest.json'))['fixture_sha256'])
        ctx = field(r'^case: stale-figure \(profile review, loop guard on, context_tokens (\d+)')
        node = field(r'\| model_node_version: (v\d+\.\d+\.\d+) ')
        prompt = field(r'^prompt \(\d+ chars, one argv string\):\n  (.*)$')
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


if __name__ == '__main__':
    unittest.main()
