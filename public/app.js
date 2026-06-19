"use strict";

const fmt = (n) => (n == null ? "—" : n.toLocaleString("en-US"));
const pct = (x) => Math.round((x || 0) * 100);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};

const WEIGHTS = { substance: 0.6, review_leverage: 0.3, durability_breadth: 0.1 };
const DIM_META = [
  ["substance", "Substance", "seg-substance", "--substance"],
  ["review_leverage", "Review leverage", "seg-review", "--review"],
  ["durability_breadth", "Durability & breadth", "seg-durability", "--durability"],
];

async function main() {
  let data;
  try {
    const res = await fetch("./dashboard.json", { cache: "no-store" });
    data = await res.json();
  } catch (e) {
    document.getElementById("leaderboard").innerHTML =
      '<li class="row"><div class="row-head">Failed to load dashboard.json</div></li>';
    return;
  }
  renderHeader(data.meta);
  renderBoard(data.engineers || []);
  renderFooter(data.meta);
  wireMethodology();
}

function renderHeader(m) {
  document.getElementById("window-label").textContent =
    `Last ${m.window_days} days · ${m.window_start} → ${m.window_end}`;

  const stat = document.getElementById("statline");
  const parts = [
    `<b>${fmt(m.total_prs_analyzed)}</b> merged PRs analyzed`,
    `<b>${fmt(m.human_prs)}</b> human-authored`,
    `<b>${fmt(m.total_engineers)}</b> engineers`,
    `<b>${fmt(m.candidates_llm_classified)}</b> finalists deep-analyzed`,
    `<b>${fmt(m.prs_llm_classified)}</b> PRs LLM-read`,
  ];
  stat.innerHTML = parts.join('<span class="dot">·</span>');

  const aiPct = pct(m.ai_assisted_pct_repo);
  document.getElementById("ai-banner").innerHTML =
    `⚡ <b>AI-assisted authorship is the norm at PostHog</b> — ~${aiPct}% of PRs carry agent ` +
    `signatures. That's exactly why a "most PRs/commits" ranking is meaningless here, and why ` +
    `we rank by <b>measured reach × substance</b> instead of volume.`;
}

