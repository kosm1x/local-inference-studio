// The lis-web MCP server: registration (over real stdio and in memory), the credential
// refusal, the call log and the source rules. fetch is mocked; no test reaches the network.
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createServer, logLine, REFUSAL, TOOLS } from '../server.mjs';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const NAMES = ['exa_search', 'jina_search', 'web_read', 'web_read_tweet', 'web_search'];
const KEYS = ['BRAVE_SEARCH_API_KEY', 'EXA_API_KEY', 'JINA_API_KEY'];
const realFetch = globalThis.fetch;
const rep = (c, n) => c.repeat(n);
// Credential-shaped strings, one per pattern, built at run time.
const SECRETS = [
  `hf_${rep('a', 30)}`, `sk-${rep('a', 24)}`, `ghp_${rep('a', 24)}`,
  `github_pat_${rep('a', 24)}`, `AKIA${rep('A', 16)}`, `xoxb-${rep('1', 12)}`,
  `eyJ${rep('a', 24)}.${rep('b', 12)}`, `BeArEr ${rep('a', 24)}`,
];
const saved = {};
let fetches;
let client;
let logDir;
let logFile;

async function connect() {
  const [clientT, serverT] = InMemoryTransport.createLinkedPair();
  await createServer().connect(serverT);
  const c = new Client({ name: 'test', version: '0.0.0' });
  await c.connect(clientT);
  return c;
}

const textOf = (res) => res.content[0].text;
const logLines = () =>
  existsSync(logFile) ? readFileSync(logFile, 'utf8').trim().split('\n') : [];

beforeEach(async () => {
  for (const k of [...KEYS, 'LIS_WEB_LOG']) saved[k] = process.env[k];
  for (const k of KEYS) delete process.env[k];
  logDir = mkdtempSync(join(tmpdir(), 'lis-web-test-'));
  logFile = join(logDir, 'web-calls.log');
  process.env.LIS_WEB_LOG = logFile;
  fetches = [];
  globalThis.fetch = async (url) => {
    fetches.push(String(url));
    return new Response('# Page\n\nhello', { status: 200 });
  };
  client = await connect();
});

afterEach(async () => {
  await client.close();
  globalThis.fetch = realFetch;
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  rmSync(logDir, { recursive: true, force: true });
});

describe('registration', () => {
  it('server.mjs over stdio lists exactly the five tools and answers a keyless call',
    async () => {
      const env = { ...process.env };
      for (const k of [...KEYS, 'LIS_WEB_LOG']) delete env[k];
      const t = new StdioClientTransport({
        command: process.execPath, args: [join(WEB, 'server.mjs')], env, stderr: 'pipe',
      });
      let stderr = '';
      t.stderr.on('data', (d) => { stderr += d; });
      const c = new Client({ name: 'stdio-test', version: '0.0.0' });
      await c.connect(t);
      try {
        assert.equal(c.getServerVersion().name, 'lis-web');
        const { tools } = await c.listTools();
        assert.deepEqual(tools.map((x) => x.name).sort(), NAMES);
        const res = await c.callTool({ name: 'exa_search', arguments: { query: 'q' } });
        assert.equal(res.isError, true);
        assert.match(textOf(res), /EXA_API_KEY not configured/);
      } finally {
        await c.close();
      }
      assert.match(stderr, /lis-web: keys present: none; missing: BRAVE_SEARCH_API_KEY, /);
    });

  it('each listed tool keeps its description, required arguments and properties', async () => {
    const listed = (await client.listTools()).tools;
    assert.deepEqual(listed.map((x) => x.name).sort(), NAMES);
    for (const tool of TOOLS) {
      const l = listed.find((x) => x.name === tool.name);
      assert.equal(l.description, tool.description);
      assert.equal(l.inputSchema.type, 'object');
      assert.deepEqual([...(l.inputSchema.required ?? [])].sort(),
        [...tool.parameters.required].sort());
      assert.deepEqual(Object.keys(l.inputSchema.properties).sort(),
        Object.keys(tool.parameters.properties).sort());
      assert.deepEqual(l.annotations, tool.annotations);
      assert.doesNotMatch(tool.description, /jarvis|gdocs|browser__|user_fact/i);
    }
  });
});

describe('credential refusal (a speed bump, not a guarantee)', () => {
  for (const s of SECRETS) {
    it(`refuses ${s.slice(0, 6)}... before the tool runs, logged as refused`, async () => {
      const res = await client.callTool({ name: 'web_read',
        arguments: { url: `https://example.com/?k=${s}` } });
      assert.equal(res.isError, true);
      assert.equal(textOf(res), REFUSAL);
      assert.equal(fetches.length, 0);
      const lines = logLines();
      assert.equal(lines.length, 1);
      assert.match(lines[0], / web_read refused bytes=\d+ url_host=example\.com$/);
      assert.ok(!lines[0].includes(s));
    });
  }

  it('refuses an argument over 2,000 chars, and a secret in the query', async () => {
    const long = await client.callTool({ name: 'web_read',
      arguments: { url: `https://example.com/${rep('a', 2001)}` } });
    assert.equal(textOf(long), REFUSAL);
    const q = await client.callTool({ name: 'jina_search',
      arguments: { query: `find ${SECRETS[1]}` } });
    assert.equal(textOf(q), REFUSAL);
    assert.equal(fetches.length, 0);
  });
});

