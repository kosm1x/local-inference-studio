// web_read_tweet and the X/Twitter reader web_read uses. Ported from the Jarvis
// agent-controller's src/tools/builtin/web-read-tweet.ts and the tweetTool of
// src/mcp/web-stdio.ts. Keyless: api.fxtwitter.com first, then the public syndication
// endpoint; null when both fail.
import { toolError } from './common.mjs';

export const TWEET_TIMEOUT_MS = 10_000;
const DOT = '\u00b7';

const TWEET_HOSTS = new Set([
  'x.com',
  'twitter.com',
  'mobile.twitter.com',
  'mobile.x.com',
  'fxtwitter.com',
  'vxtwitter.com',
  'fixupx.com',
]);

// /<handle>/status/<id> or /i/web/status/<id>, optional trailing segments
const STATUS_PATH_RE = /^\/(?:i\/web|[A-Za-z0-9_]{1,15})\/status(?:es)?\/(\d{1,25})(?:\/|$)/;

/** The numeric status id of an X/Twitter status URL, else null. */
export function parseTweetId(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
  if (!TWEET_HOSTS.has(host)) return null;
  return STATUS_PATH_RE.exec(parsed.pathname)?.[1] ?? null;
}

async function getJson(url) {
  try {
    const res = await fetch(url, {
      headers: { Accept: 'application/json', 'User-Agent': 'lis-web/1.0' },
      signal: AbortSignal.timeout(TWEET_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function byline(a) {
  return `**${a?.name ?? 'unknown'}** (@${a?.screen_name ?? 'unknown'})`;
}

const BLOCK_PREFIX = {
  'header-one': '# ',
  'header-two': '## ',
  'header-three': '### ',
  'unordered-list-item': '- ',
  blockquote: '> ',
  'code-block': '    ',
};

/** Renders an X Article (Draft.js blocks) to Markdown. */
function renderArticle(article) {
  const out = [`## ${article.title ?? 'Article'}`];
  const blocks = article.content?.blocks ?? [];
  let n = 0;
  for (const b of blocks) {
    const text = b.text ?? '';
    if (b.type !== 'ordered-list-item') n = 0;
    if (b.type === 'atomic' || !text.trim()) continue; // embedded media
    const prefix =
      b.type === 'ordered-list-item' ? `${++n}. ` : (BLOCK_PREFIX[b.type ?? ''] ?? '');
    out.push(prefix + (prefix ? text.replace(/\n/g, `\n${prefix}`) : text));
  }
  if (blocks.length === 0 && article.preview_text) out.push(article.preview_text);
  return out.join('\n\n');
}

function quoteOf(author, text) {
  return `> Quoting ${byline(author)}:\n> ${(text ?? '').replace(/\n/g, '\n> ')}`;
}

function renderFx(t) {
  const parts = [`${byline(t.author)} ${DOT} ${t.created_at ?? ''}`, t.url ?? ''];
  if (t.replying_to) parts.push(`Replying to @${t.replying_to}`);
  if (t.text) parts.push(t.text);
  if (t.quote) parts.push(quoteOf(t.quote.author, t.quote.text));
  if (t.article) parts.push(renderArticle(t.article));
  const media = (t.media?.all ?? []).map((m) => m.url).filter(Boolean);
  if (media.length) parts.push(`Media: ${media.join(' ')}`);
  if (t.community_note?.text) parts.push(`Community note: ${t.community_note.text}`);
  parts.push(
    `Likes ${t.likes ?? 0} ${DOT} Reposts ${t.retweets ?? 0} ${DOT} Replies ${t.replies ?? 0}` +
      (t.views != null ? ` ${DOT} Views ${t.views}` : ''),
  );
  return parts.filter(Boolean).join('\n\n');
}

function renderSyndication(t, url) {
  const parts = [`${byline(t.user)} ${DOT} ${t.created_at ?? ''}`, url];
  if (t.in_reply_to_screen_name) parts.push(`Replying to @${t.in_reply_to_screen_name}`);
  parts.push(t.text ?? '');
  if (t.note_tweet) parts.push('_(long post \u2014 the source truncates the text)_');
  if (t.quoted_tweet) parts.push(quoteOf(t.quoted_tweet.user, t.quoted_tweet.text));
  const media = (t.mediaDetails ?? []).map((m) => m.media_url_https).filter(Boolean);
  if (media.length) parts.push(`Media: ${media.join(' ')}`);
  parts.push(`Likes ${t.favorite_count ?? 0} ${DOT} Replies ${t.conversation_count ?? 0}`);
  return parts.filter(Boolean).join('\n\n');
}

/** Reads a tweet by id: fxtwitter first, syndication second; null if both fail. */
export async function readTweet(id) {
  // Third-party JSON: a render throw on an unexpected shape = that source failed.
  const fx = await getJson(`https://api.fxtwitter.com/status/${id}`);
  if (fx?.code === 200 && typeof fx.tweet?.text === 'string') {
    try {
      return { content: renderFx(fx.tweet), source: 'fxtwitter' };
    } catch (err) {
      console.error(`lis-web: tweet ${id}: fxtwitter render failed (${err}), trying syndication`);
    }
  }
  const syn = await getJson(`https://cdn.syndication.twimg.com/tweet-result?id=${id}&token=a`);
  if (syn?.__typename === 'Tweet' && typeof syn.text === 'string') {
    try {
      const handle = syn.user?.screen_name ?? 'i/web';
      return {
        content: renderSyndication(syn, `https://x.com/${handle}/status/${id}`),
        source: 'syndication',
      };
    } catch (err) {
      console.error(`lis-web: tweet ${id}: syndication render failed (${err})`);
    }
  }
  return null;
}

export const webReadTweetTool = {
  name: 'web_read_tweet',
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: true,
  },
  description: `Read one X/Twitter status (text, author, quote, article, media links, counts).

USE WHEN:
- You have an x.com or twitter.com status URL (/<handle>/status/<id>)

DO NOT USE WHEN:
- The URL is not a status link (use web_read)
- You need to search for posts (use exa_search with category "tweet")`,
  parameters: {
    type: 'object',
    properties: {
      url: {
        type: 'string',
        description: "X/Twitter status URL, e.g. 'https://x.com/<handle>/status/<id>'",
      },
    },
    required: ['url'],
  },

  async execute(args) {
    const url = typeof args.url === 'string' ? args.url : '';
    const id = parseTweetId(url);
    if (!id) return toolError('url is not an X/Twitter status link');
    const tweet = await readTweet(id);
    if (!tweet) {
      return toolError('tweet could not be read (fxtwitter and syndication failed)', { url });
    }
    return JSON.stringify({ url, content: tweet.content, source: tweet.source });
  },
};