function methodologyHTML(m) {
  const ca = (m.central_areas || [])
    .map((a) => `<code>${a.area}</code> (${a.distinct_authors})`).join(", ");
  return `
    <h3>How the impact score is computed</h3>
    <p class="formula">Composite = 0.6 · Substance + 0.3 · Review leverage + 0.1 · Durability/breadth</p>
    <ul>
      <li><b>Substance</b> — for each PR, an LLM <i>reads the actual diff</i> and rates complexity (1–5).
          That's multiplied by <b>reach</b> and a critical-path boost, then aggregated concavely
          (breadth across areas rewarded; within-area volume gets diminishing returns). Trivial /
          generated / stacked one-line PRs score ~0, so high volume alone earns little.</li>
      <li><b>Reach is measured, not guessed</b> — the number of <i>distinct engineers</i> who touch a
          code area over the window. Shared core (${ca}) scores high; isolated single-team work scores low.
          Generated/lock/CI/snapshot files are excluded.</li>
      <li><b>Review leverage</b> — substantive reviews on others' non-trivial PRs (changes-requested &gt;
          comment &gt; bare approve), weighted by the reach of the reviewed PR. A PR's review value is
          split across its reviewers, so it can't be multiplied across a crowd.</li>
      <li><b>Durability &amp; breadth</b> — distinct core areas owned, minus a small penalty for faulty self-reverts.</li>
      <li><b>Scores are relative within the analyzed cohort</b> — <i>${m.scoring_note || "100 = highest among analyzed"}</i>.</li>
      <li><b>What we do <u>not</u> claim</b> — GitHub has no production-outcome data (incidents, usage, revenue),
          and PR labels/issue-links are unused at PostHog, so we don't claim to measure business outcome. We measure
          <i>doing high-leverage engineering work</i>, and every score links to the PRs so you can verify it.</li>
      <li><b>How finalists are chosen</b> — a generous union (top by substance ∪ top reviewers ∪ anyone with a
          critical-path / high-reach PR ∪ anyone with a top-decile single PR) so a "few-but-deep" engineer is never
          cut before the LLM reads them. ${fmt(m.candidates_llm_classified)} of ${fmt(m.total_engineers)} engineers reached deep analysis.</li>
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

  // ---- collapsed head ----
  const head = el("button", "row-head");
  head.setAttribute("aria-expanded", "false");

  const composite = Math.round(eng.composite || 0);
  head.appendChild(el("div", "rank", `${eng.rank}`));

  const img = el("img", "avatar");
  img.src = eng.avatar_url || "https://github.com/github.png";
  img.alt = "";
  img.loading = "lazy";
  head.appendChild(img);

  const who = el("div", "who");
  who.appendChild(el("div", "login", eng.login));
  who.appendChild(el("div", "narrative", eng.narrative || ""));
  head.appendChild(who);

  const scoreWrap = el("div", "score-wrap");
  const bar = el("div", "score-bar");
  bar.appendChild(el("div", "score-fill")).style.width = `${composite}%`;
  scoreWrap.appendChild(bar);
  scoreWrap.appendChild(el("div", "score-num", `${composite}`));
  head.appendChild(scoreWrap);

  head.appendChild(el("div", "chev", "▸"));
  li.appendChild(head);

  // ---- expanded detail ----
  li.appendChild(detailFor(eng, composite));

  head.addEventListener("click", () => {
    const open = li.getAttribute("open-state") === "1";
    li.setAttribute("open-state", open ? "0" : "1");
    head.setAttribute("aria-expanded", open ? "false" : "true");
  });
  return li;
}

function detailFor(eng, composite) {
  const detail = el("div", "detail");
  const grid = el("div", "detail-grid");

  // left: dimension breakdown + chips
  const left = el("div");
  left.appendChild(el("div", "breakdown-title", "Score breakdown (weighted contributions)"));

  const dims = eng.dimensions || {};
  const raw = DIM_META.reduce((s, [k]) => s + WEIGHTS[k] * (dims[k] || 0), 0);
  const factor = raw > 0 ? composite / raw : 0; // make segments sum to the displayed composite
  const stack = el("div", "stack");
  DIM_META.forEach(([k, , segCls]) => {
    const contrib = WEIGHTS[k] * (dims[k] || 0) * factor;
    const seg = el("span", segCls);
    seg.style.width = `${contrib}%`;
    stack.appendChild(seg);
  });
  left.appendChild(stack);

  const legend = el("div", "legend");
  DIM_META.forEach(([k, label, , cssVar]) => {
    const contrib = Math.round(WEIGHTS[k] * (dims[k] || 0) * factor);
    legend.appendChild(
      el("span", null,
        `<i style="background:var(${cssVar})"></i>${label} <b>${contrib}</b>`)
    );
  });
  left.appendChild(legend);

  // context chips
  const s = eng.stats || {};
  const mix = Object.entries(s.work_type_mix || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([k, v]) => `${k} ${v}`).join(" · ");
  const chips = el("div", "chips");
  const chip = (h) => chips.appendChild(el("span", "chip", h));
  chip(`<b>${fmt(s.prs_merged)}</b> PRs merged`);
  chip(`<b>${fmt(s.non_trivial_prs)}</b> non-trivial`);
  chip(`<b>${fmt(s.reviews_given)}</b> reviews given`);
  chip(`<b>${pct(s.ai_assisted_pct)}%</b> AI-assisted`);
  if (s.median_pr_substance != null) chip(`median substance <b>${s.median_pr_substance}</b>`);
  if (mix) chip(mix);
  if ((s.core_areas || []).length) chip(`areas: <b>${s.core_areas.join(", ")}</b>`);
  left.appendChild(chips);
  grid.appendChild(left);

  // right: evidence PRs
  const right = el("div");
  right.appendChild(el("div", "evidence-title", "Evidence — representative PRs (click to verify)"));
  const ul = el("ul", "evidence");
  (eng.evidence || []).forEach((ev) => {
    const li = el("li", "ev");
    const tags =
      (ev.critical ? '<span class="tag tag-crit">critical path</span>' : "") +
      (ev.reach ? `<span class="tag tag-reach">reach ${ev.reach}</span>` : "");
    li.innerHTML =
      `${tags}<a href="${ev.url}" target="_blank" rel="noopener">#${ev.pr} ${escapeHtml(ev.title || "")}</a>` +
      `<div class="ev-sum">${escapeHtml(ev.summary || "")}</div>`;
    ul.appendChild(li);
  });
  right.appendChild(ul);
  grid.appendChild(right);

  detail.appendChild(grid);
  return detail;
}

function renderFooter(m) {
  const f = document.getElementById("footer");
  let html =
    `Data: all <code>${m.total_prs_analyzed?.toLocaleString?.() || m.total_prs_analyzed}</code> PRs merged to ` +
    `<code>${m.repo}</code> in the window (verified against GitHub's authoritative count). ` +
    `Bots excluded. Generated 2026-06-20.`;
  if (m.is_stub) {
    f.innerHTML = `<div class="stub-flag">⚠️ STUB DATA — placeholder numbers for layout verification; real analysis pending.</div>` + html;
  } else {
    f.innerHTML = html;
  }
  // store meta for methodology panel
  f.dataset.ready = "1";
}

function wireMethodology() {
  const btn = document.getElementById("how-btn");
  const panel = document.getElementById("methodology");
  fetch("./dashboard.json", { cache: "no-store" })
    .then((r) => r.json())
    .then((d) => { panel.innerHTML = methodologyHTML(d.meta); });
  btn.addEventListener("click", () => {
    const open = !panel.hidden;
    panel.hidden = open;
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    btn.textContent = open ? "How this is computed ▸" : "How this is computed ▾";
  });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

main();
