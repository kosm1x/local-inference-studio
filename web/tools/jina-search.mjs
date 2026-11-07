// jina_search: s.jina.ai search (env JINA_API_KEY). Ported from the Jarvis
// agent-controller's src/tools/builtin/jina-search.ts; same schema and result JSON, minus
// full_content_path: an over-cap result is fitted to the cap and nothing is written to disk.
import { errMsg, jinaReason, toolError } from './common.mjs';

const JINA_SEARCH_URL = 'https://s.jina.ai/';
export const TIMEOUT_MS = 15_000;
const MAX_NUM = 10;
export const MAX_RESULT_CONTENT = 1_500; // chars per result body
export const MAX_CONTENT = 5_000; // chars for the whole JSON result, like web_read
const MAX_DESCRIPTION = 300; // chars per result snippet
const MAX_TITLE = 300; // chars per result title
const MAX_URL = 2_000; // chars per result URL
const MIN_BODY = 200; // escaped chars a body keeps before trailing rows are dropped instead
const SITE_RE = /^[a-z0-9.-]+\.[a-z]{2,}$/i;
const LANG_RE = /^[a-z]{2}$/;

const str = (v) => (typeof v === 'string' && v ? v : undefined);

/** Length of a string once JSON-escaped, without the quotes. */
const escLen = (s) => JSON.stringify(s).length - 2;

/** Longest prefix of `s` whose JSON-escaped length is at most `max`. */
function fitEscaped(s, max) {
  if (escLen(s) <= max) return s;
  let lo = 0;
  let hi = Math.min(s.length, max);
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (escLen(s.slice(0, mid)) <= max) lo = mid;
    else hi = mid - 1;
  }
  return s.slice(0, lo);
}

