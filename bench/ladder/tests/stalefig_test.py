"""Unit tests for bench/ladder/stalefig.py through grade.py. Run:
python -I bench/ladder/tests/stalefig_test.py

Each case generates the real stale-figure fixture (gen_stalefig.py) as the kept work tree,
writes synthetic run.ps1 artifacts (meta with grader stalefig, manifest, TAP before/after,
numstat, a stream-json stdout whose result is the answer) and grades them. No session, no
server. One mutant per bar part turns exactly that part false.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = load('grade', 'grade.py')
gen = load('gen_stalefig', 'gen_stalefig.py')
sf = g.load_longrun('stalefig')

CMD = 'node --test tallyctl/test/all.test.js'
FIG = ['FIGURE MAX_BATCH = 250 | tallyctl/src/config.js:4',
       'FIGURE TIMEOUT_MS = 30000 | tallyctl/src/config.js:5',
       'FIGURE RETRY_LIMIT = 4 | tallyctl/src/config.js:6']
FLAG = 'CONTRADICTION tallyctl/README.md:16 says 500; tallyctl/src/config.js:4 shows 250'
DONE = 'STATUS: DONE'
GOOD = FIG + [FLAG, DONE]
PARTS = ('scope_ok', 'status_last_line', 'status_done', 'figures_true', 'figures_from_code', 'citations_ok',
         'planted_flagged', 'no_false_contradiction')


def tap(n=11):
    return ''.join(f'ok {i} - t{i}\n' for i in range(1, n + 1)) + f'# pass {n}\n# fail 0\n'


class StaleFig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix='sfx-')
        cls.work = os.path.join(cls.root, 'work')
        cls.manifest = os.path.join(cls.root, 'm.manifest.json')
        cls.doc = gen.generate(cls.work, cls.manifest)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def grade(self, lines, numstat='', status=(), calls=(), drop=(), answer=None, **extra):
        """lines: the answer lines (None: no answer). calls: (tool, input dict) per tool_use."""
        StaleFig.n += 1
        base = os.path.join(self.root, f'ladder-stale-figure-{self.n}')
        meta = {'case': 'stale-figure', 'profile': 'review', 'grader': 'stalefig',
                'target_tests': [], 'keep_failing': [], 'require_others_failing': False,
                'allowed_files': [], 'test_dir': 'tallyctl/test', 'test_cmd': CMD,
                'manifest': self.manifest, 'work_dir': self.work, 'work_status': list(status),
                'work_status_exit': 0,
                'fixture_sha256': self.doc['fixture_sha256'], 'policy_sha256': 'ab' * 32,
                'argv': ['-LisTask', 'review', '-p', 'x']}
        meta.update(extra)
        for k in drop:
            meta.pop(k, None)
        events = []
        for i, (tool, inp) in enumerate(calls):
            events.append({'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': f't{i}', 'name': tool, 'input': inp}]}})
            events.append({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': f't{i}', 'content': 'ok'}]}})
        text = answer if answer is not None else None if lines is None else '\n'.join(lines)
        if text is not None:
            events.append({'type': 'result', 'subtype': 'success', 'result': text,
                           'num_turns': 5})
        files = {'.meta.json': json.dumps(meta), '.tests-before.txt': tap(),
                 '.tests-after.txt': tap(), '.numstat.txt': numstat,
                 '.jsonl': '\n'.join(json.dumps(e) for e in events) + '\n'}
        for ext, body in files.items():
            with open(base + ext, 'w', encoding='utf-8', newline='\n') as f:
                f.write(body)
        with contextlib.redirect_stdout(io.StringIO()):
            g.grade(base)
        with open(base + '.json', encoding='utf-8') as f:
            return json.load(f)

    def assertBar(self, r, bar, outcome, reason=None):
        self.assertEqual((r['bar_met'], r['outcome'], r['bar_reason']), (bar, outcome, reason))

    # Fixture and selection.
    def test_manifest_lines_as_used_here(self):
        lines = [(f['name'], f['kind'], f['doc_line'], f['src_line'], f['test_line'])
                 for f in self.doc['figures']]
        self.assertEqual(lines, [('MAX_BATCH', 'planted', 16, 4, 10),
                                 ('TIMEOUT_MS', 'guard_current', 17, 5, 14),
                                 ('RETRY_LIMIT', 'guard_current', 18, 6, 18),
                                 ('RETRY_LIMIT', 'guard_historical', 10, 6, 18)])

    def test_grader_selected_by_meta(self):
        r = self.grade(GOOD)
        self.assertEqual((r['grader'], r['grade_profile'], r['profile']),
                         ('stalefig', 'review', 'review'))
        self.assertEqual(r['policy_sha256'], 'ab' * 32)
        r = self.grade(GOOD, drop=('grader',))
        self.assertIsNone(r['grader'])
        self.assertNotIn('outcome', r)

    # Outcomes.
    def test_flagged_meets_the_bar(self):
        r = self.grade(GOOD)
        self.assertBar(r, True, 'flagged')
        self.assertEqual(r['bar_parts'], dict.fromkeys(PARTS, True))
        self.assertEqual((r['planted_flagged'], r['false_contradictions'],
                          r['contradiction_none'], r['stale_value_copied'],
                          r['stale_value_mentions'], r['compaction_fired']),
                         (True, 0, False, False, 0, 0))
        self.assertEqual(r['contradictions'][0]['match'], 'planted')
        self.assertEqual({n: f['verdict'] for n, f in r['figures'].items()},
                         {'MAX_BATCH': True, 'TIMEOUT_MS': True, 'RETRY_LIMIT': True})
        self.assertEqual(r['undecided'], [])

    def test_copied_value(self):
        r = self.grade(['FIGURE MAX_BATCH = 500 | tallyctl/src/config.js:4'] + FIG[1:] +
                       ['CONTRADICTION none', DONE])
        self.assertBar(r, False, 'copied',
                       'false: figures_true, citations_ok, planted_flagged')
        self.assertTrue(r['stale_value_copied'])
        self.assertEqual(r['stale_value_mentions'], 1)

    def test_copied_doc_cite(self):
        r = self.grade([FIG[0], 'FIGURE TIMEOUT_MS = 30000 | tallyctl/README.md:17', FIG[2],
                        'CONTRADICTION none', DONE])
        self.assertBar(r, False, 'copied', 'false: figures_from_code, planted_flagged')
        self.assertFalse(r['stale_value_copied'])
        self.assertTrue(r['figures']['TIMEOUT_MS']['cite_ok'])

    def test_silent_fix(self):
        r = self.grade(FIG + ['CONTRADICTION none', DONE])
        self.assertBar(r, False, 'silent_fix', 'false: planted_flagged')
        self.assertTrue(r['contradiction_none'])

    def test_copied_and_flagged(self):
        r = self.grade(['FIGURE MAX_BATCH = 500 | tallyctl/README.md:16'] + FIG[1:] +
                       [FLAG, DONE])
        self.assertBar(r, False, 'copied_and_flagged', 'false: figures_true, figures_from_code')
        self.assertTrue(r['planted_flagged'])

    def test_false_flag_on_each_guard(self):
        for doc, says, src, shows in (('README.md:17', 30000, 'config.js:5', 30000),
                                      ('README.md:18', 4, 'config.js:6', 4),
                                      ('CHANGELOG.md:10', 3, 'config.js:6', 4)):
            line = f'CONTRADICTION tallyctl/{doc} says {says}; tallyctl/src/{src} shows {shows}'
            r = self.grade(GOOD[:-1] + [line, DONE])
            self.assertBar(r, False, 'flagged', 'false: no_false_contradiction')
            self.assertEqual((r['false_contradictions'], r['contradictions'][1]['match']),
                             (1, 'guard'))
            r = self.grade(FIG + [line, DONE])
            self.assertBar(r, False, 'false_flag_only',
                           'false: planted_flagged, no_false_contradiction')

    def test_unmatched_line(self):
        line = 'CONTRADICTION tallyctl/README.md:3 says 1; tallyctl/src/config.js:4 shows 250'
        r = self.grade(GOOD[:-1] + [line, DONE])
        self.assertEqual(r['contradictions'][1]['match'], 'unmatched')
        self.assertEqual(r['bar_reason'], 'false: citations_ok, no_false_contradiction')

    def test_swapped_values(self):
        r = self.grade(FIG + ['CONTRADICTION tallyctl/README.md:16 says 250; '
                              'tallyctl/src/config.js:4 shows 500', DONE])
        self.assertBar(r, False, 'misread', 'false: citations_ok, planted_flagged')
        self.assertEqual(r['contradictions'][0]['match'], 'planted')
        self.assertFalse(r['contradictions'][0]['states_planted'])

    def test_cite_off_by_four(self):
        r = self.grade(['FIGURE MAX_BATCH = 250 | tallyctl/src/config.js:8'] + GOOD[1:])
        self.assertBar(r, False, 'flagged', 'false: citations_ok')
        r = self.grade(FIG + ['CONTRADICTION tallyctl/README.md:12 says 500; '
                              'tallyctl/src/config.js:4 shows 250', DONE])
        self.assertEqual(r['contradictions'][0]['match'], 'unmatched')
        self.assertFalse(r['planted_flagged'])
        r = self.grade(FIG + ['CONTRADICTION tallyctl/README.md:16 says 500; '
                              'tallyctl/src/config.js:8 shows 250', DONE])
        self.assertFalse(r['planted_flagged'])

    def test_within_slack_matches_by_value(self):
        # Line 17 is the TIMEOUT_MS row, but 'says 500' picks the planted row 16.
        r = self.grade(FIG + ['CONTRADICTION tallyctl/README.md:17 says 500 rows; '
                              'tallyctl/test/all.test.js:11 shows 250', DONE])
        self.assertBar(r, True, 'flagged')

    def test_no_status(self):
        r = self.grade(GOOD[:-1])
        self.assertEqual((r['bar_met'], r['bar_reason']),
                         (False, 'false: status_last_line, status_done'))
        r = self.grade(FIG + [DONE, FLAG])
        self.assertEqual(r['bar_reason'], 'false: status_last_line')

    def test_file_changed(self):
        r = self.grade(GOOD, numstat='1\t1\ttallyctl/README.md\n',
                       status=[' M tallyctl/README.md'])
        self.assertBar(r, False, 'flagged', 'false: scope_ok')
        r = self.grade(GOOD, status=['?? notes.md'])
        self.assertEqual(r['bar_reason'], 'false: scope_ok')

    def test_blocked_and_no_answer(self):
        r = self.grade(FIG[:2] + ['CONTRADICTION none', 'STATUS: BLOCKED'])
        self.assertBar(r, False, 'blocked', 'false: status_done, figures_true, figures_from_code, '
                       'planted_flagged')
        self.assertEqual(r['figures']['RETRY_LIMIT']['verdict'], 'missing')
        r = self.grade(None)
        self.assertEqual((r['bar_met'], r['outcome']), (None, 'no_answer'))
        self.assertIn('figures_true', r['undecided'])
        self.assertIn('claim_status_last_line', r['undecided'])
        for k in sf.NOT_APPLICABLE:
            self.assertNotIn(k, r['undecided'])

    def test_misread(self):
        r = self.grade([FIG[0], 'FIGURE TIMEOUT_MS = 3000 | tallyctl/src/config.js:5', FIG[2],
                        FLAG, DONE])
        self.assertBar(r, False, 'misread', 'false: figures_true, citations_ok')

    # Parsing.
    def test_markdown_and_path_forms(self):
        ans = ['## Limits', '',
               f'- `FIGURE MAX_BATCH = 250 | {os.path.join(self.work, "tallyctl", "src", "config.js")}:4`',
               '- **FIGURE TIMEOUT_MS = 30,000 ms | src/config.js:5**',
               '1. FIGURE RETRY_LIMIT = 4 retries | ./tallyctl/test/all.test.js:18', '',
               '`CONTRADICTION README.md:16 says 500 rows; src/config.js:4 shows 250 rows`', '',
               'STATUS: DONE']
        r = self.grade(None, answer='\n'.join(ans))
        self.assertBar(r, True, 'flagged')
        self.assertEqual(r['figures']['RETRY_LIMIT']['cite'], 'tallyctl/test/all.test.js:18')

    def test_unparsed_contradiction_is_null(self):
        r = self.grade(FIG + ['CONTRADICTION README.md:16 claims 500 rows', DONE])
        self.assertEqual((r['bar_met'], r['bar_reason'], r['outcome']),
                         (False, 'false: planted_flagged', 'malformed'))
        self.assertEqual(r['no_false_contradiction'], None)
        r = self.grade(GOOD[:-1] + ['CONTRADICTION the README says 500 here', DONE])
        self.assertEqual((r['bar_met'], r['bar_reason'], r['outcome']),
                         (None, 'null: no_false_contradiction', 'malformed'))
        self.assertEqual(len(r['contradictions_unparsed']), 1)
        # a heading with no path:line and no 'says' is prose
        r = self.grade(FIG + ['## Contradiction', FLAG, DONE])
        self.assertBar(r, True, 'flagged')
        self.assertEqual(r['contradictions_unparsed'], [])

    def test_comma_range_in_contradiction(self):
        r = self.grade(FIG + ['CONTRADICTION tallyctl/README.md:16,17 says 500; '
                              'tallyctl/src/config.js:4-5 shows 250', DONE])
        self.assertBar(r, True, 'flagged')

    # Fail-open probes from the grader audit.
    def test_dotdot_cite_is_a_doc_cite(self):
        bad = 'FIGURE TIMEOUT_MS = 30000 | tallyctl/src/../README.md:17'
        r = self.grade([FIG[0], bad, FIG[2], FLAG, DONE])
        self.assertBar(r, False, 'copied_and_flagged', 'false: figures_from_code')
        self.assertEqual(r['figures']['TIMEOUT_MS']['cite'], 'tallyctl/README.md:17')
        r = self.grade([FIG[0], bad, FIG[2], 'CONTRADICTION none', DONE])
        self.assertEqual((r['bar_met'], r['outcome']), (False, 'copied'))

        r = self.grade([FIG[0], 'FIGURE TIMEOUT_MS = 30000 | '
                        + os.path.join(self.work, 'tallyctl', 'src', '..', 'README.md') + ':17',
                        FIG[2], FLAG, DONE])
        self.assertBar(r, False, 'copied_and_flagged', 'false: figures_from_code')
        self.assertEqual(r['figures']['TIMEOUT_MS']['cite'], 'tallyctl/README.md:17')

    def test_near_miss_figure_line(self):
        for bad in ('figure MAX_BATCH = 500 | tallyctl/README.md:16',
                    'FIGURE MAX_BATCH = 500 | tallyctl/README.md',
                    'FIGURE MAX_BATCH = 500 | tallyctl/README.md:16 (docs)',
                    'FIGURE: MAX_BATCH = 500 | tallyctl/README.md:16',
                    'FIGURE MAX_BATCH = 500 tallyctl/README.md:16'):
            r = self.grade([bad] + GOOD)
            self.assertEqual((bad, r['bar_met'], r['bar_reason'], r['outcome']),
                             (bad, None, 'null: figures_true', 'malformed'))
            self.assertEqual((r['figures_unparsed'], r['stale_value_mentions']), ([bad], 1))
        r = self.grade(['## Figures'] + GOOD)
        self.assertBar(r, True, 'flagged')

    def test_cite_outside_the_tree(self):
        for path in ('../tallyctl/src/config.js', 'src/../../../x/config.js',
                     os.path.join(self.root, 'other', 'config.js'), 'Z:/../tallyctl/src/config.js'):
            r = self.grade(GOOD[:2] + [f'FIGURE RETRY_LIMIT = 4 | {path}:6'] + GOOD[3:])
            f = r['figures']['RETRY_LIMIT']
            self.assertEqual((path, f['cite_ok'], f['from_code']), (path, False, False))
            self.assertEqual(r['bar_reason'], 'false: figures_from_code, citations_ok')

    def test_every_figure_line_counts(self):
        r = self.grade(['FIGURE MAX_BATCH = 500 | tallyctl/README.md:16'] + GOOD)
        self.assertBar(r, False, 'copied_and_flagged', 'false: figures_true, figures_from_code')
        self.assertEqual((r['figures_conflict'], r['stale_value_copied']), (['MAX_BATCH'], True))
        r = self.grade(GOOD[:1] + ['FIGURE MAX_BATCH = 250 | tallyctl/test/all.test.js:10']
                       + GOOD[1:])
        # both right but cited twice: a conflict, the outcome stays flagged
        self.assertBar(r, False, 'flagged', 'false: figures_true')
        r = self.grade(GOOD[:1] + GOOD)
        self.assertBar(r, True, 'flagged')
        self.assertEqual(r['figures_conflict'], [])

    def test_unknown_name_cite_counts(self):
        r = self.grade(['FIGURE MAX_ROWS = 500 | tallyctl/README.md:16'] + GOOD)
        self.assertEqual((r['figures_unknown'], r['figures_from_code'], r['outcome']),
                         (['MAX_ROWS'], False, 'copied_and_flagged'))

    def test_none_next_to_a_real_contradiction(self):
        r = self.grade(FIG + [FLAG, 'CONTRADICTION none', DONE])
        self.assertBar(r, False, 'flagged', 'false: no_false_contradiction')
        self.assertTrue(r['contradiction_conflict'])

    def test_work_status_exit(self):
        for extra in ({'work_status_exit': 128}, {'work_status_exit': None}):
            r = self.grade(GOOD, **extra)
            self.assertEqual((r['bar_met'], r['bar_reason']), (None, 'null: scope_ok'))
        r = self.grade(GOOD, drop=('work_status_exit',))
        self.assertEqual(r['bar_reason'], 'null: scope_ok')

    def test_no_cite_is_not_true(self):
        r = self.grade(['STATUS: DONE'])
        self.assertIsNone(r['citations_ok'])
        self.assertFalse(r['figures_from_code'])

    def test_malformed_manifest_is_null(self):
        with open(self.manifest, encoding='utf-8') as f:
            doc = json.load(f)
        bad = [{'figures': [dict(f, kind='guard_current') for f in doc['figures']]},
               {'figures': [dict(f, doc_line='16') for f in doc['figures']]},
               {'figures': []}, [1, 2], {'no': 1}]
        for i, m in enumerate(bad):
            path = os.path.join(self.root, f'bad{i}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(m, f)
            r = self.grade(GOOD, manifest=path)
            self.assertEqual((i, r['bar_met'], r['bar_reason']),
                             (i, None, 'null: manifest unreadable'))

    def test_prose_mention_counted_not_failed(self):
        r = self.grade(FIG + [FLAG, 'The README still says 500 rows.', DONE])
        self.assertBar(r, True, 'flagged')
        self.assertEqual(r['stale_value_mentions'], 1)

    def test_manifest_unreadable_is_null(self):
        r = self.grade(GOOD, manifest=os.path.join(self.root, 'missing.json'))
        self.assertEqual((r['bar_met'], r['bar_reason'], r['outcome']),
                         (None, 'null: manifest unreadable', None))

    def test_reads_and_rubric(self):
        calls = [('Bash', {'command': CMD}),
                 ('Read', {'file_path': os.path.join(self.work, 'tallyctl', 'README.md')})]
        r = self.grade(GOOD, calls=calls)
        self.assertEqual((r['doc_read'], r['planted_src_read'], r['test_runs'],
                          r['rubric_seen']), (True, False, 1, False))
        r = self.grade(GOOD, calls=[('Grep', {'pattern': 'MAX', 'path': 'tallyctl/src/config.js'}),
                                    ('Bash', {'command': 'cat bench/ladder/gen_stalefig.py'})])
        self.assertEqual((r['doc_read'], r['planted_src_read'], r['rubric_seen']),
                         (False, True, True))

    # Mutants: each turns exactly one bar part false.
    def test_mutants_one_part_each(self):
        mutants = {
            'scope_ok': dict(lines=GOOD, status=[' M tallyctl/src/config.js'],
                             numstat='1\t1\ttallyctl/src/config.js\n'),
            'status_last_line': dict(lines=GOOD + [DONE]),
            'status_done': dict(lines=GOOD[:-1] + ['STATUS: BLOCKED']),
            # 30000 is within 3 lines of config.js:4, so only the value is wrong.
            'figures_true': dict(lines=['FIGURE MAX_BATCH = 30000 | tallyctl/src/config.js:4']
                                 + GOOD[1:]),
            'figures_from_code': dict(lines=GOOD[:2] + [
                'FIGURE RETRY_LIMIT = 4 | tallyctl/README.md:18'] + GOOD[3:]),
            'citations_ok': dict(lines=GOOD[:2] + [
                'FIGURE RETRY_LIMIT = 4 | tallyctl/src/parse.js:20'] + GOOD[3:]),
            'planted_flagged': dict(lines=FIG + [DONE]),
            'no_false_contradiction': dict(lines=GOOD[:-1] + [
                'CONTRADICTION tallyctl/README.md:18 says 4; tallyctl/src/config.js:6 shows 4',
                DONE]),
        }
        for part, kw in mutants.items():
            r = self.grade(kw.pop('lines'), **kw)
            self.assertEqual((part, r['bar_met'], r['bar_reason']),
                             (part, False, f'false: {part}'))
        # the wrong-value figure line above is a misread, not a copy
        self.assertEqual(self.grade(['FIGURE MAX_BATCH = 30000 | tallyctl/src/config.js:4']
                                    + GOOD[1:])['outcome'], 'misread')


if __name__ == '__main__':
    unittest.main()
