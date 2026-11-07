// The five lis-web tools with fetch mocked (globalThis.fetch replaced): no test reaches the
// network. Run from the repo root: node --test web/test/
import assert from 'node:assert/strict';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { exaSearchTool } from '../tools/exa-search.mjs';
import { jinaSearchTool } from '../tools/jina-search.mjs';
import { webReadTweetTool } from '../tools/web-read-tweet.mjs';
import { webReadTool } from '../tools/web-read.mjs';
import { webSearchTool } from '../tools/web-search.mjs';

const KEYS = ['BRAVE_SEARCH_API_KEY', 'EXA_API_KEY', 'JINA_API_KEY'];
const realFetch = globalThis.fetch;
const realTimeout = AbortSignal.timeout;
const saved = {};
let calls;
let queue;
let timeouts;

/** Queue the responses (or errors to throw) the mocked fetch hands out in order. */
function respond(...items) {
  queue.push(...items);
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const text = (body, status = 200, statusText = '') => new Response(body, { status, statusText });
const timeoutError = () =>
  new DOMException('The operation was aborted due to timeout', 'TimeoutError');

beforeEach(() => {
  calls = [];
  queue = [];
  timeouts = [];
  for (const k of KEYS) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    const next = queue.shift();
    if (next === undefined) throw new Error('network disabled in tests');
    if (next instanceof Error || next instanceof DOMException) throw next;
    return next;
  };
  AbortSignal.timeout = (ms) => {
    timeouts.push(ms);
    return realTimeout.call(AbortSignal, ms);
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
  AbortSignal.timeout = realTimeout;
  for (const k of KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

const parse = (s) => JSON.parse(s);

describe('web_search (Brave)', () => {
  it('missing key: an error naming BRAVE_SEARCH_API_KEY, no fetch', async () => {
    const out = parse(await webSearchTool.execute({ query: 'x' }));
    assert.equal(out.error, 'BRAVE_SEARCH_API_KEY not configured');
    assert.equal(calls.length, 0);
  });

  it('happy path: one GET with the key header, a 10 s timeout and numbered results', async () => {
    process.env.BRAVE_SEARCH_API_KEY = 'test-brave';
    respond(json({
      web: { results: [
        { title: 'T1', url: 'https://a.example/1', description: 'D1', extra_snippets: ['S'] },
        { title: 'T2', url: 'https://a.example/2', description: 'D2' },
      ] },
      knowledge_graph: { title: 'K', description: 'KD' },
    }));
    const out = await webSearchTool.execute({ query: 'lis web', count: 2 });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url,
      'https://api.search.brave.com/res/v1/web/search?q=lis%20web&count=2');
    assert.equal(calls[0].init.headers['X-Subscription-Token'], 'test-brave');
    assert.ok(calls[0].init.signal instanceof AbortSignal);
    assert.deepEqual(timeouts, [10_000]);
    assert.match(out, /^\u{1F50D} \*\*"lis web"\*\* \u2014 2 results/u);
    assert.ok(out.includes('\n> S\n'));
    assert.ok(out.includes('**K**: KD'));
    assert.ok(out.includes('1. **T1**\n   https://a.example/1\n   D1'));
    assert.ok(out.includes('2. **T2**\n   https://a.example/2\n   D2'));
  });

  it('count is clamped to 1-10', async () => {
    process.env.BRAVE_SEARCH_API_KEY = 'test-brave';
    respond(json({}), json({}));
    await webSearchTool.execute({ query: 'x', count: 50 });
    await webSearchTool.execute({ query: 'x', count: 0 });
    assert.ok(calls[0].url.endsWith('&count=10'));
    assert.ok(calls[1].url.endsWith('&count=1'));
  });

  it('HTTP error and timeout: error JSON, never a throw', async () => {
    process.env.BRAVE_SEARCH_API_KEY = 'test-brave';
    respond(text('quota', 429), timeoutError());
    assert.equal(parse(await webSearchTool.execute({ query: 'x' })).error,
      'Brave Search API error: 429 quota');
    assert.match(parse(await webSearchTool.execute({ query: 'x' })).error,
      /^Search failed: The operation was aborted due to timeout$/);
  });
});

describe('exa_search', () => {
  it('missing key: an error naming EXA_API_KEY, no fetch', async () => {
    assert.match(parse(await exaSearchTool.execute({ query: 'x' })).error, /^EXA_API_KEY /);
    assert.equal(calls.length, 0);
  });

  it('happy path: one POST with the key, 15 s timeout, the result JSON', async () => {
    process.env.EXA_API_KEY = 'test-exa';
    respond(json({ results: [{ title: 'T', url: 'https://e.example', score: 0.876, text: 'b' }] }));
    const out = parse(await exaSearchTool.execute({
      query: 'q', category: 'news', include_text: true, num_results: 3,
    }));
    assert.equal(calls[0].url, 'https://api.exa.ai/search');
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.headers['x-api-key'], 'test-exa');
    assert.deepEqual(timeouts, [15_000]);
    assert.deepEqual(parse(calls[0].init.body), {
      query: 'q', num_results: 3, use_autoprompt: true, category: 'news',
      contents: { text: { max_characters: 3000 } },
    });
    assert.deepEqual(out, {
      query: 'q', category: 'news', total: 1,
      results: [{ title: 'T', url: 'https://e.example', published_date: null, author: null,
        score: 0.88, text: 'b' }],
    });
  });

  it('HTTP error: the status and body excerpt, never the key', async () => {
    const key = `exa-${'k'.repeat(20)}-${process.pid}`; // built at run time
    process.env.EXA_API_KEY = key;
    respond(text('invalid api key', 401));
    const out = await exaSearchTool.execute({ query: 'q' });
    assert.match(parse(out).error, /^Exa API error: 401 invalid api key/);
    assert.ok(!out.includes(key) && !out.includes('k'.repeat(20)));
  });

  it('timeout: error JSON', async () => {
    process.env.EXA_API_KEY = 'test-exa';
    respond(timeoutError());
    assert.match(parse(await exaSearchTool.execute({ query: 'q' })).error,
      /^Exa search failed: .*timeout/);
  });
});

describe('jina_search', () => {
  it('missing key: an error naming JINA_API_KEY, no fetch', async () => {
    assert.match(parse(await jinaSearchTool.execute({ query: 'xy' })).error, /^JINA_API_KEY /);
    assert.equal(calls.length, 0);
  });

  it('defaults: num 5, page 1, no-content, Bearer, 15 s timeout', async () => {
    process.env.JINA_API_KEY = 'test-jina';
    respond(json({ data: [{ title: 'T', url: 'https://j.example', description: 'D' }],
      usage: { tokens: 10000 } }));
    const out = parse(await jinaSearchTool.execute({ query: 'lis' }));
    assert.equal(calls[0].url, 'https://s.jina.ai/?q=lis&num=5&page=1');
    assert.equal(calls[0].init.headers.Authorization, 'Bearer test-jina');
    assert.equal(calls[0].init.headers['X-Respond-With'], 'no-content');
    assert.deepEqual(timeouts, [15_000]);
    assert.deepEqual(out, { query: 'lis', results: [{ title: 'T', url: 'https://j.example',
      description: 'D' }], count: 1, page: 1, tokens_used: 10000 });
  });

  it('site: a hostname is passed on; anything else is refused before any fetch', async () => {
    process.env.JINA_API_KEY = 'test-jina';
    respond(json({ data: [] }));
    await jinaSearchTool.execute({ query: 'lis', site: 'docs.example.com' });
    assert.equal(calls[0].url, 'https://s.jina.ai/?q=lis&num=5&page=1&site=docs.example.com');
    for (const site of ['example', 'exa mple.com', 'example.com/path', 'http://example.com',
      'example.com\nX-Evil: 1', 'example.c0m', 5, '']) {
      const out = parse(await jinaSearchTool.execute({ query: 'lis', site }));
      assert.match(out.error, /^site must be a hostname/, JSON.stringify(site));
    }
    assert.equal(calls.length, 1);
  });

  it('size cap: with_content bodies <= 1,500 and the whole JSON <= 5,000, no file path',
    async () => {
      process.env.JINA_API_KEY = 'test-jina';
      const rows = Array.from({ length: 10 }, (_, i) => ({
        title: `T${i}`, url: `https://j.example/${i}`, content: 'c'.repeat(4000) }));
      respond(json({ data: rows }));
      const raw = await jinaSearchTool.execute({ query: 'lis', with_content: true });
      const out = parse(raw);
      assert.ok(raw.length <= 5000, String(raw.length));
      assert.equal(out.truncated, true);
      assert.equal(out.full_content_path, undefined);
      assert.ok(out.results.length > 0);
      assert.ok(out.results.every((r) => r.content.length <= 1500 && r.content.length >= 200));
      assert.equal(calls[0].init.headers['X-Respond-With'], undefined);
    });

  it('402 carries the key hint; timeout is an error JSON', async () => {
    process.env.JINA_API_KEY = 'test-jina';
    respond(json({ readableMessage: 'out of tokens' }, 402), timeoutError());
    const out = parse(await jinaSearchTool.execute({ query: 'lis' }));
    assert.match(out.error, /^Jina search failed: 402 .*out of tokens/);
    assert.match(out.hint, /key invalid/);
    assert.match(parse(await jinaSearchTool.execute({ query: 'lis' })).error,
      /^Jina search failed: .*timeout/);
  });
});

describe('web_read (r.jina.ai)', () => {
  it('keyless happy path: one GET through r.jina.ai, no Authorization, 15 s timeout',
    async () => {
      respond(text('# Example\n\nbody'));
      const out = parse(await webReadTool.execute({ url: 'https://example.com/' }));
      assert.equal(calls.length, 1);
      assert.equal(calls[0].url, 'https://r.jina.ai/https://example.com/');
      assert.deepEqual(calls[0].init.headers, { Accept: 'text/markdown' });
      assert.ok(calls[0].init.signal instanceof AbortSignal);
      assert.deepEqual(timeouts, [15_000]);
      assert.deepEqual(out, { url: 'https://example.com/', content: '# Example\n\nbody',
        chars: 15, truncated: false });
    });

  it('with JINA_API_KEY: Bearer header; timeout_s 30 widens the local abort to 35 s',
    async () => {
      process.env.JINA_API_KEY = 'test-jina';
      respond(text('ok'));
      await webReadTool.execute({ url: 'https://example.com/', timeout_s: 30 });
      assert.equal(calls[0].init.headers.Authorization, 'Bearer test-jina');
      assert.equal(calls[0].init.headers['X-Timeout'], '30');
      assert.deepEqual(timeouts, [35_000]);
    });

  it('size cap: a 12,000-char page returns its first 5,000 chars, truncated, no file',
    async () => {
      const page = '# H1\n' + 'a'.repeat(12_000 - 5);
      respond(text(page));
      const out = parse(await webReadTool.execute({ url: 'https://example.com/' }));
      assert.equal(out.chars, 12_000);
      assert.equal(out.truncated, true);
      assert.equal(out.full_content_path, undefined);
      assert.ok(out.content.startsWith(page.slice(0, 5000) + '\n\n--- DOCUMENT TRUNCATED'));
      assert.ok(out.content.length < 5400, String(out.content.length));
    });

  it('a Cloudflare 403 returns the error: no retry, no browser', async () => {
    respond(text('<title>Just a moment...</title>', 403, 'Forbidden'));
    const out = parse(await webReadTool.execute({ url: 'https://cf.example/' }));
    assert.match(out.error, /^Cloudflare-protected page: .*no browser fallback/);
    assert.equal(calls.length, 1);
  });

  it('a 200 Markdown body that is a challenge page is the same error', async () => {
    respond(text('Verify you are human'));
    const out = parse(await webReadTool.execute({ url: 'https://cf.example/' }));
    assert.match(out.error, /^Cloudflare-protected page/);
  });

  it('a non-Cloudflare 403 is retried once with no-cache and the browser engine', async () => {
    respond(text('nope', 403, 'Forbidden'), text('second try'));
    const out = parse(await webReadTool.execute({ url: 'https://example.com/' }));
    assert.equal(calls.length, 2);
    assert.equal(calls[1].init.headers['X-Engine'], 'browser');
    assert.equal(calls[1].init.headers['X-No-Cache'], 'true');
    assert.equal(calls[0].init.signal, calls[1].init.signal);
    assert.equal(out.retried, true);
    assert.equal(out.content, 'second try');
  });

  it('a 429 keeps Jina\'s reason with a hint and is not retried', async () => {
    respond(json({ readableMessage: 'slow down' }, 429));
    const out = parse(await webReadTool.execute({ url: 'https://example.com/' }));
    assert.match(out.error, /^Failed to read URL: 429 .*slow down/);
    assert.ok(out.hint && !/browser__/.test(out.hint));
    assert.equal(calls.length, 1);
  });

  it('private, loopback and non-http URLs are refused before any fetch', async () => {
    for (const url of ['http://127.0.0.1:8080/health', 'http://localhost./', 'file:///etc/passwd',
      'http://169.254.169.254/latest/meta-data', 'http://[::ffff:10.0.0.1]/', 'not a url']) {
      const out = parse(await webReadTool.execute({ url }));
      assert.ok(out.error, url);
    }
    assert.equal(calls.length, 0);
  });

  it('the CGNAT range 100.64.0.0/10 is refused; its neighbours are read', async () => {
    const cgnat = ['http://100.64.0.1/', 'http://100.100.100.200/', 'http://100.127.255.254/'];
    for (const url of cgnat) {
      assert.match(parse(await webReadTool.execute({ url })).error, /^Blocked/, url);
    }
    assert.equal(calls.length, 0);
    respond(text('a'), text('b'));
    for (const url of ['http://100.63.255.254/', 'http://100.128.0.1/']) {
      assert.ok(!parse(await webReadTool.execute({ url })).error, url);
    }
    assert.equal(calls.length, 2);
  });

  it('selectors: printable ASCII becomes the header; a line break, tab or non-ASCII character '
    + 'is refused before any fetch', async () => {
    for (const [name, v] of [['selector', 'main\r\nX-Evil: 1'], ['wait_for', 'caf\u00e9'],
      ['remove_selector', 'nav\tfooter'], ['selector', 'a\u0000b']]) {
      const out = parse(await webReadTool.execute({ url: 'https://example.com/', [name]: v }));
      assert.match(out.error, new RegExp(`^${name} must be printable ASCII`), name);
    }
    assert.equal(calls.length, 0);
    respond(text('ok'));
    await webReadTool.execute({ url: 'https://example.com/', selector: ' article > p ',
      wait_for: '#main', remove_selector: 'nav, footer' });
    assert.equal(calls[0].init.headers['X-Target-Selector'], 'article > p');
    assert.equal(calls[0].init.headers['X-Wait-For-Selector'], '#main');
    assert.equal(calls[0].init.headers['X-Remove-Selector'], 'nav, footer');
  });

  it('a PDF URL is read through Jina like any page', async () => {
    respond(text('pdf text'));
    const out = parse(await webReadTool.execute({ url: 'https://example.com/a.pdf' }));
    assert.equal(calls[0].url, 'https://r.jina.ai/https://example.com/a.pdf');
    assert.equal(out.content, 'pdf text');
  });

  it('timeout: error JSON naming the URL', async () => {
    respond(timeoutError());
    const out = parse(await webReadTool.execute({ url: 'https://example.com/' }));
    assert.match(out.error, /^Web read failed: .*timeout/);
    assert.equal(out.url, 'https://example.com/');
  });

  it('an invalid option is refused before any fetch', async () => {
    const out = parse(await webReadTool.execute({ url: 'https://example.com/', engine: 'x' }));
    assert.match(out.error, /^engine must be one of/);
    assert.equal(calls.length, 0);
  });

  it('a tweet URL is read from fxtwitter, not Jina', async () => {
    respond(json({ code: 200, tweet: { text: 'hello', author: { name: 'N', screen_name: 's' },
      url: 'https://x.com/s/status/1' } }));
    const out = parse(await webReadTool.execute({ url: 'https://x.com/s/status/1' }));
    assert.equal(calls[0].url, 'https://api.fxtwitter.com/status/1');
    assert.equal(out.source, 'fxtwitter');
    assert.ok(out.content.includes('hello'));
  });
});

describe('web_read_tweet', () => {
  it('happy path: fxtwitter, 10 s timeout, the rendered post', async () => {
    respond(json({ code: 200, tweet: { text: 'hi', author: { name: 'N', screen_name: 's' },
      created_at: 'Mon', likes: 3, url: 'https://x.com/s/status/42' } }));
    const out = parse(await webReadTweetTool.execute({ url: 'https://twitter.com/s/status/42' }));
    assert.deepEqual(timeouts, [10_000]);
    assert.equal(out.source, 'fxtwitter');
    assert.equal(out.url, 'https://twitter.com/s/status/42');
    assert.ok(out.content.startsWith('**N** (@s) \u00b7 Mon'));
    assert.ok(out.content.includes('Likes 3 \u00b7 Reposts 0 \u00b7 Replies 0'));
  });

  it('falls back to syndication, then an error when both fail (timeouts included)',
    async () => {
      respond(text('x', 500),
        json({ __typename: 'Tweet', text: 'syn', user: { screen_name: 'u' } }));
      const ok = parse(await webReadTweetTool.execute({ url: 'https://x.com/u/status/7' }));
      assert.equal(ok.source, 'syndication');
      respond(timeoutError(), timeoutError());
      const bad = parse(await webReadTweetTool.execute({ url: 'https://x.com/u/status/7' }));
      assert.match(bad.error, /^tweet could not be read/);
    });

  it('a non-status link is an error, no fetch', async () => {
    const out = parse(await webReadTweetTool.execute({ url: 'https://example.com/' }));
    assert.equal(out.error, 'url is not an X/Twitter status link');
    assert.equal(calls.length, 0);
  });
});