describe('call log (LIS_WEB_LOG)', () => {
  it('one line per call: ISO time, tool, outcome, bytes, url host', async () => {
    const res = await client.callTool({ name: 'web_read',
      arguments: { url: 'https://example.com/a?b=c' } });
    assert.equal(res.isError, undefined);
    const lines = logLines();
    assert.equal(lines.length, 1);
    const bytes = Buffer.byteLength(textOf(res));
    assert.match(lines[0], new RegExp(
      `^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d\\.\\d{3}Z web_read ok bytes=${bytes} ` +
      'url_host=example\\.com$'));
  });

  it('an error result is logged as error; the query is redacted and cut to 80', async () => {
    const query = `${SECRETS[0]} ` + rep('q', 200);
    const line = logLine('web_search', 'error', 'xyz', { query }, new Date(0));
    assert.equal(line, `1970-01-01T00:00:00.000Z web_search error bytes=3 query=` +
      JSON.stringify(`[redacted] ${rep('q', 200)}`.slice(0, 80)));
    const res = await client.callTool({ name: 'web_search', arguments: { query: 'lis' } });
    assert.equal(res.isError, true);
    assert.match(logLines()[0], / web_search error bytes=\d+ query="lis"$/);
  });

  it('no line and no stderr fallback when LIS_WEB_LOG is unset', async () => {
    delete process.env.LIS_WEB_LOG;
    const write = process.stderr.write;
    let err = '';
    process.stderr.write = (chunk, ...rest) => {
      err += chunk;
      return write.call(process.stderr, chunk, ...rest);
    };
    try {
      await client.callTool({ name: 'web_read', arguments: { url: 'https://example.com/' } });
    } finally {
      process.stderr.write = write;
    }
    assert.equal(existsSync(logFile), false);
    assert.doesNotMatch(err, /web_read ok/);
  });

  it('an exa_search HTTP error reaches neither the result nor the log with the key',
    async () => {
      const key = `exa-${'z'.repeat(20)}-${process.pid}`; // built at run time
      process.env.EXA_API_KEY = key;
      globalThis.fetch = async (url) => {
        fetches.push(String(url));
        return new Response('denied', { status: 401 });
      };
      const res = await client.callTool({ name: 'exa_search', arguments: { query: 'lis' } });
      assert.equal(res.isError, true);
      assert.match(textOf(res), /Exa API error: 401 denied/);
      const log = readFileSync(logFile, 'utf8');
      assert.match(log, / exa_search error bytes=\d+ query="lis"\n$/);
      for (const s of [textOf(res), log]) assert.ok(!s.includes('z'.repeat(20)));
    });

  it('a key value never reaches the result or the log', async () => {
    process.env.JINA_API_KEY = 'test-secret-value-1234';
    const res = await client.callTool({ name: 'web_read',
      arguments: { url: 'https://example.com/' } });
    assert.ok(!textOf(res).includes('test-secret-value-1234'));
    assert.ok(!readFileSync(logFile, 'utf8').includes('test-secret-value-1234'));
  });
});

describe('source rules', () => {
  const files = [join(WEB, 'server.mjs'), join(WEB, 'package.json'), join(WEB, 'README.md'),
    ...['tools', 'test'].flatMap((d) => readdirSync(join(WEB, d)).map((f) => join(WEB, d, f)))]
    .filter((f) => existsSync(f) && statSync(f).isFile());

  it('every file is ASCII with lines of at most 100 columns', () => {
    for (const f of files) {
      const body = readFileSync(f, 'utf8');
      assert.ok(/^[\x00-\x7f]*$/.test(body), `${f}: non-ASCII`);
      body.split('\n').forEach((l, i) => assert.ok(l.length <= 100, `${f}:${i + 1}`));
    }
  });

  it('only server.mjs touches the file system (the log append); no tool writes a file', () => {
    for (const f of files.filter((x) => x.includes(`${join(WEB, 'tools')}`))) {
      assert.doesNotMatch(readFileSync(f, 'utf8'), /node:fs|writeFile|appendFile|chdir/, f);
    }
    const server = readFileSync(join(WEB, 'server.mjs'), 'utf8');
    assert.match(server, /import \{ appendFileSync \} from 'node:fs';/);
    assert.doesNotMatch(server, /readFileSync|writeFileSync|chdir|parseEnv|dotenv/);
  });
});
