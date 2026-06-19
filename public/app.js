"use strict";

const fmt = (n) => (n == null ? "—" : n.toLocaleString("en-US"));
const pct = (x) => Math.round((x || 0) * 100);

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// element with INNER HTML (only for trusted/escaped markup)
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
// element with TEXT content (safe for any data-derived string)
const textEl = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const WEIGHTS = { substance: 0.6, review_leverage: 0.3, durability_breadth: 0.1 };
const DIM_META = [
  ["substance", "Shipped substance", "seg-substance", "--substance"],
  ["review_leverage", "Review leverage", "seg-review", "--review"],
  ["durability_breadth", "Durability & breadth", "seg-durability", "--durability"],
];

// only https://github.com/... links are allowed as evidence hrefs
function safeGithubUrl(raw) {
  try {
    const u = new URL(String(raw));
    if (u.protocol === "https:" && u.hostname === "github.com") return u.href;
  } catch (e) { /* invalid */ }
  return null;
}

// round contributions to integers that sum to round(total)
function largestRemainder(vals) {
  const total = Math.round(vals.reduce((a, b) => a + b, 0));
  const floors = vals.map(Math.floor);
  let rem = total - floors.reduce((a, b) => a + b, 0);
  const order = vals.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0]);
  const out = floors.slice();
  for (let j = 0; j < rem && order.length; j++) out[order[j % order.length][1]] += 1;
  return out;
}

function showError(e) {
  document.getElementById("leaderboard").innerHTML =
    '<li class="row"><div class="row-head" style="padding:16px">Could not render the dashboard. See console for details.</div></li>';
  if (e) console.error(e);
}

async function main() {
  let data;
  try {
    const res = await fetch("./dashboard.json", { cache: "no-store" });
    data = await res.json();
  } catch (e) { return showError(e); }
  try {
    renderHeader(data.meta);
    renderBoard(data.engineers || []);
    renderFooter(data.meta);
    wireMethodology(data.meta);
  } catch (e) { showError(e); }
}

function renderHeader(m) {
  document.getElementById("window-label").textContent =
    `Last ${m.window_days} days · ${m.window_start} → ${m.window_end}`;
  const parts = [
    `<b>${fmt(m.total_prs_analyzed)}</b> merged PRs analyzed`,
    `<b>${fmt(m.human_prs)}</b> human-authored`,
    `<b>${fmt(m.total_engineers)}</b> engineers`,
    `<b>${fmt(m.candidates_llm_classified)}</b> finalists deep-analyzed`,
    `<b>${fmt(m.prs_llm_classified)}</b> PRs LLM-read`,
  ];
  document.getElementById("statline").innerHTML = parts.join('<span class="dot">·</span>');
  document.getElementById("ai-banner").innerHTML =
    `⚡ <b>AI-assisted authorship is the norm at PostHog</b> — ~${pct(m.ai_assisted_pct_repo)}% of PRs carry agent ` +
    `signatures. That's exactly why a "most PRs/commits" ranking is meaningless here, and why ` +
    `we rank by <b>measured reach × substance</b> instead of volume.`;
}

function methodologyHTML(m) {
  const ca = (m.central_areas || [])
    .map((a) => `<code>${escapeHtml(a.area)}</code> (${a.distinct_authors})`).join(", ");
  return `
    <h3>How the impact score is computed</h3>
    <p class="formula">Composite = 0.6 · Substance + 0.3 · Review leverage + 0.1 · Durability/breadth (each scaled 0–1 within the analyzed cohort, ×100)</p>
    <ul>
      <li><b>Shipped substance</b> — for each PR an LLM <i>reads the actual diff</i> and rates complexity 1–5
          on a convex scale (a complexity-1 / formulaic change scores ~0). That's multiplied by <b>reach</b>
          and a critical-path boost, counted over each engineer's top-30 PRs, and aggregated concavely
          (breadth across areas rewarded; within-area volume gets diminishing returns).</li>
      <li><b>Reach is measured, not guessed</b> — the number of <i>distinct engineers</i> who touch a code
          area over the window. Shared core (${ca}) scores high; isolated single-team work scores low.
          Generated/lock/CI/snapshot files are excluded.</li>
      <li><b>Review leverage</b> — substantive reviews on others' non-trivial PRs (changes-requested &gt;
          comment &gt; approve), weighted by the reach of the reviewed PR; a PR's value is split across its
          reviewers. Bots and self-reviews excluded.</li>
      <li><b>Durability &amp; breadth</b> — distinct core areas the engineer meaningfully touched.</li>
      <li><b>Scores are relative within the analyzed cohort</b> — ${escapeHtml(m.scoring_note || "")}. The
          breakdown bar below each engineer decomposes the score exactly.</li>
      <li><b>What we do <u>not</u> claim</b> — GitHub has no production-outcome data (incidents, usage, revenue),
          and PR labels/issue-links are unused at PostHog, so we don't claim to measure business outcome. We
          measure <i>doing high-leverage engineering work</i>, and every score links to the PRs so you can verify it.</li>
      <li><b>Finalist selection</b> — a generous union (top substance ∪ top reviewers ∪ critical-path / high-reach
          authors ∪ anyone with a top-decile single PR), so a "few-but-deep" engineer is never cut before the LLM
          reads them. ${fmt(m.candidates_llm_classified)} of ${fmt(m.total_engineers)} engineers reached deep analysis.</li>
    </ul>`;
}

function renderBoard(engineers) {
  const board = document.getElementById("leaderboard");
  board.innerHTML = "";
  engineers.slice(0, 5).forEach((eng) => board.appendChild(rowFor(eng)));
}

