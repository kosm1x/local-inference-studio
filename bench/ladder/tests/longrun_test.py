"""Unit tests for bench/ladder/longrun.py through grade.py. Run:
python -I bench/ladder/tests/longrun_test.py

Each case writes synthetic run.ps1 artifacts for a two-module long-fix run (meta with
profile longrun, manifest, TAP before/after, numstat, stderr banner, transcript, a
stream-json stdout and the final facts file) and grades them. No session, no server.
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
spec = importlib.util.spec_from_file_location('grade', os.path.join(HERE, '..', 'grade.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
spec = importlib.util.spec_from_file_location(
    'facts_inject', os.path.join(HERE, '..', '..', '..', 'scripts', 'hooks', 'facts-inject.py'))
fi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fi)
lr = g.load_longrun()

A, B, G = 'm01 alphaTrim keeps short input', 'm02 betaSort orders numbers', 'm01 alphaTrim guard'
S1, S2 = 'longfix/src/m01-alpha.js', 'longfix/src/m02-beta.js'
CMD = 'node --test longfix/test/all.test.js'
FACTS = 'lis-facts-20261026-120000.md'
CMDLINE = 'llama-server.exe -c 131072 --chat-template-kwargs "{\\"enable_thinking\\": false}"'
L1 = ['BEFORE pass 1 fail 2', 'CHECK pass 2 fail 1', f'FIXED {A} | {S1}', 'NEXT m02']
L2 = ['CHECK pass 3 fail 0', f'FIXED {B} | {S2}']
CLAIM = (f'Before: pass 1, fail 2\nAfter: pass 3, fail 0\nFixed: 2\nChanged files: {S1}, {S2}\n'
         'STATUS: DONE')


def tap(a, b):
    rows = [(A, a), (B, b), (G, True)]
    return ''.join(f"{'' if ok else 'not '}ok {i} - {n}\n" for i, (n, ok) in enumerate(rows, 1))


def run_out(p, f, names=()):
    return ''.join(f'\u2714 {n} (0.1ms)\n' for n in names) + f'\u2139 pass {p}\n\u2139 fail {f}\n'


def text(lines):
    return ''.join(ln + '\n' for ln in lines)


def ilog(n, name=FACTS):
    """n facts-inject log lines (scripts/hooks/facts-inject.py) saying injected=yes."""
    return [f'2026-11-04T12:00:0{i}+00:00 source=compact facts={name} injected=yes lines=4 '
            'bytes=80 truncated=no' for i in range(n)]


def nlog(reason, name=FACTS):
    """One facts-inject log line saying injected=no."""
    return f'2026-11-04T12:00:09+00:00 source=compact facts={name} injected=no reason={reason}'


def ctx(name=FACTS, as_list=True):
    """A transcript record of the facts-inject hook's context as Claude Code writes it."""
    c = fi.HEADER.format(name) + ' (4 lines, 80 bytes), as written before this compaction.\nX'
    return {'type': 'attachment', 'attachment': {
        'type': 'hook_additional_context', 'hookName': 'SessionStart', 'toolUseID': 'x',
        'hookEvent': 'SessionStart', 'content': [c] if as_list else c}}


def boundary(camel=False):
    m = {'trigger': 'auto', 'preTokens': 100, 'postTokens': 20, 'durationMs': 5} if camel \
        else {'trigger': 'auto', 'pre_tokens': 100, 'post_tokens': 20, 'duration_ms': 5}
    return ('boundary', {'compactMetadata' if camel else 'compact_metadata': m})


def good(work):
    """The happy path: BEFORE, fix m01, CHECK + FIXED, boundary, Read, fix m02, CHECK + FIXED."""
    fp = os.path.join(work, FACTS)
    return [
        ('Bash', {'command': CMD}, run_out(1, 2), True),
        ('Write', {'file_path': fp, 'content': text(L1[:1])}, 'ok', False),
        ('Edit', {'file_path': os.path.join(work, S1), 'old_string': 'a', 'new_string': 'b'},
         'ok', False),
        ('Bash', {'command': CMD}, run_out(2, 1, [A]), True),
        ('Edit', {'file_path': fp, 'old_string': text(L1[:1]), 'new_string': text(L1)},
         'ok', False),
        boundary(),
        ('Read', {'file_path': fp}, text(L1), False),
        ('Edit', {'file_path': os.path.join(work, S2), 'old_string': 'c', 'new_string': 'd'},
         'ok', False),
        ('Bash', {'command': CMD + ' | tail -5'}, run_out(3, 0, [A, B]), False),
        ('Edit', {'file_path': fp, 'old_string': 'NEXT m02\n',
                  'new_string': 'NEXT m02\n' + text(L2)}, 'ok', False),
    ]


