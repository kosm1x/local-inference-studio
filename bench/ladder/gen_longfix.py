"""Generate the bench/ladder long-fix fixture: M Node modules, 2 planted bugs + 1 guard each.

Usage (from the repo root):
  python -I bench/ladder/gen_longfix.py --out <work> --manifest <file>
                                        [--modules 24] [--lines 220]
Writes <work>/longfix/src/mNN-<noun>.js, <work>/longfix/test/mNN-<noun>.test.js and
<work>/longfix/test/all.test.js (the one entry point: node --test longfix/test/all.test.js).
Module i plants bug kinds K[(2i-2) % 14] and K[(2i-1) % 14], adds guard G[i % 5] (correct,
its test passes before any fix) and correct documented filler helpers until the source is
--lines +-5 lines. The bug pairs repeat every 7 modules (m01, m08, m15 and m22 plant the
same two kinds). Each buggy function has a contract comment that, with its test, fixes the
one correct repair. No RNG: the same arguments give byte-identical files. The manifest
(kept outside the work tree) lists files with sha256 and every test with expect_before.
fixture_sha256 = sha256 over the files sorted by path, each as path NUL bytes NUL.
Refuses a non-empty <work>/longfix. Stdlib only.

all.test.js sets Error.stackTraceLimit = 0, not 1: on Node 24 the spec reporter prints one
absolute-path stack line per failure, and at 48 failures under a lis-ladder work path that
put the before run at ~27.4K chars, over the 25,000 budget (0 gives ~20.6K). The reporter
still names each failing test's file:line ("test at longfix\\test\\...").
Node 22 off a TTY (what the model's Bash tool gets when its node is 22) defaults to the TAP
reporter instead: ~29.5K chars for the before run, also path-length dependent (run.ps1
measured 29,491 with its own node 22 for rep 1 of 2026-10-26). Claude Code cuts a long
tool result to its first 5,000 and last 5,000 chars around a "... [N characters truncated]
..." marker (rep 1: 20.4K chars of spec output shown as 10,040). The spec reporter prints
one line per test, then the summary ("pass N", "fail N"), then the failure details, so the
summary is in the first 5,000 only while the per-test lines fit before it: more modules
would push it into the cut.

TEST AID: generate(..., solve=True) writes each buggy function's correct body instead (the
'fix' entries of K). Only gen_longfix_test.py uses it, to prove every planted bug is real
and fixable. Because the answers live in this file, the grader's rubric_seen check
(any tool input naming bench/ladder) also covers a model reading gen_longfix.py.
"""
import argparse
import hashlib
import json
import os
import sys

VERSION = '1'
CATALOG_VERSION = '1'
MAX_LINES = 290  # the wrapper's "file over 300 lines" advice must never apply

NOUNS = ['ledger', 'invoice', 'parcel', 'sensor', 'ticket', 'roster', 'beacon', 'cargo',
         'meter', 'voucher', 'kernel', 'harbor', 'orchard', 'quarry', 'signal', 'tablet',
         'vessel', 'wallet', 'anchor', 'bridge', 'canyon', 'glacier', 'lantern', 'mosaic']

