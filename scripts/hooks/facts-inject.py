"""facts-inject: SessionStart hook (matcher compact) that puts the longrun facts file back
into context after each compaction (audit ledger T-9).

scripts/claude-local.ps1 -LisTask longrun sets LIS_FACTS_FILE (the facts file name) and
LIS_FACTS_INJECT_LOG (a log path) and registers this hook. The name is resolved against
the stdin `cwd` field when it is a non-empty string, then against the process cwd; the
first regular file found is used. When it injects, stdout is one JSON object,
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <text>}},
where <text> is a header line naming the file and then its content. Otherwise there is
no output: stdin that is not a JSON object (reason input), LIS_FACTS_FILE unset (unset),
no such file (missing), an empty one (empty), or a last line that alone exceeds the cap
(oversize).

Cap: the hooks reference says "If a value exceeds 10,000 characters, Claude Code writes
the text to a file in the session directory and passes Claude the file path with a
preview of up to the first 2,000 characters instead." The content is capped at CAP_UNITS
UTF-16 code units (the limit may be a JavaScript string length, where a character outside
the BMP counts 2), keeping the last whole lines: the file is append-only and its last
NEXT line is the current resume point. The header says when lines were left out.

Every run appends one line to LIS_FACTS_INJECT_LOG when it is set (after the output):
  <UTC ISO time> source=<source or trigger> facts=<name or -> injected=yes lines=<n>
      bytes=<n> truncated=yes|no                                      (one line)
  <UTC ISO time> source=<source or trigger> facts=<name or -> injected=no reason=<reason>
lines and bytes are those of the whole file; reason is input, unset, missing, empty,
oversize or error. bench/ladder/longrun.py reads the k-th line as the k-th compaction.
Any error gives exit 0 (a hook failure must not block the session). Stdlib only, run with
`python -I`. ASCII only.
"""
import datetime
import json
import os
import re
import sys

CAP_UNITS = 9000       # content UTF-16 units; header + content stay under Claude Code's 10,000
MAX_INPUT = 1_000_000  # stdin bytes read; more is malformed input
# The header's start; bench/ladder/longrun.py finds it in the transcript (CONTEXT_HEADER).
HEADER = 'The longrun facts file {} in the working directory holds the lines below'


def units(s):
    return len(s.encode('utf-16-le', errors='surrogatepass')) // 2


def find(name, data):
    dirs = [data['cwd']] if isinstance(data.get('cwd'), str) and data['cwd'] else []
    dirs.append(os.getcwd())
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def cap(text):
    """(kept text, truncated): the last whole lines that fit in CAP_UNITS ('' when the
    last line alone does not fit)."""
    if units(text) <= CAP_UNITS:
        return text, False
    kept, size = [], 0
    for line in reversed(text.splitlines(keepends=True)):
        size += units(line)
        if size > CAP_UNITS:
            break
        kept.append(line)
    return ''.join(reversed(kept)), True


def inject(raw_in):
    """(stdin data, facts basename or None, log fields after 'injected=', stdout or None)."""
    try:
        data = json.loads(raw_in.decode('utf-8-sig', errors='replace')) \
            if len(raw_in) <= MAX_INPUT else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {}, None, 'no reason=input', None
    name = os.environ.get('LIS_FACTS_FILE')
    if not name:
        return data, None, 'no reason=unset', None
    base = os.path.basename(name)
    path = find(name, data)
    if path is None:
        return data, base, 'no reason=missing', None
    with open(path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8-sig', errors='replace')
    if not text.strip():
        return data, base, 'no reason=empty', None
    kept, cut = cap(text)
    if not kept:
        return data, base, 'no reason=oversize', None
    n = len(text.splitlines())
    head = (HEADER.format(base)
            + f' ({n} lines, {len(raw)} bytes), as written before this compaction.')
    if cut:
        head += (f' Only its last {len(kept.splitlines())} lines fit here; the first lines '
                 'are in the file.')
    out = {'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                  'additionalContext': head + '\n' + kept}}
    fields = f'yes lines={n} bytes={len(raw)} truncated={"yes" if cut else "no"}'
    return data, base, fields, json.dumps(out) + '\n'


def word(v, default):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(v))[:64] if v else default


def main():
    data, base, fields = {}, None, 'no reason=error'
    try:
        data, base, fields, out = inject(sys.stdin.buffer.read(MAX_INPUT + 1))
        if out:
            sys.stdout.write(out)
            sys.stdout.flush()
    finally:
        log = os.environ.get('LIS_FACTS_INJECT_LOG')
        if log:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
            src = word(data.get('source') or data.get('trigger'), 'unknown')
            with open(log, 'a', encoding='utf-8', newline='\n') as f:
                f.write(f'{now} source={src} facts={word(base, "-")} injected={fields}\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
