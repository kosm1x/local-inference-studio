"""Generate the bench/ladder stale-figure fixture (rung 3): a small Node CLI, tallyctl/.

Usage (from the repo root):
  python -I bench/ladder/gen_stalefig.py --out <work> --manifest <file>
Writes <work>/tallyctl/: README.md, CHANGELOG.md, package.json, bin/tally.js, src/ (six
modules and index.js) and test/all.test.js (the test command is node --test
tallyctl/test/all.test.js; every test passes). src/config.js holds three literal
constants, MAX_BATCH = 250, TIMEOUT_MS = 30000 and RETRY_LIMIT = 4, and the tests assert
them. The README's Limits table states all three, one of them wrong: MAX_BATCH 500 rows
(the planted figure; 500 appears in no other file). Its TIMEOUT_MS and RETRY_LIMIT rows
are right (current guards), and the CHANGELOG's one line about a setting, 1.2.0
"RETRY_LIMIT raised from 3 to 4", is true for that version (the historical guard). No
other line of either doc has a number, version headings (1.2.0) aside. No RNG: the output
is byte-identical on every call. The manifest (kept outside the work tree) lists files
with sha256, every test with expect_before, and every doc statement about a setting as a
figure: name, kind (planted | guard_current | guard_historical), doc_path, doc_line,
doc_value (the value the line states; for the historical line the earlier one, 3),
src_path, src_line, test_path, test_line and true_value (the code's value), lines 1-based.
fixture_sha256 = sha256 over the files sorted by path, each as path NUL bytes NUL (as
gen_longfix.py). Refuses a non-empty <work>/tallyctl and a manifest under <work>.
Stdlib only.

Because the answers live in this file, the grader's rubric_seen check (any tool input
naming bench/ladder or stalefig) also covers a model reading it.
"""
import argparse
import hashlib
import json
import os
import sys

VERSION = 1
ROOT = 'tallyctl'
TRUE = {'MAX_BATCH': 250, 'TIMEOUT_MS': 30000, 'RETRY_LIMIT': 4}

README = '''# tallyctl

tallyctl counts the records of a CSV export by one column and prints the totals.

## Usage

    node bin/tally.js <file.csv> --by <column> [--json]

The first line of the file names the columns. Rows are counted in batches; a batch that
does not finish in time is retried, and the run stops when the retries are used up.

## Limits

| Setting | Value | Meaning |
| --- | --- | --- |
| `MAX_BATCH` | 500 rows | rows counted in one batch |
| `TIMEOUT_MS` | 30000 ms | time one batch may take before it is retried |
| `RETRY_LIMIT` | 4 | retries of one batch before the run stops |

## Output

One line per value of the column, the value and its count separated by a tab, in the
order the values first appear. With `--json`, one JSON object instead.
'''

CHANGELOG = '''# Changelog

## 1.3.0

- Add the `--json` flag, which prints the totals as one JSON object.
- Skip blank lines in the input.

## 1.2.0

- `RETRY_LIMIT` raised from 3 to 4.
- Name the line of a malformed row in the error.

## 1.1.0

- Add the `--by` option, the column to count by.

## 1.0.0

- First release.
'''

PACKAGE = '''{
  "name": "tallyctl",
  "version": "1.3.0",
  "description": "Count the records of a CSV export by one column.",
  "bin": { "tally": "bin/tally.js" },
  "license": "MIT",
  "private": true
}
'''

CONFIG = r'''"use strict";

// Limits of one run: rows per batch, milliseconds per batch, retries per batch.
const MAX_BATCH = 250;
const TIMEOUT_MS = 30000;
const RETRY_LIMIT = 4;

module.exports = { MAX_BATCH, TIMEOUT_MS, RETRY_LIMIT };
'''

PARSE = r'''"use strict";

// One CSV export: a header line, then one record per line. Blank lines are skipped.
function parseCsv(text) {
  const lines = String(text).split(/\r?\n/);
  let header = null;
  const rows = [];
  lines.forEach((line, i) => {
    if (line.trim() === "") return;
    const fields = line.split(",").map((f) => f.trim());
    if (header === null) {
      header = fields;
      return;
    }
    if (fields.length !== header.length) {
      throw new Error(`line ${i + 1}: expected ${header.length} fields, got ${fields.length}`);
    }
    rows.push(fields);
  });
  if (header === null) throw new Error("no header line");
  return { header, rows };
}

module.exports = { parseCsv };
'''

BATCH = r'''"use strict";

const { MAX_BATCH } = require("./config");

// Splits rows into batches of at most size rows, in order.
function toBatches(rows, size = MAX_BATCH) {
  if (!Number.isInteger(size) || size < 1) {
    throw new RangeError("batch size must be a positive integer");
  }
  const out = [];
  for (let i = 0; i < rows.length; i += size) out.push(rows.slice(i, i + size));
  return out;
}

module.exports = { toBatches };
'''

RETRY = r'''"use strict";

const { RETRY_LIMIT } = require("./config");

// Calls fn until it resolves: once, then up to limit retries. The last error is rethrown.
async function withRetry(fn, limit = RETRY_LIMIT) {
  let last;
  for (let attempt = 0; attempt <= limit; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (err) {
      last = err;
    }
  }
  throw last;
}

module.exports = { withRetry };
'''

