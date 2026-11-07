// lis-web: the stdio MCP server a -LisWeb session runs in the lis-web container
// (scripts/claude-local.ps1 -LisWeb). Five tools, ported from the Jarvis agent-controller's
// jarvis-web server (src/mcp/web-stdio.ts): web_search, exa_search, jina_search, web_read and
// web_read_tweet. Run: node server.mjs (stdout carries MCP protocol only).
//
// Keys come from process.env only (BRAVE_SEARCH_API_KEY, EXA_API_KEY, JINA_API_KEY); this
// process loads no key file. A missing key makes its tool return an error naming the
// variable. Every call is screened for credential-shaped argument values before the tool
// runs (a speed bump against a page that talks the model into sending a secret out, not a
// guarantee: an encoded or split secret passes) and logged as one line, with no result body,
// to the file named by LIS_WEB_LOG (no line when it is unset). Nothing else is written.
import { appendFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { errMsg } from './tools/common.mjs';
import { exaSearchTool } from './tools/exa-search.mjs';
import { jinaSearchTool } from './tools/jina-search.mjs';
import { webReadTweetTool } from './tools/web-read-tweet.mjs';
import { webReadTool } from './tools/web-read.mjs';
import { webSearchTool } from './tools/web-search.mjs';

export const TOOLS = [webSearchTool, exaSearchTool, jinaSearchTool, webReadTool, webReadTweetTool];
export const KEY_NAMES = ['BRAVE_SEARCH_API_KEY', 'EXA_API_KEY', 'JINA_API_KEY'];
export const REFUSAL = 'lis-web: argument looks like a credential; refused';
const MAX_ARG_CHARS = 2000;
const QUERY_LOG_CHARS = 80;

export const SECRET_PATTERNS = [
  /hf_[A-Za-z0-9]{20,}/,
  /sk-[A-Za-z0-9_-]{20,}/,
  /gh[pousr]_[A-Za-z0-9]{20,}/,
  /github_pat_[A-Za-z0-9_]{20,}/,
  /AKIA[0-9A-Z]{16}/,
  /xox[baprs]-[A-Za-z0-9-]{10,}/,
  /eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}/,
  /bearer\s+[A-Za-z0-9._-]{20,}/i,
];

/** True when any string in `value` (walked recursively) is credential-shaped or over 2000. */
export function looksLikeCredential(value) {
  if (typeof value === 'string') {
    return value.length > MAX_ARG_CHARS || SECRET_PATTERNS.some((re) => re.test(value));
  }
  if (Array.isArray(value)) return value.some(looksLikeCredential);
  if (value && typeof value === 'object') return Object.values(value).some(looksLikeCredential);
  return false;
}

export function redact(text) {
  return SECRET_PATTERNS.reduce(
    (s, re) => s.replace(new RegExp(re.source, `${re.flags}g`), '[redacted]'),
    text,
  );
}

/** url -> host only; query -> first 80 chars, redacted. Nothing else is logged. */
export function summarizeArgs(args) {
  const parts = [];
  if (typeof args.url === 'string') {
    let host = 'invalid-url';
    try {
      host = new URL(args.url).host || host;
    } catch {
      // keep the placeholder
    }
    parts.push(`url_host=${host}`);
  }
  if (typeof args.query === 'string') {
    parts.push(`query=${JSON.stringify(redact(args.query).slice(0, QUERY_LOG_CHARS))}`);
  }
  return parts.join(' ');
}

/** One log line: ISO time, tool, outcome (ok, error, refused), result bytes, url host, query. */
export function logLine(tool, outcome, text, args, now = new Date()) {
  const summary = summarizeArgs(args);
  return `${now.toISOString()} ${tool} ${outcome} bytes=${Buffer.byteLength(text)}` +
    (summary ? ` ${summary}` : '');
}

function logCall(tool, outcome, text, args) {
  const file = process.env.LIS_WEB_LOG;
  if (!file) return;
  try {
    appendFileSync(file, `${logLine(tool, outcome, text, args)}\n`);
  } catch (err) {
    process.stderr.write(`lis-web: log write failed: ${errMsg(err)}\n`);
  }
}

/** A tool's `{"error": "..."}` JSON return counts as an error result. */
function isErrorText(text) {
  try {
    const parsed = JSON.parse(text);
    return !!parsed && typeof parsed === 'object' && typeof parsed.error === 'string';
  } catch {
    return false;
  }
}

export function createServer(tools = TOOLS) {
  const server = new McpServer({ name: 'lis-web', version: '1.0.0' });
  for (const tool of tools) {
    server.registerTool(
      tool.name,
      {
        description: tool.description,
        inputSchema: z.fromJSONSchema(tool.parameters),
        annotations: tool.annotations,
      },
      async (input) => {
        const args = input ?? {};
        if (looksLikeCredential(args)) {
          logCall(tool.name, 'refused', REFUSAL, args);
          return { content: [{ type: 'text', text: REFUSAL }], isError: true };
        }
        let text;
        let failed;
        try {
          text = await tool.execute(args);
          failed = isErrorText(text);
        } catch (err) {
          text = errMsg(err);
          failed = true;
        }
        logCall(tool.name, failed ? 'error' : 'ok', text, args);
        return { content: [{ type: 'text', text }], ...(failed && { isError: true }) };
      },
    );
  }
  return server;
}

async function main() {
  // stdout belongs to the protocol: every console write goes to stderr.
  console.log = console.error;
  console.info = console.error;
  console.debug = console.error;
  const present = KEY_NAMES.filter((n) => process.env[n]);
  const missing = KEY_NAMES.filter((n) => !process.env[n]);
  process.stderr.write(
    `lis-web: keys present: ${present.join(', ') || 'none'}; ` +
      `missing: ${missing.join(', ') || 'none'}\n`,
  );
  await createServer().connect(new StdioServerTransport());
}

const norm = (p) => (process.platform === 'win32' ? p.toLowerCase() : p);
if (process.argv[1] && norm(resolve(process.argv[1])) === norm(fileURLToPath(import.meta.url))) {
  main().catch((err) => {
    process.stderr.write(`lis-web: fatal: ${errMsg(err)}\n`);
    process.exit(1);
  });
}
