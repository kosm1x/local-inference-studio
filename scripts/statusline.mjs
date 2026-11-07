// Status line of a lis-web container session (ledger W-15). claude-local.ps1 -LisWeb sets
// statusLine to `node /lis/scripts/statusline.mjs`; Claude Code pipes the session JSON on
// stdin and shows the one line printed. Format: `lis-web  <model> | ctx:<used>% | left:<n>`
// (left: remaining_percentage as %, else context_window_size minus the used share, in k
// tokens); a missing field drops its part, and an object with no fields prints the prefix
// only. A status line must never fail: non-object or broken input prints nothing and exits
// 0. No colour, no dependencies.
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
// C0 and C1 controls (ESC and the one-byte CSI U+009B included), line and paragraph
// separators and bidi controls become spaces: one plain line, no reordering.
const plain = (s) =>
  s.replace(/[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]/g, ' ')
    .trim();

function line(raw) {
  let d;
  try {
    d = JSON.parse(raw);
  } catch {
    return '';
  }
  if (!d || typeof d !== 'object' || Array.isArray(d)) return '';
  const cw = d.context_window && typeof d.context_window === 'object' ? d.context_window : {};
  const parts = [];
  const model = d.model && typeof d.model === 'object' ? d.model : {};
  const name = typeof model.display_name === 'string' ? plain(model.display_name) : '';
  if (name) parts.push(name);
  const used = num(cw.used_percentage);
  if (used !== null) parts.push(`ctx:${Math.round(used)}%`);
  const left = num(cw.remaining_percentage);
  const size = num(cw.context_window_size);
  if (left !== null) parts.push(`left:${Math.round(left)}%`);
  else if (size !== null && used !== null) {
    parts.push(`left:${Math.round((size * (100 - used)) / 100000)}k`);
  }
  return parts.length ? `lis-web  ${parts.join(' | ')}` : 'lis-web';
}

let raw = '';
process.stdout.on('error', () => {});
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => {
  raw += c;
});
process.stdin.on('end', () => {
  try {
    const out = line(raw);
    if (out) process.stdout.write(out + '\n');
  } catch {
    // never fail the status line
  }
});
