// web_search: Brave Search API (env BRAVE_SEARCH_API_KEY). Ported from the Jarvis
// agent-controller's src/tools/builtin/web-search.ts; same schema and result text.
import { errMsg, fetchJson, HttpStatusError, toolError } from './common.mjs';

const BRAVE_API_URL = 'https://api.search.brave.com/res/v1/web/search';
export const TIMEOUT_MS = 10_000;
const MAX_RESULTS = 5;

export const webSearchTool = {
  name: 'web_search',
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: true,
  },
  description: `Search the internet for real-time information using Brave Search.

USE WHEN:
- The task asks about current events, news, prices, releases, or anything time-sensitive
- You need factual information you're not confident about (dates, statistics, people, companies)
- The task asks you to research a topic, find resources, compare options, or look something up
- You need to verify a claim or find the latest version of something
- ANY question where your training data might be outdated or insufficient

DO NOT USE WHEN:
- The answer is in the working tree (use Read, Grep or Glob instead)
- You already have the information from this session

ALWAYS prefer searching over guessing. If you're unsure, search.

AFTER SEARCHING: Cite specific sources (title + URL) when reporting findings. Never present \
search results as your own knowledge.`,
  parameters: {
    type: 'object',
    properties: {
      query: {
        type: 'string',
        description:
          'Search query in natural language. Be specific. Use English for broader results or ' +
          'Spanish for Mexico-specific results.',
      },
      count: {
        type: 'number',
        description: `Number of results to return (1-10, default: ${MAX_RESULTS})`,
      },
    },
    required: ['query'],
  },

  async execute(args) {
    const query = args.query;
    if (!query) return toolError('query is required');
    const apiKey = process.env.BRAVE_SEARCH_API_KEY;
    if (!apiKey) return toolError('BRAVE_SEARCH_API_KEY not configured');
    const count = Math.min(Math.max(args.count ?? MAX_RESULTS, 1), 10);
    const url = `${BRAVE_API_URL}?q=${encodeURIComponent(query)}&count=${count}`;
    try {
      const data = await fetchJson(url, {
        timeoutMs: TIMEOUT_MS,
        headers: { 'Accept-Encoding': 'gzip', 'X-Subscription-Token': apiKey },
      });
      const results = (data.web?.results ?? []).slice(0, count).map((r) => ({
        title: r.title,
        url: r.url,
        description: r.description,
      }));
      const snippet = data.web?.results?.find((r) => r.extra_snippets?.length)
        ?.extra_snippets?.[0];
      const knowledge = data.knowledge_graph
        ? { title: data.knowledge_graph.title, description: data.knowledge_graph.description }
        : null;
      // Numbered results with title, URL and description (the Jarvis text, emoji included).
      const lines = [`\u{1F50D} **"${query}"** \u2014 ${results.length} results`];
      if (snippet) lines.push(`\n> ${snippet}\n`);
      if (knowledge) lines.push(`\u{1F4D6} **${knowledge.title}**: ${knowledge.description}\n`);
      for (let i = 0; i < results.length; i++) {
        lines.push(
          `${i + 1}. **${results[i].title}**\n   ${results[i].url}\n   ${results[i].description}`,
        );
      }
      return lines.join('\n');
    } catch (err) {
      if (err instanceof HttpStatusError) {
        return toolError(`Brave Search API error: ${err.status} ${err.bodyText}`);
      }
      return toolError(`Search failed: ${errMsg(err)}`);
    }
  },
};