function rowFor(eng) {
  const li = el("li", "row");
  li.setAttribute("open-state", "0");

  const head = el("button", "row-head");
  head.setAttribute("aria-expanded", "false");
  const composite = Math.round(eng.composite || 0);

  head.appendChild(el("div", "rank", `${eng.rank}`));

  const img = el("img", "avatar");
  img.src = safeGithubUrl(eng.avatar_url) || `https://github.com/${encodeURIComponent(eng.login)}.png`;
  img.alt = "";
  img.loading = "lazy";
  head.appendChild(img);

  const who = el("div", "who");
  who.appendChild(textEl("div", "login", eng.login));
  who.appendChild(textEl("div", "narrative", eng.narrative || ""));
  head.appendChild(who);

  const scoreWrap = el("div", "score-wrap");
  const bar = el("div", "score-bar");
  bar.appendChild(el("div", "score-fill")).style.width = `${composite}%`;
  scoreWrap.appendChild(bar);
  scoreWrap.appendChild(el("div", "score-num", `${composite}`));
  head.appendChild(scoreWrap);

  head.appendChild(el("div", "chev", "▸"));
  li.appendChild(head);
  li.appendChild(detailFor(eng));

  head.addEventListener("click", () => {
    const open = li.getAttribute("open-state") === "1";
    li.setAttribute("open-state", open ? "0" : "1");
    head.setAttribute("aria-expanded", open ? "false" : "true");
  });
  return li;
}

function detailFor(eng) {
  const detail = el("div", "detail");
  const grid = el("div", "detail-grid");
  const dims = eng.dimensions || {};

  // weighted contributions (each dim ∈[0,1]) × 100 — these sum EXACTLY to the composite
  const exact = DIM_META.map(([k]) => WEIGHTS[k] * (dims[k] || 0) * 100);
  const rounded = largestRemainder(exact);

  const left = el("div");
  left.appendChild(el("div", "breakdown-title", "Score breakdown (these add up to the score)"));
  const stack = el("div", "stack");
  DIM_META.forEach(([, , segCls], i) => {
    const seg = el("span", segCls);
    seg.style.width = `${exact[i]}%`;        // bar fills to the composite, decomposed
    stack.appendChild(seg);
  });
  left.appendChild(stack);

  const legend = el("div", "legend");
  DIM_META.forEach(([, label, , cssVar], i) => {
    legend.appendChild(el("span", null,
      `<i style="background:var(${cssVar})"></i>${escapeHtml(label)} <b>${rounded[i]}</b>`));
  });
  left.appendChild(legend);

  // context chips
  const s = eng.stats || {};
  const mix = Object.entries(s.work_type_mix || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([k, v]) => `${escapeHtml(k)} ${v}`).join(" · ");
  const chips = el("div", "chips");
  const chip = (h) => chips.appendChild(el("span", "chip", h));
  chip(`<b>${fmt(s.prs_merged)}</b> PRs merged`);
  chip(`<b>${fmt(s.non_trivial_prs)}</b> non-trivial`);
  chip(`<b>${fmt(s.reviews_given)}</b> reviews given`);
  chip(`<b>${pct(s.ai_assisted_pct)}%</b> AI-assisted`);
  if (s.median_pr_substance != null) chip(`median substance <b>${escapeHtml(s.median_pr_substance)}</b>`);
  if (mix) chip(mix);
  if ((s.core_areas || []).length) chip(`areas: <b>${escapeHtml(s.core_areas.join(", "))}</b>`);
  left.appendChild(chips);
  grid.appendChild(left);

  // evidence
  const right = el("div");
  right.appendChild(el("div", "evidence-title", "Evidence — representative PRs (click to verify)"));
  const ul = el("ul", "evidence");
  (eng.evidence || []).forEach((ev) => {
    const li = el("li", "ev");
    const tags =
      (ev.critical ? '<span class="tag tag-crit">critical path</span>' : "") +
      (ev.reach ? `<span class="tag tag-reach">reach ${escapeHtml(ev.reach)}</span>` : "");
    const url = safeGithubUrl(ev.url);
    const titleText = `#${ev.pr} ${ev.title || ""}`;
    const link = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(titleText)}</a>`
      : `<span>${escapeHtml(titleText)}</span>`;
    li.innerHTML = `${tags}${link}<div class="ev-sum">${escapeHtml(ev.summary || "")}</div>`;
    ul.appendChild(li);
  });
  right.appendChild(ul);
  grid.appendChild(right);

  detail.appendChild(grid);
  return detail;
}

function renderFooter(m) {
  const f = document.getElementById("footer");
  const html =
    `Data: all <code>${fmt(m.total_prs_analyzed)}</code> PRs merged to ` +
    `<code>${escapeHtml(m.repo)}</code> in the window (verified against GitHub's authoritative count). ` +
    `Bots excluded. Generated ${escapeHtml(m.generated_at)}.`;
  f.innerHTML = m.is_stub
    ? `<div class="stub-flag">⚠️ STUB DATA — placeholder numbers for layout verification.</div>` + html
    : html;
}

function wireMethodology(meta) {
  const btn = document.getElementById("how-btn");
  const panel = document.getElementById("methodology");
  panel.innerHTML = methodologyHTML(meta);
  btn.addEventListener("click", () => {
    const open = !panel.hidden;
    panel.hidden = open;
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    btn.textContent = open ? "How this is computed ▸" : "How this is computed ▾";
  });
}

main();
