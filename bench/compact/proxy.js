// Capture proxy for bench/compact: 127.0.0.1:<port> -> llama-server on 127.0.0.1:8080.
// Usage: node bench/compact/proxy.js [port=8081] [capture.jsonl]
// Every request is passed through unchanged (all headers, Authorization included, except
// accept-encoding, dropped so the captured body is plain text, and host, set to the
// upstream 127.0.0.1:8080) and the response is streamed back as it arrives. When the response ends, one JSON line is appended to the
// capture file; schema in bench/compact/README.md.
'use strict';
const http = require('node:http');
const fs = require('node:fs');

const port = Number(process.argv[2] || 8081);
const out = process.argv[3] || 'compact.capture.jsonl';
const UP_HOST = '127.0.0.1';
const UP_PORT = 8080;

function parseJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

// Rebuild the final Anthropic message from a Messages API event stream.
// Returns null if the stream has no message_start (another API or a broken stream).
function assembleSse(text) {
  let msg = null;
  for (const block of text.split(/\r?\n\r?\n/)) {
    const data = block.split(/\r?\n/).filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trimStart()).join('\n');
    if (!data || data === '[DONE]') continue;
    const ev = parseJson(data);
    if (!ev) continue;
    if (ev.type === 'message_start') { msg = { ...ev.message, content: [] }; continue; }
    if (ev.type === 'error') { msg = msg || { content: [] }; msg.error = ev.error; continue; }
    if (!msg) continue;
    const b = msg.content[ev.index];
    if (ev.type === 'content_block_start') {
      msg.content[ev.index] = { ...ev.content_block };
    } else if (ev.type === 'content_block_delta' && b) {
      const d = ev.delta || {};
      if (d.type === 'text_delta') b.text = (b.text || '') + d.text;
      else if (d.type === 'thinking_delta') b.thinking = (b.thinking || '') + d.thinking;
      else if (d.type === 'signature_delta') b.signature = (b.signature || '') + d.signature;
      else if (d.type === 'input_json_delta') b.partial_json = (b.partial_json || '') + d.partial_json;
    } else if (ev.type === 'content_block_stop' && b && b.partial_json !== undefined) {
      const input = parseJson(b.partial_json);
      if (input !== null) { b.input = input; delete b.partial_json; }
    } else if (ev.type === 'message_delta') {
      Object.assign(msg, ev.delta || {});
      msg.usage = { ...(msg.usage || {}), ...(ev.usage || {}) };
    }
  }
  if (msg && Array.isArray(msg.content)) msg.content = msg.content.filter(Boolean);
  return msg;
}

function record(entry) {
  fs.appendFileSync(out, JSON.stringify(entry) + '\n');
}

http.createServer((req, res) => {
  const t0 = Date.now();
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const reqBody = Buffer.concat(chunks);
    const reqText = reqBody.toString('utf8');
    const reqJson = reqText ? parseJson(reqText) : null;
    const base = { ts: new Date(t0).toISOString(), method: req.method, path: req.url,
      request: reqJson !== null ? reqJson : (reqText || null),
      request_kind: reqJson !== null ? 'json' : (reqText ? 'text' : 'empty') };
    const headers = { ...req.headers, host: `${UP_HOST}:${UP_PORT}` };
    delete headers['accept-encoding'];
    const up = http.request({ host: UP_HOST, port: UP_PORT, method: req.method,
      path: req.url, headers }, (ur) => {
      res.writeHead(ur.statusCode, ur.headers);
      const parts = [];
      ur.on('data', (c) => { parts.push(c); if (!clientAborted) res.write(c); });
      ur.on('end', () => res.end());
      ur.on('close', () => {
        const text = Buffer.concat(parts).toString('utf8');
        const ctype = String(ur.headers['content-type'] || '');
        let response = null;
        let kind = 'empty';
        if (ctype.includes('text/event-stream')) {
          response = assembleSse(text);
          kind = response ? 'sse-assembled' : 'sse-raw';
          if (!response) response = text;
        } else if (text) {
          response = parseJson(text);
          kind = response !== null ? 'json' : 'text';
          if (response === null) response = text;
        }
        record({ ...base, status: ur.statusCode, response_kind: kind, response,
          complete: ur.complete, client_aborted: clientAborted, duration_ms: Date.now() - t0 });
      });
    });
    // A client that hangs up (Claude Code cancelled the request) also ends the upstream
    // request, so the server stops generating as it would without the proxy.
    let clientAborted = false;
    res.on('close', () => { if (!res.writableFinished) { clientAborted = true; up.destroy(); } });
    res.on('error', () => {});
    up.on('error', (e) => {
      if (res.headersSent) return; // the response was under way: recorded on its close
      record({ ...base, status: 502, response_kind: 'proxy-error', response: String(e),
        complete: false, client_aborted: clientAborted, duration_ms: Date.now() - t0 });
      if (clientAborted) return;
      res.writeHead(502, { 'content-type': 'text/plain' });
      res.end(String(e));
    });
    up.end(reqBody);
  });
}).listen(port, '127.0.0.1', () => {
  console.log(`compact proxy 127.0.0.1:${port} -> ${UP_HOST}:${UP_PORT}, capture ${out}`);
});
