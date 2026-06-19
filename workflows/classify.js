export const meta = {
  name: 'classify-prs',
  description: 'LLM-classify candidate PR complexity by reading the actual diff (bounded fan-out)',
  phases: [{ title: 'Classify', detail: 'one agent per batch of PRs' }],
}

const SCHEMA = {
  type: 'object', additionalProperties: false, required: ['classifications'],
  properties: {
    classifications: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['number', 'complexity', 'work_type', 'one_line_summary'],
        properties: {
          number: { type: 'integer' },
          complexity: { type: 'integer', minimum: 1, maximum: 5 },
          work_type: { type: 'string', enum: ['feature', 'bugfix', 'refactor', 'perf', 'infra', 'docs', 'test', 'chore', 'other'] },
          one_line_summary: { type: 'string' },
        },
      },
    },
  },
}

let a = args
if (typeof a === "string") { try { a = JSON.parse(a) } catch (e) { /* leave as string */ } }
a = a || {}
log(`args type=${typeof args} count=${a.count} dir=${a.dir}`)
const batchPaths = a.batchPaths
  || Array.from({ length: Number(a.count) || 0 }, (_, i) => `${a.dir}/b${String(i).padStart(3, "0")}.json`)
log(`resolved ${batchPaths.length} batch paths`)

const PROMPT = (path) => `Read the JSON file at ${path}. It is a list of merged GitHub PRs from PostHog/posthog. Each item has: number, title, body, labels, files (paths), and diff (the actual code change, truncated).

For EACH PR, judge **from the DIFF (the real code)**, not the description's claims:
- **complexity (1-5)** — be strict; most PRs are 1-3:
  1 = trivial/mechanical/formulaic (rename, config, copy-paste fix, dep tweak, a 2-3 file fix that looks like one of many near-identical integration fixes)
  2 = small localized change with minor logic
  3 = substantial feature or fix with real, non-trivial logic
  4 = complex, multi-component change requiring careful design
  5 = deep architectural / algorithmic / cross-cutting work
- **work_type**: feature | bugfix | refactor | perf | infra | docs | test | chore | other
- **one_line_summary**: what it actually accomplished, concrete, <= 18 words.

Return {classifications: [{number, complexity, work_type, one_line_summary}, ...]} covering EVERY PR in the file. If a diff is empty, judge from title/body/files.`

phase('Classify')
const results = await parallel(batchPaths.map((path, i) => () =>
  agent(PROMPT(path), { label: `classify:b${i}`, phase: 'Classify', schema: SCHEMA })
))

const all = results.filter(Boolean).flatMap((r) => r.classifications || [])
// dedupe by number (last wins) in case of any overlap
const byNum = {}
for (const c of all) byNum[c.number] = c
const classifications = Object.values(byNum)

return {
  classifications,
  batches: batchPaths.length,
  batches_returned: results.filter(Boolean).length,
  n_classified: classifications.length,
}
