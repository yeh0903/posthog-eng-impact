export const meta = {
  name: 'narratives',
  description: 'Write a grounded 1-2 sentence impact narrative per top-5 engineer from their PR diffs',
  phases: [{ title: 'Narrate', detail: 'one agent per top-5 engineer' }],
}

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['login', 'narrative', 'evidence'],
  properties: {
    login: { type: 'string' },
    narrative: { type: 'string', description: '1-2 sentences, concrete, what they accomplished and its reach' },
    evidence: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['number', 'summary'],
        properties: { number: { type: 'integer' }, summary: { type: 'string' } },
      },
    },
  },
}

let a = args
if (typeof a === 'string') { try { a = JSON.parse(a) } catch (e) {} }
a = a || {}
const paths = a.paths
  || Array.from({ length: Number(a.count) || 0 }, (_, i) => `${a.dir}/n${i}.json`)

phase('Narrate')
const results = await parallel(paths.map((path, i) => () =>
  agent(`Read the JSON file at ${path}. It describes ONE PostHog engineer and their most substantial PRs over the last 90 days. It contains: login, a stats summary (PRs merged, non-trivial count, reviews given, distinct core areas, work-type mix, AI-assisted %), and prs[] — each with number, title, the LLM complexity, the areas touched and their reach (distinct authors), and a truncated diff.

Write for a busy PostHog engineering leader who will NOT read the PRs:
- "narrative": 1-2 sentences, concrete and specific, on what this engineer actually accomplished and WHY it's impactful (name the systems/areas; emphasize reach and depth, not volume). No fluff, no "they demonstrated"; say what shipped. <= 40 words.
- "evidence": for each PR in the file, a tightened <= 16-word summary of what that PR did, grounded in its diff.

Return {login, narrative, evidence:[{number, summary}]}.`,
    { label: `narrate:${i}`, phase: 'Narrate', schema: SCHEMA })
))

return { narratives: results.filter(Boolean) }