export const jinaSearchTool = {
  name: 'jina_search',
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: true,
  },
  description: `Web search through Jina (s.jina.ai) that can return the text of the top results \
in one call.

USE WHEN:
- The task needs what the top sources actually say in one call (research) - set with_content=true
- The search must be restricted to one site (site="example.com")
- web_search returned nothing useful

DO NOT USE WHEN:
- A plain list of links is enough (use web_search instead - it is cheaper: a Jina search costs \
at least 10,000 tokens per request)
- You already have the URL (use web_read)
- JINA_API_KEY is not configured (the tool returns an error)

Without with_content you get title, URL, snippet and date per result (cheapest form). With \
with_content each result carries up to 1,500 chars of page text.

AFTER SEARCHING: Cite the URLs. Distinguish between what the pages claim and your own analysis.`,
  parameters: {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Search query, 2-400 characters.' },
      num: {
        type: 'integer',
        description: `Number of results, integer 1-${MAX_NUM} (default: 5).`,
      },
      page: { type: 'integer', description: 'Result page, integer >= 1 (default: 1).' },
      site: {
        type: 'string',
        description:
          "Optional hostname to restrict results to (e.g., 'example.com', 'docs.example.org').",
      },
      country: {
        type: 'string',
        description:
          "Optional two-letter lowercase country code for result ranking (e.g., 'mx', 'us').",
      },
      language: {
        type: 'string',
        description: "Optional two-letter lowercase language code (e.g., 'es', 'en').",
      },
      with_content: {
        type: 'boolean',
        description:
          'Include page text per result (default: false). Same price per request; larger output.',
      },
    },
    required: ['query'],
  },

  async execute(args) {
    const query = typeof args.query === 'string' ? args.query.trim() : '';
    if (query.length < 2 || query.length > 400) {
      return toolError('query must be 2-400 characters');
    }
    const num = args.num ?? 5;
    if (typeof num !== 'number' || !Number.isInteger(num) || num < 1 || num > MAX_NUM) {
      return toolError(`num must be an integer from 1 to ${MAX_NUM}`);
    }
    const page = args.page ?? 1;
    if (typeof page !== 'number' || !Number.isInteger(page) || page < 1) {
      return toolError('page must be an integer >= 1');
    }
    const site = args.site;
    if (site !== undefined && (typeof site !== 'string' || !SITE_RE.test(site))) {
      return toolError("site must be a hostname like 'example.com'");
    }
    for (const name of ['country', 'language']) {
      const v = args[name];
      if (v !== undefined && (typeof v !== 'string' || !LANG_RE.test(v))) {
        return toolError(`${name} must be a two-letter lowercase code`);
      }
    }
    const withContent = args.with_content === true;
    const apiKey = process.env.JINA_API_KEY;
    if (!apiKey) return toolError('JINA_API_KEY not configured. Get one at https://jina.ai');

    const params = new URLSearchParams({ q: query, num: String(num), page: String(page) });
    if (site) params.set('site', site);
    if (args.country) params.set('gl', args.country);
    if (args.language) params.set('hl', args.language);
    const headers = { Authorization: `Bearer ${apiKey}`, Accept: 'application/json' };
    if (!withContent) headers['X-Respond-With'] = 'no-content';

    try {
      const response = await fetch(`${JINA_SEARCH_URL}?${params}`, {
        headers,
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      if (!response.ok) {
        const reason = jinaReason(await response.text().catch(() => ''));
        const hint =
          response.status === 401 || response.status === 402
            ? 'key invalid or out of tokens; check the Jina dashboard'
            : response.status === 429
              ? 'rate limited; use web_search'
              : undefined;
        return toolError(
          `Jina search failed: ${response.status} ${response.statusText}` +
            (reason ? ` \u2014 ${reason}` : ''),
          hint ? { hint } : {},
        );
      }
      // A 200 that is not a JSON object is a failed search, not "no results".
      let parsed;
      try {
        parsed = JSON.parse(await response.text());
      } catch {
        parsed = undefined;
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return toolError('Jina search returned a non-JSON response', {
          hint: 'the search did not complete; retry once or use web_search',
        });
      }
      const rows = Array.isArray(parsed.data) ? parsed.data : [];
      const results = rows
        .filter((r) => !!r && typeof r === 'object')
        .map((r) => {
          const content = withContent ? str(r.content) : undefined;
          const description = str(r.description);
          const title = str(r.title);
          const url = str(r.url);
          return {
            ...(title && { title: title.slice(0, MAX_TITLE) }),
            ...(url && { url: url.slice(0, MAX_URL) }),
            ...(description && { description: description.slice(0, MAX_DESCRIPTION) }),
            ...(str(r.date) && { date: str(r.date) }),
            ...(content && { content: content.slice(0, MAX_RESULT_CONTENT) }),
          };
        });
      const tokens = parsed.usage?.tokens;
      const shape = (list, extra = {}) =>
        JSON.stringify({
          query,
          results: list,
          count: list.length,
          page,
          ...(typeof tokens === 'number' && { tokens_used: tokens }),
          ...extra,
        });
      const full = shape(results);
      if (full.length <= MAX_CONTENT) return full;

      // Too big: the returned JSON stays parseable and within the cap. Page bodies are
      // shortened evenly (sizes measured JSON-escaped); when a body would drop under
      // MIN_BODY, or the rows alone are too big, trailing rows are dropped instead.
      const fit = (list) => {
        const extra = {
          truncated: true,
          ...(list.length < results.length && { dropped: results.length - list.length }),
        };
        const bodies = list.filter((r) => r.content).map((r) => r.content);
        let fitted = list;
        if (bodies.length) {
          const bare = list.map((r) => (r.content ? { ...r, content: '' } : r));
          const share = Math.floor((MAX_CONTENT - shape(bare, extra).length) / bodies.length);
          const need = Math.min(MIN_BODY, Math.max(...bodies.map(escLen)));
          if (share < need) return null;
          fitted = list.map((r) =>
            r.content ? { ...r, content: fitEscaped(r.content, share) } : r);
        }
        const json = shape(fitted, extra);
        return json.length <= MAX_CONTENT || list.length === 0 ? json : null;
      };
      for (let n = results.length; n > 0; n--) {
        const json = fit(results.slice(0, n));
        if (json) return json;
      }
      return fit([]);
    } catch (err) {
      return toolError(`Jina search failed: ${errMsg(err)}`);
    }
  },
};
