// exa_search: Exa semantic search (env EXA_API_KEY). Ported from the Jarvis
// agent-controller's src/tools/builtin/exa-search.ts; same schema and result JSON.
import { errMsg, fetchJson, HttpStatusError, toolError } from './common.mjs';

const EXA_API_URL = 'https://api.exa.ai/search';
export const TIMEOUT_MS = 15_000;
const MAX_RESULTS = 10;
const CATEGORIES = [
  'company',
  'research paper',
  'tweet',
  'github',
  'linkedin',
  'news',
  'pdf',
  'personal site',
];

export const exaSearchTool = {
  name: 'exa_search',
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: false,
    openWorldHint: true,
  },
  description: `Semantic web search using Exa - finds content by meaning, not just keywords.

USE WHEN:
- Researching companies, products, or organizations (returns structured company data)
- Looking for in-depth articles, reports, or analysis on a topic
- The query requires understanding intent, not just keyword matching
- You need high-quality sources (academic, industry reports, authoritative blogs)
- Finding companies in a specific vertical or with specific characteristics
- Scanning for trends, emerging topics, or market shifts

DO NOT USE WHEN:
- Quick factual lookups (use web_search instead - faster, broader)
- Current events or breaking news (use web_search - fresher index)
- Looking for a specific known URL or page (use web_read)
- The answer is in the working tree (use Read or Grep)

CATEGORIES (use to narrow results):
- "company" - company websites and profiles
- "research paper" - academic and research publications
- "tweet" - Twitter/X posts
- "github" - GitHub repositories
- "linkedin" - LinkedIn profiles and posts
- "news" - news articles
- "pdf" - PDF documents
- "personal site" - personal websites and blogs
Leave empty for general semantic search across all categories.`,
  parameters: {
    type: 'object',
    properties: {
      query: {
        type: 'string',
        description:
          "Search query - can be a natural language description of what you're looking for. " +
          'Be specific about the topic and what kind of content you want.',
      },
      category: {
        type: 'string',
        enum: CATEGORIES,
        description: 'Narrow results to a specific content category. Omit for general search.',
      },
      num_results: {
        type: 'number',
        description: `Number of results (1-${MAX_RESULTS}, default: 5)`,
      },
      include_text: {
        type: 'boolean',
        description:
          'Include page text content in results (default: false). Set true when you need to ' +
          'read the actual content, not just titles/URLs.',
      },
      start_published_date: {
        type: 'string',
        description:
          'Filter: only results published after this date (ISO format, e.g. 2025-01-01). ' +
          'Useful for finding recent content.',
      },
    },
    required: ['query'],
  },

  async execute(args) {
    const query = args.query;
    if (!query) return toolError('query is required');
    const apiKey = process.env.EXA_API_KEY;
    if (!apiKey) return toolError('EXA_API_KEY not configured. Get one at https://exa.ai');
    const numResults = Math.min(Math.max(args.num_results ?? 5, 1), MAX_RESULTS);
    const body = { query, num_results: numResults, use_autoprompt: true };
    if (args.category) body.category = args.category;
    if (args.start_published_date) body.start_published_date = args.start_published_date;
    // Page text is capped by Exa at 3,000 chars per result.
    if (args.include_text) body.contents = { text: { max_characters: 3000 } };
    try {
      const data = await fetchJson(EXA_API_URL, {
        method: 'POST',
        timeoutMs: TIMEOUT_MS,
        headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey },
        body: JSON.stringify(body),
      });
      const results = (data.results ?? []).map((r) => ({
        title: r.title,
        url: r.url,
        published_date: r.published_date ?? null,
        author: r.author ?? null,
        score: r.score != null ? Math.round(r.score * 100) / 100 : null,
        ...(r.text ? { text: r.text } : {}),
      }));
      return JSON.stringify({
        query,
        category: args.category ?? 'all',
        results,
        total: results.length,
      });
    } catch (err) {
      if (err instanceof HttpStatusError) {
        return toolError(`Exa API error: ${err.status} ${err.bodyText.slice(0, 300)}`);
      }
      return toolError(`Exa search failed: ${errMsg(err)}`);
    }
  },
};