TIMEOUT = r'''"use strict";

const { TIMEOUT_MS } = require("./config");

// Settles as promise does, or rejects once ms milliseconds have passed.
function withTimeout(promise, ms = TIMEOUT_MS) {
  let timer;
  const expired = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms);
  });
  return Promise.race([promise, expired]).finally(() => clearTimeout(timer));
}

module.exports = { withTimeout };
'''

TALLY = r'''"use strict";

// Counts rows by the value of one column: { value: count } in first-seen order.
function tally(header, rows, column) {
  const idx = header.indexOf(column);
  if (idx < 0) throw new Error(`unknown column: ${column}`);
  const counts = {};
  for (const row of rows) {
    const key = row[idx];
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

// Adds the counts of b into a and returns a.
function merge(a, b) {
  for (const [k, n] of Object.entries(b)) a[k] = (a[k] || 0) + n;
  return a;
}

module.exports = { tally, merge };
'''

INDEX = r'''"use strict";

module.exports = {
  ...require("./config"),
  ...require("./parse"),
  ...require("./batch"),
  ...require("./retry"),
  ...require("./timeout"),
  ...require("./tally"),
};
'''

BIN = r'''#!/usr/bin/env node
"use strict";

const fs = require("fs");
const { parseCsv, toBatches, withRetry, withTimeout, tally, merge } = require("../src");

function parseArgs(argv) {
  const opts = { file: null, by: null, json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--json") opts.json = true;
    else if (a === "--by") opts.by = argv[++i];
    else if (opts.file === null) opts.file = a;
    else throw new Error(`unexpected argument: ${a}`);
  }
  if (!opts.file || !opts.by) throw new Error("usage: tally <file.csv> --by <column> [--json]");
  return opts;
}

async function run(argv, readFile = (p) => fs.promises.readFile(p, "utf8")) {
  const opts = parseArgs(argv);
  const { header, rows } = parseCsv(await readFile(opts.file));
  const totals = {};
  for (const batch of toBatches(rows)) {
    const counted = await withRetry(() => withTimeout(Promise.resolve(tally(header, batch, opts.by))));
    merge(totals, counted);
  }
  if (opts.json) return JSON.stringify(totals);
  return Object.entries(totals).map(([k, n]) => `${k}\t${n}`).join("\n");
}

if (require.main === module) {
  run(process.argv.slice(2)).then(
    (out) => console.log(out),
    (err) => {
      console.error(`tally: ${err.message}`);
      process.exitCode = 1;
    },
  );
}

module.exports = { parseArgs, run };
'''

TEST = r'''"use strict";

const test = require("node:test");
const assert = require("node:assert");
const config = require("../src/config");
const { parseCsv, toBatches, withRetry, withTimeout, tally, merge } = require("../src");
const { parseArgs, run } = require("../bin/tally");

test("config: MAX_BATCH", () => {
  assert.strictEqual(config.MAX_BATCH, 250);
});

test("config: TIMEOUT_MS", () => {
  assert.strictEqual(config.TIMEOUT_MS, 30000);
});

test("config: RETRY_LIMIT", () => {
  assert.strictEqual(config.RETRY_LIMIT, 4);
});

test("parseCsv reads the header and the rows, skipping blank lines", () => {
  const { header, rows } = parseCsv("a,b\n1,2\n\n3,4\n");
  assert.deepStrictEqual(header, ["a", "b"]);
  assert.deepStrictEqual(rows, [["1", "2"], ["3", "4"]]);
});

test("parseCsv names the line of a malformed row", () => {
  assert.throws(() => parseCsv("a,b\n1,2\n3\n"), /line 3/);
});

test("toBatches splits rows in order and keeps the remainder", () => {
  const rows = Array.from({ length: 600 }, (_, i) => i);
  assert.deepStrictEqual(toBatches(rows).map((b) => b.length), [250, 250, 100]);
  assert.deepStrictEqual(toBatches([1, 2, 3], 2), [[1, 2], [3]]);
  assert.throws(() => toBatches([1], 0), RangeError);
});

test("withRetry calls once plus RETRY_LIMIT retries, then rethrows", async () => {
  let calls = 0;
  const fail = async () => {
    calls += 1;
    throw new Error("down");
  };
  await assert.rejects(withRetry(fail), /down/);
  assert.strictEqual(calls, config.RETRY_LIMIT + 1);
});

test("withRetry returns the first success", async () => {
  const seen = [];
  const out = await withRetry(async (n) => {
    seen.push(n);
    if (n < 2) throw new Error("not yet");
    return "ok";
  });
  assert.strictEqual(out, "ok");
  assert.deepStrictEqual(seen, [0, 1, 2]);
});

test("withTimeout passes a fast result through and rejects a slow one", async () => {
  assert.strictEqual(await withTimeout(Promise.resolve(7), 50), 7);
  await assert.rejects(withTimeout(new Promise(() => {}), 10), /timed out after 10 ms/);
});

test("tally counts rows by one column and merge adds counts", () => {
  const counts = tally(["k", "v"], [["a", "1"], ["b", "2"], ["a", "3"]], "k");
  assert.deepStrictEqual(counts, { a: 2, b: 1 });
  assert.deepStrictEqual(merge({ a: 1 }, { a: 2, c: 1 }), { a: 3, c: 1 });
  assert.throws(() => tally(["k"], [], "x"), /unknown column/);
});

test("run prints the totals, or one JSON object with --json", async () => {
  const read = async () => "k,v\na,1\nb,2\na,3\n";
  assert.strictEqual(await run(["in.csv", "--by", "k"], read), "a\t2\nb\t1");
  assert.strictEqual(await run(["in.csv", "--by", "k", "--json"], read), '{"a":2,"b":1}');
  assert.throws(() => parseArgs(["in.csv"]), /usage/);
});
'''