class LongRun(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='ladder-longrun-')
        self.work = os.path.join(self.root, 'work')
        os.makedirs(self.work)
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.root)

    def grade(self, steps=None, claim=CLAIM, final=L1 + L2, after=(True, True),
              transcript=(1, 1), meta_extra=None, profile='longrun',
              numstat=f'1\t1\t{S1}\n1\t1\t{S2}\n6\t0\t{FACTS}\n', debug=None, copy=None,
              result=True, inject=None, transcript2=None):
        """steps: (tool, input, result text, is_error), boundary(), ('init', {}) (a system
        init record: a relaunched session's start) or ('text', text). copy:
        the lines of <base>.facts.md (run.ps1's copy), not written when None. transcript:
        (boundaries, summaries), a list of records, or None (no transcript file). result:
        False leaves out the final result event (a session cut off before its report).
        inject: the lines of <base>.inject.log (the facts-inject log), absent when None.
        transcript2: the records of <base>.transcript.2.jsonl (meta transcript_2), or None."""
        self.n += 1
        base = os.path.join(self.root, f'case{self.n}')
        man = base + '.manifest.json'
        tests = [{'name': n, 'module': n[:3], 'file': f'longfix/test/{s}.test.js',
                  'kind': k, 'expect_before': e}
                 for n, s, k, e in ((A, 'm01-alpha', 'bug', 'fail'), (B, 'm02-beta', 'bug', 'fail'),
                                    (G, 'm01-alpha', 'guard', 'pass'))]
        meta = {'case': 'long-fix', 'profile': profile, 'allowed_files': [S1, S2],
                'keep_failing': [], 'require_others_failing': False, 'target_tests': [],
                'test_dir': 'longfix/test', 'test_cmd': CMD, 'manifest': man,
                'argv': ['-LisTask', 'longrun', '-p', 'x'], 'work_dir': self.work,
                'server': {'cmdline': CMDLINE}}
        meta.update(meta_extra or {})
        if transcript2 is not None:
            meta['transcript_2'] = base + '.transcript.2.jsonl'
            with open(meta['transcript_2'], 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(json.dumps(x) for x in transcript2))
        lines = []
        for i, st in enumerate(good(self.work) if steps is None else steps):
            if st[0] == 'boundary':
                lines.append(json.dumps(dict({'type': 'system', 'subtype': 'compact_boundary'},
                                             **st[1])))
                continue
            if st[0] == 'init':
                lines.append(json.dumps(dict({'type': 'system', 'subtype': 'init',
                                              'session_id': f's{i}'}, **st[1])))
                continue
            if st[0] == 'text':
                lines.append(json.dumps({'type': 'assistant', 'message': {'content': [
                    {'type': 'text', 'text': st[1]}]}}))
                continue
            tool, inp, out, err = st
            lines.append(json.dumps({'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': f't{i}', 'name': tool, 'input': inp}]}}))
            lines.append(json.dumps({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': f't{i}', 'is_error': err,
                 'content': out}]}}))
        lines.append(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'text', 'text': claim}]}}))
        if result:
            lines.append(json.dumps({'type': 'result', 'result': claim, 'num_turns': 9}))
        files = {'.meta.json': json.dumps(meta), '.manifest.json': json.dumps({'tests': tests}),
                 '.tests-before.txt': tap(False, False), '.tests-after.txt': tap(*after),
                 '.numstat.txt': numstat, '.jsonl': '\n'.join(lines) + '\n',
                 '.diff.txt': f'+++ b/{S1}\n+const x = require("child_process");\n+ok();\n',
                 '.stderr.txt': f'claude-local: profile: longrun\n  ...plus ?? {FACTS}\n'}
        if debug is not None:
            files['.debug.log'] = debug
        if copy is not None:
            files['.facts.md'] = text(copy)
        if inject is not None:
            files['.inject.log'] = text(inject)
        if isinstance(transcript, list):
            files['.transcript.jsonl'] = '\n'.join(json.dumps(x) for x in transcript)
        elif transcript:
            files['.transcript.jsonl'] = '\n'.join(
                [json.dumps({'type': 'system', 'subtype': 'compact_boundary'})] * transcript[0]
                + [json.dumps({'type': 'user', 'isCompactSummary': True})] * transcript[1])
        for ext, body in files.items():
            with open(base + ext, 'w', encoding='utf-8', newline='\n') as f:
                f.write(body)
        fp = os.path.join(self.work, FACTS)
        if os.path.exists(fp):
            os.remove(fp)
        if final is not None:
            with open(fp, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text(final))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            g.grade(base)
        self.out = out.getvalue()
        with open(base + '.json', encoding='utf-8') as f:
            return json.load(f)

    def test_placeholder_line_changed_is_a_violation(self):
        # Reps 2 and 3: a placeholder BEFORE line, then an Edit that replaced it.
        steps, ph = good(self.work), 'BEFORE pass 0 fail 0'
        steps[1] = ('Write', dict(steps[1][1], content=ph + '\n'), 'ok', False)
        steps[4] = ('Edit', dict(steps[4][1], old_string=ph + '\n'), 'ok', False)
        r = self.grade(steps)
        self.assertEqual(r['facts_retracted'], {'count': 1, 'first': [ph]})
        self.assertEqual(r['instruction_violations'],
                         ['facts_line_changed:1', 'piped_test_runs:1'])
        self.assertEqual((r['facts_survived'], r['bar_met']), (True, True))  # report-only

    def test_good_run_meets_bar(self):
        extra = {'rep_key': 'k' * 64, 'context_tokens': 65536, 'before_output_chars': 20594,
                 'model_node_version': 'v24.22.1', 'node_version': 'v22.23.4'}
        r = self.grade(meta_extra=extra)
        self.assertEqual({k: r[k] for k in extra}, extra)
        self.assertEqual(r['facts_source'], 'work_dir')
        self.assertEqual((r['facts_bash_appends'], r['test_runs_nonexact'],
                          r['test_runs_piped']), (0, 0, 1))
        self.assertIsNone(r['compaction_failed_source'])
        self.assertTrue(r['claim_fixed_vs_tap'])
        self.assertEqual((r['axis_exercised'], r['compaction_mid_edit'], r['compaction_fired']),
                         (True, True, 1))
        self.assertEqual(r['facts_at_boundary'], [L1])
        self.assertTrue(r['facts_replay_ok'])
        self.assertEqual((r['facts_survived'], r['facts_survived_strict'], r['next_rewrites'],
                          r['facts_survived_missing']), (True, True, 0, []))
        self.assertEqual((r['facts_survived_missing_total'], r['facts_order_breaks'],
                          r['facts_retracted']), (0, 0, {'count': 0, 'first': []}))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])
        self.assertEqual((r['facts_true'], r['facts_false'], r['facts_undecided']), (5, 0, 0))
        self.assertEqual(r['facts_kinds'], {'BEFORE': 1, 'CHECK': 2, 'FIXED': 2, 'NEXT': 1})
        self.assertTrue(r['claim_before_agrees'])
        self.assertTrue(r['claim_fixed_count_agrees'])
        self.assertTrue(r['claim_agrees'])
        self.assertTrue(r['claim_after_last_boundary'])
        self.assertEqual(r['facts_read_after_boundary'], [True])
        self.assertEqual(r['facts_write_tools'], {'Write': 1, 'Edit': 2, 'Bash': 0})
        self.assertEqual(r['facts_fixed_verified'], 2)
        self.assertEqual(r['redo_after_compaction'], 0)
        self.assertEqual(r['test_runs'], 3)
        self.assertTrue(r['scope_ok'])
        self.assertEqual(r['diff_suspicious'], ['const x = require("child_process");'])
        self.assertTrue(r['server_reasoning_off'])
        self.assertTrue(r['compaction_consistency'])
        self.assertEqual(r['compaction_boundaries'][0]['pre_tokens'], 100)
        self.assertEqual((r['grade_profile'], r['bar_met'], r['bar_reason']),
                         ('longrun', True, None))
        self.assertEqual(r['undecided'], [])

    def test_no_boundary_axis_false_bar_null(self):
        steps = [s for s in good(self.work) if s[0] != 'boundary']
        r = self.grade(steps, transcript=None)
        self.assertEqual((r['compaction_fired'], r['axis_exercised']), (0, False))
        self.assertIsNone(r['bar_met'])
        self.assertIn('axis_exercised=False', r['bar_reason'])

    def test_fixed_line_lost_after_boundary_fails(self):
        lost = f'FIXED {A} | {S1}'
        r = self.grade(final=[x for x in L1 + L2 if x != lost],
                       claim=CLAIM.replace('Fixed: 2', 'Fixed: 1'))
        self.assertEqual((r['facts_survived'], r['facts_survived_strict'], r['next_rewrites']),
                         (False, False, 0))
        self.assertEqual(r['facts_survived_missing'], [{'i': 10, 'kind': 'FIXED', 'line': lost}])
        self.assertEqual(r['facts_retracted'], {'count': 1, 'first': [lost]})
        self.assertEqual((r['bar_met'], r['bar_reason']), (False, 'false: facts_gate'))

    def test_other_line_lost_after_boundary_fails(self):
        # Only NEXT is exempt: a malformed line held at the boundary and deleted later fails.
        note, steps = 'note m01 done', good(self.work)
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(L1 + [note])), 'ok', False)
        r = self.grade(steps)
        self.assertEqual(r['facts_at_boundary'], [L1 + [note]])
        self.assertEqual((r['facts_survived'], r['facts_survived_strict'], r['next_rewrites']),
                         (False, False, 0))
        self.assertEqual((r['bar_met'], r['bar_reason']), (False, 'false: facts_gate'))

    def test_order_break_is_counted(self):
        # Every line kept but two swapped: lost nothing, out of order.
        r = self.grade(final=[L1[1], L1[0]] + L1[2:] + L2)
        self.assertEqual((r['facts_survived'], r['facts_order_breaks'],
                          r['facts_survived_missing_total']), (False, 1, 0))
        self.assertFalse(r['bar_met'])

    def test_next_rewritten_in_place_is_exempt(self):
        # Rep 2 (20261026-132833): each Edit replaced the last NEXT line instead of keeping it.
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string=text(L2)), 'ok', False)
        steps.insert(8, boundary())
        r = self.grade(steps, final=L1[:3] + L2, transcript=(2, 2))
        self.assertEqual(r['facts_at_boundary'], [L1, L1])
        # Two boundaries held the same NEXT line: one distinct pointer rewritten.
        self.assertEqual((r['facts_survived'], r['facts_survived_strict'], r['next_rewrites']),
                         (True, False, 1))
        self.assertEqual([(x['kind'], x['line']) for x in r['facts_survived_missing']],
                         [('NEXT', 'NEXT m02')] * 2)
        self.assertEqual((r['facts_survived_missing_total'], r['facts_order_breaks']), (2, 0))
        self.assertEqual(r['facts_retracted'], {'count': 1, 'first': ['NEXT m02']})
        # The second boundary has no Read and the transcript no restore attachment.
        v = ['next_rewritten_in_place:1', 'facts_not_read_after_compaction:1',
             'piped_test_runs:1']
        self.assertEqual(r['instruction_violations'], v)
        self.assertEqual((r['facts_gate'], r['bar_met'], r['bar_reason']), (True, True, None))
        self.assertIn('survived True (strict False, next_rewrites 1)', self.out)
        self.assertIn(f'violations {v}', self.out)

    def test_mismatched_check_is_false(self):
        steps = good(self.work)
        bad = [L1[0], 'CHECK pass 3 fail 0'] + L1[2:]
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(bad)), 'ok', False)
        r = self.grade(steps, final=bad + L2)
        self.assertEqual(r['facts_false'], 1)
        self.assertEqual([v['verdict'] for v in r['facts_verdicts'] if v['kind'] == 'CHECK'],
                         [False, True])
        self.assertFalse(r['bar_met'])

    def test_fixed_for_still_failing_test_is_false(self):
        claim = (f'Before: pass 1, fail 2\nAfter: pass 2, fail 1\nFixed: 2\n'
                 f'Changed files: {S1}, {S2}\nSTATUS: BLOCKED')
        r = self.grade(claim=claim, after=(True, False))
        self.assertTrue(r['claim_agrees'])
        self.assertTrue(r['claim_fixed_count_agrees'])  # 2 FIXED lines in the facts file
        self.assertFalse(r['claim_fixed_vs_tap'])  # TAP shows 1 test fixed
        fixed = {v['line']: v['verdict'] for v in r['facts_verdicts'] if v['kind'] == 'FIXED'}
        self.assertEqual(fixed, {f'FIXED {A} | {S1}': True, f'FIXED {B} | {S2}': False})
        self.assertEqual((r['bar_met'], r['bar_reason']), (False, 'false: facts_gate'))

    def test_fixed_wrong_path_is_false(self):
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(
            [L2[0], f'FIXED {B} | {S1}'])), 'ok', False)
        r = self.grade(steps, final=L1 + [L2[0], f'FIXED {B} | {S1}'])
        self.assertEqual(r['facts_false'], 1)
        self.assertFalse(r['bar_met'])

    def test_bash_write_makes_replay_null(self):
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        r = self.grade(steps)
        self.assertFalse(r['facts_replay_ok'])
        self.assertEqual(r['facts_at_boundary'], [None])
        self.assertIsNone(r['facts_survived'])
        self.assertEqual((r['next_rewrites'], r['facts_order_breaks'], r['facts_retracted']),
                         (None, None, None))
        self.assertIsNone(r['bar_met'])
        self.assertIn('facts_gate', r['bar_reason'])
        self.assertEqual((r['facts_write_tools']['Bash'], r['facts_bash_appends'],
                          r['facts_bash_reads']), (1, 0, 0))

    def test_bash_reads_keep_replay(self):
        # Rep 2 (20261026-132833) ended with grep -c '^FIXED ' <facts>: a read, not a write.
        reads = (f"grep -c '^FIXED ' {FACTS}", f'cat {FACTS}', f'wc -l {FACTS}',
                 f'tail -n 5 {FACTS}', f"sed -n '1,5p' {FACTS}", f'grep X {FACTS} | wc -l')
        for cmd in reads + (f'sort {FACTS}', f'grep -n NEXT {FACTS} 2>&1 | tail -1'):
            self.assertTrue(lr.bash_read(cmd, FACTS), cmd)
        # A glob in a segment that does not name the facts file does not matter.
        self.assertTrue(lr.bash_read(f"grep X {FACTS} | grep -c '[0-9]'", FACTS))
        steps = good(self.work)
        steps += [('Bash', {'command': c}, 'x', False) for c in reads[3:]]
        steps[5:5] = [('Bash', {'command': c}, 'x', False) for c in reads[:3]]
        r = self.grade(steps)
        self.assertTrue(r['facts_replay_ok'])
        self.assertEqual(r['facts_at_boundary'], [L1])
        self.assertEqual((r['facts_bash_reads'], r['facts_bash_appends'],
                          r['facts_write_tools']['Bash']), (6, 0, 6))
        self.assertEqual((r['facts_true'], r['facts_false'], r['facts_undecided']), (5, 0, 0))
        self.assertEqual((r['bar_met'], r['bar_reason']), (True, None))

    def test_bash_non_reads_null_replay(self):
        refused = (f"sed -i 's/a/b/' {FACTS}", f'grep X {FACTS} > out', f'cat {FACTS} | tee f2',
                   f'tee {FACTS}', f"python -I -c \"print(open('{FACTS}').read())\"",
                   f'cp {FACTS} g', f"sed '1,5p' {FACTS}", f'grep X {FACTS} && rm {FACTS}',
                   f'sort -o {FACTS} {FACTS}', f'cat {FACTS} $(touch x)',
                   f"sed -n -Ei 's/a/b/' {FACTS}", f"sed -n '1e touch Z' {FACTS}",
                   f"awk --include=inplace '{{print}}' {FACTS}",
                   f"awk --dump-variables={FACTS} 'NR<2' x", f"awk '{{print $1}}' {FACTS}",
                   f'sort -uo {FACTS} {FACTS}', f'sort -ro{FACTS} {FACTS}',
                   f'uniq -c {FACTS} {FACTS}', f"sed -n 'w {FACTS}' {FACTS}",
                   f'less -O{FACTS} {FACTS}', f'grep -i x {FACTS}', f'cut -c1-5 {FACTS}',
                   # bash expansion: $'..' and {a,b} can build -o, w or -i
                   f"sort $'-\\x6f' {FACTS} {FACTS}", f'sort {{-o,{FACTS}}} {FACTS}',
                   f"sed -n $'\\x77 {FACTS}' {FACTS}", f'sed -n {{-i,1d}} {FACTS}',
                   f"sed -n '*' {FACTS}", f"awk 'NR<5' {FACTS}",
                   f"sed -n '$p' {FACTS}")  # a real read: the accepted cost of rejecting $
        for cmd in refused:
            self.assertFalse(lr.bash_read(cmd, FACTS), cmd)
        for cmd in refused[1:4]:
            steps = good(self.work) + [('Bash', {'command': cmd}, '', False)]
            r = self.grade(steps)
            self.assertEqual((r['facts_replay_ok'], r['facts_bash_reads'], r['bar_met']),
                             (False, 0, None), cmd)

    def test_facts_recall_reads_the_final_file(self):
        # A null replay gives no add index, but the final file still names both fixes.
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        r = self.grade(steps)
        self.assertFalse(r['facts_replay_ok'])
        self.assertEqual(r['facts_recall'], {'fixed_lines': 2, 'tests_fixed': 2, 'named': 2})

    def test_bash_heredoc_appends_are_replayed(self):
        # Rep 1 (20261026-122359): one Write, then every append as cat >> <relative> << 'EOF'.
        steps = good(self.work)
        steps[4] = ('Bash', {'command': f"cat >> {FACTS} << 'EOF'\n" + text(L1[1:]) + 'EOF'},
                    '', False)
        steps[9] = ('Bash', {'command': f'cat >> {os.path.join(self.work, FACTS)} <<EOF\n'
                             + text(L2) + 'EOF\n'}, '', False)
        r = self.grade(steps)
        self.assertTrue(r['facts_replay_ok'])
        self.assertEqual(r['facts_at_boundary'], [L1])
        self.assertEqual((r['facts_true'], r['facts_false'], r['facts_undecided']), (5, 0, 0))
        self.assertEqual(r['facts_write_tools'], {'Write': 1, 'Edit': 0, 'Bash': 2})
        self.assertEqual(r['facts_bash_appends'], 2)
        self.assertEqual(r['instruction_violations'],
                         ['bash_write_to_facts:2', 'piped_test_runs:1'])
        self.assertEqual(r['bar_met'], True)

    def test_bash_echo_printf_and_rewrite_are_replayed(self):
        fp = os.path.join(self.work, FACTS)
        steps = good(self.work)
        steps[1] = ('Bash', {'command': f'printf "{L1[0]}\\n" > "{fp}"'}, '', False)
        steps[4] = ('Bash', {'command': f"echo '{L1[1]}' >> {FACTS}"}, '', False)
        steps.insert(5, ('Bash', {'command': f'printf \'{L1[2]}\\n{L1[3]}\\n\' >> {FACTS}'},
                         '', False))
        r = self.grade(steps)
        self.assertTrue(r['facts_replay_ok'])
        self.assertEqual(r['facts_at_boundary'], [L1])
        self.assertEqual(r['facts_bash_appends'], 3)
        self.assertEqual(r['bar_met'], True)

    def test_bash_write_forms(self):
        cases = {
            f"cat >> {FACTS} << 'EOF'\nA\nB\nEOF": ('>>', 'A\nB\n'),
            f'cat >> {FACTS} << EOF\nA\nEOF\n': ('>>', 'A\n'),
            f"cat >>{FACTS} <<'EOF'\nEOF": ('>>', ''),
            f'cat > ./{FACTS} <<"EOF"\nA $x\nEOF': ('>', 'A $x\n'),
            f"echo 'A | b' >> {FACTS}": ('>>', 'A | b\n'),
            f'echo "A" > {FACTS}': ('>', 'A\n'),
            f"printf 'A\\tB\\n' >> '{FACTS}'": ('>>', 'A\tB\n'),
            f'printf "A" >> {FACTS}': ('>>', 'A'),
        }
        for cmd, want in cases.items():
            self.assertEqual(lr.bash_write(cmd, FACTS), want, cmd)
        for cmd in (f"sed -i 's/a/b/' {FACTS}", f"echo -e 'A' >> {FACTS}",
                    f'echo "A $x" >> {FACTS}', f"echo 'A\\nB' >> {FACTS}",
                    f"printf '%s\\n' A >> {FACTS}", f"printf 'A\\\\n' >> {FACTS}",
                    f'cat >> {FACTS} << EOF\nA $x\nEOF', f'cat >> {FACTS} <<-EOF\nA\nEOF',
                    f"cat >> {FACTS} << 'EOF'\nA\nEOF\nB\nEOF",
                    f"cat >> {FACTS} << 'EOF'\nA\nEOF\n && cat {FACTS}",
                    f"echo 'A' >> {FACTS} && echo 'B' >> {FACTS}", f"cat {FACTS}",
                    f"echo 'A' >> other-{FACTS}", f"echo 'A' >> {FACTS}.bak"):
            self.assertIsNone(lr.bash_write(cmd, FACTS), cmd)
        steps = good(self.work)
        steps[4] = ('Bash', {'command': f"echo -e '{L1[1]}' >> {FACTS}"}, '', False)
        self.assertFalse(self.grade(steps)['facts_replay_ok'])

    def test_replay_honours_replace_all(self):
        def ev(i, inp):
            return {'i': i, 'kind': 'tool_use', 'name': 'Edit' if 'old_string' in inp
                    else 'Write', 'id': f't{i}', 'input': dict(inp, file_path=FACTS),
                    'is_error': None}
        events = [ev(0, {'content': 'NEXT m01\nNEXT m01\n'}),
                  ev(1, {'old_string': 'NEXT m01', 'new_string': 'NEXT m02'})]
        self.assertEqual(lr.replay(events, FACTS)[1][-1][1], 'NEXT m02\nNEXT m01\n')
        events[1]['input']['replace_all'] = True
        ok, steps, adds = lr.replay(events, FACTS)
        self.assertEqual((ok, steps[-1][1]), (True, 'NEXT m02\nNEXT m02\n'))
        self.assertEqual(adds['NEXT m02'], [1, 1])

    def test_reasoning_off_forms(self):
        kw_off, kw_on = '"{\\"enable_thinking\\": false}"', '"{\\"enable_thinking\\": true}"'
        for cmd, want in (('x --reasoning off', True), ('x --reasoning=off', True),
                          ('x -rea off', True), ('x --reasoning-format auto --reasoning off',
                                                 True),
                          ('x --reasoning off --reasoning on', False),
                          ('x --reasoning=off -rea auto', False),
                          ('x --reasoning on --reasoning off', True),
                          ('x --reasoning auto', False), (f'x --reasoning off -k {kw_on}', False),
                          ('x --reasoning-format auto', False), (f'x -k {kw_off}', True),
                          (f'x -k {kw_off} -k {kw_on}', False), (f'x -k {kw_on}', False),
                          ('', False)):
            self.assertEqual(lr.reasoning_off(cmd), want, cmd)
        r = self.grade(meta_extra={'server': {'cmdline': 'x --reasoning off --reasoning auto'}})
        self.assertFalse(r['server_reasoning_off'])

    def test_fixed_count_is_the_facts_lines(self):
        # A FIXED line for the guard test (it passed from the start): 3 lines, TAP fixed 2.
        extra = f'FIXED {G} | {S1}'
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + [extra])),
                    'ok', False)
        r = self.grade(steps, claim=CLAIM.replace('Fixed: 2', 'Fixed: 3'),
                       final=L1 + L2 + [extra])
        self.assertTrue(r['claim_fixed_count_agrees'])
        self.assertFalse(r['claim_fixed_vs_tap'])
        self.assertEqual(r['facts_false'], 1)
        self.assertFalse(r['bar_met'])
        r = self.grade(claim=CLAIM.replace('Fixed: 2\n', '').replace('Before: pass 1, fail 2\n',
                                                                      ''))
        self.assertEqual((r['claim_fixed_count_agrees'], r['claim_before_agrees']),
                         (False, False))
        self.assertIsNone(r['claim_fixed_vs_tap'])
        self.assertFalse(r['claim_agrees'])

    def test_nonexact_run_makes_check_null(self):
        steps = good(self.work)
        steps[0] = ('Bash', {'command': CMD + ' 2>&1'}, run_out(1, 2), True)
        steps.insert(4, ('Bash', {'command': f'cd . && {CMD} --test-reporter=tap'},
                         run_out(2, 1), True))
        r = self.grade(steps)
        self.assertEqual((r['test_runs'], r['test_runs_nonexact'], r['test_runs_piped']),
                         (3, 1, 2))
        self.assertEqual(r['instruction_violations'],
                         ['test_runs_nonexact:1', 'piped_test_runs:2'])
        checks = [v['verdict'] for v in r['facts_verdicts'] if v['kind'] == 'CHECK']
        self.assertEqual(checks, [None, True])
        self.assertIsNone(r['bar_met'])
        # A read of the test file is neither a run nor non-exact: the CHECK stays true.
        steps = good(self.work)
        steps.insert(4, ('Bash', {'command': 'cat longfix/test/all.test.js'}, 'x', False))
        steps.insert(5, ('Bash', {'command': 'grep -n m01 longfix/test/all.test.js'}, 'x', False))
        r = self.grade(steps)
        self.assertEqual((r['test_runs'], r['test_runs_nonexact']), (3, 0))
        checks = [v['verdict'] for v in r['facts_verdicts'] if v['kind'] == 'CHECK']
        self.assertEqual(checks, [True, True])
        self.assertTrue(r['bar_met'])
        for cmd, want in ((CMD + ' --test-reporter=tap', True), (f'cd . && {CMD}', True),
                          (f'cd longfix && cd .. && {CMD} | tail -5', True),
                          ('cat longfix/test/all.test.js', False),
                          ('grep -c ok longfix/test/all.test.js', False),
                          ('nodemon longfix/test/all.test.js', False),
                          ('node --test longfix/test/', False)):
            self.assertEqual(lr.node_run(cmd, 'longfix/test/all.test.js'), want, cmd)

    def test_compaction_failed_sources(self):
        r = self.grade(debug='[ERROR] Prompt is too long\n')
        self.assertEqual((r['compaction_failed'], r['compaction_failed_source']),
                         (True, ['debug_log']))
        self.assertFalse(r['bar_met'])
        steps = good(self.work)
        steps.insert(6, ('text', 'Error: summarization produced empty response'))
        r = self.grade(steps, debug='')
        self.assertEqual(r['compaction_failed_source'], ['assistant_text'])

    def test_facts_copy_is_preferred(self):
        r = self.grade(final=None, copy=L1 + L2)
        self.assertEqual((r['facts_source'], r['facts_exists']), ('facts_copy', True))
        self.assertTrue(r['bar_met'])
        r = self.grade(final=L1 + L2, copy=[x for x in L1 + L2 if x != 'NEXT m02'])
        self.assertEqual(r['facts_source'], 'facts_copy')
        self.assertEqual((r['facts_survived'], r['facts_survived_strict']), (True, False))

    def test_errored_edit_is_not_applied(self):
        steps = good(self.work)
        fp = os.path.join(self.work, FACTS)
        steps.insert(7, ('Edit', {'file_path': fp, 'old_string': 'not there', 'new_string': 'x'},
                         'File has not been read yet. Read it first.', True))
        r = self.grade(steps)
        self.assertTrue(r['facts_replay_ok'])
        self.assertTrue(r['bar_met'])

    def test_next_none_parses(self):
        # The prompt's last facts line: kind NEXT, not graded (null verdict).
        self.assertEqual(lr.parse_line('NEXT none'), ('NEXT', ('none',)))
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + ['NEXT none'])),
                    'ok', False)
        r = self.grade(steps, final=L1 + L2 + ['NEXT none'])
        last = r['facts_verdicts'][-1]
        self.assertEqual((last['line'], last['kind'], last['verdict']),
                         ('NEXT none', 'NEXT', None))
        self.assertTrue(r['bar_met'])

    def test_errored_bash_append_is_not_applied(self):
        # A Bash append whose tool_result is an error never reached the file.
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"echo 'NEXT m09' >> {FACTS}"},
                         'bash: permission denied', True))
        r = self.grade(steps)
        self.assertTrue(r['facts_replay_ok'])
        self.assertEqual(r['facts_at_boundary'], [L1])
        self.assertTrue(r['facts_survived'])
        self.assertTrue(r['bar_met'])

    def test_claim_before_disagrees(self):
        r = self.grade(claim=CLAIM.replace('Before: pass 1, fail 2', 'Before: pass 0, fail 3'))
        self.assertFalse(r['claim_before_agrees'])
        self.assertFalse(r['claim_agrees'])
        self.assertFalse(r['bar_met'])

    def test_snake_and_camel_metadata(self):
        for camel in (False, True):
            steps = good(self.work)
            steps[5] = boundary(camel)
            b = self.grade(steps)['compaction_boundaries'][0]
            self.assertEqual((b['trigger'], b['pre_tokens'], b['post_tokens'], b['duration_ms']),
                             ('auto', 100, 20, 5))

    def restore_transcript(self, attach=True, other=False):
        """One boundary, its summary, then file attachments as Claude Code's restore writes
        them (the facts file when attach, a src file when other)."""
        recs = [{'type': 'system', 'subtype': 'compact_boundary'},
                {'type': 'user', 'isCompactSummary': True}]
        for on, f in ((attach, FACTS), (other, S1)):
            if on:
                recs.append({'type': 'attachment', 'attachment': {
                    'type': 'file', 'filename': os.path.join(self.work, f),
                    'displayPath': f}})
        return recs

    def test_facts_read_after_boundary_read(self):
        r = self.grade(transcript=self.restore_transcript(attach=False))
        b = r['compaction_boundaries'][0]
        self.assertEqual((b['facts_read_after'], b['facts_restored_after'],
                          b['facts_read_after_any']), (True, False, True))
        self.assertEqual((r['facts_read_after_boundary_any'],
                          r['facts_read_after_boundary_strict']), ([True], 1))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def test_facts_restore_attachment_counts_as_read(self):
        # Reps 2-4: no Read after the boundary, but the restore re-attached the facts file.
        steps = [s for s in good(self.work) if s[0] != 'Read']
        r = self.grade(steps, transcript=self.restore_transcript())
        b = r['compaction_boundaries'][0]
        self.assertEqual((b['facts_read_after'], b['facts_restored_after'],
                          b['facts_read_after_any']), (False, True, True))
        self.assertEqual((r['facts_read_after_boundary'], r['facts_read_after_boundary_any'],
                          r['facts_read_after_boundary_strict']), ([False], [True], 0))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def test_facts_neither_read_nor_restored_is_a_violation(self):
        # Rep 4 boundary 1: no Read and no facts attachment (another file was restored).
        steps = [s for s in good(self.work) if s[0] != 'Read']
        r = self.grade(steps, transcript=self.restore_transcript(attach=False, other=True))
        self.assertEqual((r['facts_read_after_boundary_any'],
                          r['facts_read_after_boundary_strict']), ([False], 0))
        self.assertEqual(r['instruction_violations'],
                         ['facts_not_read_after_compaction:1', 'piped_test_runs:1'])
        self.assertEqual(r['bar_met'], True)  # report-only

    def test_facts_restore_index_follows_boundary(self):
        # Two boundaries, the facts file restored after the first only: the k-th stream
        # boundary takes the k-th transcript boundary's restore.
        steps = [s for s in good(self.work) if s[0] != 'Read']
        steps.insert(7, boundary())
        b, summ = ({'type': 'system', 'subtype': 'compact_boundary'},
                   {'type': 'user', 'isCompactSummary': True})
        att = {'type': 'attachment', 'attachment': {
            'type': 'file', 'filename': os.path.join(self.work, FACTS), 'displayPath': FACTS}}
        r = self.grade(steps, transcript=[b, summ, att, b, summ])
        self.assertEqual([x['facts_restored_after'] for x in r['compaction_boundaries']],
                         [True, False])
        self.assertEqual(r['facts_read_after_boundary_any'], [True, False])
        self.assertIn('facts_not_read_after_compaction:1', r['instruction_violations'])

    def test_facts_read_any_null_without_transcript(self):
        steps = [s for s in good(self.work) if s[0] != 'Read']
        for t in (None, (2, 2)):  # absent, or a boundary count that differs from the stream
            r = self.grade(steps, transcript=t)
            self.assertEqual((r['facts_read_after_boundary_any'],
                              r['facts_read_after_boundary_strict']), ([None], 0))
            self.assertIsNone(r['compaction_boundaries'][0]['facts_restored_after'])
            self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def no_read(self):
        return [s for s in good(self.work) if s[0] != 'Read']

    def test_facts_context_counts_as_read(self):
        # T-9: no Read and no restore, but the hook's context is in the transcript after
        # the boundary, as a list of strings or as a string.
        for as_list in (True, False):
            t = self.restore_transcript(attach=False) + [ctx(as_list=as_list)]
            r = self.grade(self.no_read(), transcript=t)
            b = r['compaction_boundaries'][0]
            self.assertEqual((b['facts_read_after'], b['facts_restored_after'],
                              b['facts_context_after'], b['facts_read_after_any']),
                             (False, False, True, True), as_list)
            self.assertEqual((r['facts_context_after_boundary'], r['facts_context_count']),
                             ([True], 1))
            self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def test_facts_context_follows_its_boundary(self):
        # Two boundaries, the context after the second only; a header for another facts
        # name and one before the first boundary do not count for a boundary.
        steps = self.no_read()
        steps.insert(7, boundary())
        b, summ = ({'type': 'system', 'subtype': 'compact_boundary'},
                   {'type': 'user', 'isCompactSummary': True})
        other = ctx(name='lis-facts-20261026-999999.md')
        r = self.grade(steps, transcript=[ctx(), b, summ, other, b, summ, ctx(as_list=False)])
        self.assertEqual((r['facts_context_after_boundary'], r['facts_context_count'],
                          r['facts_read_after_boundary_any']), ([False, True], 2, [False, True]))
        self.assertIn('facts_not_read_after_compaction:1', r['instruction_violations'])

    def test_facts_context_null_without_transcript(self):
        for t in (None, (2, 2)):  # absent, or a boundary count that differs from the stream
            r = self.grade(self.no_read(), transcript=t, inject=ilog(1))
            self.assertEqual((r['facts_context_after_boundary'],
                              r['facts_read_after_boundary_any']), ([None], [None]))
        self.assertIsNone(self.grade(transcript=None)['facts_context_count'])

    def test_facts_injected_is_report_only(self):
        # The hook ran (injected=yes) but no context reached the transcript: any is false.
        r = self.grade(self.no_read(), transcript=self.restore_transcript(attach=False),
                       inject=ilog(1))
        b = r['compaction_boundaries'][0]
        self.assertEqual((b['facts_injected_after'], b['facts_context_after'],
                          b['facts_read_after_any']), (True, False, False))
        self.assertEqual((r['facts_injected_after_boundary'], r['facts_injected_count']),
                         ([True], 1))
        self.assertIn('facts_not_read_after_compaction:1', r['instruction_violations'])

    def test_context_header_matches_the_hook(self):
        self.assertEqual(lr.CONTEXT_HEADER, fi.HEADER)

    def test_facts_injected_null_without_log(self):
        r = self.grade()
        self.assertIsNone(r['compaction_boundaries'][0]['facts_injected_after'])
        self.assertEqual((r['facts_injected_after_boundary'], r['facts_injected_count'],
                          r['facts_read_after_boundary_any']), ([None], None, [True]))
        # A Read decides any even when the restore and the injection are both unknown.
        r = self.grade(transcript=None)
        self.assertEqual(r['facts_read_after_boundary_any'], [True])

    def test_facts_injected_matches_boundaries_by_order(self):
        # Two boundaries, one injection logged (plus a line for another facts file and a
        # malformed one): the first boundary is injected, the second is not.
        steps = self.no_read()
        steps.insert(7, boundary())
        b, summ = ({'type': 'system', 'subtype': 'compact_boundary'},
                   {'type': 'user', 'isCompactSummary': True})
        log = ilog(1) + ilog(1, name='lis-facts-20261026-999999.md') + ['not a log line']
        r = self.grade(steps, transcript=[b, summ, b, summ], inject=log)
        self.assertEqual((r['facts_injected_after_boundary'], r['facts_injected_count']),
                         ([True, False], 1))

    def test_facts_injected_no_line_holds_its_boundary(self):
        # Batch E audit W3: the first compaction came before the facts file existed. Its
        # injected=no line keeps the second boundary's yes line on the second boundary.
        steps = self.no_read()
        steps.insert(7, boundary())
        b, summ = ({'type': 'system', 'subtype': 'compact_boundary'},
                   {'type': 'user', 'isCompactSummary': True})
        r = self.grade(steps, transcript=[b, summ, b, summ], inject=[nlog('missing')] + ilog(1))
        self.assertEqual((r['facts_injected_after_boundary'], r['facts_injected_count']),
                         ([False, True], 1))
        # Only yes lines count; a no line for every reason is false.
        for reason in ('unset', 'empty', 'oversize', 'input', 'error'):
            r = self.grade(self.no_read(), transcript=self.restore_transcript(attach=False),
                           inject=[nlog(reason, name='-' if reason in ('unset', 'input')
                                        else FACTS)])
            self.assertEqual((r['facts_injected_after_boundary'], r['facts_injected_count']),
                             ([False], 0), reason)

    def test_facts_injection_leaves_the_bar_alone(self):
        for extra in (None, {'bar_v': 2}):
            a = self.grade(meta_extra=extra)
            z = self.grade(meta_extra=extra, inject=ilog(1),
                           transcript=self.restore_transcript(attach=False) + [ctx()])
            self.assertEqual([(x['bar_parts'], x['bar_met'], x['bar_reason']) for x in (a, z)],
                             [(a['bar_parts'], a['bar_met'], a['bar_reason'])] * 2)

    def test_transcript_consistency(self):
        self.assertTrue(self.grade(transcript=(1, 1))['compaction_consistency'])
        r = self.grade(transcript=(2, 2))
        self.assertFalse(r['compaction_consistency'])
        self.assertEqual(r['compaction_transcript'], {'boundaries': 2, 'summaries': 2})
        self.assertIsNone(self.grade(transcript=None)['compaction_consistency'])

    def test_boundary_only_in_transcript_is_undecided(self):
        steps = [s for s in good(self.work) if s[0] != 'boundary']
        r = self.grade(steps, transcript=(1, 1))
        self.assertEqual((r['compaction_fired'], r['axis_exercised'], r['bar_met']),
                         (1, None, None))
        self.assertIsNone(r['next_rewrites'])

    def test_compaction_failure_fails(self):
        r = self.grade(claim='Autocompact is thrashing; stopped.\nSTATUS: BLOCKED')
        self.assertTrue(r['compaction_failed'])
        self.assertFalse(r['bar_met'])

    def test_no_facts_on_disk_fails(self):
        r = self.grade(final=None, numstat=f'1\t1\t{S1}\n1\t1\t{S2}\n')
        self.assertFalse(r['facts_exists'])
        self.assertIsNone(r['facts_source'])
        self.assertFalse(r['bar_met'])
        # The stream's facts writes replay cleanly, but there is no file to hold them
        # against: null, not true (true before ruling 39), and the summary line says so.
        self.assertIsNone(r['facts_replay_ok'])
        self.assertIn('replay_ok None (facts file missing or empty)', self.out)

    def test_empty_facts_file_nulls_replay_ok(self):
        r = self.grade(final=[])
        self.assertEqual((r['facts_exists'], r['facts_lines']), (True, 0))
        self.assertIsNone(r['facts_replay_ok'])
        self.assertEqual((r['facts_gate'], r['bar_met']), (False, False))  # gate, not replay_ok
        self.assertIn('replay_ok None (facts file missing or empty)', self.out)
        r = self.grade()
        self.assertTrue(r['facts_replay_ok'])
        self.assertIn('replay_ok True | ', self.out)

    def test_wrongly_named_facts_file_out_of_scope(self):
        r = self.grade(numstat=f'1\t1\t{S1}\n1\t1\t{S2}\n6\t0\tlis-facts.md\n')
        self.assertFalse(r['scope_ok'])
        self.assertFalse(r['bar_met'])

    def test_rung1_meta_takes_the_old_path(self):
        r = self.grade(profile=None, meta_extra={'target_tests': [A, B]})
        self.assertIsNone(r['grade_profile'])
        self.assertNotIn('facts_gate', r)
        self.assertNotIn('bar_reason', r)
        self.assertFalse(r['scope_ok'])  # the facts file is not in scope without the profile

    def test_fixed_name_without_module_tag_is_unmatched(self):
        # Rep 163439: every FIXED name lacked the 'mNN ' prefix TAP prints.
        bare = f'FIXED {A[4:]} | {S1}'
        bad = L1[:2] + [bare] + L1[3:]
        steps = good(self.work)
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(bad)), 'ok', False)
        for after, would in (((True, True), 1), ((False, True), 0)):
            r = self.grade(steps, final=bad + L2, after=after)
            fixed = [v for v in r['facts_verdicts'] if v['kind'] == 'FIXED']
            self.assertEqual([(v['verdict'], v['reason']) for v in fixed],
                             [(False, 'name_unmatched'), (True, None)])
            self.assertEqual((r['facts_name_unmatched'],
                              r['facts_name_unmatched_would_pass']), (1, would))
            self.assertEqual((r['facts_false'], r['bar_met']), (1, False))
            self.assertIn('facts_false 1 unmatched 1 | ', self.out)
        r = self.grade()
        self.assertEqual((r['facts_name_unmatched'], r['facts_name_unmatched_would_pass']),
                         (0, 0))

    def test_fixed_false_reasons(self):
        # An existing name: the guard test passed before; m02 still failing; wrong path.
        extra = f'FIXED {G} | {S1}'
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + [extra])),
                    'ok', False)
        r = self.grade(steps, final=L1 + L2 + [extra], after=(True, False))
        self.assertEqual([v['reason'] for v in r['facts_verdicts'] if v['kind'] == 'FIXED'],
                         [None, 'still_failing', 'passed_before'])
        others = [v for v in r['facts_verdicts'] if v['kind'] != 'FIXED']
        self.assertEqual({v['kind'] for v in others}, {'BEFORE', 'CHECK', 'NEXT'})
        for v in others:
            self.assertNotIn('reason', v)  # schema: only FIXED verdicts carry a reason
        self.assertEqual((r['facts_name_unmatched'], r['facts_name_unmatched_would_pass']),
                         (0, 0))
        wrong = f'FIXED {B} | {S1}'
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text([L2[0], wrong])),
                    'ok', False)
        r = self.grade(steps, final=L1 + [L2[0], wrong])
        self.assertEqual([v['reason'] for v in r['facts_verdicts'] if v['kind'] == 'FIXED'],
                         [None, 'wrong_file'])

    def checks_after_last_run(self, extra):
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + extra)),
                    'ok', False)
        return self.grade(steps, final=L1 + L2 + extra)

    def test_second_check_after_one_run_is_a_violation(self):
        # Rep 163439: 6 CHECK lines added in one Edit after the last of 2 test runs.
        for extra, n in ((['CHECK pass 3, fail 0'], 1),
                         (['CHECK pass 3, fail 0', 'CHECK pass  3 fail 0'], 2)):
            r = self.checks_after_last_run(extra)
            self.assertIn(f'check_without_run:{n}', r['instruction_violations'])
            self.assertEqual((r['facts_false'], r['bar_met']), (0, True))  # report-only

    def test_one_check_per_run_is_no_violation(self):
        r = self.grade()
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('check_without_run')])
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        r = self.grade(steps)  # replay null: not counted
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('check_without_run')])

    def fixed_one(self, line, **kw):
        """The m01 FIXED line replaced by line: (verdict dict of line, result)."""
        bad = L1[:2] + [line] + L1[3:]
        steps = good(self.work)
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(bad)), 'ok', False)
        r = self.grade(steps, final=bad + L2, **kw)
        return next(v for v in r['facts_verdicts'] if v['line'] == line), r

    def test_fixed_manifest_reasons(self):
        man = os.path.join(self.root, 'm02-only.json')
        with open(man, 'w', encoding='utf-8') as f:
            json.dump({'tests': [{'name': B, 'file': 'longfix/test/m02-beta.test.js'}]}, f)
        v, _ = self.fixed_one(f'FIXED {A} | {S1}', meta_extra={'manifest': man})
        self.assertEqual((v['verdict'], v['reason']), (False, 'not_in_manifest'))
        v, _ = self.fixed_one(f'FIXED {A} | {S1}', numstat=f'1\t1\t{S2}\n6\t0\t{FACTS}\n')
        self.assertEqual((v['verdict'], v['reason']), (False, 'not_in_diff'))

    def test_would_pass_needs_a_flip(self):
        # 'm01 ' + the bare guard name is a TAP test, but it passed before.
        v, r = self.fixed_one(f'FIXED {G[4:]} | {S1}')
        self.assertEqual((v['reason'], r['facts_name_unmatched'],
                          r['facts_name_unmatched_would_pass']), ('name_unmatched', 1, 0))

    def test_unmatched_fields_null_without_tap(self):
        from unittest import mock
        for gone in (tap(False, False), tap(True, True)):  # tests-before, tests-after
            real = g.tap
            with mock.patch.object(g, 'tap', lambda t, gone=gone: None if t == gone
                                   else real(t)):
                r = self.grade()
            self.assertEqual((r['facts_name_unmatched'],
                              r['facts_name_unmatched_would_pass']), (None, None))

    def test_check_without_run_edges(self):
        def viol(r):
            return [v for v in r['instruction_violations'] if v.startswith('check_without_run')]
        fp = os.path.join(self.work, FACTS)
        two = ['CHECK pass 1 fail 2', 'CHECK pass 2 fail 1']
        # No run before either CHECK: both false, neither a repeat of a run.
        r = self.grade([('Write', {'file_path': fp, 'content': text(two)}, 'ok', False)],
                       final=two)
        self.assertEqual(([v['verdict'] for v in r['facts_verdicts']], viol(r)),
                         ([False, False], []))
        # Exact run, CHECK, non-exact run, CHECK: a run happened before each (audit R1).
        steps = [('Bash', {'command': CMD}, run_out(1, 2), True),
                 ('Write', {'file_path': fp, 'content': text(two[:1])}, 'ok', False),
                 ('Bash', {'command': 'node --test --test-reporter=tap longfix/test/all.test.js'},
                  run_out(2, 1), True),
                 ('Edit', {'file_path': fp, 'old_string': text(two[:1]), 'new_string': text(two)},
                  'ok', False)]
        r = self.grade(steps, final=two)
        self.assertIn('test_runs_nonexact:1', r['instruction_violations'])
        self.assertEqual(viol(r), [])
        # Two CHECK lines after the non-exact run, final order unlike the add order.
        steps[3] = ('Edit', dict(steps[3][1], new_string=text(two + ['CHECK pass 2, fail 1'])),
                    'ok', False)
        r = self.grade(steps, final=['CHECK pass 2, fail 1'] + two)
        self.assertEqual(viol(r), ['check_without_run:1'])
        # One repeat after each of two runs: 2 (the repeats sum, not max or any; audit R2).
        four = ['CHECK pass 1 fail 2', 'CHECK pass 1, fail 2', 'CHECK pass 2 fail 1',
                'CHECK pass 2, fail 1']
        steps = [('Bash', {'command': CMD}, run_out(1, 2), True),
                 ('Write', {'file_path': fp, 'content': text(four[:2])}, 'ok', False),
                 ('Bash', {'command': CMD}, run_out(2, 1), True),
                 ('Edit', {'file_path': fp, 'old_string': text(four[:2]),
                           'new_string': text(four)}, 'ok', False)]
        r = self.grade(steps, final=four)
        self.assertEqual(([v['verdict'] for v in r['facts_verdicts']], viol(r)),
                         ([True] * 4, ['check_without_run:2']))

    def test_fixed_verified_in_reporter_format(self):
        # Series 4 runs use the fixture reporter: one line per module, then '# pass/fail N'.
        def rep(m02, p, f):
            return f'm01 FAIL 1/2: {G}\n{m02}\n# pass {p}\n# fail {f}\n'
        extra = f'FIXED {G} | {S1}'
        steps = good(self.work)
        steps[3] = ('Bash', {'command': CMD}, rep(f'm02 FAIL 0/1: {B}', 2, 1), True)
        steps[8] = ('Bash', {'command': CMD}, rep('m02 ok 1/1', 3, 0), False)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + [extra])),
                    'ok', False)
        r = self.grade(steps, final=L1 + L2 + [extra])
        # A: m01 FAIL lists another test; B: m02 ok; G: m01 FAIL lists G itself.
        self.assertEqual(r['facts_fixed_verified'], 2)
        self.assertEqual([v['verdict'] for v in r['facts_verdicts'] if v['kind'] == 'CHECK'],
                         [True, True])  # '# pass N' / '# fail N' read as the run counts
        self.assertFalse(lr.run_ok('m01 ok 2/2\n# pass 2\n# fail 0\n', A[4:]))  # no mNN prefix
        self.assertTrue(lr.run_ok(f'ok 1 - {A}\n', A))  # TAP (series 1-3) still ok

    def test_fixed_verified_needs_a_real_name(self):
        # An invented mNN name under an ok module line is not verified (audit R3).
        fake = f'FIXED m02 betaSort invented name | {S2}'
        steps = good(self.work)
        steps[8] = ('Bash', {'command': CMD}, 'm01 ok 2/2\nm02 ok 1/1\n# pass 3\n# fail 0\n',
                    False)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2 + [fake])),
                    'ok', False)
        r = self.grade(steps, final=L1 + L2 + [fake])
        self.assertEqual(r['facts_fixed_verified'], 2)  # A (spec line) and B; not fake

    def test_run_ok_reporter_crlf(self):
        crlf = f'm01 FAIL 1/2: {G}\r\nm02 FAIL 0/1: {B}\r\n# pass 1\r\n# fail 2\r\n'
        self.assertEqual([lr.run_ok(crlf, t) for t in (A, B, G)], [True, False, False])
        self.assertEqual(lr.run_counts(crlf), {'pass': 1, 'fail': 2})

    def test_test_runs_short(self):
        # Series 4 rep 1 (175551): 3 test-command runs where the prompt asks for 14.
        p48 = ('Run the test command once before any change, then after m04, m08, m12, m16, '
               'm20, m24, m28, m32, m36, m40, m44 and m48, and once more before your report.')
        r = self.grade(meta_extra={'prompt': p48})
        self.assertEqual((r['test_runs_instructed'], r['test_runs_exact']), (14, 3))
        self.assertIn('test_runs_short:11', r['instruction_violations'])
        self.assertEqual((r['bar_met'], r['bar_reason']), (True, None))  # report-only
        r = self.grade()  # no checkpoint list in the prompt: unknown, no violation
        self.assertEqual((r['test_runs_instructed'], r['test_runs_exact']), (None, 3))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def test_compliant_runs_and_checks_have_no_violation(self):
        # 4 runs for "after m01 and m02" (before, m01, m02, report), each later run a CHECK.
        last = 'CHECK pass 3, fail 0'
        steps = good(self.work) + [
            ('Bash', {'command': CMD}, run_out(3, 0, [A, B]), False),
            ('Edit', {'file_path': os.path.join(self.work, FACTS), 'old_string': text(L2[1:]),
                      'new_string': text(L2[1:] + [last])}, 'ok', False)]
        prompt = 'then after m01 and m02, and once more before your report.'
        r = self.grade(steps, final=L1 + L2 + [last], meta_extra={'prompt': prompt})
        self.assertEqual((r['test_runs_instructed'], r['test_runs_exact']), (4, 4))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])
        self.assertEqual((r['facts_lines_at_boundaries'], r['facts_fixed_at_boundaries']),
                         ([3], [1]))  # BEFORE, CHECK, FIXED (not NEXT) held at the boundary
        # One run more than instructed (with its CHECK) is not short.
        extra = 'CHECK pass  3 fail 0'
        steps += [('Bash', {'command': CMD}, run_out(3, 0, [A, B]), False),
                  ('Edit', {'file_path': os.path.join(self.work, FACTS),
                            'old_string': last + '\n', 'new_string': text([last, extra])},
                   'ok', False)]
        r = self.grade(steps, final=L1 + L2 + [last, extra], meta_extra={'prompt': prompt})
        self.assertEqual((r['test_runs_instructed'], r['test_runs_exact']), (4, 5))
        self.assertEqual(r['instruction_violations'], ['piped_test_runs:1'])

    def test_run_without_check_is_check_missing(self):
        # The run before the report (step 8) gets FIXED but no CHECK line, and the session
        # reports: the closing run, exempt by ruling (21) (was check_missing:1).
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2[1:])),
                    'ok', False)
        r = self.grade(steps, final=L1 + L2[1:])
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('check_missing')])
        self.assertEqual(r['check_missing_final_exempt'], 1)
        # A middle run (step 3) without a CHECK: the next run's CHECK does not cover it.
        steps2 = good(self.work)
        no_check = L1[:1] + L1[2:]
        steps2[4] = ('Edit', dict(steps2[4][1], new_string=text(no_check)), 'ok', False)
        r = self.grade(steps2, final=no_check + L2)
        self.assertIn('check_missing:1', r['instruction_violations'])
        self.assertEqual(r['check_missing_final_exempt'], 0)  # the final run has a CHECK
        # Replay null: the boundary counts and check_missing are unknown.
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        r = self.grade(steps, final=L1 + L2[1:])
        self.assertEqual((r['facts_lines_at_boundaries'], r['facts_fixed_at_boundaries']),
                         ([None], [None]))
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('check_missing')])
        self.assertIsNone(r['check_missing_final_exempt'])

    def test_final_run_exempt_from_check_missing(self):
        # Ruling (21): the closing run (4 runs for "after m01 and m02"), with no CHECK line
        # and nothing after it but the report.
        fp, last = os.path.join(self.work, FACTS), 'CHECK pass 3, fail 0'
        final_run = ('Bash', {'command': CMD}, run_out(3, 0, [A, B]), False)
        cadence = {'prompt': 'then after m01 and m02, and once more before your report.'}

        def grade(steps, **kw):
            r = self.grade(steps, meta_extra=cadence, **kw)
            return ([v for v in r['instruction_violations']
                     if v.startswith(('check_missing', 'test_runs_short'))],
                    r['check_missing_final_exempt'])

        self.assertEqual(grade(good(self.work) + [final_run]), ([], 1))
        # A facts write after it (a record, not an edit): still exempt.
        nxt = ('Edit', {'file_path': fp, 'old_string': text(L2[1:]),
                        'new_string': text(L2[1:] + ['NEXT none'])}, 'ok', False)
        self.assertEqual(grade(good(self.work) + [final_run, nxt],
                               final=L1 + L2 + ['NEXT none']), ([], 1))
        # A source Write after it, errored or not: counted as before, no exemption.
        src = ('Write', {'file_path': os.path.join(self.work, S1), 'content': 'x'}, 'ok', False)
        for w in (src, src[:2] + ('denied', True)):
            self.assertEqual(grade(good(self.work) + [final_run, w]),
                             (['check_missing:1'], 0))
        # With its CHECK line the final run is not missing: nothing to exempt.
        chk = ('Edit', {'file_path': fp, 'old_string': text(L2[1:]),
                        'new_string': text(L2[1:] + [last])}, 'ok', False)
        self.assertEqual(grade(good(self.work) + [final_run, chk], final=L1 + L2 + [last]),
                         ([], 0))
        # Series 4 shape: runs skipped (3 of 4), the last one has no CHECK, and the session
        # reports with a STATUS line: still the closing run, exempt.
        steps = good(self.work)
        steps[9] = ('Edit', dict(steps[9][1], new_string='NEXT m02\n' + text(L2[1:])),
                    'ok', False)
        self.assertEqual(grade(steps, final=L1 + L2[1:]), (['test_runs_short:1'], 1))
        # The stream stops after that run with no final result (timeout, turn limit): not
        # the closing run, so it counts and nothing is exempt.
        self.assertEqual(grade(steps, final=L1 + L2[1:], result=False),
                         (['test_runs_short:1', 'check_missing:1'], 0))
        # A final result with no STATUS line: no report, nothing exempt.
        self.assertEqual(grade(steps, final=L1 + L2[1:], claim=CLAIM.replace('STATUS', 'S')),
                         (['test_runs_short:1', 'check_missing:1'], 0))

    def test_no_test_run_has_no_check_missing(self):
        steps = [st for st in good(self.work)
                 if not (st[0] == 'Bash' and st[1]['command'].startswith(CMD))]
        r = self.grade(steps)
        self.assertEqual((r['test_runs'], r['check_missing_final_exempt']), (0, 0))
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('check_missing')])

    def test_no_test_cmd_has_no_run_count(self):
        prompt = 'then after m01 and m02, and once more before your report.'
        r = self.grade(meta_extra={'test_cmd': None, 'prompt': prompt})
        self.assertEqual((r['test_runs_instructed'], r['test_runs_exact']), (4, None))
        self.assertFalse([v for v in r['instruction_violations']
                          if v.startswith('test_runs_short')])

    def test_count_lines_unbacked(self):
        # T-1: each BEFORE and CHECK line needs its own earlier run that printed its pair.
        r = self.grade()
        self.assertEqual(r['count_lines_unbacked'], {'count': 0, 'lines': []})
        self.assertIn('trust (report-only): count_lines_unbacked 0 | lines_removed 0 | '
                      "cadence_runs {'done': 3, 'asked': None} | shell_redirect_writes 0 | "
                      'fixed_names_inexact 0 missing 0 | claim_fixed_count_agrees True | '
                      'exact_command_violations 1', self.out)
        # Rep 163439: a second CHECK line for the one run before it.
        extra = 'CHECK pass 3, fail 0'
        r = self.checks_after_last_run([extra])
        self.assertEqual(r['count_lines_unbacked'], {'count': 1, 'lines': [extra]})
        self.assertEqual(r['bar_met'], True)  # report-only
        # Rep 183719: a pair no run printed.
        bad = [L1[0], 'CHECK pass 140 fail 4'] + L1[2:]
        steps = good(self.work)
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(bad)), 'ok', False)
        r = self.grade(steps, final=bad + L2)
        self.assertEqual(r['count_lines_unbacked'], {'count': 1, 'lines': [bad[1]]})
        # Reps 132833, 141312: a placeholder BEFORE before any run, later replaced.
        steps, ph = good(self.work), 'BEFORE pass 0 fail 0'
        steps[1] = ('Write', dict(steps[1][1], content=ph + '\n'), 'ok', False)
        steps[4] = ('Edit', dict(steps[4][1], old_string=ph + '\n'), 'ok', False)
        r = self.grade(steps)
        self.assertEqual((r['count_lines_unbacked'], r['bar_met']),
                         ({'count': 1, 'lines': [ph]}, True))
        self.assertIn('count_lines_unbacked 1 | lines_removed 1 | ', self.out)
        # A run with no summary lines backs nothing; a cd run backs its line.
        for cmd, out, n in ((CMD, 'no summary\n', 1), ('cd . && ' + CMD, run_out(2, 1), 0)):
            steps = good(self.work)
            steps[3] = ('Bash', {'command': cmd}, out, True)
            self.assertEqual(self.grade(steps)['count_lines_unbacked']['count'], n)
        # A run after the write does not back it (the Edit precedes the 3/0 run).
        steps = good(self.work)
        steps[8], steps[9] = steps[9], steps[8]
        self.assertEqual(self.grade(steps)['count_lines_unbacked'],
                         {'count': 1, 'lines': [L2[0]]})
        # A final count line with no replayed add is unbacked.
        r = self.grade(final=L1 + L2 + ['CHECK pass 9 fail 9'])
        self.assertEqual(r['count_lines_unbacked'],
                         {'count': 1, 'lines': ['CHECK pass 9 fail 9']})
        # Replay null: unknown.
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        self.assertIsNone(self.grade(steps)['count_lines_unbacked'])

    def test_cadence_runs_and_shell_redirect_writes(self):
        # T-2: series 4 rep 1 (175551) ran 3 times where the prompt asks for 14.
        p48 = ('Run the test command once before any change, then after m04, m08, m12, m16, '
               'm20, m24, m28, m32, m36, m40, m44 and m48, and once more before your report.')
        r = self.grade(meta_extra={'prompt': p48})
        self.assertEqual((r['cadence_runs'], r['bar_met']), ({'done': 3, 'asked': 14}, True))
        steps = good(self.work)
        steps.insert(3, ('Bash', {'command': 'ls && ' + CMD}, run_out(1, 2), True))
        self.assertEqual(self.grade(steps)['cadence_runs'], {'done': 4, 'asked': None})
        self.assertIsNone(self.grade(meta_extra={'test_cmd': None})['cadence_runs'])
        # Rep 183719: cat >> appends, counted by command; an unparsed or errored one too.
        fp = os.path.join(self.work, FACTS)
        steps = good(self.work)
        steps[4] = ('Bash', {'command': f"cat >> {FACTS} << 'EOF'\n" + text(L1[1:]) + 'EOF'},
                    '', False)
        steps[9] = ('Bash', {'command': f'echo "$X" >>"{fp}"'}, 'denied', True)
        steps += [('Bash', {'command': f'cat {FACTS} > copy.md 2>&1'}, '', False),
                  ('Bash', {'command': CMD + ' 2>&1 > out.txt'}, run_out(3, 0), False)]
        r = self.grade(steps)
        self.assertEqual((r['shell_redirect_writes'], r['facts_bash_appends']), (2, 1))
        self.assertEqual(r['bar_met'], None)  # replay null from the echo: as before

    def test_fixed_names_inexact_and_missing(self):
        # T-3: rep 163439 dropped the 'mNN ' prefix; rep 181610 named tests that do not exist.
        r = self.grade()
        self.assertEqual((r['fixed_names_inexact'], r['fixed_names_missing']),
                         ({'count': 0, 'names': []}, {'count': 0, 'names': []}))
        _, r = self.fixed_one(f'FIXED {A[4:]} | {S1}')
        self.assertEqual((r['fixed_names_inexact'], r['fixed_names_missing']),
                         ({'count': 1, 'names': [A[4:]]}, {'count': 0, 'names': []}))
        fake = 'm01 alphaTrim invented name'
        _, r = self.fixed_one(f'FIXED {fake} | {S1}')
        self.assertEqual((r['fixed_names_inexact'], r['fixed_names_missing']),
                         ({'count': 1, 'names': [fake]}, {'count': 1, 'names': [fake]}))
        self.assertIn('fixed_names_inexact 1 missing 1 | ', self.out)
        r = self.grade(meta_extra={'manifest': None})
        self.assertEqual((r['fixed_names_inexact'], r['fixed_names_missing']), (None, None))

    def test_fixed_count_agrees_in_summary(self):
        # T-4 reuses claim_fixed_count_agrees (141312: Fixed: 48, 47 FIXED lines).
        r = self.grade(claim=CLAIM.replace('Fixed: 2', 'Fixed: 3'))
        self.assertFalse(r['claim_fixed_count_agrees'])
        self.assertIn('claim_fixed_count_agrees False | ', self.out)

    def test_exact_command_violations(self):
        # T-6: rep 143441 ran the tests once as cd <work> && <test command>.
        steps = good(self.work)
        steps[8] = ('Bash', {'command': CMD}, run_out(3, 0, [A, B]), False)
        self.assertEqual(self.grade(steps)['exact_command_violations'], 0)
        for cmd in ('cd /w && ' + CMD, 'ls && ' + CMD, CMD + ' 2>&1',
                    CMD.replace('--test', '--test --test-only')):
            steps[3] = ('Bash', {'command': cmd}, run_out(2, 1, [A]), True)
            r = self.grade(steps)
            self.assertEqual(r['exact_command_violations'], 1, cmd)
        self.assertEqual(self.grade()['exact_command_violations'], 1)  # the | tail -5 run
        self.assertIsNone(self.grade(meta_extra={'test_cmd': None})['exact_command_violations'])

    def relaunched(self, first=None):
        """good() with an init first and a relaunch after the Read that follows the boundary:
        session 1 ends, a second init starts session 2, whose first tool call is first
        (default: the test command), then the rest of good()."""
        steps = good(self.work)
        cut = [i for i, s in enumerate(steps) if s[0] == 'Read'][0] + 1
        first = first or ('Bash', {'command': CMD}, run_out(2, 1, [A]), True)
        return [('init', {})] + steps[:cut] + [('init', {}), first] + steps[cut:]

    def test_relaunch_fields(self):
        # R-W2 / T-5: one init per session; the second session ran the test command first.
        # Its startup context (transcript 2, before any boundary) belongs to no boundary, and
        # the startup log lines are no compactions.
        startup = '2026-11-04T12:00:0{} source=startup facts={} injected={}'
        log = [startup.format(0, FACTS, 'no reason=not-relaunch')] + ilog(1) \
            + [startup.format(5, FACTS, 'yes lines=4 bytes=80 truncated=no')]
        r = self.grade(self.relaunched(), transcript=self.restore_transcript(attach=False),
                       transcript2=[ctx()], inject=log)
        self.assertEqual((r['relaunches'], r['relaunch_test_first']), (1, True))
        self.assertEqual((r['facts_context_after_boundary'], r['facts_context_count'],
                          r['facts_injected_after_boundary'], r['facts_injected_count']),
                         ([False], 1, [True], 1))
        self.assertEqual((r['compaction_fired'], r['compaction_consistency'],
                          r['compaction_transcript']),
                         (1, True, {'boundaries': 1, 'summaries': 1}))
        # Without a relaunch: 0 and null, and the second transcript is not read.
        r = self.grade(transcript=self.restore_transcript(attach=False), transcript2=[ctx()])
        self.assertEqual((r['relaunches'], r['relaunch_test_first'], r['facts_context_count']),
                         (0, None, 0))

    def test_relaunch_test_first_false(self):
        # The first call after the relaunch init is a Read, or a piped or other command.
        fp = os.path.join(self.work, FACTS)
        for first in (('Read', {'file_path': fp}, text(L1), False),
                      ('Bash', {'command': 'cat ' + FACTS}, text(L1), False),
                      ('Bash', {'command': 'node --test longfix/test/m01.test.js'}, 'x', False)):
            r = self.grade(self.relaunched(first), transcript=self.restore_transcript(),
                           transcript2=[])
            self.assertEqual((r['relaunches'], r['relaunch_test_first']), (1, False), first)
        # No tool call at all after the relaunch init.
        r = self.grade([('init', {})] + good(self.work) + [('init', {})])
        self.assertEqual((r['relaunches'], r['relaunch_test_first']), (1, False))

    def test_relaunch_boundaries_span_both_transcripts(self):
        # A boundary in each session: each transcript holds its own, in order; without the
        # second transcript the per-boundary transcript fields are null, not misplaced.
        steps = self.relaunched()
        steps.insert(len(steps) - 1, boundary())
        t1 = self.restore_transcript(attach=False)
        t2 = [ctx()] + self.restore_transcript(attach=True)
        r = self.grade(steps, transcript=t1, transcript2=t2)
        self.assertEqual([b['facts_restored_after'] for b in r['compaction_boundaries']],
                         [False, True])
        self.assertEqual((r['facts_context_after_boundary'], r['facts_context_count'],
                          r['compaction_consistency']), ([False, False], 1, True))
        r = self.grade(steps, transcript=t1)
        self.assertEqual([b['facts_restored_after'] for b in r['compaction_boundaries']],
                         [None, None])
        self.assertEqual((r['facts_context_after_boundary'], r['facts_context_count'],
                          r['compaction_transcript']), ([None, None], None, None))

    def test_relaunch_leaves_the_bar_alone(self):
        for extra in (None, {'bar_v': 2}):
            a = self.grade(meta_extra=extra)
            z = self.grade(self.relaunched(), meta_extra=extra)
            self.assertEqual(z['relaunches'], 1)
            # The extra test run is the only difference: compare the bar fields.
            self.assertEqual((z['bar_met'], z['bar_parts']), (a['bar_met'], a['bar_parts']))

    def test_ruling_46_record_parts_join_the_bar_from_bar_v_2(self):
        def both(steps=None, **kw):
            """(bar_met, bar_reason) without bar_v, then with bar_v 2, and the v2 result."""
            old = self.grade(steps, **kw)
            new = self.grade(steps, meta_extra={'bar_v': 2}, **kw)
            self.assertEqual((old['bar_v'], new['bar_v']), (1, 2))
            return (old['bar_met'], old['bar_reason']), (new['bar_met'], new['bar_reason']), new
        # A retracted line (placeholder BEFORE replaced, reps 132833 and 141312).
        steps, ph = good(self.work), 'BEFORE pass 0 fail 0'
        steps[1] = ('Write', dict(steps[1][1], content=ph + '\n'), 'ok', False)
        steps[4] = ('Edit', dict(steps[4][1], old_string=ph + '\n'), 'ok', False)
        old, new, r = both(steps)
        self.assertEqual((old, new), ((True, None), (False, 'false: record_intact')))
        self.assertEqual((r['record_intact'], r['no_redirect_writes']), (False, True))
        self.assertIn('record_intact', r['bar_parts'])
        # A shell-redirect write (cat >> appends, rep 183719).
        steps = good(self.work)
        steps[4] = ('Bash', {'command': f"cat >> {FACTS} << 'EOF'\n" + text(L1[1:]) + 'EOF'},
                    '', False)
        old, new, r = both(steps)
        self.assertEqual((old, new), ((True, None), (False, 'false: no_redirect_writes')))
        self.assertIn('bar_v 2 | bar_reason false: no_redirect_writes | ', self.out)
        # Both clean: the bar is what the other parts give (true; false with a bad CHECK).
        old, new, r = both()
        self.assertEqual((old, new), ((True, None), (True, None)))
        self.assertEqual((r['record_intact'], r['no_redirect_writes']), (True, True))
        steps = good(self.work)
        bad = [L1[0], 'CHECK pass 3 fail 0'] + L1[2:]
        steps[4] = ('Edit', dict(steps[4][1], new_string=text(bad)), 'ok', False)
        old, new, _ = both(steps, final=bad + L2)
        self.assertEqual((old, new), ((False, 'false: facts_gate'), (False, 'false: facts_gate')))
        # Replay null: record_intact null, so a v2 bar that was true is null.
        steps = good(self.work)
        steps.insert(5, ('Bash', {'command': f"sed -i 's/m02/m03/' {FACTS}"}, '', False))
        old, new, r = both(steps)
        self.assertIsNone(r['record_intact'])
        self.assertEqual(new[0], None if old[0] is True else old[0])
        self.assertIn('record_intact', new[1])
        # Without bar_v the parts stay out of bar_parts (history keeps its verdicts).
        self.assertNotIn('record_intact', self.grade()['bar_parts'])
        # A bar_v that is not an int counts as 1.
        self.assertEqual(self.grade(meta_extra={'bar_v': '2'})['bar_v'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=1)
