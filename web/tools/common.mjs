// Helpers shared by the lis-web tools, ported from the Jarvis agent-controller
// (src/lib/fetch-json.ts, err-msg.ts, url-safety.ts, the jinaReason of web-read.ts and the
// Cloudflare check of stealth-browser.ts). Nothing here writes a file.

/** A readable message from an unknown catch value. */
export function errMsg(e) {
  return e instanceof Error ? e.message : String(e);
}

/** A tool's failure return: always a JSON object with a string `error`. */
export function toolError(error, extra = {}) {
  return JSON.stringify({ error, ...extra });
}

/** Non-2xx HTTP response; `bodyText` is the full response body ("" if unreadable). */
export class HttpStatusError extends Error {
  constructor(label, status, bodyText) {
    const excerpt = bodyText.slice(0, 200).replace(/\s+/g, ' ').trim();
    super(`${label} error: ${status}${excerpt ? ` ${excerpt}` : ''}`);
    this.name = 'HttpStatusError';
    this.status = status;
    this.bodyText = bodyText;
  }
}

/**
 * Fetches a URL and returns its parsed JSON body. The timeout (AbortSignal.timeout) covers
 * connect and body read. Throws HttpStatusError on a non-2xx status, a TimeoutError
 * DOMException on timeout and a SyntaxError on a 2xx body that is not JSON.
 */
export async function fetchJson(url, opts = {}) {
  const response = await fetch(url, {
    method: opts.method,
    headers: { Accept: 'application/json', ...opts.headers },
    ...(opts.body !== undefined && { body: opts.body }),
    signal: AbortSignal.timeout(opts.timeoutMs ?? 15_000),
  });
  if (!response.ok) {
    let bodyText = '';
    try {
      bodyText = await response.text();
    } catch {
      // unreadable error body: keep ""
    }
    throw new HttpStatusError(opts.label ?? 'HTTP', response.status, bodyText);
  }
  return response.json();
}

/** Jina's error reason from a non-ok body (JSON or plain text), at most 300 chars. */
export function jinaReason(body) {
  let reason = '';
  try {
    const parsed = JSON.parse(body);
    const msg = parsed?.readableMessage ?? parsed?.message;
    if (typeof msg === 'string') reason = msg;
  } catch {
    if (!body.trimStart().startsWith('<')) reason = body;
  }
  return reason.replace(/\s+/g, ' ').trim().slice(0, 300);
}

/** True when an HTML or Markdown body is a Cloudflare challenge page. */
export function isCloudflareChallenge(html) {
  return (
    html.includes('challenges.cloudflare.com') ||
    html.includes('<title>Just a moment') ||
    html.includes('Checking if the site connection is secure') ||
    html.includes('Verify you are human') ||
    html.includes('cf-challenge-running')
  );
}

// Private and reserved address ranges a tool never asks for.
const BLOCKED_IP_PATTERNS = [
  /^127\./,
  /^10\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^192\.168\./,
  /^169\.254\./,
  /^0\./,
  /^100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./,
  /^::1$/,
  /^::0*$/,
  /^f[cd][0-9a-f]{0,2}:/i,
  /^fe80:/i,
];
const BLOCKED_HOSTS = new Set([
  'localhost',
  'metadata.google.internal',
  'metadata',
  'instance-data.ec2.internal',
]);
const ALLOWED_SCHEMES = new Set(['http:', 'https:']);

/**
 * The string checks of Jarvis's validateOutboundUrl: http(s) only, no blocked host name,
 * no private or reserved IP literal (IPv4-mapped IPv6 included), no cloud metadata path.
 * Returns null when the URL may be read, else the reason.
 */
export function validateOutboundUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return 'Invalid URL';
  }
  if (!ALLOWED_SCHEMES.has(parsed.protocol)) {
    return `Blocked scheme: ${parsed.protocol} (only http/https allowed)`;
  }
  const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.+$/, '');
  if (BLOCKED_HOSTS.has(hostname)) return `Blocked host: ${hostname}`;
  let checkHost = hostname;
  const dotted = hostname.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/i);
  const hex = hostname.match(/^::ffff:([0-9a-f]+):([0-9a-f]+)$/i);
  if (dotted) {
    checkHost = dotted[1];
  } else if (hex) {
    const hi = parseInt(hex[1], 16);
    const lo = parseInt(hex[2], 16);
    checkHost = `${(hi >> 8) & 0xff}.${hi & 0xff}.${(lo >> 8) & 0xff}.${lo & 0xff}`;
  }
  if (BLOCKED_IP_PATTERNS.some((p) => p.test(checkHost))) {
    return `Blocked private/reserved IP: ${hostname}`;
  }
  if (hostname === '169.254.169.254' || parsed.pathname.includes('/latest/meta-data')) {
    return 'Blocked cloud metadata endpoint';
  }
  return null;
}

/**
 * The first `max` chars of an over-long body plus a marker and the Markdown headings, the
 * preview Jarvis's eviction returns, without the file (lis-web writes none).
 */
export function truncatePreview(content, max) {
  const headings = content
    .split('\n')
    .filter((l) => /^#{1,6}\s/.test(l))
    .map((h) => h.replace(/^#+\s*/, '').trim())
    .slice(0, 30);
  const toc = headings.length
    ? `\n\nTABLE OF CONTENTS (${headings.length} sections):\n` +
      headings.map((h) => `- ${h}`).join('\n')
    : '';
  return (
    content.slice(0, max) +
    `\n\n--- DOCUMENT TRUNCATED (${content.length} chars total) ---` +
    '\nThe rest is not kept; narrow the read with selector or max_tokens.' +
    toc
  );
}