FILES = {
    'README.md': README, 'CHANGELOG.md': CHANGELOG, 'package.json': PACKAGE,
    'bin/tally.js': BIN, 'src/config.js': CONFIG, 'src/parse.js': PARSE,
    'src/batch.js': BATCH, 'src/retry.js': RETRY, 'src/timeout.js': TIMEOUT,
    'src/tally.js': TALLY, 'src/index.js': INDEX, 'test/all.test.js': TEST,
}
DOCS = ('README.md', 'CHANGELOG.md')
# name, kind, doc file, the doc line's marker, doc_value
FIGURES = (
    ('MAX_BATCH', 'planted', 'README.md', '| `MAX_BATCH` |', 500),
    ('TIMEOUT_MS', 'guard_current', 'README.md', '| `TIMEOUT_MS` |', 30000),
    ('RETRY_LIMIT', 'guard_current', 'README.md', '| `RETRY_LIMIT` |', 4),
    ('RETRY_LIMIT', 'guard_historical', 'CHANGELOG.md', '`RETRY_LIMIT` raised from 3 to 4', 3),
)


def line_of(text, marker):
    """1-based number of the one line containing marker."""
    hits = [i for i, ln in enumerate(text.split('\n'), 1) if marker in ln]
    if len(hits) != 1:
        raise SystemExit(f'generator bug: {marker!r} is on {len(hits)} lines')
    return hits[0]


def test_names():
    """The test() names of all.test.js, in order."""
    return [ln.split('"')[1] for ln in TEST.split('\n') if ln.startswith('test("')]


def figures():
    out = []
    for name, kind, doc, marker, value in FIGURES:
        out.append(dict(
            name=name, kind=kind, doc_path=f'{ROOT}/{doc}',
            doc_line=line_of(FILES[doc], marker), doc_value=value,
            src_path=f'{ROOT}/src/config.js',
            src_line=line_of(CONFIG, f'const {name} = {TRUE[name]};'),
            test_path=f'{ROOT}/test/all.test.js',
            test_line=line_of(TEST, f'assert.strictEqual(config.{name}, {TRUE[name]});'),
            true_value=TRUE[name]))
    return out


def generate(out, manifest):
    """Write the fixture under out/tallyctl and the manifest; return the manifest dict."""
    root = os.path.join(out, ROOT)
    if os.path.isdir(root) and os.listdir(root):
        raise SystemExit(f'refusing to write into non-empty {root}')
    # Anywhere under out (out itself included), not only under the fixture root; realpath,
    # so a symlink or junction into out is refused too.
    m, o = (os.path.normcase(os.path.realpath(p)) for p in (manifest, out))
    if m == o or m.startswith(o.rstrip(os.sep) + os.sep):
        raise SystemExit('the manifest must be outside --out')
    files = {f'{ROOT}/{p}': text for p, text in FILES.items()}
    whole, listing = hashlib.sha256(), []
    for path in sorted(files):
        data = files[path].encode('ascii')
        whole.update(path.encode('ascii') + b'\0' + data + b'\0')
        listing.append(dict(path=path, sha256=hashlib.sha256(data).hexdigest(),
                            lines=data.count(b'\n')))
        os.makedirs(os.path.dirname(os.path.join(out, path)), exist_ok=True)
        with open(os.path.join(out, path), 'wb') as f:
            f.write(data)
    doc = dict(generator=dict(version=VERSION), fixture_sha256=whole.hexdigest(),
               files=listing,
               tests=[dict(name=n, file=f'{ROOT}/test/all.test.js', expect_before='pass')
                      for n in test_names()],
               figures=figures())
    with open(manifest, 'wb') as f:
        f.write((json.dumps(doc, indent=1) + '\n').encode('ascii'))
    return doc


def main(argv=None):
    p = argparse.ArgumentParser(description='Generate the bench/ladder stale-figure fixture.')
    p.add_argument('--out', required=True)
    p.add_argument('--manifest', required=True)
    a = p.parse_args(argv)
    doc = generate(a.out, a.manifest)
    print(f"{len(doc['files'])} files, {len(doc['tests'])} tests, "
          f"{len(doc['figures'])} figures, fixture_sha256 {doc['fixture_sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