# Bug catalog. doc = the contract comment; '@' in a test body is the function name.
K = [
    dict(base='take', args='items, n', does='returns the first n items',
         doc='First n items of items as a new array; all of them when n >= items.length.',
         bug='return items.slice(0, n - 1);', fix='return items.slice(0, n);',
         test="assert.deepStrictEqual(@(['a', 'b', 'c', 'd'], 2), ['a', 'b']);\n"
              "assert.deepStrictEqual(@(['a', 'b'], 5), ['a', 'b']);"),
    dict(base='inRange', args='x, lo, hi', does='includes both range ends',
         doc='True when lo <= x <= hi: both ends of the range are inclusive.',
         bug='return x >= lo && x < hi;', fix='return x >= lo && x <= hi;',
         test='assert.strictEqual(@(1, 1, 5), true);\nassert.strictEqual(@(5, 1, 5), true);\n'
              'assert.strictEqual(@(6, 1, 5), false);'),
    dict(base='labelLength', args='s', does='treats null and undefined as empty',
         doc='Length of s after trimming whitespace; 0 when s is null or undefined.',
         bug='return s.trim().length;', fix='if (s == null) return 0;\nreturn s.trim().length;',
         test="assert.strictEqual(@('  ab '), 2);\nassert.strictEqual(@(null), 0);\n"
              'assert.strictEqual(@(undefined), 0);'),
    dict(base='clamp', args='x, lo, hi', does='keeps values inside the bounds',
         doc='x limited to [lo, hi]: lo when x is below, hi when x is above, else x itself.',
         bug='return Math.max(hi, Math.min(lo, x));', fix='return Math.min(hi, Math.max(lo, x));',
         test='assert.strictEqual(@(5, 0, 10), 5);\nassert.strictEqual(@(-3, 0, 10), 0);\n'
              'assert.strictEqual(@(42, 0, 10), 10);'),
    dict(base='sortedAmounts', args='nums',
         does='orders numbers numerically without mutating input',
         doc='New array of nums in ascending numeric order; nums itself is left unchanged.',
         bug='return nums.sort();', fix='return [...nums].sort((a, b) => a - b);',
         test='const input = [10, 9, 100, 1];\n'
              'assert.deepStrictEqual(@(input), [1, 9, 10, 100]);\n'
              'assert.deepStrictEqual(input, [10, 9, 100, 1]);'),
    dict(base='product', args='nums', does='multiplies every number',
         doc='Product of all numbers in nums; 1 for an empty array.',
         bug='let p = 0;\nfor (const n of nums) p *= n;\nreturn p;',
         fix='let p = 1;\nfor (const n of nums) p *= n;\nreturn p;',
         test='assert.strictEqual(@([2, 3, 4]), 24);\nassert.strictEqual(@([]), 1);'),
    dict(base='percent', args='part, whole', does='rounds to the nearest whole percent',
         doc='part / whole as a whole-number percentage, rounded to the nearest integer\n'
             '(a half rounds up), e.g. 2 of 3 is 67.',
         bug='return Math.floor((part / whole) * 100);',
         fix='return Math.round((part / whole) * 100);',
         test='assert.strictEqual(@(1, 3), 33);\nassert.strictEqual(@(2, 3), 67);\n'
              'assert.strictEqual(@(1, 8), 13);'),
    dict(base='sameCode', args='a, b', does='compares codes ignoring case',
         doc='True when codes a and b are equal ignoring letter case.',
         bug='return a === b;', fix='return a.toLowerCase() === b.toLowerCase();',
         test="assert.strictEqual(@('AbC', 'abc'), true);\n"
              "assert.strictEqual(@('abc', 'abd'), false);"),
    dict(base='csvRow', args='fields', does='joins fields with a bare comma',
         doc='fields joined into one CSV line: values separated by a comma, no spaces.',
         bug="return fields.join(', ');", fix="return fields.join(',');",
         test="assert.strictEqual(@(['a', 'b', 'c']), 'a,b,c');"),
    dict(base='stripDigits', args='s', does='removes every digit',
         doc='s with every digit 0-9 removed, wherever it occurs.',
         bug="return s.replace(/[0-9]/, '');", fix="return s.replace(/[0-9]/g, '');",
         test="assert.strictEqual(@('a1b22c3'), 'abc');"),
    dict(base='kibibytes', args='bytes', does='uses 1024 bytes per KiB',
         doc='bytes converted to kibibytes (1 KiB = 1024 bytes), as a plain number.',
         bug='return bytes / 1000;', fix='return bytes / 1024;',
         test='assert.strictEqual(@(2048), 2);\nassert.strictEqual(@(512), 0.5);'),
    dict(base='total', args='nums', does='sums numbers and gives 0 for none',
         doc='Sum of nums; 0 for an empty array.',
         bug='return nums.reduce((a, b) => a + b);',
         fix='return nums.reduce((a, b) => a + b, 0);',
         test='assert.strictEqual(@([1, 2, 3]), 6);\nassert.strictEqual(@([]), 0);'),
    dict(base='activeOnly', args='items', does='keeps only active items',
         doc='The items whose active property is true, in their original order.',
         bug='return items.filter((it) => !it.active);',
         fix='return items.filter((it) => it.active);',
         test='const items = [{ id: 1, active: true }, { id: 2, active: false },\n'
              '  { id: 3, active: true }];\n'
              'assert.deepStrictEqual(@(items).map((it) => it.id), [1, 3]);'),
    dict(base='parsePairs', args='text', does='reads semicolon separated pairs',
         doc="Parse 'k=v;k2=v2' into { k: 'v', k2: 'v2' }. Pairs are separated by ';', a key\n"
             "from its value by the first '='; values stay strings; '' gives {}.",
         bug="throw new Error('not implemented');",
         fix="const out = {};\nif (text === '') return out;\n"
             "for (const pair of text.split(';')) {\n  const at = pair.indexOf('=');\n"
             '  out[pair.slice(0, at)] = pair.slice(at + 1);\n}\nreturn out;',
         test="assert.deepStrictEqual(@('a=1;b=x=y'), { a: '1', b: 'x=y' });\n"
              "assert.deepStrictEqual(@(''), {});"),
]

