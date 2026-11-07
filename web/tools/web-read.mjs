// web_read: any URL as Markdown through Jina Reader (r.jina.ai; keyless at 20 RPM, JINA_API_KEY
// raises the limit). Ported from the Jarvis agent-controller's
// src/tools/builtin/web-read.ts, same schema and result JSON, with three changes: no browser
// fallback (a Cloudflare challenge returns the tool's error), no local PDF extraction (a PDF
// URL is read through Jina like any page) and no eviction file (an over-cap page returns
// its first MAX_CONTENT chars, `truncated: true` and no full_content_path).
import {
  isCloudflareChallenge,
  jinaReason,
  toolError,
  truncatePreview,
  validateOutboundUrl,
} from './common.mjs';
import { parseTweetId, readTweet } from './web-read-tweet.mjs';

const JINA_PREFIX = 'https://r.jina.ai/';
export const TIMEOUT_MS = 15_000;
export const MAX_CONTENT = 5_000; // chars
const CLOUDFLARE_ERROR =
  'Cloudflare-protected page: Jina Reader got a challenge and lis-web has no browser fallback';
const REFUSED_HINT =
  'Jina Reader refused this URL; the page itself may be fine. Retry once with ' +
  "engine 'browser' and fresh true, or find another source with web_search.";

const ENGINES = ['direct', 'browser'];
const FORMATS = ['markdown', 'text', 'html'];
const WAITS = ['visible-content', 'mutation-idle', 'network-idle'];
const SELECTOR_MAX = 200;
const SELECTOR_RE = /^[\x20-\x7E]*$/; // printable ASCII: no CR/LF, no bytes a header cannot carry
const LOCALE_RE = /^[a-z]{2}(-[A-Z]{2})?$/;
const PROXY_RE = /^(auto|[a-z]{2})$/;

const intInRange = (v, min, max) =>
  typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;

/**
 * Optional Jina Reader parameters as request headers, or an error string for an invalid
 * value. With no options: no headers and the default timeout.
 */
function readerOptions(args, hasKey) {
  const headers = {};
  let timeoutMs = TIMEOUT_MS;
  let note;
  const selectors = [
    ['selector', 'X-Target-Selector'],
    ['wait_for', 'X-Wait-For-Selector'],
    ['remove_selector', 'X-Remove-Selector'],
  ];
  for (const [name, header] of selectors) {
    const v = args[name];
    if (v === undefined || v === null) continue;
    if (typeof v !== 'string') return `${name} must be a string`;
    if (!SELECTOR_RE.test(v)) {
      return `${name} must be printable ASCII (no line breaks or non-ASCII characters)`;
    }
    const t = v.trim();
    if (t.length > SELECTOR_MAX) return `${name} must be at most ${SELECTOR_MAX} characters`;
    if (t) headers[header] = t;
  }
  if (args.engine !== undefined) {
    if (!ENGINES.includes(args.engine)) return `engine must be one of: ${ENGINES.join(', ')}`;
    headers['X-Engine'] = args.engine;
  }
  if (args.fresh === true) headers['X-No-Cache'] = 'true';
  if (args.format !== undefined) {
    if (!FORMATS.includes(args.format)) return `format must be one of: ${FORMATS.join(', ')}`;
    if (args.format !== 'markdown') headers['X-Respond-With'] = args.format;
  }
  if (args.links_summary === true) headers['X-With-Links-Summary'] = 'true';
  if (args.images_summary === true) headers['X-With-Images-Summary'] = 'true';
  if (args.strip_images === true) headers['X-Retain-Images'] = 'none';
  if (args.timeout_s !== undefined) {
    if (!intInRange(args.timeout_s, 5, 60)) return 'timeout_s must be an integer from 5 to 60';
    headers['X-Timeout'] = String(args.timeout_s);
    timeoutMs = (args.timeout_s + 5) * 1000;
  }
  if (args.max_tokens !== undefined) {
    if (!intInRange(args.max_tokens, 200, 20_000)) {
      return 'max_tokens must be an integer from 200 to 20000';
    }
    headers['X-Max-Tokens'] = String(args.max_tokens);
  }
  if (args.locale !== undefined) {
    if (typeof args.locale !== 'string' || !LOCALE_RE.test(args.locale)) {
      return "locale must look like 'es' or 'es-MX'";
    }
    headers['X-Locale'] = args.locale;
  }
  if (args.proxy !== undefined) {
    if (typeof args.proxy !== 'string' || !PROXY_RE.test(args.proxy)) {
      return "proxy must be 'auto' or a two-letter lowercase country code";
    }
    // Jina proxies need a key; without one the read goes out unproxied.
    if (hasKey) headers['X-Proxy'] = args.proxy;
    else note = 'proxy ignored: JINA_API_KEY not set';
  }
  if (args.wait !== undefined) {
    if (!WAITS.includes(args.wait)) return `wait must be one of: ${WAITS.join(', ')}`;
    headers['X-Respond-Timing'] = args.wait;
  }
  return { headers, timeoutMs, ...(note && { note }) };
}

