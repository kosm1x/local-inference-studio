"""Measure Claude Code auto-compaction from a bench/compact capture.

Usage (from the repo root):
  python -I bench/compact/analyze.py <capture.jsonl> [--result <result.json>]
      [--transcript <transcript.jsonl>]

A compaction request is a /v1/messages request whose last user message or system text
carries one of MARKERS (or both "summary" and "<analysis>"). Claude Code accepts a
summary when the FIRST text block of the response has non-empty trimmed text; otherwise
it reports "summarization produced empty response". This script applies that same test.
Exit code is always 0: this is a measurement, not a gate.
"""
import argparse
import json
import sys

MARKERS = ("CRITICAL: Respond with TEXT ONLY", "Do NOT call any tools")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def marker_of(req):
    msgs = [m for m in req.get("messages") or [] if isinstance(m, dict)]
    users = [m for m in msgs if m.get("role") == "user"]
    last_user = text_of(users[-1].get("content")) if users else ""
    system = text_of(req.get("system"))
    for where, text in (("last-user", last_user), ("system", system)):
        for m in MARKERS:
            if m in text:
                return f"{where}: {m}"
        if "summary" in text.lower() and "<analysis>" in text:
            return f"{where}: summary+<analysis>"
    return None


def prompt_tokens(usage):
    keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    vals = [usage.get(k) for k in keys if isinstance(usage.get(k), int)]
    return sum(vals) if vals else None


def describe(rec):
    req = rec["request"]
    resp = rec.get("response") if isinstance(rec.get("response"), dict) else {}
    blocks = [b for b in resp.get("content") or [] if isinstance(b, dict)]
    usage = resp.get("usage") or {}
    parts, thinking_len = [], 0
    for b in blocks:
        t = b.get("type")
        if t == "text":
            parts.append(f"text({len(b.get('text') or '')})")
        elif t in ("thinking", "redacted_thinking"):
            n = len(b.get("thinking") or b.get("data") or "")
            thinking_len += n
            parts.append(f"{t}({n})")
        elif t == "tool_use":
            parts.append(f"tool_use({b.get('name')})")
        else:
            parts.append(str(t))
    first_text = next((b for b in blocks if b.get("type") == "text"), None)
    text = (first_text.get("text") or "").strip() if first_text else ""
    return {
        "ts": rec.get("ts"), "status": rec.get("status"), "marker": marker_of(req),
        "response_kind": rec.get("response_kind"),
        "client_aborted": rec.get("client_aborted"),
        "req_max_tokens": req.get("max_tokens"), "req_thinking": req.get("thinking"),
        "req_output_config": req.get("output_config"),
        "req_effort": (req.get("output_config") or {}).get("effort"),
        "req_stream": req.get("stream"), "req_tools": len(req.get("tools") or []),
        "prompt_tokens": prompt_tokens(usage), "output_tokens": usage.get("output_tokens"),
        "stop_reason": resp.get("stop_reason"), "error": resp.get("error"),
        "blocks": parts, "accepted": bool(text), "thinking_len": thinking_len,
        "summary": "<summary>" in text or text.startswith("<analysis>"),
        "text_head": text[:300],
    }


def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                print(f"capture line {n}: not JSON, skipped")
    return recs


def report_capture(path):
    recs = load(path)
    calls = [r for r in recs if str(r.get("path", "")).split("?")[0] == "/v1/messages"
             and isinstance(r.get("request"), dict)]
    rows = [describe(r) for r in calls]
    peak = max((r["prompt_tokens"] for r in rows if r["prompt_tokens"]), default=None)
    print(f"capture: {len(recs)} requests, {len(calls)} /v1/messages calls, "
          f"peak prompt tokens {peak}")
    comp = [r for r in rows if r["marker"]]
    print(f"{'#':>2} {'ts':24} {'status':>6} {'prompt':>7} {'output':>6} "
          f"{'stop_reason':14} {'accepted':8} {'summary':7} {'think':>6}  blocks")
    for i, r in enumerate(comp, 1):
        print(f"{i:>2} {str(r['ts']):24} {str(r['status']):>6} {str(r['prompt_tokens']):>7} "
              f"{str(r['output_tokens']):>6} {str(r['stop_reason']):14} "
              f"{'yes' if r['accepted'] else 'NO':8} {'yes' if r['summary'] else 'NO':7} "
              f"{r['thinking_len']:>6}  "
              f"{' '.join(r['blocks']) or '(none)'}")
        print(f"   marker {r['marker']} | request max_tokens {r['req_max_tokens']}, "
              f"thinking {json.dumps(r['req_thinking'])}, "
              f"output_config {json.dumps(r['req_output_config'])}, "
              f"stream {r['req_stream']}, tools {r['req_tools']} | "
              f"response {r['response_kind']}, client_aborted {r['client_aborted']}")
        if r["error"]:
            print(f"   error: {json.dumps(r['error'])[:300]}")
        if r["text_head"]:
            print("   text: " + r["text_head"].replace("\n", " "))
    acc = sum(1 for r in comp if r["accepted"])
    shaped = sum(1 for r in comp if r["summary"])
    hits = sum(1 for r in comp if r["stop_reason"] == "max_tokens")

    def seen(key, fmt=str):
        vals = []
        for r in comp:
            v = "absent" if r[key] is None else fmt(r[key])
            if v not in vals:
                vals.append(v)
        return " / ".join(vals) or "(no compaction request)"

    # What the case env changed on the wire: compare across cases.
    print(f"effect: max_tokens {seen('req_max_tokens')}, "
          f"effort {seen('req_effort')}, thinking {seen('req_thinking', json.dumps)}")
    print(f"compaction: fired {len(comp)}, accepted {acc} (summary-shaped {shaped}), "
          f"empty {len(comp) - acc}; max_tokens hits {hits}")
    return acc


def report_result(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.lstrip().startswith("{")]
        env = json.loads(lines[-1])
    except (OSError, ValueError, IndexError) as e:
        print(f"session: result envelope unreadable ({e})")
        return
    head = str(env.get("result") or "")[:200].replace("\n", " ")
    denials = len(env.get("permission_denials") or [])
    print(f"session: is_error {env.get('is_error')}, subtype {env.get('subtype')}, "
          f"num_turns {env.get('num_turns')}, permission_denials {denials}, result: {head}")


def report_transcript(path):
    boundary = summary = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                    boundary += 1
                if e.get("isCompactSummary"):
                    summary += 1
    except OSError as e:
        print(f"transcript: unreadable ({e})")
        return None
    print(f"transcript: compact_boundary records {boundary}, "
          f"isCompactSummary records {summary}")
    return boundary


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture")
    ap.add_argument("--result", help="stdout of the -p run (--output-format json)")
    ap.add_argument("--transcript", help="session transcript .jsonl")
    a = ap.parse_args()
    acc = None
    try:
        acc = report_capture(a.capture)
    except OSError as e:
        print(f"capture: unreadable ({e})")
    if a.result:
        report_result(a.result)
    if a.transcript:
        boundary = report_transcript(a.transcript)
        if acc is not None and boundary is not None:
            print(f"consistency: accepted {acc} vs compact_boundary {boundary}"
                  f"{'' if acc == boundary else ' (MISMATCH)'}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:  # usage error or --help: argparse already printed it
        pass
    except Exception as e:  # a measurement never fails the caller
        print(f"analyze error: {e!r}", file=sys.stderr)
    sys.exit(0)