# Guards: correct functions with one test each (expect_before = pass).
G = [
    dict(base='safeDivide', args='a, b', does='returns null for a zero divisor',
         doc='a / b, or null when b is 0.', fix='if (b === 0) return null;\nreturn a / b;',
         test='assert.strictEqual(@(6, 3), 2);\nassert.strictEqual(@(1, 0), null);'),
    dict(base='firstOr', args='items, fallback', does='falls back on an empty list',
         doc='First item of items, or fallback when items is empty or not an array.',
         fix='if (!Array.isArray(items) || items.length === 0) return fallback;\n'
             'return items[0];',
         test="assert.strictEqual(@(['x'], 'z'), 'x');\nassert.strictEqual(@([], 'z'), 'z');\n"
              "assert.strictEqual(@(null, 'z'), 'z');"),
    dict(base='parseCount', args='text', does='rejects non-numeric text',
         doc='Non-negative integer parsed from decimal text; null for anything else.',
         fix="if (typeof text !== 'string' || !/^[0-9]+$/.test(text)) return null;\n"
             'return Number(text);',
         test="assert.strictEqual(@('42'), 42);\nassert.strictEqual(@('4x'), null);\n"
              'assert.strictEqual(@(7), null);'),
    dict(base='initial', args='name', does='gives an empty string for a missing name',
         doc="Upper-case first letter of name; '' for an empty or missing name.",
         fix="if (!name) return '';\nreturn name.charAt(0).toUpperCase();",
         test="assert.strictEqual(@('mia'), 'M');\nassert.strictEqual(@(''), '');\n"
              "assert.strictEqual(@(undefined), '');"),
    dict(base='atIndex', args='items, i', does='returns undefined outside the list',
         doc='items[i] when 0 <= i < items.length, else undefined.',
         fix='if (i < 0 || i >= items.length) return undefined;\nreturn items[i];',
         test="assert.strictEqual(@(['a', 'b'], 1), 'b');\n"
              "assert.strictEqual(@(['a'], -1), undefined);\n"
              "assert.strictEqual(@(['a'], 1), undefined);"),
]

# Filler helpers: correct, documented, untested (base, args, doc, body); <= 8 lines each.
H = [
    ('padLeft', 's, width, ch', 'String(s) left-padded with ch to at least width characters.',
     'return String(s).padStart(width, ch);'),
    ('isBlank', 's', 'True when s is null, undefined or only whitespace.',
     "return s == null || String(s).trim() === '';"),
    ('unique', 'items', 'The distinct items of items in first-seen order, as a new array.',
     'return [...new Set(items)];'),
    ('chunk', 'items, size', 'items cut into arrays of size items; the last may be shorter.',
     'const out = [];\n'
     'for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));\n'
     'return out;'),
    ('capitalize', 's', 'Copy of s with its first character upper-cased.',
     'return s.charAt(0).toUpperCase() + s.slice(1);'),
    ('average', 'nums', 'Arithmetic mean of nums; 0 for an empty array.',
     'if (nums.length === 0) return 0;\nreturn nums.reduce((a, b) => a + b, 0) / nums.length;'),
    ('lastItem', 'items', 'Last item of items, or undefined when items is empty.',
     'return items[items.length - 1];'),
    ('countBy', 'items, key', 'Object mapping each value of item[key] to its item count.',
     'const out = {};\n'
     'for (const item of items) out[item[key]] = (out[item[key]] || 0) + 1;\nreturn out;'),
    ('range', 'n', 'Array of the integers 0 to n - 1; empty when n <= 0.',
     'const out = [];\nfor (let i = 0; i < n; i++) out.push(i);\nreturn out;'),
    ('pick', 'obj, keys', 'New object with those of keys that obj has as own properties.',
     'const out = {};\n'
     'for (const k of keys) if (Object.hasOwn(obj, k)) out[k] = obj[k];\nreturn out;'),
    ('maxOf', 'nums', 'Largest number in nums; -Infinity for an empty array.',
     'return Math.max(...nums);'),
    ('words', 's', 'Whitespace-separated words of s; empty for a blank string.',
     "const t = s.trim();\nreturn t === '' ? [] : t.split(/\\s+/);"),
]


def indent(text, pad='  '):
    return '\n'.join(pad + line for line in text.split('\n'))


def function(name, args, doc, body):
    comment = '\n'.join('// ' + line for line in doc.split('\n'))
    return f'{comment}\nfunction {name}({args}) {{\n{indent(body)}\n}}\n'


def render(header, blocks):
    names = ''.join(f'  {name},\n' for name, _ in blocks)
    return header + '\n'.join(text for _, text in blocks) + f'\nmodule.exports = {{\n{names}}};\n'