/** The result JSON of a read body, cut to MAX_CONTENT chars when longer. */
function readResult(url, content, extra) {
  const truncated = content.length > MAX_CONTENT;
  return JSON.stringify({
    url,
    content: truncated ? truncatePreview(content, MAX_CONTENT) : content,
    chars: content.length,
    truncated,
    ...extra,
  });
}

export const webReadTool = {
  name: 'web_read',
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: true,
  },
  description: `Read a web page and return its content as clean Markdown.

USE WHEN:
- The task gives a URL and asks you to read, summarize, or analyze it
- You need to read a GitHub repo README, documentation page, article, or blog post
- You found a URL via web_search and need to read the full content

DO NOT USE WHEN:
- You just need search results (use web_search instead)
- The URL requires authentication (login-protected pages won't work)
- You need to interact with the page: click buttons, fill forms, scroll (not available here)

Returns clean Markdown with headings, code blocks, and links preserved.
Works with: GitHub repos, news articles, documentation, blogs, PDFs (read through Jina).
X/Twitter status links are read directly (text, author, quotes, articles).
Cloudflare-protected pages return an error: there is no browser fallback.
JS-rendered pages are rendered by Jina; use wait_for if the content loads late and selector \
to keep only the useful part of the page.
OPTIONS: all optional, omit them for a plain read; each parameter says what it does (page \
part, rendering, freshness, output, region).

AFTER READING: Cite the URL when reporting content. Distinguish between what the page says \
and your own analysis.`,
  parameters: {
    type: 'object',
    properties: {
      url: {
        type: 'string',
        description: "The full URL to read (e.g., 'https://github.com/user/repo')",
      },
      selector: {
        type: 'string',
        description:
          "Optional CSS selector; return only that part of the page (e.g., 'article', 'main', " +
          "'#content'). Max 200 chars.",
      },
      wait_for: {
        type: 'string',
        description:
          'Optional CSS selector to wait for before extracting (pages that load content ' +
          'late). Max 200 chars.',
      },
      remove_selector: {
        type: 'string',
        description:
          "Optional CSS selector to drop before extracting (e.g., 'nav, footer, .ads'). " +
          'Max 200 chars.',
      },
      engine: {
        type: 'string',
        enum: ENGINES,
        description:
          "Optional: 'browser' renders the page in a real browser (JS-heavy pages); 'direct' " +
          "is faster for static pages. Omit for Jina's default.",
      },
      fresh: {
        type: 'boolean',
        description:
          "Optional: true bypasses Jina's cache (live prices, pages updated minutes ago).",
      },
      format: {
        type: 'string',
        enum: FORMATS,
        description: 'Optional output format (default: markdown).',
      },
      links_summary: {
        type: 'boolean',
        description: 'Optional: true appends a list of the links found on the page.',
      },
      images_summary: {
        type: 'boolean',
        description: 'Optional: true appends a list of the images found on the page.',
      },
      strip_images: {
        type: 'boolean',
        description: 'Optional: true removes images from the output.',
      },
      timeout_s: {
        type: 'integer',
        description:
          "Optional: seconds Jina may wait for a slow page, integer 5-60 (default: Jina's " +
          'own, 15 s local limit).',
      },
      max_tokens: {
        type: 'integer',
        description: 'Optional: server-side cap on the returned tokens, integer 200-20000.',
      },
      locale: {
        type: 'string',
        description: "Optional browser locale, 'xx' or 'xx-YY' (e.g., 'es', 'es-MX').",
      },
      proxy: {
        type: 'string',
        description:
          "Optional: 'auto' or a two-letter lowercase country code (e.g., 'mx', 'us') for " +
          'geo-dependent pages. Needs JINA_API_KEY; ignored without it.',
      },
      wait: {
        type: 'string',
        enum: WAITS,
        description:
          'Optional: when the page counts as loaded before extraction (late-loading content).',
      },
    },
    required: ['url'],
  },

  async execute(args) {
    const url = args.url;
    if (!url) return toolError('url is required');
    // No private, loopback or metadata address and no scheme but http(s).
    const urlError = validateOutboundUrl(url);
    if (urlError) return toolError(urlError, { url });
    const apiKey = process.env.JINA_API_KEY;
    const opts = readerOptions(args, Boolean(apiKey));
    if (typeof opts === 'string') return toolError(opts, { url });
    const note = opts.note;

    // X/Twitter status links: Jina blocks anonymous x.com reads.
    const tweetId = parseTweetId(url);
    if (tweetId) {
      try {
        const tweet = await readTweet(tweetId);
        if (tweet) return readResult(url, tweet.content, { source: tweet.source });
      } catch (err) {
        console.error(`lis-web: tweet path failed for ${url} (${err}), falling back to Jina`);
      }
    }

    // One signal for the read and its retry: the abort window is shared.
    const signal = AbortSignal.timeout(opts.timeoutMs);
    try {
      const headers = {
        Accept: opts.headers['X-Respond-With'] ? 'text/plain' : 'text/markdown',
      };
      if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
      Object.assign(headers, opts.headers);
      let response = await fetch(`${JINA_PREFIX}${url}`, { headers, signal });

      // One cheap second try through Jina on 403/503 before giving up: bypass its cache and
      // force the browser engine (+ proxy with a key). Never on 429 (a retry without backoff
      // only burns the quota) and never on a Cloudflare challenge.
      let failBody;
      let retried = false;
      if ((response.status === 403 || response.status === 503) &&
          headers['X-Engine'] !== 'browser') {
        failBody = await response.text().catch(() => '');
        if (!isCloudflareChallenge(failBody)) {
          const retryHeaders = { ...headers, 'X-No-Cache': 'true', 'X-Engine': 'browser' };
          if (apiKey && !retryHeaders['X-Proxy']) retryHeaders['X-Proxy'] = 'auto';
          try {
            const retry = await fetch(`${JINA_PREFIX}${url}`, { headers: retryHeaders, signal });
            if (retry.ok) {
              response = retry;
              retried = true;
            } else {
              await retry.body?.cancel().catch(() => {});
            }
          } catch {
            // keep the original failure
          }
        }
      }

      if (!response.ok) {
        const body =
          failBody ??
          ([403, 429, 451, 503].includes(response.status)
            ? await response.text().catch(() => '')
            : '');
        if ((response.status === 403 || response.status === 503) && isCloudflareChallenge(body)) {
          return toolError(CLOUDFLARE_ERROR, { url });
        }
        // Jina refused (blocked domain, rate limit): keep its reason.
        if ([403, 429, 451].includes(response.status)) {
          const reason = jinaReason(body);
          return toolError(
            `Failed to read URL: ${response.status} ${response.statusText}` +
              (reason ? ` \u2014 ${reason}` : ''),
            { url, hint: REFUSED_HINT, ...(note && { note }) },
          );
        }
        return toolError(`Failed to read URL: ${response.status} ${response.statusText}`, {
          url,
          ...(note && { note }),
        });
      }

      const content = await response.text();
      // Jina sometimes returns challenge HTML as content. Markdown only: an html or text
      // body of a normal page may load challenges.cloudflare.com (Turnstile).
      if (!headers['X-Respond-With'] && isCloudflareChallenge(content)) {
        return toolError(CLOUDFLARE_ERROR, { url });
      }
      return readResult(url, content, { ...(retried && { retried: true }), ...(note && { note }) });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return toolError(`Web read failed: ${message}`, { url });
    }
  },
};