def module(i, lines, solve):
    """(stem, src, test source, [(test name, kind)]) for module i (1-based)."""
    noun, mm = NOUNS[(i - 1) % len(NOUNS)], f'm{i:02d}'
    stem = f'{mm}-{noun}'

    def fn(base):
        return noun + base[0].upper() + base[1:]
    picked = [(K[(2 * i - 2) % len(K)], 'bug'), (K[(2 * i - 1) % len(K)], 'bug'),
              (G[i % len(G)], 'guard')]
    tested = [(fn(c['base']), function(fn(c['base']), c['args'], c['doc'],
                                       c['bug'] if kind == 'bug' and not solve else c['fix']))
              for c, kind in picked]
    header = (f"'use strict';\n\n// {mm} {noun}: helpers for {noun} records. A comment above"
              ' a\n// function is its contract.\n\n')
    fill, k = [], 0
    while True:
        base, args, doc, body = H[(i + k) % len(H)]
        name = fn(base) + (str(k // len(H) + 1) if k >= len(H) else '')
        nxt = fill + [(name, function(name, args, doc, body))]
        if render(header, tested + nxt).count('\n') > lines + 5:
            break
        fill, k = nxt, k + 1
    h = len(fill) // 2
    src = render(header, [tested[0]] + fill[:h] + [tested[1]] + fill[h:] + [tested[2]])
    if not solve and abs(src.count('\n') - lines) > 5:
        raise SystemExit(f'--lines {lines} too small for module {i}')
    names = [(f'{mm} {name} {c["does"]}', kind) for (c, kind), (name, _) in zip(picked, tested)]
    test = ("'use strict';\nconst test = require('node:test');\n"
            "const assert = require('node:assert');\n"
            f"const {{ {', '.join(n for n, _ in tested)} }} = require('../src/{stem}');\n")
    for (c, _), (name, _), (title, _) in zip(picked, tested, names):
        body = indent(c['test'].replace('@', name))
        test += f'\ntest({json.dumps(title)}, () => {{\n{body}\n}});\n'
    return stem, src, test, names


def generate(out, manifest, modules=24, lines=220, solve=False):
    """Write the fixture under out/longfix and the manifest; return the manifest dict.
    solve=True is the test aid described in the module docstring."""
    if not 1 <= modules <= 99:
        raise SystemExit('--modules must be 1..99')
    if lines > MAX_LINES:
        raise SystemExit(f'--lines must be <= {MAX_LINES}')
    root = os.path.join(out, 'longfix')
    if os.path.isdir(root) and os.listdir(root):
        raise SystemExit(f'refusing to write into non-empty {root}')
    if os.path.normcase(os.path.abspath(manifest)).startswith(
            os.path.normcase(os.path.abspath(root)) + os.sep):
        raise SystemExit('the manifest must be outside the fixture tree')
    files, tests = {}, []
    for i in range(1, modules + 1):
        stem, src, test, names = module(i, lines, solve)
        tf = f'longfix/test/{stem}.test.js'
        files[f'longfix/src/{stem}.js'], files[tf] = src, test
        tests += [dict(name=name, module=f'm{i:02d}', file=tf, kind=kind,
                       expect_before='fail' if kind == 'bug' else 'pass')
                  for name, kind in names]
    requires = ''.join(f"require('./{p[len('longfix/test/'):]}');\n"
                       for p in sorted(files) if p.startswith('longfix/test/'))
    files['longfix/test/all.test.js'] = "'use strict';\nError.stackTraceLimit = 0;\n" + requires
    whole, listing = hashlib.sha256(), []
    for path in sorted(files):
        data = files[path].encode('ascii')
        whole.update(path.encode('ascii') + b'\0' + data + b'\0')
        listing.append(dict(path=path, sha256=hashlib.sha256(data).hexdigest(),
                            lines=data.count(b'\n')))
        os.makedirs(os.path.dirname(os.path.join(out, path)), exist_ok=True)
        with open(os.path.join(out, path), 'wb') as f:
            f.write(data)
    doc = dict(generator=dict(version=VERSION, modules=modules, lines=lines,
                              catalog_version=CATALOG_VERSION),
               fixture_sha256=whole.hexdigest(), files=listing, tests=tests)
    with open(manifest, 'wb') as f:
        f.write((json.dumps(doc, indent=1) + '\n').encode('ascii'))
    return doc


def main(argv=None):
    p = argparse.ArgumentParser(description='Generate the bench/ladder long-fix fixture.')
    p.add_argument('--out', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--modules', type=int, default=24)
    p.add_argument('--lines', type=int, default=220)
    a = p.parse_args(argv)
    doc = generate(a.out, a.manifest, a.modules, a.lines)
    print(f"{len(doc['files'])} files, {len(doc['tests'])} tests, "
          f"fixture_sha256 {doc['fixture_sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
