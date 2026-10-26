// FOMC Tone Lab dashboard. No build step: plain ES module + vendored ECharts.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const local = {
  get(k, d) { try { const v = localStorage.getItem("fomc." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("fomc." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const TYPES = { statement: "Statements", minutes: "Minutes", presser: "Press conferences", speech: "Board speeches" };
const ONE = { statement: "Statement", minutes: "Minutes", presser: "Press conference", speech: "Speech" };
const DIMS = ["policy_action", "forward_guidance", "inflation_assessment", "activity_labor_assessment", "risk_balance", "balance_sheet"];
const OUTCOMES = { d3m: "3m", d2y: "2y", d5y: "5y", d10y: "10y", d30y: "30y", dslope: "2s10s", pre_d2y: "Day before", drift5_d2y: "Next 5 days", drift20_d2y: "Next 20 days" };
const OUTCOME_LONG = { d3m: "3-month bill over the release window", d2y: "2-year over the release window", d5y: "5-year over the release window", d10y: "10-year over the release window", d30y: "30-year over the release window", dslope: "10y minus 2y slope over the release window", pre_d2y: "2-year on the day before the window opens (placebo)", drift5_d2y: "2-year over the 5 days after the window", drift20_d2y: "2-year over the 20 days after the window" };
const TENORS = ["d3m", "d2y", "d5y", "d10y", "d30y"];
const ROBUST = { base: ["all", "none", "Baseline"], d3m: ["all", "d3m", "+ 3-month bill control"], decision: ["all", "decision", "+ rate decision control"],
  baseline: ["all", "baseline", "+ TF-IDF tone (Claude)"], presser: ["all", "presser", "+ press conference tone (statements)"], no_presser: ["no_presser", "none", "No press conference (statements)"],
  development: ["development", "none", "2009-2019 only"], holdout: ["holdout", "none", "2020 onward only"] };
const ROBUST_OUTCOMES = ["d2y", "d5y", "d10y", "dslope"];
const GROUPS = { statement: "Statements", minutes: "Minutes", presser: "Press conferences", speech: "Speeches, all", speech_chair: "Speeches: Chair", speech_other: "Speeches: other members" };
const GROUP_SHORT = { statement: "Statements", minutes: "Minutes", presser: "Pressers", speech: "Speeches", speech_chair: "Chair", speech_other: "Other members" };
const state = { method: local.get("method", null), overview: null, settings: null, page: "overview", doc: null, durationInputs: null, durationSource: null, durationAppliedDoc: null, durationRuleApplied: false };
const dash = "–";
const NAV = {
  home: { title: "Home", pages: [["overview", "Home"]] },
  fed: { title: "Fed now", pages: [["fed", "Rates and the Committee"], ["tracker", "Decisions"]] },
  documents: { title: "Documents", pages: [["documents", "Search"], ["live", "Score a text"]] },
  research: { title: "Research", pages: [["event-study", "Event study"], ["forecast", "Next decision"], ["validity", "Validity"], ["label", "Team labels"]] },
  duration: { title: "Duration", pages: [["duration", "Signal to exposure"], ["backtest", "Historical test"], ["forward", "Forward test"]] },
  system: { title: "System", pages: [["system", "Data"], ["pipeline", "Pipeline"], ["settings", "Settings"]] },
}; // the Story is not a section: the deck lives apart, at /story
const PAGE_GROUP = Object.fromEntries(Object.entries(NAV).flatMap(([g, v]) => v.pages.map(([p]) => [p, g])));
const TIME_SOURCE = { document_text: "time printed in the document", speech_json: "time from the Fed's speech feed", calendar: "release date on the FOMC calendar", convention: "standard press-conference time", default: "standard release time" };

// ------------------------------------------------------------------ utilities
// GET responses are kept for a short while and shared between callers (stale-while-revalidate),
// so moving between pages is instant; the server's ETags make each revalidation a cheap 304.
const cache = new Map(); const FRESH_MS = 60000;
const busy = { n: 0, set(d) { this.n = Math.max(0, this.n + d); document.documentElement.classList.toggle("loading", this.n > 0); } };
async function request(path, opts) {
  busy.set(1);
  try {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return await res.json();
  } finally { busy.set(-1); }
}
async function api(path, opts = {}) {
  if (opts.method && opts.method !== "GET") { const out = await request(path, opts); cache.clear(); return out; }
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.promise;
  const promise = request(path, opts);
  cache.set(path, { at: Date.now(), promise });
  promise.catch(() => cache.delete(path));
  if (hit) { try { return await promise; } catch { return hit.promise; } }  // stale copy if the network fails
  return promise;
}
const PREFETCH = { story: ["/api/story"], overview: ["/api/overview", "/api/pulse", "/api/findings", "/api/fed"], fed: ["/api/fed"], tracker: ["/api/tracker"],
  "event-study": ["/api/event-study"], backtest: ["/api/backtests"], duration: ["/api/duration"], forecast: ["/api/forecast"], forward: ["/api/forward"], validity: ["/api/validity", "/api/labels/summary", "/api/reliability"], label: ["/api/labels/summary"],
  system: ["/api/system"], pipeline: ["/api/pipeline"] };
function prefetch(page) { (PREFETCH[page] || []).forEach((u) => api(u).catch(() => {})); }
const linkPage = (a) => (a.getAttribute("href") || "").replace(/^#\//, "").split("?")[0];
document.addEventListener("pointerover", (e) => { const a = e.target.closest?.("#nav a, #page-tabs a"); if (a) prefetch(linkPage(a)); });
document.addEventListener("focusin", (e) => { const a = e.target.closest?.("#nav a, #page-tabs a"); if (a) prefetch(linkPage(a)); });

// View state in the URL (#/page?key=value), so any filtered view can be shared or bookmarked.
function viewParams() { return new URLSearchParams(location.hash.split("?")[1] || ""); }
function setViewParams(obj) {
  const p = viewParams();
  Object.entries(obj).forEach(([k, v]) => (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length) ? p.delete(k) : p.set(k, Array.isArray(v) ? v.join(",") : v)));
  const q = p.toString();
  history.replaceState(null, "", `#/${state.page}${q ? "?" + q : ""}`);
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2600); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
// a date string, or a chart's time-axis value (a timestamp), as YYYY-MM-DD in local time
const isoDay = (d) => { if (typeof d !== "number") return String(d).slice(0, 10); const t = new Date(d); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };
const fmt = {
  date: (d) => (d ? new Date(isoDay(d) + "T12:00:00").toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : dash),
  num: (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? dash : Number(v).toFixed(d)),
  signed: (v, d = 2) => {  // a true minus sign: a hyphen reads short and detached at display sizes
    if (v === null || v === undefined || Number.isNaN(Number(v))) return dash;
    const s = Number(v).toFixed(d);
    return Number(s) > 0 ? "+" + s : Number(s) < 0 ? "\u2212" + s.slice(1) : s.replace("-", "");
  },
  int: (v) => (v === null || v === undefined ? dash : Number(v).toLocaleString("en-US")),
  short: (d) => (d ? new Date(isoDay(d) + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : dash),
  money: (v) => "$" + Number(v || 0).toFixed(2),
  ago: (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return "just now"; if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago"; return Math.round(s / 86400) + " days ago";
  },
};
function methodLabel(m) {
  if (!m) return dash;
  if (m.startsWith("llm:")) return "Claude " + m.split(":")[1].replace("claude-", "").replace(/^(\w)(\w*)-(\d+)-(\d+)$/, (_, a, b, c, d) => a.toUpperCase() + b + " " + c + "." + d);
  if (m.startsWith("llmshift:")) return "Claude vs previous statement";
  if (m.startsWith("shift:")) return methodLabel(m.slice(6)) + ", shift";
  return { dictionary: "Dictionary", supervised: "TF-IDF classifier", embedding: "Sentence embeddings", roberta_tuned: "Fine-tuned RoBERTa", fomc_roberta: "FOMC-RoBERTa" }[m] || m;
}
function scale(m) { return m && m.startsWith("supervised") ? 2.5 : m && m.startsWith("llmshift") ? 0.5 : 1; }
function scoreStyle(v, m) {
  if (v === null || v === undefined) return "background:var(--surface-2);color:var(--muted)";
  const t = Math.max(-1, Math.min(1, v * scale(m)));
  const a = Math.abs(t);
  if (a < 0.05) return "background:color-mix(in srgb, var(--neutral) 55%, var(--surface));color:var(--text-2)";  // no lean either way
  return `background:color-mix(in srgb, ${t >= 0 ? "var(--hawk)" : "var(--dove)"} ${Math.round(10 + a * 38)}%, var(--surface));color:var(--text)`;  // a tint under dark text: readable at any strength
}
const scoreChip = (v, m) => `<span class="score" style="${scoreStyle(v, m)}">${fmt.signed(v)}</span>`;
const typeBadge = (t) => `<span class="badge"><i style="background:var(--t-${t})"></i>${ONE[t] || t}</span>`;
function delta(v) { if (v === null || v === undefined) return `<span class="muted">${dash}</span>`; return `<span class="delta ${v > 0 ? "up" : v < 0 ? "down" : ""}">${fmt.signed(v, 1)}</span>`; }
function empty(title, body) { return `<div class="empty"><b>${title}</b><span>${body}</span></div>`; }
const code = (cmd) => `<span class="code"><span>${esc(cmd).replace(/-/g, "\u2011")}</span><button data-copy="${esc(cmd)}">copy</button></span>`;
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (b) { navigator.clipboard?.writeText(b.dataset.copy).then(() => toast("Copied")); }
});

// ------------------------------------------------------------ info tooltips
// Secondary text lives behind an (i): hover on a desktop, tap on a phone.
const info = (html) => `<button type="button" class="tipbtn" aria-label="More information" data-tip="${esc(html)}">i</button>`;
function tipFor(btn) { return btn.dataset.tipHtml ?? btn.dataset.tip; }
function infoButton(html) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "tipbtn"; b.setAttribute("aria-label", "More information"); b.textContent = "i";
  b.dataset.tipHtml = html; return b;
}
function tuck(root) {
  const keep = (el) => el.id || el.classList.contains("keep") || !el.textContent.trim();
  root.querySelectorAll(".sub").forEach((el) => {
    const head = el.previousElementSibling;
    if (keep(el) || !head || !/^H[1-3]$/.test(head.tagName)) return;
    head.append(infoButton(el.innerHTML)); el.remove();
  });
  [[".kpi .foot", ".label"], [".insight .det", ".lbl"], [".mkt .sub", ".label"]].forEach(([sel, target]) => {
    root.querySelectorAll(sel).forEach((el) => {
      const card = el.closest(".kpi, .insight, .mkt"); const t = card && card.querySelector(target);
      if (keep(el) || !t || (sel === ".kpi .foot" && el.textContent.trim().length <= 72)) return;
      t.append(infoButton(el.innerHTML)); el.remove();
    });
  });
}
const tip = { el: null, pinned: null };
function showTip(btn) {
  if (!tip.el) { tip.el = document.createElement("div"); tip.el.id = "tip"; tip.el.setAttribute("role", "tooltip"); document.body.append(tip.el); }
  tip.el.innerHTML = tipFor(btn);  // our own markup: server values are escaped where they are rendered
  tip.el.classList.add("show");
  const r = btn.getBoundingClientRect(); const w = tip.el.offsetWidth; const h = tip.el.offsetHeight;
  let left = Math.min(window.innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
  let top = r.bottom + 8; if (top + h > window.innerHeight - 10) top = r.top - h - 8;
  tip.el.style.left = left + "px"; tip.el.style.top = top + "px";
}
function hideTip() { if (tip.el) tip.el.classList.remove("show"); tip.pinned = null; }
document.addEventListener("mouseover", (e) => { const b = e.target.closest(".tipbtn"); if (b && !tip.pinned) showTip(b); });
document.addEventListener("mouseout", (e) => { const b = e.target.closest(".tipbtn"); if (b && !tip.pinned && !b.contains(e.relatedTarget)) hideTip(); });
document.addEventListener("focusin", (e) => { const b = e.target.closest?.(".tipbtn"); if (b) showTip(b); });
document.addEventListener("focusout", (e) => { if (e.target.closest?.(".tipbtn") && !tip.pinned) hideTip(); });
document.addEventListener("click", (e) => {
  const b = e.target.closest(".tipbtn");
  if (b) { e.preventDefault(); e.stopPropagation(); if (tip.pinned === b) hideTip(); else { showTip(b); tip.pinned = b; } return; }
  if (tip.pinned) hideTip();
}, true);
window.addEventListener("scroll", () => { if (!tip.pinned) hideTip(); }, true);

// --------------------------------------------------------------------- charts
const charts = new Set();
function mk(el) {
  const c = echarts.init(el, null, { renderer: "canvas", ...(state.chartDpr ? { devicePixelRatio: state.chartDpr } : {}) }); charts.add(c);
  // follow the chart's own box, not only the window: a drawer going full screen, the sidebar folding
  if (window.ResizeObserver) {
    let seen = false;
    c.__ro = new ResizeObserver(() => { if (seen && !c.isDisposed()) c.resize(); seen = true; });
    c.__ro.observe(el);
  }
  // a chart is an image to assistive technology, named after its card; the tables carry the numbers
  const name = el.closest(".card")?.querySelector("h2, h3")?.textContent.trim() || el.previousElementSibling?.textContent.trim() || "Chart";
  el.setAttribute("role", "img"); el.setAttribute("aria-label", name);
  return c;
}
function clearCharts() { charts.forEach((c) => { c.__ro?.disconnect(); c.dispose(); }); charts.clear(); }
window.addEventListener("resize", () => charts.forEach((c) => c.resize()));
function axis(extra = {}) {
  return { axisLine: { lineStyle: { color: css("--border") } }, axisTick: { show: false },
    axisLabel: { color: css("--text-2"), fontSize: 11 }, splitLine: { lineStyle: { color: css("--grid") } }, ...extra };
}
function base(extra = {}) {
  // no animation for people who opt out, nor when a slide is being rendered to an image (headless Chrome)
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches && !viewParams().get("export");
  const out = { animation: motion, animationDuration: 350, textStyle: { fontFamily: css("--chart-font") || "inherit" }, grid: { left: 52, right: 20, top: 26, bottom: 34 },
    toolbox: { right: 0, top: -4, itemSize: 13, iconStyle: { borderColor: css("--muted") }, emphasis: { iconStyle: { borderColor: css("--accent") } },
      feature: { saveAsImage: { title: "Save PNG", pixelRatio: 2, backgroundColor: css("--surface"), name: "fomc-tone-lab" } } },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 } },
    ...extra };
  // the save icon sits above the plot, never on its newest points; a phone has no use for it
  if (window.matchMedia("(max-width: 700px)").matches) delete out.toolbox;
  else {
    const g = Array.isArray(out.grid) ? out.grid[0] : out.grid;
    if (g && typeof g.top === "number" && g.top < 24 && out.toolbox) g.top = 24;
  }
  // a legend stays on one line (paging when narrow), so on a phone it never wraps over the axis
  if (out.legend && !Array.isArray(out.legend) && !out.legend.type) {
    out.legend = { type: "scroll", pageIconSize: 10, pageIconColor: css("--text-2"), pageTextStyle: { color: css("--text-2") }, ...out.legend };
  }
  return out;
}

const SOURCE_VIEWS={overview:["fed","fred","treasury","yahoo","nyfed"],fed:["fed","nyfed","fred","treasury"],documents:["fed"],"event-study":["fed","fred","treasury","tdw"],duration:["fed","yahoo"],system:null,pipeline:null};
async function sourceFooter(view,name) {
  if(!(name in SOURCE_VIEWS)) return;
  const result=await api("/api/sources").catch(()=>null);if(!result||!view.isConnected) return;
  const ids=SOURCE_VIEWS[name],list=result.sources.filter(x=>!ids||ids.includes(x.id));
  const footer=document.createElement("section");footer.className="card source-card";
  footer.innerHTML=`<div class="card-head"><div><h2>Data sources</h2><p class="small muted">Public inputs, with source roles and dates from this store.</p></div><span class="pill-mini">Research frozen ${esc(result.research_freeze)}</span></div><div class="source-badges">${list.map(x=>`<a class="source-badge" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer" title="${esc(x.detail)}"><span class="source-mark">${esc(x.mark)}</span><span><b>${esc(x.name)}</b><small>${esc(x.role)}${x.as_of?` · ${esc(x.as_of)}`:""}</small><small>${esc(x.detail)}</small></span><svg class="ic" aria-hidden="true"><use href="#i-external-link"/></svg></a>`).join("")}</div>`;
  view.append(footer);
}

// ---------------------------------------------------------------------- pages
const pages = {};

const VERDICT_ICON = { Supported: ["ok", "#i-check"], "Not supported": ["no", "#i-x"], Mixed: ["mixed", "#i-minus"] };
const minus = (s) => String(s).replace(/^-/, "−");
pages.overview = {
  title: "Home", sub: "How the Fed sounds now, what the Treasury market prices, and what the research found. Every number here is computed from the project's store.",
  async render(view) {
    const [pulse, fed, finds, ov] = await Promise.all([api("/api/pulse"), api("/api/fed"), api("/api/findings"), api("/api/overview")]);
    state.overview = ov;
    const r = Object.fromEntries(pulse.readings.map((x) => [x.doc_type, x]));
    const mood = pulse.mood || "balanced";
    const tone = (p) => (p >= 60 ? "hawk" : p <= 40 ? "dove" : "");
    const m = r.minutes;
    const lead = !m ? "Run the pipeline to see where Fed language sits."
      : m.percentile >= 50 ? `The latest minutes, released ${fmt.date(m.date)}, read more hawkish than <b>${Math.round(m.percentile)}%</b> of every set since 2009.`
        : `The latest minutes, released ${fmt.date(m.date)}, read more dovish than <b>${Math.round(100 - m.percentile)}%</b> of every set since 2009.`;
    const rows = ["statement", "minutes", "presser", "speech"].filter((t) => r[t]).map((t) => { const x = r[t]; const c = tone(x.percentile);
      return `<button type="button" class="pulse-row" data-doc="${x.doc_id}"><span class="name">${t === "speech" ? "Speeches" : ONE[t]} <small>${t === "speech" ? "last 25" : fmt.short(x.date)}</small></span>
        <span class="bar" aria-hidden="true"><i class="${c}" style="width:${Math.max(2, x.percentile)}%"></i></span><b class="${c}">${ordinal(x.percentile)}</b></button>`; }).join("");
    const cur = fed.current; const lean = fed.market ? fed.market.t2y_minus_effr_bp : null; const nm = pulse.next_meeting;
    const move = !cur ? dash : cur.action === 0 ? "Hold" : `${cur.change_bp > 0 ? "+" : "−"}${Math.abs(cur.change_bp)} bp`;
    const moveCls = !cur || cur.action === 0 ? "" : cur.change_bp > 0 ? "hawk" : "dove";
    const range = cur ? `${cur.range_low.toFixed(2)}–${cur.range_high.toFixed(2)}%` : "";
    const leanWord = lean === null ? "" : lean > 25 ? "more hikes" : lean < -25 ? "cuts" : "little change";
    const policy = [
      ["Latest decision", move, moveCls, cur ? `${cur.action === 0 ? "kept at" : "to"} ${range} on ${fmt.date(cur.date)}, by ${cur.vote.replace("–", " votes to ")}` : "", "#/tracker"],
      ["Next decision", nm ? fmt.short(nm.date) : dash, "", nm ? `in ${nm.days} day${nm.days === 1 ? "" : "s"}; statement at 2:00 p.m., press conference at 2:30` : "", "#/fed"],
      ["What the market prices", lean === null ? dash : `${minus(fmt.signed(lean, 0))} bp`, tone(lean > 25 ? 100 : lean < -25 ? 0 : 50),
        lean === null ? "" : `the 2-year (${fmt.num(fed.market.t2y)}%) over the overnight rate (${fmt.num(fed.effr.effr)}%) on ${fmt.short(fed.market.date)}: ${leanWord}`, "#/fed"],
    ];
    const latest = (ov.latest || []).slice(0, 5).map((d) => { // the API leaves out speeches that are not about policy
      const word = d.score > 0.15 ? "hawkish" : d.score < -0.15 ? "dovish" : "balanced";
      const pill = d.score === null || d.score === undefined ? '<span class="tone-pill">Not scored</span>'
        : `<span class="tone-pill" style="${scoreStyle(d.score, state.method)}">${fmt.signed(d.score)} <small>${word}</small></span>`;
      const who = esc(d.speaker || "FOMC");
      return `<button type="button" class="latest-row" data-doc="${d.doc_id}"><span class="when">${fmt.short(d.release_date)}</span><span class="what"><b>${esc(d.title || ONE[d.doc_type])}</b><small><span class="when-inline">${fmt.short(d.release_date)} &middot; </span>${d.title ? `${ONE[d.doc_type]} &middot; ${who}` : who}</small></span>${pill}</button>`; }).join("");
    view.innerHTML = `
      <section class="card home-pulse" aria-labelledby="pulse-title">
        <div class="home-lead">
          <span class="eyebrow">Fed pulse &middot; read by ${esc(methodLabel(pulse.method))}</span>
          <h2 id="pulse-title">Fed language is running <em class="${mood === "hawkish" ? "hawk" : mood === "dovish" ? "dove" : ""}">${mood}</em></h2>
          <p>${lead}</p>
          ${m ? `<a href="#/documents?doc=${encodeURIComponent(m.doc_id)}" data-doc="${m.doc_id}">Read the minutes with Claude's evidence &rarr;</a>` : ""}
        </div>
        <div class="pulse-rows"><div class="pulse-caption">Percentile against each type's own history since 2009</div><div class="pulse-scale"><span></span><span class="ends"><span>Dovish</span><span class="median" title="Historical median">50th</span><span>Hawkish</span></span><span></span></div>${rows}</div>
      </section>
      <section class="home-policy" aria-label="Policy and pricing">${policy.map(([label, value, cls, cap, href]) => `<a class="card policy" href="${href}"><span class="label">${label}</span><b class="${cls}">${value}</b><span class="cap">${cap}</span></a>`).join("")}</section>
      ${finds.length ? `<section class="home-found" aria-labelledby="found-title">
        <div class="section-head"><h2 id="found-title">What the research found</h2><a href="#/event-study">See the evidence &rarr;</a></div>
        <div class="found-grid">${finds.map((f) => { const [cls, icon] = VERDICT_ICON[f.verdict] || VERDICT_ICON.Mixed;
          return `<a class="card finding" href="${f.link}"><span class="label">${esc(f.label)}</span><span class="claim">${esc(f.claim)}</span><span class="verdict ${cls}"><svg class="ic" aria-hidden="true"><use href="${icon}"/></svg>${esc(f.verdict)}</span><span class="value">${esc(f.value)} <small>${esc(f.unit)}</small></span><span class="cap">${esc(f.detail)}</span></a>`; }).join("")}</div></section>` : ""}
      <section class="card" aria-labelledby="tone-title">
        <div class="card-head"><div><h2 id="tone-title">How Fed language has sounded since 2009</h2><div class="sub keep">Each dot is one document read by ${esc(methodLabel(state.method))}, red when hawkish and blue when dovish; the line is a rolling median. Click a dot to read it.</div></div>
          <div class="seg" id="type-seg">${Object.entries(TYPES).map(([k, v]) => `<button data-t="${k}" class="${k === "minutes" ? "on" : ""}">${v}</button>`).join("")}</div></div>
        <div id="c-tone" class="chart"></div>
      </section>
      <section class="card" aria-labelledby="latest-title">
        <div class="card-head"><div><h2 id="latest-title">Latest on monetary policy</h2></div><span class="head-links"><a href="/feed.xml" title="Atom feed: subscribe in any feed reader">Subscribe</a><a href="#/documents">All documents &rarr;</a></span></div>
        <div class="latest-list">${latest || '<p class="muted">No documents yet.</p>'}</div>
      </section>`;
    view.querySelectorAll("[data-doc]").forEach((el) => el.addEventListener("click", (e) => { e.preventDefault(); openDoc(el.dataset.doc); }));
    const draw = async (t) => {
      const idx = await api(`/api/index?method=${encodeURIComponent(state.method || "")}&types=${t}`);
      if ($("#c-tone")) drawTone(idx.series[t] || [], [], t);
    };
    $("#type-seg")?.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      $$("#type-seg button").forEach((x) => x.classList.toggle("on", x === b)); draw(b.dataset.t);
    });
    draw("minutes");
  },
};

function ordinal(p) {
  const n = Math.round(p); const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th";
  return n + s;
}
function chg(bp) {
  if (bp === null || bp === undefined) return "";
  return `<span class="chg ${bp > 0 ? "up" : bp < 0 ? "down" : ""}" title="change over one month">${fmt.signed(bp, 0)} bp 1m</span>`;
}
function spark(el, data, color) {
  if (!el) return;
  const c = mk(el);
  c.setOption({ animation: false, grid: { left: 6, right: 6, top: 4, bottom: 2 },
    xAxis: { type: "time", show: false }, yAxis: { type: "value", show: false, scale: true },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (ps) => `${fmt.date(ps[0].data[0])}<br><b>${fmt.num(ps[0].data[1], 2)}</b>` },
    series: [{ type: "line", data, showSymbol: false, smooth: true, lineStyle: { width: 2, color },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: color + "55" }, { offset: 1, color: color + "00" }]) } }] });
}

function drawTone(points, yields, t) {
  [$("#c-tone"), $("#c-yield")].filter(Boolean).forEach((el) => { const old = echarts.getInstanceByDom(el); if (old) dropChart(old); });
  const tone = mk($("#c-tone")); const yc = $("#c-yield") ? mk($("#c-yield")) : null;
  const start = points.length ? points[0].date.slice(0, 4) + "-01-01" : yields[0]?.date;
  // one scale for every reader, centred on zero: Claude reads -1 to +1; a baseline gets its own symmetric range
  const top = (state.method || "").startsWith("llm") ? 1 : Math.max(0.25, Math.ceil(4 * Math.max(...points.map((p) => Math.abs(p.score)), 0)) / 4);
  const [hawk, dove, mid] = [css("--hawk"), css("--dove"), css("--muted")];
  const dot = (v) => (v >= 0.15 * top ? hawk : v <= -0.15 * top ? dove : mid);
  const pole = (text, pos) => ({ type: "text", left: 58, ...pos, silent: true, style: { text, fill: css("--text-2"), fontSize: 11, fontWeight: 600 } });
  tone.setOption(base({
    grid: { left: 52, right: 20, top: 24, bottom: 26 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
      formatter: (p) => p.seriesType === "scatter" ? `${esc(p.data[2])}<br>${fmt.date(p.data[0])}<br>score <b>${fmt.signed(p.data[1])}</b>` : `${fmt.date(p.data[0])}<br>rolling median <b>${fmt.signed(p.data[1])}</b>` },
    xAxis: { type: "time", min: start, ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 11, showMaxLabel: true, hideOverlap: true } }) },
    yAxis: { type: "value", min: -top, max: top, interval: top / 2, ...axis({ axisLabel: { color: css("--text-2"), fontSize: 11, formatter: (v) => (v > 0 ? "+" : "") + fmt.signed(v, top < 1 ? 2 : 1).replace(/^\+/, "") } }) },
    dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false }],
    series: [
      { type: "scatter", symbolSize: t === "speech" ? 6 : 8, z: 2, cursor: "pointer",
        data: points.map((p) => ({ value: [p.date, p.score, p.doc_id], itemStyle: { color: dot(p.score), opacity: 0.8, borderColor: css("--surface"), borderWidth: 1 } })),
        markLine: { silent: true, symbol: "none", animation: false, label: { show: false }, lineStyle: { color: css("--text-2"), width: 1, type: "solid", opacity: 0.6 }, data: [{ yAxis: 0 }] } },
      { type: "line", showSymbol: false, lineStyle: { width: 2.5, color: css("--text") }, itemStyle: { color: css("--text") }, data: points.filter((p) => p.smooth !== null).map((p) => [p.date, p.smooth]), z: 3 },
      // Invisible targets preserve the plotted dots while making each document easier to open.
      { type: "scatter", name: "Document", symbolSize: window.matchMedia("(pointer: coarse)").matches ? 44 : 28, z: 4, cursor: "pointer",
        data: points.map((p) => [p.date, p.score, p.doc_id]), itemStyle: { color: "rgba(0,0,0,0)" }, emphasis: { disabled: true } },
    ],
    graphic: points.length ? [pole("Hawkish \u2191", { top: 28 }), pole("Dovish \u2193", { bottom: 32 })]
      : [{ type: "text", left: "center", top: "middle", style: { text: (state.method || "").startsWith("llmshift:") ? "This method reads statements only: choose Statements" : "No scores for this document type yet", fill: css("--muted"), fontSize: 13 } }],
  }));
  tone.on("click", (p) => { if (p.seriesType === "scatter") openDoc(p.data[2]); });
  if (!yc) return;
  yc.setOption(base({
    grid: { left: 52, right: 20, top: 10, bottom: 26 },
    xAxis: { type: "time", min: start, ...axis({ splitLine: { show: false } }) },
    yAxis: { type: "value", scale: true, ...axis() },
    dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false }],
    series: [{ type: "line", name: "2-year yield", showSymbol: false, lineStyle: { width: 1.6, color: css("--text-2") }, itemStyle: { color: css("--text-2") }, data: yields.map((r) => [r.date, r.t2y]) }],
  }));
  tone.group = yc.group = "tone"; echarts.connect("tone");
}

// ------------------------------------------------------------------ documents
const docState = { q: "", types: [], start: "", end: "", speaker: "", offset: 0, limit: 25 };
pages.documents = {
  title: "Documents", sub: "Every statement, set of minutes, press conference and Board speech since 2009, with full-text search.",
  async render(view) {
    const vp = viewParams();
    if ([...vp.keys()].some((k) => k !== "doc")) Object.assign(docState, { q: vp.get("q") || "", types: (vp.get("types") || "").split(",").filter(Boolean),
      start: vp.get("from") || "", end: vp.get("to") || "", speaker: vp.get("speaker") || "", offset: Number(vp.get("offset") || 0) });
    view.innerHTML = `
      <div class="card">
        <div class="toolbar form-grid">
          <label class="field grow"><span>Search the text ${info('All words must appear. "Exact phrase", OR between words, -word or NOT word to leave documents out, word* for a prefix.')}</span><input id="f-q" placeholder='e.g. "inflation expectations" -transitory' value="${esc(docState.q)}"></label>
          <label class="field"><span>From</span><input id="f-start" type="date" value="${docState.start}"></label>
          <label class="field"><span>To</span><input id="f-end" type="date" value="${docState.end}"></label>
          <label class="field speaker"><span>Speaker</span><input id="f-speaker" placeholder="e.g. Powell" value="${esc(docState.speaker)}"></label>
          <button class="btn ghost" id="f-reset">Reset</button>
        </div>
        <div class="chips" id="f-types" style="margin-top:12px"><span class="chips-label">Types</span><button class="chip ${docState.types.length ? "" : "on"}" data-t="" aria-pressed="${!docState.types.length}">All types</button>${Object.entries(TYPES).map(([k, v]) => `<button class="chip ${docState.types.includes(k) ? "on" : ""}" data-t="${k}" aria-pressed="${docState.types.includes(k)}"><i style="background:var(--t-${k})"></i>${v}</button>`).join("")}</div>
      </div>
      <div class="card"><div class="card-head"><div><h2>Tone over time</h2><p class="sub keep" id="doc-timeband-summary">All matching documents, independent of the table page.</p></div><div class="seg" id="doc-time-view" role="group" aria-label="Timeline view"><button data-time-view="quarter" class="on">Quarterly</button><button data-time-view="documents">Documents</button></div></div><div id="doc-timeband" class="doc-timeband"></div></div>
      <div class="card"><div id="doc-results"><div class="skeleton"></div></div></div>`;
    let timer;
    const refresh = () => { docState.offset = 0; loadDocs(); };
    $("#f-q").addEventListener("input", (e) => { docState.q = e.target.value; clearTimeout(timer); timer = setTimeout(refresh, 300); });
    $("#f-speaker").addEventListener("input", (e) => { docState.speaker = e.target.value; clearTimeout(timer); timer = setTimeout(refresh, 300); });
    $("#f-start").addEventListener("change", (e) => { docState.start = e.target.value; refresh(); });
    $("#f-end").addEventListener("change", (e) => { docState.end = e.target.value; refresh(); });
    $("#f-types").addEventListener("click", (e) => {
      const b = e.target.closest("[data-t]"); if (!b) return;
      const type = b.dataset.t;
      docState.types = !type ? [] : docState.types.includes(type) ? docState.types.filter((t) => t !== type) : [...docState.types, type];
      if (docState.types.length === Object.keys(TYPES).length) docState.types = [];
      $$("#f-types [data-t]").forEach((btn) => {
        const on = btn.dataset.t ? docState.types.includes(btn.dataset.t) : !docState.types.length;
        btn.classList.toggle("on", on); btn.setAttribute("aria-pressed", String(on));
      });
      refresh();
    });
    $("#f-reset").addEventListener("click", () => { Object.assign(docState, { q: "", types: [], start: "", end: "", speaker: "", offset: 0 }); route(); });
    $("#doc-time-view").onclick = (e) => { const b=e.target.closest("[data-time-view]"); if (!b) return; docState.timeView=b.dataset.timeView; if (docState.scatter) drawDocumentTimeband($("#doc-timeband"),docState.scatter); };
    loadDocs();
  },
};

async function loadDocs() {
  setViewParams({ q: docState.q, types: docState.types, from: docState.start, to: docState.end, speaker: docState.speaker, offset: docState.offset || null });
  const p = new URLSearchParams({ q: docState.q, types: docState.types.join(","), start: docState.start, end: docState.end,
    speaker: docState.speaker, method: state.method || "", limit: docState.limit, offset: docState.offset });
  const box = $("#doc-results");
  const requestId = loadDocs.requestId = (loadDocs.requestId || 0) + 1;
  const scatterParams = new URLSearchParams(p);
  scatterParams.delete("limit"); scatterParams.delete("offset"); scatterParams.set("mode", "scatter");
  try {
    const [r, scatter] = await Promise.all([api("/api/documents?" + p), api("/api/documents?" + scatterParams).catch(() => null)]);
    if (!box.isConnected || requestId !== loadDocs.requestId) return;
    const timeband = $("#doc-timeband");
    if (scatter) { docState.scatter=scatter; drawDocumentTimeband(timeband, scatter); }
    else {  // never keep, or redraw, the previous filter's timeline
      $$(".document-mini", timeband).forEach((node) => dropChart(echarts.getInstanceByDom(node))); docState.scatter = null;
      timeband.innerHTML = empty("Timeline unavailable", "The matching documents remain in the table below.");
    }
    if (!r.items.length) { box.innerHTML = empty("No documents match", "Try fewer filters or a different search term."); return; }
    box.innerHTML = `
      <div class="docs-key">Tone read by ${esc(methodLabel(r.method))} &middot; &Delta;2y: the 2-year yield over the release window, bp</div>
      <div class="table-wrap" data-nosort data-total="${r.total}"><table class="table docs"><thead><tr><th>Date</th><th>Type</th><th>Document</th>
        <th class="num">Tone (${esc(methodLabel(r.method))})</th><th class="num" title="Change in the 2-year yield over the release window, basis points">&Delta;2y bp</th></tr></thead>
      <tbody>${r.items.map((d) => `<tr data-doc="${d.doc_id}"><td class="nowrap">${fmt.date(d.release_date)}<div class="snippet tnum">${d.release_time_et || ""} ET</div></td>
        <td>${typeBadge(d.doc_type)}</td>
        <td><div class="doc-title">${esc(d.title || ONE[d.doc_type])}</div><div class="snippet">${esc(d.speaker || "FOMC")}${d.n_words ? " &middot; " + fmt.int(d.n_words) + " words" : ""}</div>${d.snippet ? `<div class="snippet">${d.snippet}</div>` : ""}</td>
        <td class="num">${d.relevance === "low" ? `<span class="score low-rel" title="Low monetary-policy relevance: the research and the timeline leave this reading out">${fmt.signed(d.score)}</span><div class="snippet">low relevance</div>` : scoreChip(d.score, r.method)}</td><td class="num">${delta(d.d2y_bp)}</td></tr>`).join("")}</tbody></table></div>
      <div class="pager"><span>${fmt.int(docState.offset + 1)}&ndash;${fmt.int(Math.min(docState.offset + docState.limit, r.total))} of ${fmt.int(r.total)}</span>
        <span><button class="btn ghost" id="pg-prev" ${docState.offset === 0 ? "disabled" : ""}>Previous</button> <button class="btn ghost" id="pg-next" ${docState.offset + docState.limit >= r.total ? "disabled" : ""}>Next</button></span></div>`;
    $("tbody", box).addEventListener("click", (e) => { const tr = e.target.closest("[data-doc]"); if (tr) openDoc(tr.dataset.doc); });
    $("#pg-prev").onclick = () => { docState.offset = Math.max(0, docState.offset - docState.limit); loadDocs(); };
    $("#pg-next").onclick = () => { docState.offset += docState.limit; loadDocs(); };
  } catch (e) { box.innerHTML = empty("Search failed", esc(e.message)); }
}

function drawDocumentTimeband(el, result) {
  const scored = result.items.filter((d) => Number.isFinite(d.score) && d.release_date);
  const mode=docState.timeView || "quarter";
  $$("#doc-time-view button").forEach(b=>{const on=b.dataset.timeView===mode;b.classList.toggle("on",on);b.setAttribute("aria-pressed",on);});
  const low = result.low_relevance ? ` ${fmt.int(result.low_relevance)} low-relevance readings are left out, as in the research.` : "";
  $("#doc-timeband-summary").textContent = `${fmt.int(scored.length)} scored documents.${low} ${mode === "quarter" ? "Quarterly medians and the middle 50% of readings, split by type. Ranges show document variation, not confidence intervals." : "Individual documents, split by type. Select a point to read its evidence."}`;
  $$(".document-mini",el).forEach(node=>dropChart(echarts.getInstanceByDom(node)));
  if (!scored.length) { el.innerHTML = empty("No tone readings match", "Try another reader or fewer filters."); return; }
  const types=Object.entries(TYPES).filter(([type])=>scored.some(d=>d.doc_type===type));
  el.innerHTML=`<div class="document-mini-grid">${types.map(([type,name])=>`<section class="document-mini-pane"><div class="mini-heading"><b><i style="background:var(--t-${type})"></i>${name}</b><span>${fmt.int(scored.filter(d=>d.doc_type===type).length)} readings</span></div><div class="document-mini" data-series="${type}"></div></section>`).join("")}</div>`;
  const times=scored.map(d=>d.release_date).sort();
  types.forEach(([type,name])=>{
    const docs=scored.filter(d=>d.doc_type===type), color=css(`--t-${type}`), node=el.querySelector(`[data-series="${type}"]`);
    const series=[];
    if(mode==="documents") series.push({name,type:"scatter",symbolSize:8,itemStyle:{color,opacity:.62},data:docs.map(d=>({value:[d.release_date,d.score],doc:d.doc_id}))});
    else {
      const buckets=new Map();
      docs.forEach(d=>{const q=Math.floor((Number(d.release_date.slice(5,7))-1)/3)*3+1;const date=`${d.release_date.slice(0,4)}-${String(q).padStart(2,"0")}-01`;if(!buckets.has(date)) buckets.set(date,{scores:[],latest:d.release_date});const bucket=buckets.get(date);bucket.scores.push(d.score);if(d.release_date>bucket.latest)bucket.latest=d.release_date;});
      const quant=(xs,p)=>{const k=(xs.length-1)*p,i=Math.floor(k);return xs[i]+(xs[Math.min(i+1,xs.length-1)]-xs[i])*(k-i);};
      const groups=[...buckets].sort(([a],[b])=>a.localeCompare(b)).map(([,bucket])=>{const xs=bucket.scores;xs.sort((a,b)=>a-b);return {date:bucket.latest,low:quant(xs,.25),mid:quant(xs,.5),high:quant(xs,.75),n:xs.length};});
      series.push({type:"custom",silent:true,z:1,renderItem:(params,api)=>{const g=groups[params.dataIndex];const x=api.coord([g.date,g.low])[0],y0=api.coord([g.date,g.low])[1],y1=api.coord([g.date,g.high])[1];return {type:"line",shape:{x1:x,y1:y0,x2:x,y2:y1},style:{stroke:color,lineWidth:7,opacity:.22}};},data:groups.map(g=>[g.date,g.mid])});
      series.push({name,type:"line",z:2,symbolSize:8,itemStyle:{color},lineStyle:{color,width:2},data:groups.map(g=>({value:[g.date,g.mid],count:g.n,low:g.low,high:g.high}))});
    }
    const chart=mk(node);chart.setOption(base({grid:{left:38,right:12,top:12,bottom:28},toolbox:undefined,
      tooltip:{trigger:"item",backgroundColor:css("--surface"),borderColor:css("--border"),textStyle:{color:css("--text")},formatter:p=>`${name}<br>${fmt.date(p.value[0])}<br>${mode==="quarter"?"Median":"Tone"}: <b>${fmt.signed(p.value[1])}</b>${p.data.count?`<br>${p.data.count} documents, IQR ${fmt.signed(p.data.low)} to ${fmt.signed(p.data.high)}`:""}`},
      xAxis:{type:"time",min:times[0],max:times[times.length-1],splitNumber:4,...axis({axisLine:{onZero:false,lineStyle:{color:css("--border")}},splitLine:{show:false}})},
      yAxis:{type:"value",min:-1,max:1,interval:.5,...axis()},series}));
    chart.on("click",p=>{if(p.data?.doc)openDoc(p.data.doc);});
  });
}

// -------------------------------------------------------------- document drawer
function canon(s) { return String(s).replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, "-").replace(/--/g, "-").replace(/\s+/g, " ").toLowerCase(); }
// The text, painted: each evidence quote takes the direction of its dimension (vermilion hawkish, indigo dovish,
// sand neutral), and the dictionary's matches can be underlined beside them, so a reader sees what Claude cites
// and what a word count would count.
function dimValue(p, dim) { return dim === "overall" || dim === "overall_stance" ? p.overall_stance : p[dim]; }
function dirOf(v) { return v > 0 ? "hawk" : v < 0 ? "dove" : "flat"; }
const DIR_WORD = { hawk: "hawkish", dove: "dovish", flat: "neutral" };
function dimName(dim) { return DIM_NAMES[dim] || (dim === "overall" || dim === "overall_stance" ? "Overall" : dim.replace(/_/g, " ")); }
function normMap(text) {  // lower case, straight quotes and dashes, single spaces; map back to the original index
  const out = []; const map = []; let space = false;
  for (let i = 0; i < text.length; i++) {
    let ch = text[i];
    if (/\s/.test(ch)) { if (space) continue; ch = " "; space = true; } else space = false;
    out.push(ch.replace(/[‘’]/, "'").replace(/[“”]/, '"').replace(/[–—]/, "-").toLowerCase()); map.push(i);
  }
  return { s: out.join(""), map };
}
function evidenceSpans(text, p) {
  const { s, map } = normMap(text);
  return (p.evidence || []).map((e, idx) => {
    const probe = normMap(e.quote.trim()).s.replace(/[ .,;:"']+$/, "");
    const k = probe.length > 8 ? s.indexOf(probe) : -1;
    const v = dimValue(p, e.dimension);
    return { idx, dim: e.dimension, v, dir: dirOf(v), start: k >= 0 ? map[k] : -1, end: k >= 0 ? map[k + probe.length - 1] + 1 : -1 };
  });
}
function paintText(text, ev, words) {
  const marks = ev.filter((e) => e.start >= 0);
  const cuts = new Set([0, text.length]);
  marks.forEach((e) => { cuts.add(e.start); cuts.add(e.end); });
  words.forEach(([a, b]) => { cuts.add(a); cuts.add(b); });
  const pts = [...cuts].sort((a, b) => a - b); const seen = new Set(); let html = "";
  for (let k = 0; k < pts.length - 1; k++) {
    const a = pts[k]; const b = pts[k + 1]; const piece = esc(text.slice(a, b));
    const e = marks.find((m) => m.start <= a && m.end >= b); const w = words.find(([s, t]) => s <= a && t >= b);
    if (!e && !w) { html += piece; continue; }
    const cls = `${e ? `ev ev-${e.dir}` : ""} ${w ? `dw dw-${w[2] > 0 ? "hawk" : "dove"}` : ""}`.trim();  // separate names: a span can carry both
    const id = e && !seen.has(e.idx) ? (seen.add(e.idx), ` id="ev-${e.idx}"`) : "";
    const tip = e ? ` title="${esc(`${dimName(e.dim)}: ${DIR_WORD[e.dir]}${e.v === null || e.v === undefined ? "" : ` (${fmt.signed(e.v, 0)})`}`)}"` : w ? ` title="Dictionary: ${w[2] > 0 ? "hawkish" : "dovish"} words"` : "";
    html += `<span class="${cls}"${id}${tip}>${piece}</span>`;
  }
  return html;
}
function textLegend(ev, words) {
  const by = new Map();
  ev.filter((e) => e.start >= 0).forEach((e) => by.set(e.dim, [...(by.get(e.dim) || []), e]));
  const chips = [...by.entries()].map(([dim, list]) => `<button type="button" class="ev-chip ${list[0].dir}" data-jump="ev-${list[0].idx}" title="Show it in the text"><i></i>${esc(dimName(dim))}${list[0].v === null || list[0].v === undefined ? "" : ` <b>${fmt.signed(list[0].v, 0)}</b>`}${list.length > 1 ? ` <small>&times;${list.length}</small>` : ""}</button>`).join("");
  const hawk = words.filter((w) => w[2] > 0).length;
  return `<div class="ev-legend">${chips}${words.length ? `<label class="dw-toggle" title="Underline what the dictionary baseline counts"><input type="checkbox" id="dw-toggle" ${local.get("dw", false) ? "checked" : ""}> Word counts <span class="dw-n hawk">${hawk}</span><span class="dw-n dove">${words.length - hawk}</span></label>` : ""}</div>`;
}
// the overall stance on the same diverging track as the dimensions below it
function stanceMeter(v) {
  const word = v > 0.15 ? "hawkish" : v < -0.15 ? "dovish" : "neutral";
  const fill = `<span class="fill" style="${v >= 0 ? "left:50%" : `left:${50 + v * 50}%`};width:${Math.abs(v) * 50}%;background:${v >= 0 ? "var(--hawk)" : "var(--dove)"}"></span>`;
  return `<div class="stance-meter"><div class="stance-num"><b>${fmt.signed(v)}</b><span>${word}</span></div>
    <div class="bar">${fill}</div><div class="ends"><span>dovish &minus;1</span><span>0</span><span>+1 hawkish</span></div></div>`;
}
function dimBars(p) {
  return `<div class="dims">${DIMS.map((d) => {
    const v = p[d];
    const fill = v === null || v === undefined ? "" : `<span class="fill" style="${v >= 0 ? "left:50%" : `left:${50 + v * 25}%`};width:${Math.abs(v) * 25}%;background:${v >= 0 ? "var(--hawk)" : "var(--dove)"}"></span>`;
    return `<div class="dim"><span>${esc(dimName(d))}</span><span class="bar">${fill}</span><span class="v">${v === null || v === undefined ? dash : fmt.signed(v, 0)}</span></div>`;
  }).join("")}<div class="dim dim-key"><span></span><span class="ends"><span>&larr; dovish</span><span>hawkish &rarr;</span></span><span></span></div></div>`;
}
function evidence(p, text) {
  const src = text ? canon(text) : null;
  return (p.evidence || []).map((e, i) => {
    const ok = src ? src.includes(canon(e.quote).replace(/[ .,;:"']+$/, "")) : true;
    const v = dimValue(p, e.dimension); const dir = dirOf(v);
    return `<div class="quote ${ok ? dir : "bad"}" ${ok && text ? `data-jump="ev-${i}" title="Show it in the text"` : ""}>&ldquo;${esc(e.quote)}&rdquo;<span class="meta">${esc(dimName(e.dimension))} &middot; ${DIR_WORD[dir]}${v === null || v === undefined ? "" : ` (${fmt.signed(v, 0)})`} &middot; ${ok ? "verified verbatim" : "not found in text"}</span></div>`;
  }).join("");
}
function llmPanel(p, text) {
  const stance = p.overall_stance > 0 ? "Hawkish" : p.overall_stance < 0 ? "Dovish" : "Neutral";
  return `<div class="meta-grid"><div><span>Overall stance</span><b>${stance} (${fmt.signed(p.overall_stance, 0)})</b></div>
    <div><span>Stance score</span><b>${fmt.signed(p.stance_score)}</b></div><div><span>Confidence &middot; relevance</span><b>${fmt.num(p.confidence)} &middot; ${esc(p.policy_relevance)}</b></div></div>
    ${dimBars(p)}<div class="section-title">Evidence</div>${evidence(p, text)}<p class="sub">${esc(p.rationale || "")}</p>`;
}

// decisions and redlines (shared by the drawer and the tracker)
const rate = (v) => (v === null || v === undefined ? dash : Number(v).toFixed(2));
const rangeTxt = (lo, hi) => (hi === null || hi === undefined ? dash : `${rate(lo)}&ndash;${rate(hi)}%`);
const ARROW = { up: '<svg viewBox="0 0 10 10"><path d="M5 1l4 7H1z"/></svg>', down: '<svg viewBox="0 0 10 10"><path d="M5 9L1 2h8z"/></svg>', hold: '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="3"/></svg>' };
function moveBadge(action, bp) {
  if (action === null || action === undefined) return `<span class="move">${dash}</span>`;
  if (action > 0) return `<span class="move hike">${ARROW.up}Hike${bp ? " +" + bp + " bp" : ""}</span>`;
  if (action < 0) return `<span class="move cut">${ARROW.down}Cut${bp ? " " + fmt.signed(bp, 0) + " bp" : ""}</span>`;
  return `<span class="move hold">${ARROW.hold}Hold</span>`;
}
const pct = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? dash : (Number(v) * 100).toFixed(d) + "%");
function redlineHtml(segments) {
  let out = ""; let last = "";
  for (const s of segments) {
    const sep = !out || last === "\n" || s.text.startsWith("\n") ? "" : " ";
    let html;
    if (s.op === "insert") html = `<ins>${esc(s.text)}</ins>`;
    else if (s.op === "delete") html = `<del>${esc(s.text)}</del>`;
    else {
      const w = s.text.split(" ");
      html = w.length > 90
        ? `${esc(w.slice(0, 30).join(" "))} <button class="fold" data-fold>${fmt.int(w.length - 60)} unchanged words</button><span hidden> ${esc(w.slice(30, -30).join(" "))}</span> ${esc(w.slice(-30).join(" "))}`
        : esc(s.text);
    }
    out += sep + html; last = s.text.slice(-1);
  }
  return out;
}
async function loadRedline(id, box) {
  try {
    const r = await api(`/api/documents/${encodeURIComponent(id)}/diff`);
    const long = r.segments.reduce((n, s) => n + s.text.trim().split(/\s+/).length, 0) > 180;
    const redlineId = `redline-${id}-${box.id || "comparison"}`;
    box.innerHTML = `<p class="redline-sum">Against ${fmt.date(r.prev_date)}: <b>+${fmt.int(r.words_added)}</b> / <b>&minus;${fmt.int(r.words_removed)}</b> words, <b>${pct(1 - r.similarity)}</b> of the wording changed</p>
      <div class="redline-preview${long ? " is-collapsed" : ""}"><div class="redline" id="${esc(redlineId)}">${redlineHtml(r.segments)}</div></div>
      ${long ? `<button type="button" class="btn ghost small redline-expand" aria-expanded="false" aria-controls="${esc(redlineId)}">Show full statement</button>` : ""}
      <div class="legend-inline"><span><ins class="lg-ins">added</ins>underlined</span><span><del class="lg-del">removed</del>struck through</span></div>`;
    const expand = box.querySelector(".redline-expand");
    if (expand) expand.onclick = () => {
      const open = expand.getAttribute("aria-expanded") !== "true";
      expand.setAttribute("aria-expanded", String(open));
      expand.textContent = open ? "Show less" : "Show full statement";
      box.querySelector(".redline-preview").classList.toggle("is-collapsed", !open);
      if (open) box.querySelectorAll("[data-fold]").forEach((b) => { b.nextElementSibling.hidden = false; b.remove(); });
    };
    return r;
  } catch (e) { box.innerHTML = empty("No comparison available", esc(e.message)); return null; }
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-fold]"); if (b) { b.nextElementSibling.hidden = false; b.remove(); } });

function docLink(id) { const p = viewParams(); p.set("doc", id); return `${location.origin}${location.pathname}#/${state.page}?${p}`; }
// keep keyboard focus inside an open drawer (WAI-ARIA dialog pattern)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Tab" || $("#drawer").hidden) return;
  const items = $$("#drawer a[href], #drawer button:not([disabled]), #drawer input, #drawer select, #drawer textarea").filter((el) => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0]; const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});
function setFull(on, { updateUrl = true } = {}) {
  $("#drawer").classList.toggle("full", on);
  const b = $(".drawer-full"); b.setAttribute("aria-pressed", on); b.title = on ? "Back to the side panel (F)" : "Read full screen (F)";
  b.querySelector("use").setAttribute("href", on ? "#i-minimize" : "#i-maximize");
  if (updateUrl) setViewParams({ full: on ? 1 : null });
}
async function openDoc(id, { updateUrl = true } = {}) {
  const drawer = $("#drawer"); drawer.hidden = false; state.doc = id; state.member = null;
  dropChart(state.memberChart); state.memberChart = null;
  if (updateUrl) setViewParams({ doc: id });
  setFull(viewParams().get("full") === "1", { updateUrl: false });
  if (!drawer.contains(document.activeElement)) state.returnFocus = document.activeElement;
  setTimeout(() => $(".drawer-close").focus(), 30);
  const body = $("#drawer-body"); body.innerHTML = '<div class="skeleton" style="min-height:400px"></div>';
  try {
    const r = await api("/api/documents/" + encodeURIComponent(id));
    const d = r.document; const evt = r.event; const dec = r.decision; const llm = r.llm.find((x) => x.mode === "level" && x.parsed);
    const hasRedline = Boolean(dec && dec.prev_doc_id);
    const ev = llm ? evidenceSpans(d.text || "", llm.parsed) : []; const words = r.dictionary_spans || [];
    const from = viewParams().get("member");  // opened from a member's panel: a way back
    body.innerHTML = `
      <header class="doc-head">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${typeBadge(d.doc_type)}<span class="muted">${fmt.date(d.release_date)} &middot; ${d.release_time_et} ET <span title="Where the release time comes from">(${esc(TIME_SOURCE[d.time_source] || "standard release time")})</span></span></div>
        <h2 id="drawer-title">${esc(d.title || `${ONE[d.doc_type]}, ${fmt.date(d.release_date)}`)}</h2>
        <div class="muted">${esc(d.speaker ? d.speaker + (d.speaker_role ? ", " + d.speaker_role : "") : "Federal Open Market Committee")} &middot; <a href="${esc(d.url)}" target="_blank" rel="noopener">source</a></div>
        <div class="drawer-actions">${from ? `<button class="btn ghost small" id="back-member"><svg class="ic" aria-hidden="true"><use href="#i-arrow-left"/></svg>${esc(from)}</button>` : ""}<button class="btn ghost small" id="copy-link">Copy link</button><a class="btn ghost small" href="#/duration?signal=${encodeURIComponent(d.doc_id)}">Explore duration</a>${hasRedline ? '<button class="btn ghost small" id="jump-redline">What changed</button>' : ""}</div>
      </header>
      <div class="doc-layout">
        <section class="doc-side">
          ${dec && dec.action !== null ? `<div class="meta-grid"><div><span>Decision</span><b>${moveBadge(dec.action, dec.change_bp)}</b></div><div><span>Target range after</span><b>${rangeTxt(dec.range_low, dec.range_high)}</b></div><div><span>Wording carried over</span><b>${pct(dec.similarity)}</b></div></div>` : ""}
          <div class="meta-grid">
            <div><span>&Delta; 2y over window</span><b>${evt ? fmt.signed(evt.d2y_bp, 1) + " bp" : dash}</b></div>
            <div><span>&Delta; 10y over window</span><b>${evt ? fmt.signed(evt.d10y_bp, 1) + " bp" : dash}</b></div>
            <div><span>Window ${info("The Treasury closes before and after the release that its yield changes are measured between.")}</span><b>${evt ? `${fmt.short(evt.ust_pre)} &rarr; ${fmt.short(evt.ust_post)}` : dash}</b></div>
          </div>
          <div class="section-title">Claude reading</div>
          <div id="llm-box">${llm ? llmPanel(llm.parsed, d.text) : `<div class="callout"><span>No Claude score for this document yet.${canScoreHere() ? "" : state.settings?.read_only ? " Scores appear here once the owner runs the scoring batch." : ' <a href="#/settings">Add your API key</a> to enable.'}</span></div>
            ${canScoreHere() ? '<button class="btn" id="score-now" style="margin-top:10px">Score this document with Claude</button>' : ""}`}</div>
          ${hasRedline ? '<div class="section-title" id="redline-title">What changed against the previous decision</div><div id="redline-box"><div class="skeleton"></div></div>' : ""}
          <div class="section-title">Scores</div>
          <div class="table-wrap"><table class="table"><tbody>${r.scores.map((s) => `<tr style="cursor:default"><td>${esc(methodLabel(s.method))}</td><td class="num">${scoreChip(s.score, s.method)}</td></tr>`).join("") || `<tr><td class="muted">No scores yet</td></tr>`}</tbody></table></div>
        </section>
        <section class="doc-main">
          <div class="section-title">Text</div>
          ${ev.length || words.length ? textLegend(ev, words) : ""}
          <div class="doc-text ${local.get("dw", false) ? "show-dw" : ""}" id="doc-text">${paintText(d.text || "", ev, words)}</div>
        </section>
      </div>`;
    const dw = $("#dw-toggle");
    if (dw) dw.onchange = () => { local.set("dw", dw.checked); $("#doc-text").classList.toggle("show-dw", dw.checked); };
    $("#copy-link").onclick = () => navigator.clipboard?.writeText(docLink(id)).then(() => toast("Link copied"));
    if (from) $("#back-member").onclick = () => openMember(from);
    if (hasRedline) {
      loadRedline(id, $("#redline-box"));
      $("#jump-redline").onclick = () => $("#redline-title").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    const btn = $("#score-now");
    if (btn) btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Scoring…";
      try { const res = await api("/api/score", { method: "POST", body: JSON.stringify({ text: (d.text || "").slice(0, 60000), doc_type: d.doc_type }) });
        $("#llm-box").innerHTML = llmPanel(res.parsed, d.text) + `<p class="sub">Model ${esc(res.model)} &middot; cost ${fmt.money(res.cost_usd)}</p>`;
      } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Score this document with Claude"; }
    };
  } catch (e) { body.innerHTML = empty("Could not open document", esc(e.message)); }
}
function closeDrawer() {
  if ($("#drawer").hidden) return;
  $("#drawer").hidden = true; state.doc = null; state.member = null; $("#drawer").classList.remove("full");
  dropChart(state.memberChart); state.memberChart = null;
  setViewParams({ doc: null, member: null, full: null });
  state.returnFocus?.focus?.(); state.returnFocus = null;
}

// ------------------------------------------------------------- a member over time
const KIND = { office: "Office", role: "Title", dissent: "Dissent", shift: "Tone", extreme: "Speech" };
const leanClass = (d) => (d > 0 ? "hawk" : d < 0 ? "dove" : "");
function dropChart(c) { if (c) { c.__ro?.disconnect(); c.dispose(); charts.delete(c); } }
function memberLink(name) { const p = viewParams(); p.delete("doc"); p.set("member", name); return `${location.origin}${location.pathname}#/${state.page}?${p}`; }
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
const daysBefore = (iso, n) => new Date(new Date(iso + "T12:00:00").getTime() - n * 864e5).toISOString().slice(0, 10);

async function openMember(name, { updateUrl = true } = {}) {
  const drawer = $("#drawer"); drawer.hidden = false; state.member = name; state.doc = null;
  if (updateUrl) setViewParams({ member: name, doc: null });
  setFull(viewParams().get("full") === "1", { updateUrl: false });
  if (!drawer.contains(document.activeElement)) state.returnFocus = document.activeElement;
  setTimeout(() => $(".drawer-close").focus(), 30);
  dropChart(state.memberChart); state.memberChart = null;
  const body = $("#drawer-body"); body.innerHTML = '<div class="skeleton" style="min-height:400px"></div>';
  try {
    const r = await api("/api/member?" + new URLSearchParams({ name }));
    if (state.member !== name) return;  // another panel opened meanwhile
    const status = { voter: "Voter", alternate: "Alternate", "non-voting": "Non-voting" }[r.status];
    const read = r.speeches.filter((x) => x.score !== null && x.relevance !== "low");
    const dissents = r.events.filter((e) => e.kind === "dissent");
    const shifts = r.events.filter((e) => e.kind === "shift").length;
    const year = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
    const bio = r.bio || {};
    const eligible = Number(r.tone_n) || 0;
    const toneMissing = !r.board ? "Reserve Bank speeches are outside this corpus"
      : eligible < 3 ? `${eligible} eligible speech${eligible === 1 ? "" : "es"} in past 2 years; 3 required`
        : "Recent tone is unavailable in the current sample";
    const toneNote = `Average tone of the last ${r.tone_n} relevant speeches in the past two years, as a percentile of every run of as many Board speeches since 2009; ${esc(methodLabel(r.method))}.`;
    body.innerHTML = `
      <header class="doc-head">
        <div class="mhead lg"><span class="avatar ${r.board ? "on-board" : "at-bank"}">${initials(r.name)}</span><div><h2 id="drawer-title">${esc(r.name)}</h2><span>${esc(memberRole(r))}</span></div></div>
        <div class="mtags"><span class="pill-mini ${r.status === "voter" ? "on" : ""}">${status} in ${String(r.as_of).slice(0, 4)}</span>${r.fomc_vice_chair ? '<span class="pill-mini">FOMC Vice Chair</span>' : ""}${r.board ? '<span class="pill-mini">Governor</span>' : `<span class="pill-mini">Federal Reserve Bank of ${esc(r.bank)}</span>`}</div>
        <div class="drawer-actions"><button class="btn ghost small" id="copy-link">Copy link</button></div>
      </header>
      <div class="meta-grid kpi4">
        <div><span>${r.office === "Board member" ? "On the Board since" : "Took office"}</span><b>${r.took_office ? fmt.date(r.took_office) : dash}</b><small>${!r.took_office ? "not in the biography" : r.office && r.office !== "Board member" ? `as ${esc(r.office)}, Fed biography` : "Fed biography"}</small></div>
        <div><span>Speeches on file</span><b>${fmt.int(r.speeches.length)}</b><small>${r.speeches.length ? `${r.speeches.filter((x) => x.date >= year).length} collected in past 12 months` : r.board ? "none yet" : "Board speeches only"}</small></div>
        <div><span>Recent tone ${r.tone_pct === null ? "" : info(toneNote)}</span><b style="color:${r.tone_pct === null ? "var(--muted)" : pctColor(r.tone_pct)}">${r.tone_pct === null ? dash : ordinal(r.tone_pct)}</b><small>${r.tone_pct === null ? esc(toneMissing) : `percentile, last ${r.tone_n} eligible speeches in past 2 years`}</small></div>
        <div><span>Dissents</span><b>${dissents.length}</b><small>${dissents.length ? `latest ${fmt.date(dissents[0].date)}` : "none on file"}</small></div>
      </div>
      <div class="mem-layout">
        <section class="mem-chart">
          <div class="section-title">${read.length ? "Tone over time" : "Decisions and dissents"} ${info(read.length
            ? `Each dot is a speech scored by ${esc(methodLabel(r.method))}, hawkish up, dovish down; the ticks along the bottom are speeches Claude rated of low policy relevance, left out as in the research. The thick lines are the average between shifts, found by circular binary segmentation: a stretch of at least five speeches is split where a run differs most from the rest, kept when fewer than 1 in 100 shuffles of the same speeches differ as much. Dashed lines: a new title. Below, the top of the target range, with this member's dissents as diamonds.`
            : "The top of the target range since the member took office, with this member's dissents as diamonds: red wanted tighter policy, blue looser, gray dissented on something other than the rate.")}</div>
          <div id="c-member" class="chart ${read.length ? "member-tall" : "short"}"></div>
          <div class="legend-inline">${read.length ? `<span><i class="lg-dot hawk"></i>hawkish speech</span><span><i class="lg-dot dove"></i>dovish</span><span><i class="lg-dot"></i>in between</span><span><i class="lg-rug"></i>low policy relevance, left out</span><span><i class="lg-bar"></i>${shifts ? `average between shifts (${shifts} shift${shifts === 1 ? "" : "s"})` : "average (no shift found)"}</span>${r.events.some((e) => (e.kind === "office" && e.office !== "Board member") || e.kind === "role") ? '<span><i class="lg-dash"></i>new title</span>' : ""}` : ""}<span><i class="lg-line"></i>target range, top</span>${dissents.length ? '<span><i class="lg-diamond"></i>dissent</span>' : ""}</div>
        </section>
        <section class="mem-events">
          <div class="section-title">What changed</div>
          ${memberEvents(r)}
        </section>
        <section class="mem-bio">
          <div class="section-title">Background</div>
          ${["took", "before", "school"].some((k) => bio[k])
            ? `<div class="bio">${["took", "before", "school"].filter((k) => bio[k]).map((k) => `<p>${esc(bio[k])}</p>`).join("")}
                <div class="muted small">In the Fed's own words, from ${(bio.sources || []).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`).join(" and ")}${bio.fetched ? ` (read ${fmt.date(bio.fetched)})` : ""}.</div></div>`
            : `<div class="callout"><span>No biography found on the Fed's pages yet.</span></div>`}
          ${r.roles.length ? `<div class="section-title">Titles in the speech record ${info("The title under each speech as the Fed's speech pages list it: the first and the last speech given under it.")}</div>
            <div class="spells">${r.roles.map((x) => `<div><b>${esc(x.role)}</b><span>${fmt.date(x.from)} to ${fmt.date(x.to)}</span><span class="muted">${x.n} speech${x.n === 1 ? "" : "es"}</span></div>`).join("")}</div>` : ""}
        </section>
        <section class="mem-speeches">
          <div class="section-title">Speeches</div>
          ${memberSpeeches(r)}
        </section>
      </div>`;
    $("#copy-link").onclick = () => navigator.clipboard?.writeText(memberLink(name)).then(() => toast("Link copied"));
    body.querySelectorAll(".events [data-doc], .mem-speeches .row[data-doc]").forEach((el) => {
      el.onclick = () => openDoc(el.dataset.doc);
      el.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openDoc(el.dataset.doc); } };
    });
    state.memberChart = memberChart($("#c-member"), r);
  } catch (e) { body.innerHTML = empty("Could not open this member", esc(e.message)); }
}
function memberEvents(r) {
  if (!r.events.length) return `<div class="callout"><span>Nothing on file yet: no dissents, new titles or shifts in tone.</span></div>`;
  return `<ol class="events">${r.events.map((e) => `<li class="${leanClass(e.direction)}" ${e.doc_id ? `data-doc="${esc(e.doc_id)}" tabindex="0" role="button"` : ""}>
    <span class="when">${fmt.date(e.date)}</span>
    <span class="what"><span class="pill-mini ${leanClass(e.direction)}">${KIND[e.kind]}</span> ${esc(e.text)}${e.detail ? `<small>${esc(e.detail)}</small>` : ""}</span></li>`).join("")}</ol>`;
}
function memberSpeeches(r) {
  if (!r.speeches.length) return `<div class="callout"><span>${r.board ? "No speeches on file yet." : "The corpus holds the Board's speeches (federalreserve.gov), so a Reserve Bank president has no tone line here. The dissents and the background still come from the Fed's own pages."}</span></div>`;
  const list = [...r.speeches].reverse();
  const row = (x) => `<div class="row" data-doc="${esc(x.doc_id)}" tabindex="0" role="button"><div><div class="doc-title">${esc(x.title)}</div><div class="muted small">${fmt.date(x.date)}${x.role ? " &middot; " + esc(x.role) : ""}${x.relevance === "low" ? " &middot; low policy relevance" : ""}</div></div><div>${scoreChip(x.score, r.method)}</div></div>`;
  const rest = list.slice(8);
  return `<div class="list">${list.slice(0, 8).map(row).join("")}</div>${rest.length ? `<button class="btn ghost small fold-more" data-fold>Show all ${list.length} speeches</button><div class="list" hidden>${rest.map(row).join("")}</div>` : ""}`;
}
function memberChart(el, r) {
  const today = new Date().toISOString().slice(0, 10);
  const read = r.speeches.filter((x) => x.score !== null && x.relevance !== "low");
  const low = r.speeches.filter((x) => x.score !== null && x.relevance === "low");
  const dis = r.events.filter((e) => e.kind === "dissent");
  const first = [r.speeches[0]?.date, r.took_office, dis.at(-1)?.date].filter(Boolean).sort()[0] || daysBefore(today, 365);
  // a new title: the date the biography gives, else the first speech under it (joining the Board starts the line)
  const titles = r.events.filter((e) => (e.kind === "office" && e.office !== "Board member") || e.kind === "role").filter((e) => e.date >= daysBefore(first, 90) && e.office);
  const start = daysBefore(first, 90);
  const prior = r.decisions.filter((d) => d.date < start).at(-1);
  const steps = [...(prior ? [[start, prior.range_high]] : []), ...r.decisions.filter((d) => d.date >= start).map((d) => [d.date, d.range_high])];
  if (steps.length) steps.push([today, steps.at(-1)[1]]);
  const topAt = (iso) => (r.decisions.filter((d) => d.date <= iso).at(-1) || {}).range_high;
  const tone = read.length > 0;
  const [hawk, dove, mid, ink] = [css("--hawk"), css("--dove"), css("--muted"), css("--text-2")];
  const col = (v) => (v >= 0.15 ? hawk : v <= -0.15 ? dove : mid);
  const grid = tone ? [{ left: 44, right: 14, top: 14, bottom: "36%" }, { left: 44, right: 14, top: "70%", bottom: 24 }] : [{ left: 44, right: 14, top: 14, bottom: 24 }];
  const p = tone ? 1 : 0;  // the grid with the policy path
  const label = { color: ink, fontSize: 11 };
  const series = [];
  if (tone) {
    const marks = [
      ...r.regimes.map((x) => [{ coord: [x.from, x.mean], lineStyle: { color: col(x.mean), width: 3.5, type: "solid", opacity: 0.85 },
        label: { show: r.regimes.length > 1, position: "insideStartTop", formatter: fmt.signed(x.mean), ...label, fontWeight: 650 } }, { coord: [x.to, x.mean] }]),
      ...titles.map((e) => ({ xAxis: e.date, lineStyle: { color: ink, type: "dashed", width: 1 }, label: { position: "insideEndTop", formatter: e.office, ...label } })),
    ];
    series.push({ name: "Speech", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, symbolSize: 9, z: 3, cursor: "pointer",
      data: read.map((x) => ({ value: [x.date, x.score], s: x, itemStyle: { color: col(x.score), borderColor: css("--surface"), borderWidth: 1.5 } })),
      markLine: { silent: true, symbol: "none", animation: false, data: marks } });
    if (low.length) series.push({ name: "Low relevance", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, symbol: "rect", symbolSize: [2, 9], z: 2, cursor: "pointer",
      data: low.map((x) => ({ value: [x.date, -0.96], s: x, itemStyle: { color: mid, opacity: 0.55 } })) });
  }
  series.push({ name: "Target range, top", type: "line", step: "end", xAxisIndex: p, yAxisIndex: p, showSymbol: false, silent: true, z: 2, data: steps,
    lineStyle: { width: 2, color: css("--s1") }, areaStyle: { color: css("--s1"), opacity: 0.08 } });
  if (dis.length) series.push({ name: "Dissent", type: "scatter", xAxisIndex: p, yAxisIndex: p, symbol: "diamond", symbolSize: 14, z: 4, cursor: "pointer",
    data: dis.map((e) => ({ value: [e.date, topAt(e.date)], e, itemStyle: { color: e.direction > 0 ? hawk : e.direction < 0 ? dove : mid, borderColor: css("--surface"), borderWidth: 1.5 } })) });
  const ch = mk(el);
  ch.setOption(base({
    grid,
    tooltip: { trigger: "item", confine: true, backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 }, extraCssText: "max-width:320px;white-space:normal",
      formatter: (q) => {
        const x = q.data && q.data.s; const e = q.data && q.data.e;
        if (x) return `${fmt.date(x.date)}<br><b>${esc(x.title)}</b><br>${x.role ? esc(x.role) + " &middot; " : ""}tone <b>${fmt.signed(x.score)}</b>${x.relevance === "low" ? "<br>low policy relevance: not in the average" : ""}`;
        if (e) return `${fmt.date(e.date)}<br><b>${esc(e.text)}</b><br>${esc(e.detail || "")}`;
        return "";
      } },
    xAxis: grid.map((_, i) => ({ type: "time", gridIndex: i, min: start, max: today, ...axis({ splitLine: { show: false }, axisLabel: { show: i === grid.length - 1, ...label } }) })),
    yAxis: [
      ...(tone ? [{ type: "value", gridIndex: 0, min: -1, max: 1, interval: 0.5, ...axis({ axisLabel: { ...label, formatter: (v) => (v > 0 ? "+" : "") + v } }) }] : []),
      { type: "value", gridIndex: p, min: 0, splitNumber: 2, ...axis({ axisLabel: { ...label, formatter: (v) => v + "%" } }) },
    ],
    series,
  }));
  ch.on("click", (q) => { const id = q.data?.s?.doc_id || q.data?.e?.doc_id; if (id) openDoc(id); });
  return ch;
}
function canScoreHere() { const st = state.settings; return Boolean(st && st.score_enabled && !st.score_token_required); }
document.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeDrawer(); });
document.addEventListener("click", (e) => { if (e.target.closest("[data-full]")) setFull(!$("#drawer").classList.contains("full")); });
document.addEventListener("click", (e) => {  // a legend chip or an evidence quote: show the words in the text
  const j = e.target.closest("[data-jump]"); const el = j && document.getElementById(j.dataset.jump); if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  const parts = [...document.querySelectorAll(`#doc-text [title="${CSS.escape(el.title)}"]`)].filter((x) => x === el || x.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING);
  [el, ...parts.slice(0, 12)].forEach((x) => { x.classList.remove("flash"); void x.offsetWidth; x.classList.add("flash"); });
});
document.addEventListener("keydown", (e) => {
  if ($("#drawer").hidden || e.key.toLowerCase() !== "f" || e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test(e.target.tagName)) return;
  e.preventDefault(); setFull(!$("#drawer").classList.contains("full"));
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#palette").hidden) closeDrawer(); });

// ----------------------------------------------------------------- live score
pages.live = {
  usesMethod: false,
  title: "Score a text", sub: "Paste any Fed text and Claude scores it with the same rubric used for the corpus.",
  async render(view) {
    const st = (state.settings = await api("/api/settings"));
    const blocked = st.read_only && !st.score_enabled;
    const notice = blocked
      ? '<div class="callout"><span><b>Live scoring is off on this public demo.</b> Each request would spend the owner&rsquo;s Claude credits. Clone the repository and run <span class="mono">make serve</span> with your own key to use it; everything else on this site works.</span></div>'
      : !st.key_configured ? '<div class="callout warn"><span><b>No API key yet.</b> Live scoring calls Claude with your own key. <a href="#/settings">Add it in Settings</a>.</span></div>' : "";
    view.innerHTML = `${notice}
      <div class="grid cols-2">
        <div class="card"><div class="card-head"><div><h2>Text</h2><div class="sub">A speech, a statement, minutes or a press-conference answer. Up to 60,000 characters.</div></div>
          <div class="head-actions"><button class="btn ghost small" data-sample="statement">Load latest statement</button><button class="btn ghost small" data-sample="speech">Load latest speech</button></div></div>
          <textarea id="live-text" placeholder="Paste text here..."></textarea>
          <div class="toolbar form-grid" style="margin-top:12px">
            <label class="field"><span>Document type</span><select id="live-type">${Object.entries(ONE).map(([k, v]) => `<option value="${k}" ${k === "speech" ? "selected" : ""}>${v}</option>`).join("")}</select></label>
            <label class="field"><span>Model</span><select id="live-model" ${st.read_only ? "disabled" : ""}>${st.models_available.map((m) => `<option value="${esc(m)}" ${m === st.model ? "selected" : ""}>${esc(methodLabel("llm:" + m))}</option>`).join("")}</select></label>
            ${st.score_token_required ? '<label class="field"><span>Access token</span><input id="live-token" type="password" autocomplete="off" style="width:150px"></label>' : ""}
            <button class="btn" id="live-go" ${blocked || !st.key_configured ? "disabled" : ""}>Score with Claude</button>
          </div></div>
        <div class="card" id="live-out">${empty("No result yet", "The stance, six dimensions, verified evidence and the implied duration tilt appear here.")}</div>
      </div>`;
    view.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", async () => {
      try {
        const t = b.dataset.sample;
        const list = await api("/api/documents?" + new URLSearchParams({ types: t, limit: 1, ...(t === "speech" ? { speaker: "Powell" } : {}) }));
        if (!list.items.length) return;
        const doc = await api("/api/documents/" + encodeURIComponent(list.items[0].doc_id));
        $("#live-text").value = (doc.document.text || "").slice(0, 60000); $("#live-type").value = t;
        toast(`Loaded: ${doc.document.title || ONE[t]} (${fmt.date(doc.document.release_date)})`);
      } catch (e) { toast(e.message); }
    }));
    $("#live-go").onclick = async () => {
      const text = $("#live-text").value.trim();
      if (text.length < 50) { toast("Paste at least a paragraph"); return; }
      const out = $("#live-out"); out.innerHTML = '<div class="skeleton" style="min-height:360px"></div>';
      const headers = { "Content-Type": "application/json" };
      if ($("#live-token")) headers["X-Score-Token"] = $("#live-token").value;
      try {
        const r = await api("/api/score", { method: "POST", headers, body: JSON.stringify({ text, doc_type: $("#live-type").value, model: st.read_only ? null : $("#live-model").value }) });
        const p = r.parsed;
        const tilt = r.tilt ? `<div class="tilt"><span class="big" style="color:${r.tilt.theta < 0 ? "var(--hawk-ink)" : "var(--dove-ink)"}">${fmt.signed(r.tilt.duration_years)}</span><span class="muted">years of active duration (${r.tilt.theta < 0 ? "shorten" : r.tilt.theta > 0 ? "extend" : "unchanged"}), z = ${fmt.num(r.tilt.z)} vs ${r.tilt.history_n} scored ${ONE[$("#live-type").value].toLowerCase()}s; illustrative sizing rule</span></div>`
          : `<p class="muted small">The duration tilt needs at least ${r.tilt_min_events} corpus documents of this type scored by the same model and relevant policy content.</p>`;
        out.innerHTML = `<div class="card-head"><div><h2>Result</h2><div class="sub">${esc(r.model)} &middot; ${fmt.int(r.usage.input_tokens)} in / ${fmt.int(r.usage.output_tokens)} out tokens &middot; ${fmt.money(r.cost_usd)}</div></div></div>
          ${stanceMeter(p.stance_score)}${tilt}<div class="section-title">Dimensions</div>${llmPanel(p, text)}`;
      } catch (e) { out.innerHTML = empty("Scoring failed", esc(e.message)); }
    };
  },
};

// ---------------------------------------------------------------- event study
const evState = { outcome: "d2y", regressor: "level", robust: "base", methods: null, focus: "minutes", curve: null };
function fresh(el) { const old = echarts.getInstanceByDom(el); if (old) dropChart(old); return mk(el); }
function ci95(r) { const se = r.t ? r.beta_bp_per_sd / r.t : 0; return [r.beta_bp_per_sd - 1.96 * se, r.beta_bp_per_sd + 1.96 * se]; }
function ciSeries(name, color, pts, horizontal, symbol = "circle") {
  // a filled dot when the 95% interval excludes zero, hollow when it does not
  const off = (p) => !(p.lo <= 0 && p.hi >= 0);
  return [
    { type: "custom", name, itemStyle: { color }, z: 2,
      renderItem: (params, a) => {
        const p1 = horizontal ? a.coord([a.value(1), a.value(0)]) : a.coord([a.value(0), a.value(1)]);
        const p2 = horizontal ? a.coord([a.value(2), a.value(0)]) : a.coord([a.value(0), a.value(2)]);
        return { type: "line", shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] }, style: { stroke: color, lineWidth: 2, lineCap: "round" } };
      },
      data: pts.map((p) => ({ value: [p.pos, p.lo, p.hi], r: p.r })), encode: horizontal ? { x: [1, 2], y: 0 } : { x: 0, y: [1, 2] } },
    { type: "scatter", name, symbol, symbolSize: 11, z: 3, itemStyle: { color, borderColor: css("--surface"), borderWidth: 2 },
      data: pts.map((p) => ({ value: horizontal ? [p.b, p.pos] : [p.pos, p.b], r: p.r,
        itemStyle: off(p) ? { color, borderColor: css("--surface"), borderWidth: 2 } : { color: css("--surface"), borderColor: color, borderWidth: 2 } })) },
  ];
}
const coefTip = () => ({ trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
  formatter: (p) => { const r = p.data?.r; if (!r) return "";
    return `${esc(methodLabel(r.method))}<br>${GROUPS[r.doc_type]}, tone ${r.regressor} &rarr; ${OUTCOMES[r.outcome]}<br>&beta; <b>${fmt.signed(r.beta_bp_per_sd, 2)}</b> bp/SD &middot; t ${fmt.num(r.t)} &middot; n ${r.n}${r.q_bh !== null && r.q_bh !== undefined ? ` &middot; q ${fmt.num(r.q_bh, 3)}` : ""}`; } });
const zeroLine = (axisKey) => ({ type: "line", data: [], markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: css("--muted"), type: "solid" }, data: [{ [axisKey]: 0 }] } });
function methodColor(m) {
  const key = String(m || "").replace(/^shift:/, "");
  if (key.startsWith("llm")) return css("--claude");
  return { dictionary: css("--s1"), embedding: css("--s2"), supervised: css("--s4") }[key] || css("--muted");
}
const methodDot = (m) => `<i class="mdot" style="background:${methodColor(m)}"></i>`;

function groupChart(el, rows, methods) {
  const groups = Object.keys(GROUPS); const narrow = el.clientWidth < 520;
  const series = methods.flatMap((m, k) => {
    const off = (k - (methods.length - 1) / 2) * 0.22;
    const pts = rows.filter((r) => r.method === m && groups.includes(r.doc_type)).map((r) => { const [lo, hi] = ci95(r); return { pos: groups.indexOf(r.doc_type) + off, b: r.beta_bp_per_sd, lo, hi, r }; });
    return ciSeries(methodLabel(m), methodColor(m), pts, true, m.startsWith("llmshift") ? "diamond" : "circle");
  });
  fresh(el).setOption(base({
    grid: { left: narrow ? 96 : 168, right: 24, top: 36, bottom: 42 },
    legend: { top: 0, icon: "circle", itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-2") }, data: methods.map(methodLabel) },
    tooltip: coefTip(),
    xAxis: { type: "value", name: "bp per SD of tone (hollow: interval spans zero)", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: css("--text-2") },
      ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } } }) },
    yAxis: [{ type: "value", min: -0.5, max: groups.length - 0.5, inverse: true, show: false },
      { type: "category", data: groups.map((g) => (narrow ? GROUP_SHORT : GROUPS)[g]), inverse: true, position: "left", boundaryGap: true,
        ...axis({ splitLine: { show: true, lineStyle: { color: css("--grid") } }, axisLabel: { color: css("--text-2"), fontSize: 12 } }) }],
    series: [...series, zeroLine("xAxis")],
    graphic: series.length ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "Not estimated for this selection", fill: css("--muted"), fontSize: 13 } }],
  }));
}

function termChart(el, rows, methods) {
  const series = methods.flatMap((m, k) => {
    const off = (k - (methods.length - 1) / 2) * 0.16; const color = methodColor(m);
    const pts = TENORS.map((o, i) => { const r = rows.find((x) => x.method === m && x.outcome === o); if (!r) return null; const [lo, hi] = ci95(r); return { pos: i + off, b: r.beta_bp_per_sd, lo, hi, r }; }).filter(Boolean);
    return [{ type: "line", name: methodLabel(m), silent: true, z: 1, showSymbol: false, data: pts.map((p) => [p.pos, p.b]), lineStyle: { width: 1, color, opacity: 0.35 }, itemStyle: { color } },
      ...ciSeries(methodLabel(m), color, pts, false, m.startsWith("llmshift") ? "diamond" : "circle")];
  });
  fresh(el).setOption(base({
    grid: { left: 54, right: 16, top: 56, bottom: 30 }, // room for the legend above the axis name
    legend: { top: 0, icon: "circle", itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-2") }, data: methods.map(methodLabel) },
    tooltip: coefTip(),
    xAxis: [{ type: "value", min: -0.5, max: TENORS.length - 0.5, show: false },
      { type: "category", data: TENORS.map((t) => OUTCOMES[t]), position: "bottom", boundaryGap: true, ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 12 } }) }],
    yAxis: { type: "value", name: "bp per SD", nameTextStyle: { color: css("--text-2") }, ...axis({ axisLine: { show: false } }) },
    series: [...series, zeroLine("yAxis")],
  }));
}

function curveChart(el, data) {
  const spec = [["dovish", css("--dove"), "Most dovish third"], ["middle", css("--muted"), "Middle third"], ["hawkish", css("--hawk"), "Most hawkish third"]];
  const days = (data.middle || data.dovish || data.hawkish || []).map((p) => String(p.day));
  const series = [];
  spec.forEach(([b, color, name]) => {
    const pts = data[b] || []; if (!pts.length) return;
    if (b !== "middle") {
      // the 95% interval as two hairlines: filled bands of opposite colors would mix where they overlap
      [-1, 1].forEach((side) => series.push({ type: "line", name: name + " band", silent: true, showSymbol: false, z: 1,
        lineStyle: { width: 1, color, opacity: 0.45, type: [3, 3] }, data: pts.map((p) => p.mean_bp + side * 1.96 * p.se_bp) }));
    }
    series.push({ type: "line", name, showSymbol: false, z: 3, lineStyle: { width: 2, color }, itemStyle: { color }, data: pts.map((p) => ({ value: p.mean_bp, se: p.se_bp, n: p.n })) });
  });
  const c = fresh(el);
  c.setOption(base({
    grid: { left: 54, right: 18, top: 56, bottom: 44 },
    legend: { top: 0, icon: "roundRect", itemWidth: 16, itemHeight: 3, textStyle: { color: css("--text-2") }, data: spec.filter(([b]) => data[b]).map(([, , n]) => n) },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
      formatter: (ps) => `Day ${ps[0].axisValue}<br>` + ps.filter((p) => !p.seriesName.endsWith(" band")).map((p) => `${p.marker}${p.seriesName}: <b>${fmt.signed(p.data.value, 1)} bp</b> <span style="color:var(--muted)">&plusmn;${fmt.num(1.96 * p.data.se, 1)}, n ${p.data.n}</span>`).join("<br>") },
    xAxis: { type: "category", data: days, boundaryGap: false, name: "trading days from the close that ends the release window", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: css("--text-2") }, ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), interval: 4 } }) },
    yAxis: { type: "value", name: "cumulative 2y, bp", nameTextStyle: { color: css("--text-2") }, ...axis() },
    series: [...series, { type: "line", data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: css("--muted"), type: "dashed" }, label: { color: css("--text-2"), formatter: "window closes", position: "end", rotate: 0, fontSize: 11 }, data: [{ xAxis: "0" }] } }],
    graphic: series.length ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "Too few documents for terciles", fill: css("--muted"), fontSize: 13 } }],
  }));
}

// Dashboard small multiples keep each tercile's uncertainty separate; the Story retains its compact overlay.
function curveSmallMultiples(root, data) {
  const all = Object.values(data).flat();
  if (!all.length) {
    $$(".curve-small", root).forEach((el) => { const old = echarts.getInstanceByDom(el); if (old) dropChart(old); });
    root.innerHTML = empty("Too few documents for terciles", "Choose another group or reader.");
    return;
  }
  const bounds = all.flatMap((p) => [p.mean_bp - 1.96 * p.se_bp, p.mean_bp + 1.96 * p.se_bp]);
  const lo = Math.floor(Math.min(0, ...bounds) / 5) * 5, hi = Math.ceil(Math.max(0, ...bounds) / 5) * 5;
  const spec = [["dovish", "Most dovish third", css("--dove"), "var(--dove-ink)"], ["middle", "Middle third", css("--muted"), "var(--text-2)"], ["hawkish", "Most hawkish third", css("--hawk"), "var(--hawk-ink)"]];
  // Reuse hosts when changing a selection, so old ECharts instances can be disposed before replacement.
  if (!root.querySelector("[data-tercile]")) root.innerHTML = spec.map(([key, label, , ink]) => `<figure><figcaption style="color:${ink}">${label}</figcaption><div class="chart curve-small" data-tercile="${key}"></div></figure>`).join("");
  spec.forEach(([key, label, color]) => {
    const el = root.querySelector(`[data-tercile="${key}"]`), pts = data[key] || [];
    const ribbons = pts.slice(1).map((p, i) => { const a = pts[i]; return [a.day, a.mean_bp - 1.96 * a.se_bp, a.mean_bp + 1.96 * a.se_bp, p.day, p.mean_bp - 1.96 * p.se_bp, p.mean_bp + 1.96 * p.se_bp]; });
    fresh(el).setOption(base({
      toolbox: { show: false }, grid: { left: 44, right: 12, top: 26, bottom: 44 },
      tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
        formatter: (ps) => { const p = ps.find((p) => p.data?.se !== undefined); return p ? `${esc(label)} &middot; day ${p.data.value[0]}<br>Mean <b>${fmt.signed(p.data.value[1], 1)} bp</b><br>95% interval ±${fmt.num(1.96 * p.data.se, 1)} bp &middot; n ${p.data.n}` : ""; } },
      xAxis: { type: "value", min: Math.min(...all.map((p) => p.day)), max: Math.max(...all.map((p) => p.day)), interval: 5,
        name: "Trading days", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: css("--text-2"), fontSize: 11 }, ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
      yAxis: { type: "value", min: lo, max: hi > lo ? hi : lo + 5, name: "bp", nameTextStyle: { color: css("--text-2"), fontSize: 11 },
        ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } }, axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
      series: [
        { type: "custom", silent: true, z: 1, clip: true, data: ribbons, encode: { x: [0, 3], y: [1, 2, 4, 5] },
          renderItem: (params, a) => ({ type: "polygon", shape: { points: [a.coord([a.value(0), a.value(1)]), a.coord([a.value(0), a.value(2)]), a.coord([a.value(3), a.value(5)]), a.coord([a.value(3), a.value(4)])] }, style: { fill: color, opacity: 0.16 } }) },
        { type: "line", name: label, showSymbol: false, z: 3, lineStyle: { width: 2, color }, itemStyle: { color },
          data: pts.map((p) => ({ value: [p.day, p.mean_bp], se: p.se_bp, n: p.n })),
          markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: css("--muted"), type: "dashed", width: 1 }, data: [{ xAxis: 0 }, { yAxis: 0 }] } },
      ],
      graphic: pts.length ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "No tercile data", fill: css("--muted"), fontSize: 12 } }],
    }));
  });
}
const eventMobileSelect = (id, label, rows, value) => `<label class="ev-mobile-select" for="${id}"><span>${label}</span><select id="${id}">${rows.map(([k, v]) => `<option value="${esc(k)}" ${k === value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;

pages["event-study"] = {
  title: "Event study", sub: "Treasury moves over each release window, regressed on tone: basis points per one standard deviation, with placebo, drift, controls, sample splits and false-discovery control.",
  async render(view) {
    const all = await api("/api/event-study");
    if (!all.length) { view.innerHTML = `<div class="card">${empty("No results yet", "Run " + code("fomc evaluate"))}</div>`; return; }
    const methods = [...new Set(all.map((r) => r.method))];
    const vp = viewParams();
    if (vp.get("out") && OUTCOMES[vp.get("out")]) evState.outcome = vp.get("out");
    if (["level", "shift"].includes(vp.get("reg"))) evState.regressor = vp.get("reg");
    if (ROBUST[vp.get("rob")]) evState.robust = vp.get("rob");
    if (GROUPS[vp.get("focus")]) evState.focus = vp.get("focus");
    if (vp.get("m")) evState.methods = vp.get("m").split(",");
    if (vp.get("curve")) evState.curve = vp.get("curve");
    evState.methods = (evState.methods || methods).filter((m) => methods.includes(m)).slice(0, 3);
    if (!evState.methods.length) evState.methods = methods.slice(0, 3);
    if (!evState.curve || !methods.includes(evState.curve)) {
      evState.curve = methods.includes(state.method) ? state.method : methods.find((m) => m.startsWith("llm:")) || (methods.includes("supervised") ? "supervised" : methods[0]);
    }
    const main = all.filter((r) => r.sample === "all" && r.control === "none");
    const tests = main.filter((r) => r.q_bh !== null && r.q_bh !== undefined);
    const survive = tests.filter((r) => r.q_bh < 0.1);
    const d2y = main.filter((r) => r.outcome === "d2y" && ["statement", "minutes", "presser", "speech"].includes(r.doc_type));
    const best = d2y.length ? d2y.reduce((a, b) => (Math.abs(b.t) > Math.abs(a.t) ? b : a)) : null;
    const same = (r, extra) => all.find((x) => x.doc_type === r.doc_type && x.method === r.method && x.regressor === r.regressor && x.outcome === r.outcome && Object.entries(extra).every(([k, v]) => x[k] === v));
    const ctrl = best ? same(best, { sample: "all", control: "d3m" }) : null;
    const pre = best ? all.find((x) => x.doc_type === best.doc_type && x.method === best.method && x.regressor === best.regressor && x.outcome === "pre_d2y" && x.sample === "all" && x.control === "none") : null;
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">Strongest release-day effect</div><div class="value">${best ? "t = " + fmt.num(best.t) : dash}</div><div class="foot">${best ? `${GROUPS[best.doc_type]}, tone ${best.regressor}, ${esc(methodLabel(best.method))}: ${fmt.signed(best.beta_bp_per_sd)} bp/SD on the 2-year` : ""}</div></div>
        <div class="card kpi"><div class="label">Same test, day before (placebo)</div><div class="value">${pre ? "t = " + fmt.num(pre.t) : dash}</div><div class="foot">tone should not explain moves before the release</div></div>
        <div class="card kpi"><div class="label">With the 3-month bill control</div><div class="value">${ctrl ? "t = " + fmt.num(ctrl.t) : dash}</div><div class="foot">beyond the near-term rate surprise</div></div>
        <div class="card kpi"><div class="label">Survive false-discovery control</div><div class="value">${survive.length}<small class="of"> of ${tests.length}</small></div><div class="foot">Benjamini-Hochberg q below 0.10 across the main grid</div></div>
      </div>
      <div class="card">
        <div class="card-head"><div><h2>Effect by document type</h2></div></div>
        <div class="ev-mobile-controls">
          ${eventMobileSelect("ev-out-mobile", "Outcome", Object.entries(OUTCOMES), evState.outcome)}
          ${eventMobileSelect("ev-reg-mobile", "Tone", [["level", "Level"], ["shift", "Change"]], evState.regressor)}
          ${eventMobileSelect("ev-rob-mobile", "View", Object.entries(ROBUST).map(([k, v]) => [k, v[2]]), evState.robust)}
        </div>
        <div class="toolbar ev-desktop-controls">
          <span class="ctl-label">Outcome</span><div class="seg" id="ev-out">${Object.entries(OUTCOMES).map(([k, v]) => `<button data-k="${k}" class="${k === evState.outcome ? "on" : ""}">${v}</button>`).join("")}</div>
          <span class="ctl-label">Tone</span><div class="seg" id="ev-reg">${["level", "shift"].map((k) => `<button data-k="${k}" class="${k === evState.regressor ? "on" : ""}">${k === "level" ? "level" : "change"}</button>`).join("")}</div>
        </div>
        <div class="toolbar" style="margin-top:10px">
          <div class="ev-desktop-controls ev-view-control"><span class="ctl-label">View</span><div class="seg" id="ev-rob">${Object.entries(ROBUST).map(([k, v]) => `<button data-k="${k}" class="${k === evState.robust ? "on" : ""}">${v[2]}</button>`).join("")}</div></div>
          <span class="ctl-label">Readers, up to 3</span><div class="chips" id="ev-m">${methods.map((m) => `<button class="chip ${evState.methods.includes(m) ? "on" : ""}" data-m="${esc(m)}">${methodDot(m)}${esc(methodLabel(m))}</button>`).join("")}</div>
        </div>
        <div class="caption-row"><div class="sub" id="ev-caption"></div>${info("<b>How to read this.</b> Dots are coefficients with 95% intervals (HC1). <b>Day before</b> is a placebo; <b>next 5 / 20 days</b> test whether anything is left to trade. Robustness views exist for the 2y, 10y and 2s10s: the <b>3-month bill</b> control asks for tone beyond the near-term rate surprise (it over-controls if tone itself moves expectations), the <b>rate decision</b> control applies to statements and press conferences, and the split samples check that an effect is not one era. q-values control the false-discovery rate across the main grid.")}</div>
        <div id="c-ev" class="chart tall" style="margin-top:4px"></div>

      </div>
      <div class="card">
        <div class="card-head"><div><h2>Focus on one group</h2><div class="sub">Across the curve, and the path of the 2-year around the release, for the tone regressor selected above</div></div>
          <div class="toolbar ev-desktop-controls"><div class="seg" id="ev-focus">${Object.entries(GROUP_SHORT).map(([k, v]) => `<button data-k="${k}" class="${k === evState.focus ? "on" : ""}">${v}</button>`).join("")}</div></div></div>
        <div class="ev-mobile-controls">${eventMobileSelect("ev-focus-mobile", "Document group", Object.entries(GROUP_SHORT), evState.focus)}</div>
        <div><div class="mini-head"><div><h3 class="mini-title">Response across the curve</h3><div class="sub">bp per SD of tone, release window, 95% intervals</div></div></div><div id="c-term" class="chart"></div></div>
        <div class="event-terciles"><div class="mini-head"><div><h3 class="mini-title">Around the release, by tercile of tone</h3><div class="sub">Average cumulative 2-year move; shaded bands are 95% intervals. Shared scales; day 0 ends the release window.</div></div>
          <label class="ev-curve-reader" for="ev-curve"><span>Curve reader</span><select id="ev-curve" class="compact">${methods.map((m) => `<option value="${esc(m)}" ${m === evState.curve ? "selected" : ""}>${esc(methodLabel(m))}</option>`).join("")}</select></label></div><div id="c-curves" class="curve-triptych"></div></div>
      </div>
      <div class="card"><div class="card-head"><div><h2>Coefficients ${info("For the outcome and robustness view selected above. Bold t: |t| of 2 or more. FDR badge: Benjamini-Hochberg q below 0.10 across the main grid.")}</h2></div></div><div id="ev-table"></div></div>`;

    const syncControls = () => {
      [["out", "outcome"], ["reg", "regressor"], ["rob", "robust"], ["focus", "focus"]].forEach(([id, key]) => {
        $(`#ev-${id}-mobile`).value = evState[key];
        $$(`#ev-${id} button`).forEach((b) => b.classList.toggle("on", b.dataset.k === evState[key]));
      });
    };
    const drawMain = () => {
      const robustOk = ROBUST_OUTCOMES.includes(evState.outcome);
      if (!robustOk) evState.robust = "base";
      remember(); syncControls();
      $$("#ev-rob button").forEach((b) => { b.disabled = !robustOk && b.dataset.k !== "base"; });
      $$("#ev-rob-mobile option").forEach((o) => { o.disabled = !robustOk && o.value !== "base"; });
      const [sample, control] = ROBUST[evState.robust];
      const rows = all.filter((r) => r.outcome === evState.outcome && r.sample === sample && r.control === control);
      groupChart($("#c-ev"), rows.filter((r) => r.regressor === evState.regressor && evState.methods.includes(r.method)), evState.methods);
      $("#ev-caption").innerHTML = `<b>${OUTCOME_LONG[evState.outcome]}</b> &middot; tone ${evState.regressor} &middot; ${ROBUST[evState.robust][2].replace(/^\+ /, "with ")}`;
      const order = Object.keys(GROUPS); const sorted = [...rows].sort((a, b) => order.indexOf(a.doc_type) - order.indexOf(b.doc_type) || a.method.localeCompare(b.method) || a.regressor.localeCompare(b.regressor));
      $("#ev-table").innerHTML = `<div class="table-wrap scroll-box" style="max-height:520px"><table class="table"><thead><tr><th>Group</th><th>Method</th><th>Tone</th><th class="num wide-only">n</th><th class="num">&beta; bp/SD</th><th class="num">t</th><th class="num wide-only">p</th><th class="num">q (BH)</th><th class="num wide-only">R&sup2;</th></tr></thead>
        <tbody>${sorted.map((r) => `<tr style="cursor:default"><td>${esc(GROUP_SHORT[r.doc_type] || GROUPS[r.doc_type] || r.doc_type)}</td><td class="nowrap">${methodDot(r.method)}${esc(methodLabel(r.method))}</td><td>${r.regressor === "level" ? "level" : "change"}</td><td class="num wide-only">${r.n}</td><td class="num">${fmt.signed(r.beta_bp_per_sd)}</td>
        <td class="num" style="${Math.abs(r.t) >= 2 ? "font-weight:700;color:var(--text)" : "color:var(--text-2)"}">${fmt.num(r.t)}</td><td class="num wide-only">${fmt.num(r.p, 3)}</td><td class="num">${r.q_bh === null || r.q_bh === undefined ? dash : fmt.num(r.q_bh, 3) + (r.q_bh < 0.1 ? '<span class="qbadge">FDR</span>' : "")}</td><td class="num wide-only">${fmt.num(r.r2, 3)}</td></tr>`).join("") || `<tr><td colspan="9" class="muted">Not estimated for this selection</td></tr>`}</tbody></table></div>`;
    };
    const remember = () => setViewParams({ out: evState.outcome, reg: evState.regressor, rob: evState.robust === "base" ? null : evState.robust,
      m: evState.methods, focus: evState.focus, curve: evState.curve });
    const drawFocus = async () => {
      remember(); syncControls();
      const rows = main.filter((r) => r.doc_type === evState.focus && r.regressor === evState.regressor && evState.methods.includes(r.method));
      termChart($("#c-term"), rows, evState.methods);
      const selection = [evState.focus, evState.curve, evState.regressor].join("|");
      const current = () => selection === [evState.focus, evState.curve, evState.regressor].join("|") && $("#c-curves");
      let cv;
      try { cv = await api(`/api/event-curves?${new URLSearchParams({ doc_type: evState.focus, method: evState.curve, regressor: evState.regressor })}`); }
      catch (e) {  // never leave the previous group's curves under the new selection
        const root = current(); if (!root) return;
        $$(".curve-small", root).forEach((el) => dropChart(echarts.getInstanceByDom(el)));
        root.innerHTML = empty("Response curves unavailable", esc(e.message)); return;
      }
      if (current()) curveSmallMultiples($("#c-curves"), cv);
    };
    const segClick = (id, key, after) => { $(id).onclick = (e) => { const b = e.target.closest("button"); if (!b || b.disabled) return; evState[key] = b.dataset.k; $$(id + " button").forEach((x) => x.classList.toggle("on", x === b)); after(); }; };
    segClick("#ev-out", "outcome", drawMain);
    segClick("#ev-reg", "regressor", () => { drawMain(); drawFocus(); });
    segClick("#ev-rob", "robust", drawMain);
    segClick("#ev-focus", "focus", drawFocus);
    [["out", "outcome", drawMain], ["reg", "regressor", () => { drawMain(); drawFocus(); }], ["rob", "robust", drawMain], ["focus", "focus", drawFocus]].forEach(([id, key, after]) => {
      $(`#ev-${id}-mobile`).onchange = (e) => { evState[key] = e.target.value; after(); };
    });
    $("#ev-curve").onchange = (e) => { evState.curve = e.target.value; drawFocus(); };
    $("#ev-m").onclick = (e) => {
      const b = e.target.closest("[data-m]"); if (!b) return;
      if (!b.classList.contains("on") && $$("#ev-m .on").length >= 3) { toast("Up to three methods at once"); return; }
      if (b.classList.contains("on") && $$("#ev-m .on").length === 1) return;
      b.classList.toggle("on"); evState.methods = $$("#ev-m .on").map((x) => x.dataset.m); drawMain(); drawFocus();
    };
    drawMain(); drawFocus();
  },
};

// ------------------------------------------------------------------- backtest
const SHORT_METHOD = { dictionary: "Dictionary", supervised: "TF-IDF", embedding: "Embeddings" };
const shortMethod = (m) => (String(m).startsWith("shift:") ? shortMethod(m.slice(6)) + ", change" : String(m).startsWith("llmshift") ? "Claude vs previous" : String(m).startsWith("llm") ? "Claude" : SHORT_METHOD[m] || methodLabel(m));
const runSpec = (id) => { const [, t, h, e] = id.split("|"); return `${t.replace("+", " + ")} · ${h.replace(/^h(\d+)$/, "$1-day hold")} · ${e === "etf_entry" ? "same-close entry" : "next-day entry"}`; };
const runName = (id) => { const [m, t, h, e] = id.split("|"); return `${methodLabel(m)} · ${t.replace("+", " + ")} · ${h.replace(/^h(\d+)$/, "$1-day hold")} · ${e === "etf_entry" ? "same close" : "next day"}`; };
pages.backtest = {
  title: "Backtest", sub: "Duration tilt in IEF against SHY: hawkish shortens, dovish extends. Trades use only what was public at the time, costs included, and every variant is reported and counts against the result.",
  async render(view) {
    const rows = await api("/api/backtests");
    if (!rows.length) { view.innerHTML = `<div class="card">${empty("No backtests yet", "Run " + code("fomc backtest"))}</div>`; return; }
    if (![null, "", "AGG", "IEI"].includes(viewParams().get("bench"))) setViewParams({ bench: null });
    const prim = rows.find((r) => r.is_primary);
    const hurdle = rows[0].sharpe_hurdle; const trials = rows[0].n_trials || rows.length;
    const bestDsr = rows.filter((r) => r.dsr !== null).reduce((a, b) => (!a || b.dsr > a.dsr ? b : a), null);
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">Variants tested</div><div class="value">${rows.length}</div><div class="foot">all reported, none hidden</div></div>
        <div class="card kpi"><div class="label">Luck hurdle (Sharpe)</div><div class="value">${fmt.num(hurdle)}</div><div class="foot">what the best of ${trials} no-skill variants would show by chance</div></div>
        <div class="card kpi"><div class="label">Pre-registered primary</div><div class="value">${prim ? fmt.num(prim.sharpe) : dash}</div><div class="foot">${prim ? `Sharpe; PSR ${pct(prim.psr)}, t ${fmt.num(prim.t_nw)} (Newey-West)${prim.active_bp === null || prim.active_bp === undefined ? "" : `; ${fmt.signed(prim.active_bp, 0)} bp a year on AGG at &plusmn;1 year of duration`}` : "Claude score, minutes + speeches, next-day entry, 5-day hold: runs once Claude scores exist"}</div></div>
        <div class="card kpi"><div class="label">Best deflated Sharpe</div><div class="value">${bestDsr ? pct(bestDsr.dsr) : dash}</div><div class="foot">${bestDsr ? `${esc(runName(bestDsr.run_id))}; 95% would clear the hurdle` : ""}</div></div>
      </div>
      <div class="card"><div class="card-head"><div><h2 id="bt-title">Cumulative return ${info("Overlay: summed daily returns of IEF against SHY, after costs. On AGG or IEI: the same trade sized to move that portfolio's duration by up to one year, against the portfolio alone. Click a row in the table below to plot it.")}</h2><div class="sub keep" id="bt-spec"></div></div>
        <div class="seg" id="bt-bench" role="group" aria-label="Show the trade as">${[["", "Overlay"], ["AGG", "On AGG"], ["IEI", "On IEI"]].map(([k, v]) => `<button data-b="${k}" class="${k === (viewParams().get("bench") || "") ? "on" : ""}" aria-pressed="${k === (viewParams().get("bench") || "")}">${v}</button>`).join("")}</div></div><div id="c-bt" class="chart tall"></div></div>
      <div class="card"><div class="card-head"><div><h2>All variants</h2><div class="sub">Shaded row = pre-registered primary. PSR: confidence that the true Sharpe is above zero, allowing for skew and fat tails. DSR: the same against the luck hurdle, for exploratory variants. Development 2009-2019, holdout 2020-Jun 2026.</div></div>
        <select id="bt-filter" aria-label="Filter variants by method"><option value="">All methods</option>${[...new Set(rows.map((r) => r.method))].map((m) => `<option value="${esc(m)}">${esc(methodLabel(m))}</option>`).join("")}</select></div>
        <div id="bt-table"></div></div>`;
    const table = (filter) => {
      const list = rows.filter((r) => !filter || r.method === filter);
      $("#bt-table").innerHTML = `<p class="hint">Click a row to plot it; the shaded row is the pre-registered primary. Scroll to see every measure.</p><div class="bt-scroll-shell"><div class="table-wrap scroll-box bt-scroll" tabindex="0" role="region" aria-label="All backtest variants, scroll horizontally for more measures" style="max-height:520px"><table class="table bt"><thead><tr><th>Method</th><th>Tone</th><th class="wide-only">Documents</th><th class="num wide-only">Hold</th><th class="wide-only">Entry</th><th class="num wide-only">Signals</th><th class="num">Sharpe</th><th class="num wide-only">t (NW)</th><th class="num">PSR</th><th class="num">DSR</th><th class="num wide-only">Hit</th><th class="num wide-only">Dev</th><th class="num wide-only">Holdout</th><th class="num wide-only">After cutoff</th><th class="num wide-only">AGG bp/yr</th><th class="num wide-only">Placebo p</th></tr></thead>
        <tbody>${list.map((r) => `<tr data-run="${esc(r.run_id)}" class="${r.is_primary ? "primary" : ""}"><td class="method">${methodDot(r.method)}${esc(methodLabel(r.method))}${r.is_primary ? ' <span class="qbadge">pre-registered</span>' : ""}<div class="phone-only small muted">${esc(runSpec(r.run_id))}</div></td><td class="nowrap">${r.signal === "shift" || r.method.startsWith("llmshift:") ? "Change" : "Level"}</td><td class="nowrap wide-only">${r.doc_types.replace("+", " + ")}</td><td class="num wide-only">${r.hold}d</td><td class="nowrap wide-only">${r.entry === "etf_entry" ? "same close" : "next day"}</td>
        <td class="num wide-only">${fmt.int(r.n_signals)}</td><td class="num"><b>${fmt.num(r.sharpe)}</b></td><td class="num wide-only">${fmt.num(r.t_nw)}</td><td class="num">${pct(r.psr)}</td><td class="num" style="${r.dsr >= 0.95 ? "font-weight:700;color:var(--text)" : "color:var(--text-2)"}">${pct(r.dsr)}</td><td class="num wide-only">${r.hit_rate === null ? dash : fmt.num(r.hit_rate * 100, 0) + "%"}</td>
        <td class="num wide-only">${fmt.num(r.sharpe_development)}</td><td class="num wide-only">${fmt.num(r.sharpe_holdout)}</td><td class="num wide-only">${fmt.num(r.sharpe_post_cutoff)}</td><td class="num wide-only">${r.active_bp === null || r.active_bp === undefined ? dash : fmt.signed(r.active_bp, 0)}</td><td class="num wide-only">${fmt.num(r.placebo_p)}</td></tr>`).join("")}</tbody></table></div></div>`;
      $("#bt-table tbody").onclick = (e) => { const tr = e.target.closest("[data-run]"); if (tr) plot([tr.dataset.run]); };
      const scroll = $(".bt-scroll");
      const scrollHint = () => scroll.parentElement.classList.toggle("has-more", scroll.scrollWidth - scroll.clientWidth - scroll.scrollLeft > 2);
      scroll.addEventListener("scroll", scrollHint, { passive: true });
      requestAnimationFrame(scrollHint);
    };
    let shown = [], plotSeq = 0;
    const plot = async (runIds) => {
      shown = runIds;
      const owner = ++plotSeq, root = $("#c-bt");
      if (!root || !view.isConnected) return;
      const candidate = viewParams().get("bench") || "";
      const bench = ["", "AGG", "IEI"].includes(candidate) ? candidate : "";
      if (candidate !== bench) setViewParams({ bench: null });
      setViewParams({ run: runIds.length === 1 ? runIds[0] : null });
      const specs = [...new Set(runIds.map(runSpec))];
      $("#bt-spec").textContent = specs.length === 1 ? `${specs[0]}${bench ? `, on ${bench}` : ""}` : "";
      let curves;
      try {
        curves = await Promise.all(runIds.map((id) => api("/api/backtests/curve?run_id=" + encodeURIComponent(id) + (bench ? "&benchmark=" + bench : ""))));
      } catch (error) {
        if (owner !== plotSeq || !root.isConnected) return;
        const old = echarts.getInstanceByDom(root); if (old) dropChart(old);
        root.innerHTML = empty("Could not load this curve", esc(error.message));
        return;
      }
      if (owner !== plotSeq || !root.isConnected) return;
      // the pre-registered run in its method's color and weight; the others thinner, named at their ends
      const isPrim = (id) => rows.some((r) => r.run_id === id && r.is_primary);
      const ends = [];
      const series = curves.map((cv, i) => { const id = runIds[i]; const m = id.split("|")[0]; const lead = isPrim(id) || runIds.length === 1; const color = methodColor(m);
        const last = cv.length ? (bench ? cv[cv.length - 1].port : cv[cv.length - 1].cum) * 100 : null;
        if (last !== null) ends.push(last);
        return { type: "line", name: shortMethod(m) + (isPrim(id) ? " (pre-registered)" : "") + (specs.length > 1 ? `, ${runSpec(id)}` : ""), showSymbol: false, z: lead ? 4 : 2,
          lineStyle: { width: lead ? 2.5 : 1.25, color, opacity: lead ? 1 : 0.7 }, itemStyle: { color }, emphasis: { focus: "series" },
          data: cv.map((p) => [p.date, (bench ? p.port : p.cum) * 100]),
          endLabel: { show: true, color: css("--text-2"), fontSize: 11, formatter: (p) => `${shortMethod(m)} ${fmt.signed(p.value[1], 1)}%` }, labelLayout: { moveOverlap: "shiftY" } }; });
      if (bench && curves.length) series.push({ type: "line", name: `${bench} alone`, showSymbol: false, lineStyle: { width: 1.5, type: "dashed", color: css("--muted") }, itemStyle: { color: css("--muted") },
        data: curves[0].map((p) => [p.date, p.bench * 100]), endLabel: { show: true, color: css("--text-2"), fontSize: 11, formatter: (p) => `${bench} ${fmt.signed(p.value[1], 1)}%` }, labelLayout: { moveOverlap: "shiftY" } });
      if (series.length) series[0].markLine = { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: css("--text-2"), width: 1, type: "solid", opacity: 0.5 }, data: [{ yAxis: 0 }] };
      const narrow = $("#c-bt").clientWidth < 520;
      fresh($("#c-bt")).setOption(base({
        grid: { left: 48, right: narrow ? 104 : 130, top: 24, bottom: 34 },
        tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
          formatter: (ps) => `${fmt.date(ps[0].axisValue)}<br>` + ps.map((p) => `${p.marker}${esc(p.seriesName)}: <b>${fmt.signed(p.value[1], 1)}%</b>`).join("<br>") },
        xAxis: { type: "time", ...axis({ splitLine: { show: false } }) },
        yAxis: { type: "value", name: bench ? "cumulative return %" : "cumulative %", nameTextStyle: { color: css("--text-2") },
          max: (v) => Math.max(1, Math.ceil(v.max)), ...axis({ axisLabel: { color: css("--text-2"), formatter: (v) => fmt.signed(v, 0).replace(/^\+0$/, "0") } }) },
        dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false }],
        series,
      }));
    };
    $("#bt-bench").onclick = (e) => {
      const b = e.target.closest("button[data-b]"); if (!b) return;
      setViewParams({ bench: b.dataset.b || null });
      $$("#bt-bench button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
      plot(shown);
    };
    $("#bt-filter").onchange = (e) => { setViewParams({ m: e.target.value }); table(e.target.value); };
    const vpm = viewParams().get("m") || "";
    if (vpm) $("#bt-filter").value = vpm;
    table(vpm);
    const primaryRuns = rows.filter((r) => r.doc_types === "minutes+speech" && r.hold === 5 && r.entry === "etf_entry_next").map((r) => r.run_id).slice(0, 3);
    const vpRun = viewParams().get("run");
    plot(vpRun && rows.some((r) => r.run_id === vpRun) ? [vpRun] : primaryRuns.length ? primaryRuns : [rows[0].run_id]);
  },
};

// ------------------------------------------------------------ duration scenarios
pages.duration = {
  title: "Signal to exposure", usesMethod: false,
  sub: "Follow a scored Fed document through its earlier history and frozen sizing rule into dollar exposure. Review its evidence, timing and historical test alongside a what-if stress calculation.",
  async render(view) {
    const meta = await api("/api/duration");
    if (!view.isConnected) return;
    const requested=viewParams().get("signal") || state.durationSource;
    // a document the frozen reader never scored (a stale bookmark, a mistyped id) falls back to a custom scenario
    const envelope=requested==="custom"?{context:null,reason:null}:await api("/api/duration/context"+(requested?"?doc_id="+encodeURIComponent(requested):"")).catch(()=>({context:null,missing:true,reason:requested?"No reading from the frozen reader exists for that document, so a custom scenario is shown.":"The document link is unavailable, so a custom scenario is shown."}));
    if (!view.isConnected) return;
    const context=envelope.context, sourceID=context?.document.doc_id || (envelope.missing ? "custom" : requested || "custom");
    if(envelope.missing&&viewParams().get("signal"))setViewParams({signal:null});
    state.durationSource=sourceID;
    const fields = [
      ["nav_usd", "Portfolio market value (USD)", 1, 1e12, "any"],
      ["base_duration", "Portfolio modified duration (years)", 0, 30, "any"],
      ["duration_change", "Requested duration change (years)", -5, 5, "any"],
      ["duration_budget", "Duration budget (+/- years)", 0, 5, "any"],
      ["shock_bp", "Parallel yield shock (bp)", -500, 500, "any"],
      ["cost_bp_per_side", "Cost per ETF leg (bp of notional)", 0, 100, "any"],
    ];
    const finding = meta.research;
    const values = { ...meta.defaults, ...(state.durationInputs || {}) };
    // a document's rule moves duration by theta times the budget, as in the historical test
    const ruleChange=(budget)=>+(context.theta*Number(budget)).toFixed(4);
    if(state.durationAppliedDoc!==sourceID){
      values.duration_change=context?context.eligible?ruleChange(values.duration_budget):0:meta.defaults.duration_change;
      state.durationAppliedDoc=sourceID;state.durationRuleApplied=Boolean(context?.eligible);state.durationInputs={...values};
    }
    const choices=[...(meta.documents || [])];
    if(context&&!choices.some(d=>d.doc_id===sourceID))choices.unshift(context.document);
    const sourcePanel=`<div class="card duration-source"><div class="card-head"><div><h2>1. Choose the evidence</h2><p class="sub keep">The frozen primary reader, using earlier policy-relevant documents of the same type.</p></div><a class="btn ghost small" href="#/documents">Browse documents</a></div>
      <label class="field"><span>Fed document or custom scenario</span><select id="duration-source"><option value="custom" ${sourceID==="custom"?"selected":""}>Custom scenario, no document signal</option>${choices.map(d=>`<option value="${esc(d.doc_id)}" ${d.doc_id===sourceID?"selected":""}>${esc(d.release_date)} · ${esc(ONE[d.doc_type])} · ${esc((d.title||d.speaker||d.doc_id).slice(0,100))}</option>`).join("")}</select></label>
      ${context?`<div class="duration-chain"><div><span>Document</span><b>${esc(ONE[context.document.doc_type])}</b><small>${esc(context.document.release_date)} ${esc(context.document.release_time_et||"")} ET</small></div><div><span>Tone reading</span><b>${fmt.signed(context.document.score)}</b><small>${esc(methodLabel(context.method))}, ${context.history_n} earlier peers</small></div><div><span>Single-document rule</span><b>${context.eligible?fmt.signed(context.theta)+" × budget":"No rule-sized trade"}</b><small>${context.z===null?"Signal unavailable":"z = "+fmt.signed(context.z)+"; "+fmt.signed(context.duration_change_years)+" years at the research's "+fmt.num(context.duration_budget_years,1)+"-year budget"}</small></div><div><span>Frozen trade timing</span><b>${context.entry_date?fmt.date(context.entry_date):"Entry not available"}</b><small>${context.hold_days}-day hold, earns after entry close</small></div></div>
      <p class="small ${context.eligible?"muted":""}">${esc(context.reason || context.scope)}</p>
      <p id="duration-link-state" class="small muted">${state.durationRuleApplied?"Requested exposure below follows this isolated document rule: theta times your duration budget, as in the historical test, which also combines overlapping trades.":!context.eligible&&Number(values.duration_change)===0?"This document gets no rule-sized trade, so the change below starts at zero; enter a change to explore a manual scenario.":"A manual scenario is selected; the document is reference evidence."}</p>
      <div class="duration-links"><a class="btn ghost small" href="#/duration?signal=${encodeURIComponent(sourceID)}&doc=${encodeURIComponent(sourceID)}">Read evidence</a><a class="btn ghost small" href="#/backtest?run=${encodeURIComponent(context.run_id)}&bench=AGG">Frozen test on AGG</a><a class="btn ghost small" href="#/event-study?focus=${context.document.doc_type}">Yield response study</a><a class="btn ghost small" href="#/forward">Forward test</a></div>`:`<p class="small muted">${esc(envelope.reason || "Choose a document to trace its signal, or enter a custom duration change below.")}</p>`}</div>`;
    view.innerHTML = `${sourcePanel}<div class="card note-card"><b>Historical strategy evidence: ${esc(finding?.verdict || "unavailable")}</b><p>${finding ? `${esc(finding.value)} ${esc(finding.unit)}. ${esc(finding.detail)}.` : "No stored primary result is available."} The linked rule is a research illustration, with no demonstrated reliable trading edge.</p></div>
      <div class="card"><div class="card-head"><div><h2>2. Size the exposure</h2><div class="sub">Positive changes extend duration; positive shocks raise yields. Portfolio duration is your input. A document's rule scales with the duration budget; a manual change is capped at it.</div></div></div>
      <p class="small muted keep">Assumed ETF durations: ${esc(meta.assumptions.long_etf)} ${fmt.num(meta.assumptions.long_duration, 1)} years; ${esc(meta.assumptions.short_etf)} ${fmt.num(meta.assumptions.short_duration, 1)} years. Fixed inputs, not live estimates.</p>
      <form id="duration-form"><div class="duration-fields">${fields.map(([key, label, min, max, step]) => `<label class="field"><span>${label}</span><input name="${key}" type="number" required min="${min}" max="${max}" step="${step}" value="${esc(values[key])}"></label>`).join("")}</div>
      <div class="duration-actions"><button class="btn" type="submit">Calculate scenario</button><button class="btn ghost" type="button" id="duration-reset">Reset example</button><span class="small muted">Calculations stay out of the research store and use no model call.</span></div></form>
      <div id="duration-error" class="duration-error" role="alert" hidden></div></div>
      <div id="duration-output" aria-live="polite"></div>
      <div class="card"><h2>Assumptions and execution limits</h2><p>${esc(meta.assumptions.duration_source)}: ${esc(meta.assumptions.long_etf)} ${fmt.num(meta.assumptions.long_duration, 1)} years, ${esc(meta.assumptions.short_etf)} ${fmt.num(meta.assumptions.short_duration, 1)} years. Stored ETF prices through ${esc(meta.market_as_of || "an unavailable date")}; this calculation does not use live prices.</p><p>${esc(meta.assumptions.pnl_method)}. ${esc(meta.assumptions.execution_limit)}</p>
      <p class="small muted">A single dollar DV01 does not measure yield-curve twists or credit-spread risk. Large shocks need fuller repricing. ${meta.assumptions.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.label)}</a>`).join("; ")}</p></div>`;
    const form = $("#duration-form"), out = $("#duration-output"), error = $("#duration-error");
    $("#duration-source").onchange=e=>{state.durationInputs=Object.fromEntries(new FormData(form));state.durationSource=e.target.value;state.durationAppliedDoc=null;setViewParams({signal:e.target.value==="custom"?null:e.target.value});route({force:true});};
    let calculation = 0;
    const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value === 0 ? 0 : value).replace("-", "−");
    const compactMoney = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
    const draw = (r) => {
      const selected = r.selected;
      out.innerHTML = `${r.budget_capped ? `<div class="card note-card"><b>Active duration limit applied.</b> Requested ${fmt.signed(r.inputs.duration_change)} years; applied ${fmt.signed(r.applied_duration_change)} years.</div>` : ""}
        ${r.target_duration < 0 ? '<div class="card note-card"><b>Net short duration.</b> The selected target has negative rate duration under these assumptions.</div>' : ""}
        <div class="kpis duration-kpis">
          <div class="card kpi"><div class="label">Portfolio duration after tilt</div><div class="value">${fmt.num(r.target_duration)} <small class="of">years</small></div><div class="foot">Before ${fmt.num(r.inputs.base_duration)}; change ${fmt.signed(r.applied_duration_change)} years</div></div>
          <div class="card kpi"><div class="label">Dollar DV01 after tilt</div><div class="value">${money(r.dv01_after_usd)}</div><div class="foot">USD per bp; before <span class="nowrap">${money(r.dv01_before_usd)}</span>, active <span class="nowrap">${money(r.dv01_active_usd)}</span></div></div>
          <div class="card kpi"><div class="label">Round-trip trading cost</div><div class="value">${money(r.cost_usd)}</div><div class="foot">Both legs, in and out: ${money(r.traded_notional_usd)} traded, as in the historical test</div></div>
          <div class="card kpi"><div class="label">P&amp;L after tilt and cost</div><div class="value">${money(selected.portfolio_pnl_after_cost_usd)}</div><div class="foot">${fmt.signed(selected.shock_bp, 1)} bp parallel yield shock</div></div>
        </div>
        <div class="card"><h2>Illustrative equal-dollar overlay</h2><div class="duration-legs">${r.legs.map((leg) => `<div><b>${esc(leg.action === "none" ? "No trade" : leg.action === "buy" ? "Buy" : "Sell")} ${esc(leg.ticker)}</b><span>${money(Math.abs(leg.signed_notional_usd))}</span></div>`).join("")}</div>
        ${r.gross_notional_usd ? `<p class="small">${esc(r.assumptions.execution_limit)}</p>` : ""}
        <p class="small muted">${r.breakeven_shock_bp === null ? "No active duration change, no trade and no transaction cost." : `Cost break-even: a ${fmt.signed(r.breakeven_shock_bp, 2)} bp parallel yield move, ignoring carry, financing and convexity. The two legs offset in dollars, not in DV01.`}</p></div>
        <div class="card"><div class="card-head"><div><h2>3. Stress the result</h2><div class="sub">First-order mark-to-market P&amp;L in USD. The adjusted portfolio includes the round-trip trading cost.</div></div></div><div id="c-duration" class="chart"></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Yield shock</th><th class="num">Before tilt</th><th class="num">Active, net cost</th><th class="num">After tilt, net cost</th></tr></thead><tbody>${r.scenarios.map((s) => `<tr><td data-sort-value="${s.shock_bp}">${fmt.signed(s.shock_bp, 0)} bp</td><td class="num" data-sort-value="${s.base_pnl_usd}">${money(s.base_pnl_usd)}</td><td class="num" data-sort-value="${s.active_pnl_after_cost_usd}">${money(s.active_pnl_after_cost_usd)}</td><td class="num" data-sort-value="${s.portfolio_pnl_after_cost_usd}">${money(s.portfolio_pnl_after_cost_usd)}</td></tr>`).join("")}</tbody></table></div></div>`;
      fresh($("#c-duration")).setOption(base({ legend: { top: 0, textStyle: { color: css("--text-2") } }, grid: { left: 70, right: 15, top: 40, bottom: 38 },
        tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") }, formatter: (ps) => `${ps[0].axisValue} bp<br>` + ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${money(p.value[1])}`).join("<br>") },
        xAxis: { type: "value", min: r.scenarios[0].shock_bp, max: r.scenarios[r.scenarios.length - 1].shock_bp, ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } } }), name: "bp", nameGap: 4, nameTextStyle: { color: css("--text-2") } },
        yAxis: { type: "value", ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } }, axisLabel: { color: css("--text-2"), formatter: (n) => compactMoney.format(n).replace("-", "−") } }), name: "USD", nameLocation: "middle", nameRotate: 90, nameGap: 54, nameTextStyle: { color: css("--text-2") } },
        series: [["Before tilt", "base_pnl_usd", css("--muted")], ["After tilt, net cost", "portfolio_pnl_after_cost_usd", css("--dove")]].map(([name, key, color]) => ({ name, type: "line", symbolSize: 8, itemStyle: { color }, lineStyle: { color, width: 2 }, data: r.scenarios.map((s) => [s.shock_bp, s[key]]) })) }));
      tuck(out); enhance(out);
    };
    const calculate = async () => {
      if (!form.reportValidity()) return;
      const owner = ++calculation, body = Object.fromEntries(new FormData(form));
      Object.keys(body).forEach((k) => { body[k] = Number(body[k]); });
      if (state.durationRuleApplied && context?.eligible) body.signal_theta = context.theta;
      error.hidden = true; out.setAttribute("aria-busy", "true");
      const old = $("#c-duration"); if (old) { const chart = echarts.getInstanceByDom(old); if (chart) dropChart(chart); }
      out.innerHTML = '<div class="card muted">Calculating scenario...</div>';
      try {
        const result = await request("/api/duration/scenario", { method: "POST", body: JSON.stringify(body) });
        if (owner === calculation && view.isConnected) draw(result);
      } catch (e) {
        if (owner !== calculation || !view.isConnected) return;
        out.innerHTML = ""; error.hidden = false; error.textContent = "Could not calculate: " + e.message;
      } finally { if (owner === calculation) out.removeAttribute("aria-busy"); }
    };
    form.onsubmit = (e) => { e.preventDefault(); calculate(); };
    form.oninput = (event) => {
      state.durationInputs = Object.fromEntries(new FormData(form));  // tab memory only, no financial inputs in localStorage
      if(event.target.name==="duration_change"){state.durationRuleApplied=false;const note=$("#duration-link-state");if(note)note.textContent="Manual exposure override. The selected document remains reference evidence.";}
      if(event.target.name==="duration_budget"&&state.durationRuleApplied&&context?.eligible&&event.target.value!==""){form.elements.duration_change.value=ruleChange(event.target.value);state.durationInputs=Object.fromEntries(new FormData(form));}
      ++calculation;
      out.setAttribute("aria-busy", "false");
      const old = $("#c-duration"); if (old) { const chart = echarts.getInstanceByDom(old); if (chart) dropChart(chart); }
      out.innerHTML = '<div class="card muted">Inputs changed. Calculate to update the scenario.</div>';
    };
    $("#duration-reset").onclick = () => {
      state.durationInputs=null;state.durationSource="custom";state.durationAppliedDoc=null;state.durationRuleApplied=false;setViewParams({signal:null});route({force:true});
    };
    await calculate();
  },
};

// -------------------------------------------------------------------- next decision
const DECISION = { "-1": "cut", 0: "hold", 1: "hike" };
function forecastChart(el, meetings, compact = false, showDifference = false) {
  const fs = compact ? 10 : 12;
  const lo = Math.min(-1.5, Math.floor(2 * Math.min(...meetings.flatMap((m) => [m.market, m.both]))) / 2);
  const hi = Math.max(1.5, Math.ceil(2 * Math.max(...meetings.flatMap((m) => [m.market, m.both]))) / 2);
  const byDate = Object.fromEntries(meetings.map((m) => [m.date, m]));
  const fed = (a, name, color) => ({ name, type: "scatter", z: 3, symbolSize: showDifference ? 8 : compact ? 5 : 7, itemStyle: { color, borderColor: css("--surface"), borderWidth: 1.2 },
    data: meetings.filter((m) => m.action === a).map((m) => [m.date, m.action]) });
  const grid = compact ? { left: 40, right: 10, top: 28, bottom: 22 } : { left: 52, right: 20, top: 40, bottom: 30 };
  const timeAxis = { type: "time", ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: fs, hideOverlap: true, formatter: { year: "{yyyy}", month: "", day: "" } } }) };
  const decisionAxis = { type: "value", min: lo, max: hi, interval: 0.5, ...axis({ axisLabel: { color: css("--text-2"), fontSize: fs, formatter: (x) => DECISION[x] || "" } }) };
  const series = [
    { name: "Market alone", type: "line", showSymbol: false, z: 1, lineStyle: { width: 2, color: css("--muted") }, itemStyle: { color: css("--muted") }, data: meetings.map((m) => [m.date, m.market]) },
    { name: "Market and tone", type: "line", showSymbol: false, z: 2, lineStyle: { width: 2, color: css("--claude") }, itemStyle: { color: css("--claude") }, data: meetings.map((m) => [m.date, m.both]) },
    fed(1, "Hike", css("--hawk")), fed(0, "Hold", css("--text-2")), fed(-1, "Cut", css("--dove")),
  ];
  let pane = {};
  if (showDifference) {
    const h = el.clientHeight || 460, left = compact ? 44 : 52, right = compact ? 12 : 20, lowerTop = Math.round(h * 0.73);
    const extent = { min: meetings[0].date, max: meetings[meetings.length - 1].date };
    const limit = Math.max(0.1, Math.ceil(10 * Math.max(...meetings.map((m) => Math.abs(m.both - m.market)))) / 10);
    pane = {
      grid: [{ left, right, top: 40, height: lowerTop - 100 }, { left, right, top: lowerTop, bottom: 30 }],
      xAxis: [{ ...timeAxis, ...extent, axisLabel: { show: false } }, { ...timeAxis, ...extent, gridIndex: 1 }],
      yAxis: [decisionAxis, { type: "value", gridIndex: 1, min: -limit, max: limit, splitNumber: 2,
        ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } }, axisLabel: { color: css("--text-2"), fontSize: fs, formatter: (v) => fmt.signed(v, 1) } }) }],
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      graphic: [{ type: "text", left, top: lowerTop - 26, style: { text: "Tone contribution (with minus without)", fill: css("--text-2"), fontSize: fs, fontWeight: 600 } }],
    };
    // This panel is only a subtraction of the two stored forecasts, with no refitting.
    series.push({ name: "Tone contribution", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 8, z: 2,
      data: meetings.map((m) => ({ value: [m.date, m.both - m.market], row: m, itemStyle: { color: css(m.both >= m.market ? "--hawk" : "--dove"), opacity: 0.8 } })),
      markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: css("--muted"), width: 1 }, data: [{ yAxis: 0 }] } });
  }
  mk(el).setOption(base({
    grid, legend: { top: 0, itemWidth: 16, itemHeight: 8, textStyle: { color: css("--text-2"), fontSize: fs }, data: ["Market alone", "Market and tone", "Hike", "Hold", "Cut"] },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: fs },
      formatter: (ps) => { if (!ps.length) return ""; const m = ps.find((p) => p.data?.row)?.data.row || byDate[isoDay(ps[0].axisValue)] || meetings[ps[0].dataIndex]; if (!m) return "";
        return `${fmt.date(m.date)}: <b>${DECISION[m.action]}</b><br>Market and tone: ${fmt.signed(m.both, 2)}<br>Market alone: ${fmt.signed(m.market, 2)}${showDifference ? `<br>Tone contribution: <b>${fmt.signed(m.both - m.market, 3)}</b>` : ""}`; } },
    xAxis: timeAxis, yAxis: decisionAxis, series, ...pane,
  }));
}
pages.forecast = {
  title: "Next decision", sub: "Does Fed language say more about the next decision than the market already prices? Each decision since 2009 (cut, hold or hike) is fit on the market's lean at the last close before it and on the tone of the latest minutes, recent speeches and the previous statement; the forecasts from 2017 use only earlier decisions. Added after the results, so exploratory.",
  async render(view) {
    const f = await api("/api/forecast");
    if (!f.n) { view.innerHTML = `<div class="card">${empty("Not computed yet", "Run " + code("fomc forecast") + " once Claude scores exist.")}</div>`; return; }
    const ins = f.in_sample, oos = f.out_of_sample; const pv = (p) => (p < 0.001 ? "&lt; 0.001" : fmt.num(p, 3));
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">Decisions since ${f.first.slice(0, 4)}</div><div class="value">${f.n}</div><div class="foot">${f.moves.hikes} hikes and ${f.moves.cuts} cuts; the rest holds</div></div>
        <div class="card kpi"><div class="label">The market's lean alone</div><div class="value">R² ${fmt.num(ins.r2_market, 2)}</div><div class="foot">3-month bill and 2-year over the policy rate, the evening before</div></div>
        <div class="card kpi"><div class="label">Adding Claude's tone</div><div class="value">R² ${fmt.num(ins.r2_both, 2)}</div><div class="foot">the three tone inputs together: F-test p = ${fmt.num(ins.p, 3)}</div></div>
        <div class="card kpi"><div class="label">In real time, ${oos.start.slice(0, 4)} on</div><div class="value">${fmt.num(oos.mse_both, 3)}<small class="of"> vs ${fmt.num(oos.mse_market, 3)}</small></div><div class="foot">squared error with tone vs without, ${oos.n} decisions; p = ${fmt.num(oos.p_boot, 2)}</div></div>
      </div>
      <div class="card"><div class="card-head"><div><h2>Forecasts made before each decision</h2><div class="sub">Each line is refit on the decisions before it, then forecasts the next one (cut −1, hold 0, hike +1); the dots are what the Fed did.</div></div></div><div id="c-forecast" class="chart forecast-panels"></div><p class="small muted">Lower bars subtract the market-only forecast from the forecast with tone. Positive bars shift the call toward a hike; negative bars toward a cut. Both panels use the same dates.</p></div>
      <div class="card"><div class="card-head"><div><h2>What each input adds</h2><div class="sub">Linear model of the decision on all ${f.n} decisions, inputs per standard deviation, HC1 errors.</div></div></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Input</th><th class="num">Per SD</th><th class="num">t</th><th class="num">p</th></tr></thead>
        <tbody>${ins.coefs.map((c) => `<tr style="cursor:default"><td>${esc(c.name)}</td><td class="num">${fmt.signed(c.beta, 3)}</td><td class="num">${fmt.num(c.t, 2)}</td><td class="num">${pv(c.p)}</td></tr>`).join("")}</tbody></table></div></div>`;
    forecastChart($("#c-forecast"), f.meetings, $("#c-forecast").clientWidth < 520, true);
  },
};

// ---------------------------------------------------------------- forward test
pages.forward = {
  title: "Forward test", sub: "The research was frozen on 21 October 2026. Since then the same rules are applied to each day of new data as it is collected: the pre-registered duration tilt, and each document type's strongest release-day relationship. Nothing is re-fit; give it a year before reading anything into it.",
  async render(view) {
    const f = await api("/api/forward");
    if (!f.freeze) { view.innerHTML = `<div class="card">${empty("Not computed yet", "Run " + code("fomc forward"))}</div>`; return; }
    const t = f.tilt || {}; const s = f.summary || {}; const READS = { level: "tone", shift: "change in tone" };
    const today = new Date(); const since = Math.max(0, Math.round((Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) - Date.parse(f.freeze)) / 864e5));
    const reads = (r) => (r.method && r.method.startsWith("llmshift:") ? "Claude's comparison with the last statement" : READS[r.measure]);
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">Frozen</div><div class="value">${since}<small class="of"> day${since === 1 ? "" : "s"} ago</small></div><div class="foot">on ${fmt.date(f.freeze)}; market data through ${f.as_of ? fmt.date(f.as_of) : dash}</div></div>
        <div class="card kpi"><div class="label">Release-day direction</div><div class="value">${s.called ? `${s.hits}<small class="of"> of ${s.called}</small>` : dash}</div><div class="foot">${s.p !== undefined ? `releases that moved the 2-year the way the rule said; one-sided p = ${fmt.num(s.p, 3)}` : "releases that moved the 2-year the way the rule said; a p-value from 10 on"}</div></div>
        <div class="card kpi"><div class="label">The pre-registered tilt</div><div class="value">${t.days ? `${fmt.signed(t.active_bp, 1)}<small class="of"> bp</small>` : dash}</div><div class="foot">${t.days ? `active return on an aggregate-bond portfolio over ${t.days} trading days, costs included` : "counts from the first close after the freeze"}</div></div>
        <div class="card kpi"><div class="label">Trades since the freeze</div><div class="value">${t.signals ?? dash}</div><div class="foot">minutes and speeches read by Claude, entered at the second close, held five days</div></div>
      </div>
      ${!(t.curve && t.curve.length) && !f.releases.length ? `<div class="card note-card"><b>Nothing to score yet.</b> Returns count from the first close after the freeze, and each statement, set of minutes, press conference and policy speech appears once its release window closes. The rules below are what they will be judged against.</div>` : `<div class="card"><div class="card-head"><div><h2>The trade since the freeze</h2><div class="sub">Cumulative active return of the pre-registered duration tilt on an aggregate-bond portfolio, in basis points, costs included, computed by the backtest's own code.</div></div></div>${t.curve && t.curve.length ? '<div id="c-forward" class="chart"></div>' : empty("No trading days yet", "Returns count from the first close after the freeze.")}</div>
      <div class="card"><div class="card-head"><div><h2>Every release since the freeze</h2><div class="sub">For each release, the 2-year move its type's frozen rule predicts (coefficient times standardized tone) beside the move over its release window.</div></div></div>
        ${f.releases.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Released</th><th>Document</th><th class="wide-only">Reads</th><th class="num wide-only">Tone, SD</th><th class="num">Predicted, bp</th><th class="num">Actual, bp</th><th>Right way</th></tr></thead>
          <tbody>${[...f.releases].reverse().map((r) => `<tr data-doc="${esc(r.doc_id)}"><td class="nowrap">${fmt.date(r.date)}</td><td>${ONE[r.doc_type] || esc(r.doc_type)}</td><td class="wide-only">${reads(r)}</td><td class="num wide-only">${fmt.signed(r.z, 2)}</td><td class="num">${fmt.signed(r.predicted_bp, 1)}</td><td class="num">${fmt.signed(r.actual_bp, 1)}</td><td>${r.hit === null ? "no move" : r.hit ? "yes" : "no"}</td></tr>`).join("")}</tbody></table></div>`
          : empty("No releases yet", "Each statement, set of minutes, press conference and policy speech after the freeze appears here once its release window closes.")}</div>`}
      <div class="card"><div class="card-head"><div><h2>The frozen rules</h2><div class="sub">Written once, at the first run after the freeze, to data/forward/rules.json: per document type, Claude's strongest 2-year relationship that survived false-discovery control in the event study.</div></div></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Document type</th><th class="wide-only">Reads</th><th class="num">bp per SD</th><th class="num wide-only">t</th><th class="num">q</th><th class="num wide-only">n</th></tr></thead>
        <tbody>${(f.rules || []).map((r) => `<tr style="cursor:default"><td>${TYPES[r.doc_type] || esc(r.doc_type)}<div class="phone-only small muted">${reads(r)}</div></td><td class="wide-only">${reads(r)}</td><td class="num">${fmt.signed(r.beta_bp_per_sd, 2)}</td><td class="num wide-only">${fmt.num(r.t, 2)}</td><td class="num">${fmt.num(r.q, 3)}</td><td class="num wide-only">${fmt.int(r.n)}</td></tr>`).join("")}</tbody></table></div></div>`;
    if (t.curve && t.curve.length) {
      mk($("#c-forward")).setOption(base({ grid: { left: 52, right: 20, top: 16, bottom: 30 },
        tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") }, formatter: (p) => `${fmt.date(p[0].data[0])}<br><b>${fmt.signed(p[0].data[1], 1)} bp</b>` },
        xAxis: { type: "time", ...axis({ splitLine: { show: false } }) }, yAxis: { type: "value", ...axis({ axisLabel: { color: css("--text-2"), formatter: (x) => x + " bp" } }) },
        series: [{ type: "line", showSymbol: t.curve.length < 30, symbolSize: 6, lineStyle: { width: 2, color: css("--claude") }, itemStyle: { color: css("--claude") }, data: t.curve }, zeroLine("yAxis")] }));
    }
    view.querySelectorAll("tr[data-doc]").forEach((el) => el.addEventListener("click", () => openDoc(el.dataset.doc)));
  },
};

// -------------------------------------------------------------------- validity
function teamCard(t) {
  if (!t.items) {
    return `<div class="card"><h2>Team labels after the knowledge cutoff</h2><div class="sub keep">The post-cutoff human test was not run; this tool remains available for a later check.</div>
      <div style="margin-top:12px">${empty("No team sentences yet", "Sample a set with " + code("fomc label-sample --n 150") + ' then label them under <a href="#/label">Team labels</a>.')}</div></div>`;
  }
  const done = t.annotators.reduce((a, r) => a + r.n, 0);
  return `<div class="card"><div class="card-head"><div><h2>Team labels after the knowledge cutoff</h2><div class="sub keep">${fmt.int(t.items)} post-cutoff sentences; ${done ? `${fmt.int(done)} human labels from ${t.annotators.length} annotators` : 'the human test was not run. Model predictions are not human labels'}</div></div><a href="#/label">Open the labeling tool &rarr;</a></div>
    <div class="grid cols-2">
      <div><div class="section-title" style="margin-top:4px">Agreement between people</div>${t.pairs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Pair</th><th class="num">Sentences</th><th class="num">Agreement</th><th class="num">Kappa</th></tr></thead><tbody>${t.pairs.map((p) => `<tr style="cursor:default"><td>${esc(p.a)} &middot; ${esc(p.b)}</td><td class="num">${p.n}</td><td class="num">${pct(p.agreement)}</td><td class="num"><b>${fmt.num(p.kappa)}</b></td></tr>`).join("")}</tbody></table></div>` : `<p class="small muted">Needs two annotators with at least 10 sentences in common. Kappa between people is the ceiling a method can be expected to reach.</p>`}</div>
      <div><div class="section-title" style="margin-top:4px">Methods against the majority label</div>${t.methods.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Method</th><th class="num">n</th><th class="num">Accuracy</th><th class="num">Macro-F1</th><th class="num">Kappa</th></tr></thead><tbody>${t.methods.map((m) => `<tr style="cursor:default"><td>${esc(methodLabel(m.method))}</td><td class="num">${m.n}</td><td class="num">${pct(m.accuracy)}</td><td class="num"><b>${fmt.num(m.macro_f1, 3)}</b></td><td class="num">${fmt.num(m.kappa, 3)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="small muted">Appears once at least 10 sentences have a majority label. Claude's labels join with ${code("fomc llm-submit --what team")}</p>`}</div>
    </div></div>`;
}
const statViewMode = (id) => local.get("statView." + id, "chart") === "table" ? "table" : "chart";
function statView(id, label, chart, table) {
  const mode = statViewMode(id);
  return `<section class="stat-view" data-stat-view="${id}" aria-labelledby="stat-${id}-label">
    <div class="stat-view-head"><h3 id="stat-${id}-label" class="stat-view-title">${esc(label)}</h3>
      <div class="seg stat-view-toggle" role="group" aria-label="${esc(label)} display">${["chart", "table"].map((m) => `<button type="button" data-stat-mode="${m}" class="${mode === m ? "on" : ""}" aria-pressed="${mode === m}" aria-controls="stat-${id}-${m}">${m === "chart" ? "Chart" : "Table"}</button>`).join("")}</div></div>
    <div id="stat-${id}-chart" data-stat-panel="chart" ${mode === "chart" ? "" : "hidden"}>${chart}</div>
    <div id="stat-${id}-table" data-stat-panel="table" ${mode === "table" ? "" : "hidden"}>${table}</div>
  </section>`;
}
function statNumber(value, digits = 3, signed = false) {
  if (!Number.isFinite(value)) return `<td class="num">${dash}</td>`;
  const text = digits === 0 ? fmt.int(value) : signed ? fmt.signed(value, digits) : fmt.num(value, digits);
  return `<td class="num" data-sort-value="${value}">${text}</td>`;
}
function statP(value) {
  return Number.isFinite(value) ? `<td class="num" data-sort-value="${value}">${value < 0.001 ? "&lt; 0.001" : fmt.num(value, 3)}</td>` : `<td class="num">${dash}</td>`;
}
function statTable(label, headers, rows) {
  return `<div class="table-wrap stat-view-table" role="region" aria-label="${esc(label)} table, scroll for all columns" tabindex="0"><table class="table" aria-label="${esc(label)}">
    <thead><tr>${headers.map((h, i) => `<th scope="col"${i ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr class="${r.chosen ? "primary" : ""}" style="cursor:default">${r.cells.join("")}</tr>`).join("")}</tbody></table></div>`;
}
function mountStatViews(root, renderers) {
  root.querySelectorAll("[data-stat-view]").forEach((box) => {
    const id = box.dataset.statView;
    const chartPanel = box.querySelector('[data-stat-panel="chart"]');
    const tablePanel = box.querySelector('[data-stat-panel="table"]');
    const chart = chartPanel.querySelector(".chart");
    const show = (mode) => {
      chartPanel.hidden = mode !== "chart"; tablePanel.hidden = mode !== "table";
      box.querySelectorAll("[data-stat-mode]").forEach((b) => {
        const active = b.dataset.statMode === mode;
        b.classList.toggle("on", active); b.setAttribute("aria-pressed", String(active));
      });
      // Only initialize a visible chart; dispose hidden instances and their ResizeObservers.
      dropChart(echarts.getInstanceByDom(chart)); chart.innerHTML = "";
      if (mode === "chart") renderers[id](chart);
      else enhance(tablePanel);
    };
    box.querySelector(".stat-view-toggle").addEventListener("click", (e) => {
      const button = e.target.closest("[data-stat-mode]"); if (!button) return;
      local.set("statView." + id, button.dataset.statMode); show(button.dataset.statMode);
    });
    show(statViewMode(id));
  });
}
function reliabilityCard(r, validityRows = []) {
  const tests = r.tests || []; const st = r.stability; const inv = r.invariance; const dr = r.drift;
  const idf = r.identify ? r.identify.statement || Object.values(r.identify)[0] : null;
  if (!tests.length && !st && !inv && !idf) return "";
  const last = dr && dr.months && dr.months.length ? dr.months[dr.months.length - 1] : null;
  const month = (m) => new Date(m + "-15").toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const kpi = (label, value, foot) => `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="foot keep">${foot}</div></div>`;
  const leadTable = statTable("Claude's macro-F1 lead", ["Reader", "n", "Macro-F1 gap", "95% CI low", "95% CI high", "Bootstrap p", "McNemar p"], tests.map((t) => ({ cells: [
    `<td>${methodDot(t.method)}${esc(methodLabel(t.method))}${REFERENCE.has(t.method) ? ' <span class="pill-mini">reference</span>' : ""}</td>`,
    statNumber(validityRows.find((v) => v.method === t.target)?.n, 0), statNumber(t.f1_diff, 3, true), statNumber(t.ci_low, 3, true), statNumber(t.ci_high, 3, true), statP(t.p_boot), statP(t.mcnemar_p),
  ] })));
  const table = tests.length
    ? statView("validity-lead", "Claude's macro-F1 lead",
      `<div id="c-validity-lead" class="chart validity-lead"></div><p class="small muted">Dots show Claude minus each reader, with 95% paired-bootstrap intervals; the zero line means equal macro-F1. Hover for bootstrap and McNemar p-values.</p>`,
      leadTable + '<p class="small muted">Paired bootstrap over the same expert-labeled sentences (2,000 resamples); scroll for all statistics.</p>')
    : '<p class="small muted">Appears once Claude has labeled the 496 test sentences.</p>';
  const stats = [
    st ? kpi("Scored twice", pct(st.overall_stance_agreement), `same overall stance on ${st.n} documents re-scored in a separate batch; r = ${fmt.num(st.corr_stance_score, 3)}`) : "",
    idf ? kpi("Masked dating", `<span style="color:var(--warn-ink)">${pct(idf.exact_month)}</span>`, "of masked statements dated to the exact month: Claude recognizes them") : "",
    inv ? kpi("Masked scoring", `r = ${fmt.num(inv.corr_stance_score)}`, `scores with and without dates, names and rates; same stance on ${pct(inv.overall_stance_agreement)} of ${inv.n}`) : "",
    dr ? kpi("Monthly re-read", last ? (last.drifted ? '<span style="color:var(--warn-ink)">Drifted</span>' : pct(last.overall_stance_agreement)) : `${dr.anchors.length}<small class="of"> documents</small>`,
      last ? `${last.drifted ? "the reader has moved: start a new experiment identity. " : ""}${month(last.month)}: the ${last.n} anchor documents read again, same stance on ${pct(last.overall_stance_agreement)}, mean change ${fmt.num(last.mean_abs_diff, 3)}`
        : `${dr.anchors.length} fixed documents are read again each month, through today's model and pipeline`) : "",
  ].join("");
  return `<div class="card"><h2>How far to trust the readings ${info("<b>Three questions.</b> Is Claude's lead over the baselines larger than chance on these 496 sentences? Does Claude give the same answer when asked again in a separate batch? Do its scores depend on recognizing the document? The last two come from the memorization audit after HW2.")}</h2>
    <div class="grid cols-2" style="margin-top:12px"><div>${table}${tests.length ? '<p class="small muted stat-view-caveat">RoBERTa is a reference outside H1. Positive gaps favor Claude; public-label training exposure remains possible.</p>' : ""}</div><div class="rel-stats">${stats || '<p class="small muted">Run the audit: ' + code("fomc audit") + "</p>"}</div></div></div>`;
}
const REFERENCE = new Set(["roberta_tuned", "fomc_roberta"]); // readers added after the results: outside H1
// each bar in its method's color, kappa lighter than macro-F1; a reader outside H1 drawn as an outline
const refBar = (r, v, light) => ({ value: v, itemStyle: REFERENCE.has(r.method)
  ? { color: "transparent", borderColor: css("--text-2"), borderWidth: 1.5, borderType: light ? "dashed" : "solid", borderRadius: [0, 4, 4, 0] }
  : { color: methodColor(r.method), opacity: light ? 0.45 : 1, borderRadius: [0, 4, 4, 0] } });
// Horizontal intervals share the same coordinates as their dots; no statistics are re-estimated here.
function researchRangeSeries(points) {
  return [
    { type: "custom", silent: false, z: 2, encode: { x: [0, 2, 3], y: 1 }, data: points,
      renderItem: (params, a) => {
        const lo = a.coord([a.value(2), a.value(1)]), hi = a.coord([a.value(3), a.value(1)]);
        const color = points[params.dataIndex].color;
        return { type: "group", children: [
          { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: color, lineWidth: 2 } },
          ...[lo, hi].map((v) => ({ type: "line", shape: { x1: v[0], y1: v[1] - 4, x2: v[0], y2: v[1] + 4 }, style: { stroke: color, lineWidth: 1.5 } })),
        ] };
      } },
    { type: "scatter", symbolSize: 10, z: 3, encode: { x: 0, y: 1 }, data: points },
  ];
}
function validityLeadChart(el, tests) {
  const points = tests.map((r, i) => ({ value: [r.f1_diff, i, r.ci_low, r.ci_high], row: r, color: methodColor(r.method),
    itemStyle: { color: REFERENCE.has(r.method) ? css("--surface") : methodColor(r.method), borderColor: methodColor(r.method), borderWidth: 2 } }));
  const pv = (p) => p < 0.001 ? "&lt; 0.001" : fmt.num(p, 3);
  mk(el).setOption(base({
    grid: { left: 132, right: 20, top: 25, bottom: 42 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") },
      formatter: (p) => { const r = p.data?.row; return r ? `${esc(methodLabel(r.method))}${REFERENCE.has(r.method) ? " (reference, outside H1)" : ""}<br>Claude's macro-F1 lead: <b>${fmt.signed(r.f1_diff, 3)}</b><br>95% interval [${fmt.signed(r.ci_low, 3)}, ${fmt.signed(r.ci_high, 3)}]<br>Bootstrap p ${pv(r.p_boot)} &middot; McNemar p ${pv(r.mcnemar_p)}` : ""; } },
    xAxis: { type: "value", minInterval: 0.1, splitNumber: 4, name: "Claude's macro-F1 lead", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: css("--text-2") },
      ...axis({ axisLine: { onZero: false, lineStyle: { color: css("--border") } }, axisLabel: { color: css("--text-2"), formatter: (v) => fmt.signed(v, 2) } }) },
    yAxis: { type: "category", data: tests.map((r) => methodLabel(r.method) + (REFERENCE.has(r.method) ? " (ref.)" : "")), inverse: true,
      ...axis({ axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: css("--text-2"), width: 115, overflow: "break", fontSize: 11 } }) },
    series: [...researchRangeSeries(points), zeroLine("xAxis")],
  }));
}
const readerConfigKey = (c) => JSON.stringify(Object.keys(c).sort().map((k) => [k, c[k]]));
const readerSetting = (c) => `${c.backbone.split("-").pop()} · ${c.lr.toExponential()}${c.llrd !== 1 ? ` · decay ${c.llrd}` : ""}${c.batch !== 16 ? ` · batch ${c.batch}` : ""}`;
function readerSearchChart(el, r) {
  const points = r.search.map((x, i) => {
    const chosen = readerConfigKey(x.config) === readerConfigKey(r.chosen.config), color = css(chosen ? "--text" : "--muted");
    return { value: [x.cv_macro_f1, i, x.cv_macro_f1 - x.fold_sd, x.cv_macro_f1 + x.fold_sd], row: x, chosen, color,
      itemStyle: { color: chosen ? color : css("--surface"), borderColor: color, borderWidth: 2 } };
  });
  mk(el).setOption(base({
    grid: { left: 132, right: 24, top: 24, bottom: 42 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") },
      formatter: (p) => { const r = p.data?.row; return r ? `${esc(readerSetting(r.config))}${p.data.chosen ? " (chosen)" : ""}<br>CV macro-F1 <b>${fmt.num(r.cv_macro_f1, 4)}</b><br>Fold SD ${fmt.num(r.fold_sd, 4)} &middot; best epoch ${r.best_epoch}` : ""; } },
    xAxis: { type: "value", min: (v) => Math.floor((v.min - 0.01) * 20) / 20, max: (v) => Math.ceil((v.max + 0.01) * 20) / 20,
      name: "Five-fold CV macro-F1", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: css("--text-2") }, ...axis() },
    yAxis: { type: "category", data: r.search.map((x) => readerSetting(x.config)), inverse: true,
      ...axis({ axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10, width: 117, overflow: "break" } }) },
    series: researchRangeSeries(points),
  }));
}
function readerAgreementChart(el, r) {
  const rows = Object.entries(r.types || {}).map(([type, row]) => ({ type, ...row }));
  mk(el).setOption(base({
    grid: { left: 128, right: 44, top: 24, bottom: 42 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") },
      formatter: (p) => { const r = p.data.row; return `${esc(TYPES[r.type])}<br>Pearson <b>${fmt.num(r.pearson, 3)}</b> &middot; Spearman ${fmt.num(r.spearman, 3)}<br>${fmt.int(r.n)} documents scored by both readers`; } },
    xAxis: { type: "value", min: 0, max: 1, name: "Pearson r with Claude", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: css("--text-2") }, ...axis() },
    yAxis: { type: "category", data: rows.map((r) => TYPES[r.type]), inverse: true,
      ...axis({ axisLine: { show: false }, splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 11, width: 112, overflow: "break" } }) },
    series: [{ type: "scatter", symbolSize: 11, label: { show: true, position: "right", color: css("--text"), formatter: (p) => fmt.num(p.data.row.pearson, 2) },
      data: rows.map((r, i) => ({ value: [r.pearson, i], row: r, itemStyle: { color: css("--t-" + r.type) } })) }],
  }));
}
function readersCard(readers, rows) {
  const r = (readers || {}).roberta_tuned; const row = rows.find((x) => x.method === "roberta_tuned");
  if (!r || !r.search || !row) return "";
  const seeds = r.seed_macro_f1 || [];
  const searchTable = statTable("RoBERTa settings", ["Model", "Learning rate", "Layer decay", "Batch", "Best epoch", "CV macro-F1", "Fold SD"], r.search.map((x) => {
    const chosen = readerConfigKey(x.config) === readerConfigKey(r.chosen.config);
    return { chosen, cells: [`<td>${esc(x.config.backbone.split("/").pop())}${chosen ? ' <span class="pill-mini">chosen</span>' : ""}</td>`,
      `<td class="num" data-sort-value="${x.config.lr}">${esc(x.config.lr.toExponential())}</td>`, statNumber(x.config.llrd, 1), statNumber(x.config.batch, 0), statNumber(x.best_epoch, 0), statNumber(x.cv_macro_f1, 4), statNumber(x.fold_sd, 4)] };
  }));
  const agreementRows = Object.entries(r.types || {});
  const agreementTable = statTable("Document score agreement", ["Documents", "n", "Pearson r", "Spearman rho"], agreementRows.map(([type, x]) => ({ cells: [
    `<td>${esc(TYPES[type] || type)}</td>`, statNumber(x.n, 0), statNumber(x.pearson, 3), statNumber(x.spearman, 3),
  ] })));
  return `<div class="card"><h2>A transformer trained on the same labels ${info(`<b>How it was chosen.</b> RoBERTa-base and RoBERTa-large at several learning rates, then two refinements of the best, each scored on the five folds the TF-IDF classifier is tuned on; the best setting and epoch were refit on all 1,984 sentences with five seeds, and their probabilities averaged. <b>Why it is outside H1.</b> H1 was stated against a dictionary, a TF-IDF classifier and sentence embeddings before any result; this reader came afterwards. The test split was read once, by the chosen setting.`)}</h2>
    <div class="sub keep">Fine-tuned here on the 1,984 sentences the TF-IDF classifier learns from: macro-F1 ${fmt.num(row.macro_f1, 3)} on the test split${seeds.length ? `, single seeds ${fmt.num(Math.min(...seeds), 3)} to ${fmt.num(Math.max(...seeds), 3)}` : ""}.</div>
    <div class="grid cols-2 reader-plots">
      <div>${statView("reader-search", "Every setting tried, five folds each",
        '<div id="c-reader-search" class="chart reader-plot"></div><p class="small muted">Dots are mean macro-F1; bars are ±1 fold SD at the best epoch. The filled dot is the chosen setting.</p>',
        searchTable + '<p class="small muted">Five validation folds at each setting\'s best epoch; SD is not a confidence interval.</p>')}</div>
      <div>${agreementRows.length ? statView("reader-agreement", "Document scores against Claude",
        '<div id="c-reader-agreement" class="chart reader-plot"></div><p class="small muted">Hover for document counts and Spearman correlation.</p>',
        agreementTable) + '<p class="small muted stat-view-caveat">RoBERTa averages sentence probabilities; Claude reads the whole document. Correlation measures model agreement.</p>' : '<p class="small muted">Appears once Claude has scored the documents.</p>'}</div>
    </div></div>`;
}
pages.validity = {
  title: "Validity", sub: "Do the methods label tone the way people do? H1 is supported on public expert labels; the post-cutoff human test was not run.",
  async render(view) {
    const [rows, team, rel] = await Promise.all([api("/api/validity"), api("/api/labels/summary"), api("/api/reliability")]);
    if (!rows.length) { view.innerHTML = `<div class="card">${empty("No validity results yet", "Run " + code("fomc baselines"))}</div>` + teamCard(team); return; }
    view.innerHTML = `
      <div class="grid cols-2"><div class="card"><h2>Agreement with human labels</h2><div class="sub keep">496 public expert-labeled sentences; possible training exposure, partly addressed by masking (r = 0.99)</div><div id="c-val" class="chart"></div>
        <div class="legend-inline"><span><i class="lg-solid"></i>macro-F1</span><span><i class="lg-light"></i>Cohen's kappa</span><span><i class="lg-outline"></i>reference reader, outside H1</span></div></div>
      <div class="card"><h2>Scores ${info("<b>Caveat.</b> These labels have been public since 2023, so an LLM may have seen them. The post-cutoff human test was not run. Masked and raw scores agree (r = 0.99), which partly addresses this risk.")}</h2><div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Method</th><th class="num wide-only">n</th><th class="num">Accuracy</th><th class="num">Macro-F1</th><th class="num">Kappa</th></tr></thead>
        <tbody>${rows.map((r) => `<tr style="cursor:default"><td>${methodDot(r.method)}${esc(methodLabel(r.method))}${REFERENCE.has(r.method) ? ' <span class="pill-mini">reference</span>' : ""}</td><td class="num wide-only">${r.n}</td><td class="num">${fmt.num(r.accuracy, 3)}</td><td class="num"><b>${fmt.num(r.macro_f1, 3)}</b></td><td class="num">${fmt.num(r.cohen_kappa, 3)}</td></tr>`).join("")}</tbody></table></div>
</div></div>
      ${reliabilityCard(rel, rows)}
      ${readersCard(rel.readers, rows)}
      ${teamCard(team)}`;
    const tuned = rel.readers?.roberta_tuned;
    mountStatViews(view, {
      "validity-lead": (el) => validityLeadChart(el, rel.tests),
      "reader-search": (el) => readerSearchChart(el, tuned),
      "reader-agreement": (el) => readerAgreementChart(el, tuned),
    });
    mk($("#c-val")).setOption(base({
      grid: { left: 8, right: 24, top: 10, bottom: 30, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") },
        formatter: (ps) => `${esc(ps[0].axisValue)}<br>` + ps.map((p) => `${p.seriesName}: <b>${fmt.num(p.value, 3)}</b>`).join("<br>") },
      xAxis: { type: "value", max: 1, ...axis() },
      yAxis: { type: "category", data: rows.map((r) => methodLabel(r.method) + (REFERENCE.has(r.method) ? " (ref.)" : "")), inverse: true,
        ...axis({ splitLine: { show: false }, axisLabel: { color: css("--text"), fontSize: 12, width: 120, overflow: "break" } }) },
      series: [
        { name: "Macro-F1", type: "bar", barWidth: 11, barGap: "30%", data: rows.map((r) => refBar(r, r.macro_f1, false)) },
        { name: "Cohen's kappa", type: "bar", barWidth: 11, data: rows.map((r) => refBar(r, r.cohen_kappa, true)) },
      ],
    }));
  },
};

// ------------------------------------------------------------------- fed now
const fedState = { filter: "all" };
const PREF = { hike: "wanted a hike", cut: "wanted a cut", hold: "wanted no change", other: "not on the rate" };
const initials = (n) => n.split(" ").filter((w) => !/\.$/.test(w)).map((w) => w[0]).slice(0, 2).join("");
const pctColor = (p) => (p >= 60 ? "var(--hawk-ink)" : p <= 40 ? "var(--dove-ink)" : "var(--text)");
// recent dissents, one row per meeting: who wanted what, in the statement's terms
function dissentMeetings(f) {
  if (!f.dissents.length) return empty("No dissents", "Every decision in the past two years was unanimous.");
  const moveOf = Object.fromEntries((f.path || []).map((d) => [d.doc_id, d.change_bp]));
  const meetings = [];
  for (const d of f.dissents) {  // newest first
    let m = meetings.find((x) => x.doc_id === d.doc_id);
    if (!m) meetings.push((m = { doc_id: d.doc_id, date: d.date, groups: [] }));
    let g = m.groups.find((x) => x.label === d.label);
    if (!g) m.groups.push((g = { label: d.label, lean: d.lean, names: [], reason: d.reason }));
    g.names.push(d.name.split(" ").pop());
  }
  const row = (m) => { const bp = moveOf[m.doc_id];
    return `<div class="row dissent-row" data-doc="${m.doc_id}"><div class="when"><b>${fmt.date(m.date)}</b>${bp === undefined ? "" : moveBadge(Math.sign(bp), bp)}</div>
      <div class="who">${m.groups.map((g) => `<div title="${esc(g.reason)}"><span class="pill-mini ${leanClass(g.lean)}">${esc(g.label)}</span> ${esc(g.names.join(", "))}</div>`).join("")}</div></div>`; };
  const rest = meetings.slice(5);
  return `<div class="list">${meetings.slice(0, 5).map(row).join("")}</div>${rest.length ? `<button class="btn ghost small fold-more" data-fold>${rest.length} earlier meeting${rest.length === 1 ? "" : "s"}</button><div class="list" hidden>${rest.map(row).join("")}</div>` : ""}`;
}
// the Board on one axis: each member's recent tone as a percentile, so the order reads at a glance
function toneSpectrum(members) {
  const on = members.filter((m) => m.tone_pct !== null && m.tone_pct !== undefined).sort((a, b) => a.tone_pct - b.tone_pct);
  if (on.length < 2) return "";
  return `<div class="spectrum" aria-label="Recent tone of each member, dovish to hawkish">
    <div class="spectrum-track">${on.map((m) => `<button type="button" class="spectrum-dot ${m.status === "voter" ? "voter" : ""}" data-member="${esc(m.name)}" style="left:${Math.max(1, Math.min(99, m.tone_pct))}%" title="${esc(m.name)}: ${ordinal(m.tone_pct)} percentile over ${m.tone_n} speeches"><i></i><span>${esc(m.name.split(" ").pop())}</span></button>`).join("")}</div>
    <div class="spectrum-ends"><span>&larr; dovish</span><span>tone of recent speeches, percentile of Board speeches since 2009 &middot; filled: votes this year</span><span>hawkish &rarr;</span></div></div>`;
}
// lay the spectrum's names in lanes above and below the line so none overlap
function laySpectrum(root) {
  const lanes = [[], [], [], []];  // above, below, higher above, lower below
  $$(".spectrum-dot", root).forEach((b) => {
    const label = b.querySelector("span"); const r = label.getBoundingClientRect(); const w = r.width + 8; const x = b.getBoundingClientRect().left;
    const lane = lanes.findIndex((l) => l.every(([a, z]) => x + w / 2 < a || x - w / 2 > z));
    const k = lane < 0 ? 0 : lane; lanes[k].push([x - w / 2, x + w / 2]); b.dataset.lane = k;
  });
}
const mergeSpans = (spans) => spans.reduce((out, x) => { const last = out[out.length - 1];
  if (last && last[2] === x[2] && last[3] === x[3] && last[1] === x[0]) last[1] = x[1]; else out.push([...x]); return out; }, []);
const bandOpacity = () => (document.documentElement.dataset.theme === "dark" ? 0.32 : 0.22);
const memberRole = (m) => (m.role === "Chair" ? "Chair, Board of Governors" : m.role) + (m.board && m.role !== "Chair" ? ", Board" : "");
function memberBioPreview(text, limit = 200) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (clean.length <= limit) return clean;
  // Mask abbreviation periods without shifting indexes before looking for a sentence boundary.
  const masked = clean.replace(/\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Inc)\./gi, (x) => x.slice(0, -1) + "\0")
    .replace(/\b[A-Z]\.(?=\s+[A-Z])/g, (x) => x.slice(0, -1) + "\0")
    .replace(/\b(?:U\.S|U\.K)\./g, (x) => x.replace(/\./g, "\0"));
  const sentence = /[.!?](?:["')\]]+)?(?=\s|$)/.exec(masked);
  if (sentence && sentence.index + sentence[0].length <= limit) return clean.slice(0, sentence.index + sentence[0].length);
  const head = clean.slice(0, limit - 1); const lastSpace = head.lastIndexOf(" ");
  return head.slice(0, lastSpace > limit / 2 ? lastSpace : head.length).replace(/[,;:]$/, "") + "…";
}
function memberCard(m) {
  const hasTone=Number.isFinite(m.tone_pct), n=Number(m.tone_n)||0;
  const reason=!m.board?"Outside speech corpus":n<3?`${n} of 3 readings`:"Unavailable";
  const tone=hasTone?`<span class="committee-meter"><i style="left:${Math.max(2,Math.min(98,m.tone_pct))}%"></i></span><b class="tnum" style="color:${pctColor(m.tone_pct)}">${ordinal(m.tone_pct)}</b>`:`<span class="coverage-note">${reason}</span>`;
  const dissent=m.last_dissent&&m.dissents_12m?`<span class="pill-mini ${leanClass(m.last_dissent.lean)}" data-doc="${esc(m.last_dissent.doc_id)}" title="${esc(m.last_dissent.label)}">${esc(m.last_dissent.label)} <small>${fmt.short(m.last_dissent.date)}</small></span>`:'<span class="muted small">No recent dissent</span>';
  return `<div class="committee-row" data-member="${esc(m.name)}" tabindex="0" role="button" aria-label="${esc(m.name)}: open background, speeches and dissents">
    <div class="committee-identity"><span class="avatar ${m.board?"board":"bank"}">${initials(m.name)}</span><div><b>${esc(m.name)}</b><span>${esc(memberRole(m))}</span><small>${m.status==="voter"?"Voting member":m.status==="alternate"?"Alternate":"Non-voting member"}</small></div></div>
    <div class="committee-reading">${tone}</div>
    <div class="committee-coverage">${m.board?`${n} recent readings<br><small>${m.speeches_12m||0} collected / 12 months</small>`:'<span class="coverage-note">Reserve Bank</span>'}</div>
    <div class="committee-dissent">${dissent}</div><svg class="ic" aria-hidden="true"><use href="#i-chevron-right"/></svg></div>`;
}
pages.fed = {
  title: "Fed now", sub: "Policy rates and the Committee at a glance: the target range, where overnight money trades, the latest vote, who votes this year and how they sound.",
  async render(view) {
    const f = await api("/api/fed");
    fedState.method = f.method;
    const c = f.current; const e = f.effr; const mk2 = f.market; const nm = f.next_meeting;
    if (!c) { view.innerHTML = `<div class="card">${empty("No decisions yet", "Run " + code("fomc run"))}</div>`; return; }
    const against = Number(c.vote.split("–")[1] || 0);
    const posPct = e ? Math.max(0, Math.min(100, (100 * (e.effr - c.range_low)) / (c.range_high - c.range_low))) : null;
    const lean = mk2 && mk2.t2y_minus_effr_bp !== null ? mk2.t2y_minus_effr_bp : null;
    const voters = f.members.filter((m) => m.status === "voter").length;
    fedState.filter = ["all", "voter", "board", "bank"].includes(viewParams().get("show")) ? viewParams().get("show") : "voter";
    view.innerHTML = `<div id="fed-root" class="stack">
      <div class="fedstats">
        <div class="card stat"><span class="label">Target range ${info(`Set ${fmt.date(c.date)}. Upper bound ${rate(c.range_high)}%, lower bound ${rate(c.range_low)}%.`)}</span><b class="big">${rangeTxt(c.range_low, c.range_high)}</b><span class="tagline">${moveBadge(c.action, c.change_bp)} <span class="muted">${fmt.short(c.date)}</span></span></div>
        <div class="card stat"><span class="label">Effective fed funds ${info(`Volume-weighted median of overnight fed funds trades, published by the New York Fed for ${e ? fmt.date(e.date) : dash}. The bar shows where it sits inside the target range. SOFR, the secured repo rate: ${e ? fmt.num(e.sofr) + "%" : dash}.`)}</span><b class="big">${e ? fmt.num(e.effr) + "%" : dash}</b>
          ${e ? `<span class="inrange"><span class="track"><i style="left:${posPct}%"></i></span><span class="ends"><span>${rate(c.range_low)}%</span><span>${rate(c.range_high)}%</span></span></span><span class="tagline muted">SOFR ${fmt.num(e.sofr)}%</span>` : ""}</div>
        <div class="card stat"><span class="label">Latest vote ${info(against ? `${against} member${against === 1 ? "" : "s"} voted against the decision of ${fmt.date(c.date)}.` : `Every voting member supported the decision of ${fmt.date(c.date)}.`)}</span><b class="big">${c.vote}</b><span class="tagline muted">${against ? `${against} dissent${against === 1 ? "" : "s"}` : "unanimous"}</span></div>
        <div class="card stat"><span class="label">Next decision ${info("Statement at 2:00 p.m. ET and the press conference at 2:30 p.m.; the minutes follow three weeks later.")}</span><b class="big">${nm ? nm.days + "<small> days</small>" : dash}</b><span class="tagline muted">${nm ? fmt.date(nm.date) : ""}</span></div>
        <div class="card stat"><span class="label">2-year minus EFFR ${info("A rough read of where the market expects policy over two years: a 2-year yield well above the overnight rate leans toward hikes, well below toward cuts. Term premium and bill supply also move it, so treat it as a lean, not a forecast.")}</span><b class="big" style="color:${lean > 25 ? "var(--hawk-ink)" : lean < -25 ? "var(--dove-ink)" : "var(--text)"}">${lean === null ? dash : fmt.signed(lean, 0) + " bp"}</b><span class="tagline muted">${lean === null ? "" : (lean > 25 ? "market leans to hikes" : lean < -25 ? "market leans to cuts" : "market sees little change") + " · " + fmt.short(f.market.date)}</span></div>
      </div>
      <div class="grid fed-grid">
        <div class="card fill-card"><div class="card-head"><div><h2>Policy rate, three years ${info("Shaded band: the target range. Lines: the effective fed funds rate (New York Fed) and the 2-year Treasury yield, all in percent on one axis. Triangles mark hikes and cuts; click one to read that statement.")}</h2></div></div><div id="c-fed" class="chart"></div>
          <div class="legend-inline"><span><i class="lg-band"></i>target range</span><span><i class="lg-line"></i>effective fed funds</span><span><i class="lg-line amber"></i>2-year Treasury</span><span><i class="lg-tri up"></i>hike</span><span><i class="lg-tri down"></i>cut</span></div></div>
        <div class="card"><div class="card-head"><div><h2>Recent dissents ${info("Read from the 'Voting against' sentence of every statement in the past two years, one row per meeting. Red wanted tighter policy than the decision, blue looser. Click a row to open the statement.")}</h2></div></div>
          ${dissentMeetings(f)}</div>
      </div>
      <div class="card"><div class="card-head"><div><h2>The Committee ${info("Recent tone is a percentile of Board speeches since 2009, based on up to 10 eligible speeches in two years. At least three are required. Reserve Bank speeches are outside this corpus. Select a member for their biography and full timeline.")}</h2><div class="sub keep" id="committee-summary"></div></div>
        <label class="field compact"><span>Members</span><select id="fed-filter" aria-label="Committee members">${[["voter","Voters"],["all","All members"],["board","Board"],["bank","Reserve Banks"]].map(([k,v])=>`<option value="${k}" ${k===fedState.filter?"selected":""}>${v}</option>`).join("")}</select></label></div>
        <div class="committee-column-head"><span>Member</span><span>Recent tone</span><span>Speech coverage</span><span>Latest dissent</span></div>
        <div class="committee-list" id="fed-members"></div></div></div>`;
    const drawMembers = () => {
      const list = f.members.filter((m) => fedState.filter === "all" || (fedState.filter === "voter" ? m.status === "voter" : fedState.filter === "board" ? m.board : !m.board));
      $("#fed-members").innerHTML = list.map(memberCard).join("");
      $("#committee-summary").textContent=`${list.length} members, ${list.filter(m=>Number.isFinite(m.tone_pct)).length} with readings. Lower percentiles are more dovish.`;
    };
    $("#fed-filter").onchange = (ev) => { fedState.filter=ev.target.value;setViewParams({show:fedState.filter});drawMembers(); };
    $("#fed-root").addEventListener("click", (ev) => {
      if (ev.target.closest(".tipbtn")) return;
      if (ev.target.closest("[data-fold]")) return;
      const d = ev.target.closest("[data-doc]"); const m = ev.target.closest("[data-member]");
      if (d) { ev.stopPropagation(); openDoc(d.dataset.doc); } else if (m) { ev.stopPropagation(); openMember(m.dataset.member); }
    });
    $("#fed-members").addEventListener("keydown", (ev) => { const m = ev.target.closest("[data-member]"); if (m && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); openMember(m.dataset.member); } });
    drawMembers();

    // chart: target-range band, EFFR, 2-year, moves
    const today = new Date().toISOString().slice(0, 10);
    const start = f.rates.length ? f.rates[0].date : f.yields[0]?.date;
    const path = [...f.range_before.map((r) => ({ ...r, release_date: start })), ...f.path];
    const spans = mergeSpans(path.map((d, i) => [d.release_date < start ? start : d.release_date, (path[i + 1] || { release_date: today }).release_date, d.range_low, d.range_high]));
    const moves = f.path.filter((d) => d.change_bp);
    const rangeOn = (iso) => spans.find((x) => x[0] <= iso && iso < x[1]) || spans[spans.length - 1];
    const ch = mk($("#c-fed"));
    ch.setOption(base({
      grid: { left: 46, right: 16, top: 24, bottom: 26 },
      tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 },
        formatter: (ps) => { const day = isoDay(ps[0].axisValue); const r = rangeOn(day);
          return `${fmt.date(day)}<br>` + (r ? `Target range <b>${rate(r[2])}&ndash;${rate(r[3])}%</b><br>` : "") + ps.filter((p) => p.seriesType === "line").map((p) => `${p.marker}${p.seriesName}: <b>${fmt.num(p.value[1])}%</b>`).join("<br>"); } },
      xAxis: { type: "time", min: start, max: today, ...axis({ splitLine: { show: false } }) },
      yAxis: { type: "value", scale: true, ...axis({ axisLabel: { color: css("--text-2"), formatter: (v) => v + "%" } }) },
      series: [
        { type: "custom", name: "Target range", silent: true, z: 1, itemStyle: { color: css("--s1") }, data: spans, encode: { x: [0, 1], y: [2, 3] },
          renderItem: (params, a) => { const p1 = a.coord([a.value(0), a.value(3)]); const p2 = a.coord([a.value(1), a.value(2)]);
            return { type: "rect", shape: { x: p1[0], y: p1[1], width: Math.max(1, p2[0] - p1[0] + 0.6), height: Math.max(2, p2[1] - p1[1]) }, style: { fill: css("--s1"), opacity: bandOpacity() } }; } },
        { type: "line", name: "Effective fed funds", showSymbol: false, z: 3, lineStyle: { width: 2, color: css("--s1") }, itemStyle: { color: css("--s1") }, data: f.rates.filter((r) => r.effr !== null).map((r) => [r.date, r.effr]) },
        { type: "line", name: "2-year Treasury", showSymbol: false, z: 2, lineStyle: { width: 2, color: css("--s2") }, itemStyle: { color: css("--s2") }, data: f.yields.filter((r) => r.t2y !== null).map((r) => [r.date, r.t2y]) },
        { type: "scatter", z: 4, symbol: "triangle", symbolSize: 11, cursor: "pointer", data: moves.map((d) => ({ value: [d.release_date, d.range_high], doc: d.doc_id, symbolRotate: d.change_bp < 0 ? 180 : 0, itemStyle: { color: d.change_bp > 0 ? css("--hawk") : css("--dove"), borderColor: css("--surface"), borderWidth: 1.5 } })) },
      ],
    }));
    ch.on("click", (p) => { if (p.data && p.data.doc) openDoc(p.data.doc); });
  },
};

// ------------------------------------------------------------- statement tracker
const trState = { sel: null, movesOnly: false, all: false };
pages.tracker = {
  title: "Decisions", sub: "Every FOMC decision since 2009: the target range, the move, and what changed in the statement's wording.",
  async render(view) {
    const r = await api("/api/tracker");
    if (!r.decisions.length) { view.innerHTML = `<div class="card">${empty("No decisions yet", "Run " + code("fomc events"))}</div>`; return; }
    const list = r.decisions; const c = r.current;
    const moves = list.filter((d) => d.action !== 0 && d.action !== null);
    const lastMove = moves[moves.length - 1];
    const prevMove = c.action !== 0 ? moves[moves.length - 2] : lastMove;
    const tvp = viewParams();
    if (tvp.get("sel")) trState.sel = tvp.get("sel");
    trState.movesOnly = tvp.get("moves") === "1";
    if (!trState.sel || !list.some((d) => d.doc_id === trState.sel)) trState.sel = c.doc_id;
    const moveCls = c.action > 0 ? "hawk" : c.action < 0 ? "dove" : "";
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">Target range</div><div class="value">${rangeTxt(c.range_low, c.range_high)}</div><div class="foot">${c.action !== 0 ? "set at the latest meeting" : lastMove ? "unchanged since " + fmt.date(lastMove.release_date) : "unchanged"}</div></div>
        <div class="card kpi"><div class="label">Latest decision &middot; ${fmt.date(c.date)}</div><div class="value ${moveCls}">${c.action !== 0 ? fmt.signed(c.change_bp, 0) + " bp" : "Hold"}</div><div class="foot">${c.action === 0 ? `${c.holds_in_a_row} hold${c.holds_in_a_row === 1 ? "" : "s"} in a row` : prevMove ? `previous move ${fmt.date(prevMove.release_date)} (${fmt.signed(prevMove.change_bp, 0)} bp)` : "first move in the sample"}</div></div>
        <div class="card kpi"><div class="label">Net change, 12 months</div><div class="value ${c.net_12m_bp > 0 ? "hawk" : c.net_12m_bp < 0 ? "dove" : ""}">${fmt.signed(c.net_12m_bp, 0)} bp</div><div class="foot">sum of moves over the past year</div></div>
        <div class="card kpi"><div class="label">Wording carried over</div><div class="value">${pct(c.similarity)}</div><div class="foot">of the previous statement; median since 2009 ${pct(c.median_similarity)}</div></div>
      </div>
      <div class="grid tracker-grid">
        <div class="card" id="tr-red-card"><div class="card-head"><div><h2 id="tr-red-title">What changed</h2><div class="sub" id="tr-red-sub">Word-level redline against the previous decision</div></div><button class="btn ghost small" id="tr-open">Open document</button></div><div id="tr-red"><div class="skeleton"></div></div></div>
        <div class="card tr-charts"><div class="card-head"><div><h2>Target range since 2009</h2><div class="sub keep">Click a triangle or a stem to read that decision's redline.</div></div></div>
          <div class="legend-inline tr-legend"><span><i class="lg-tri up"></i>hike</span><span><i class="lg-tri down"></i>cut (larger for bigger moves)</span><span><i class="lg-band"></i>target range</span><span><i class="lg-stem"></i>hold</span></div>
          <div id="c-range" class="chart"></div>
          <div class="chart-caption">Share of the statement's wording changed from the previous decision</div>
          <div id="c-change" class="chart mini"></div></div>
      </div>
      <div class="card"><div class="card-head"><div><h2>Decisions</h2><div class="sub">Newest first. Tone by ${esc(methodLabel(r.method))}; &Delta;2y over the statement's release window. Click a row for its redline.</div></div>
        <div class="seg" id="tr-filter"><button data-k="all" class="${trState.movesOnly ? "" : "on"}">All ${list.length}</button><button data-k="moves" class="${trState.movesOnly ? "on" : ""}">Moves ${moves.length}</button></div></div>
        <div id="tr-table"></div></div>`;

    const select = async (id, scroll = false) => {
      setViewParams({ sel: id === c.doc_id ? null : id });
      trState.sel = id;
      $$("#tr-table tr[data-doc]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.doc === id));
      const d = list.find((x) => x.doc_id === id);
      $("#tr-red-title").innerHTML = `What changed: ${fmt.date(d.release_date)} ${moveBadge(d.action, d.change_bp)}`;
      $("#tr-red-sub").innerHTML = `Target range ${rangeTxt(d.range_low, d.range_high)}${d.d2y_bp !== null ? ` &middot; 2-year ${fmt.signed(d.d2y_bp, 1)} bp over the window` : ""}`;
      const box = $("#tr-red");
      if (!d.prev_doc_id) box.innerHTML = empty("First decision in the sample", "There is no earlier decision to compare with.");
      else { box.innerHTML = '<div class="skeleton"></div>'; await loadRedline(id, box); }
      if (scroll) $("#tr-red-card").scrollIntoView({ behavior: "smooth", block: "start" });
    };
    $("#tr-open").onclick = () => openDoc(trState.sel);

    const table = () => {
      const every = [...list].reverse().filter((d) => !trState.movesOnly || d.action !== 0);
      const capped = window.matchMedia("(max-width: 700px)").matches && !trState.all && every.length > 20;  // a phone page stays short
      const rows = capped ? every.slice(0, 20) : every;
      $("#tr-table").innerHTML = `<div class="table-wrap scroll-box"><table class="table"><thead><tr><th>Date</th><th>Decision</th><th class="wide-only">Target range</th><th class="num wide-only">Wording changed</th><th class="num wide-only">Words + / &minus;</th><th class="num">Tone</th><th class="num">&Delta;2y bp</th></tr></thead>
        <tbody>${rows.map((d) => `<tr data-doc="${d.doc_id}" class="${d.doc_id === trState.sel ? "sel" : ""}"><td class="nowrap">${fmt.date(d.release_date)}</td><td>${moveBadge(d.action, d.change_bp)}</td><td class="nowrap wide-only">${rangeTxt(d.range_low, d.range_high)}</td>
          <td class="num wide-only">${d.similarity === null ? dash : pct(1 - d.similarity)}</td><td class="num wide-only">${d.words_added === null ? dash : `+${d.words_added} / &minus;${d.words_removed}`}</td><td class="num">${scoreChip(d.score, r.method)}</td><td class="num">${delta(d.d2y_bp)}</td></tr>`).join("")}</tbody></table></div>${capped ? `<button class="btn ghost small fold-more" id="tr-all">Show all ${every.length} decisions</button>` : ""}`;
      if (capped) $("#tr-all").onclick = () => { trState.all = true; table(); };
      $("#tr-table tbody").onclick = (e) => { const tr = e.target.closest("[data-doc]"); if (tr) select(tr.dataset.doc, true); };
    };
    $("#tr-filter").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; trState.movesOnly = b.dataset.k === "moves"; setViewParams({ moves: trState.movesOnly ? 1 : null }); $$("#tr-filter button").forEach((x) => x.classList.toggle("on", x === b)); table(); };

    // charts: the range band as rectangles between decisions, moves as triangles, wording change as bars
    const today = new Date().toISOString().slice(0, 10);
    const ranged = list.filter((d) => d.range_high !== null);
    const spans = mergeSpans(ranged.map((d, i) => [d.release_date, (ranged[i + 1] || { release_date: today }).release_date, d.range_low, d.range_high]));
    const color = (a) => (a > 0 ? css("--hawk") : a < 0 ? css("--dove") : css("--muted"));
    const tip = { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 12 } };
    const rc = fresh($("#c-range"));
    rc.setOption(base({
      grid: { left: 46, right: 44, top: 14, bottom: 26 }, tooltip: tip,
      xAxis: { type: "time", min: list[0].release_date, max: today, ...axis({ splitLine: { show: false } }) },
      yAxis: { type: "value", min: 0, ...axis({ axisLabel: { color: css("--text-2"), formatter: (v) => v + "%" } }) },
      dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false }],
      series: [
        { type: "custom", silent: true, z: 1, data: spans,
          renderItem: (params, a) => { const p1 = a.coord([a.value(0), a.value(3)]); const p2 = a.coord([a.value(1), a.value(2)]);
            return { type: "rect", shape: { x: p1[0], y: p1[1], width: Math.max(1, p2[0] - p1[0] + 0.6), height: Math.max(2, p2[1] - p1[1]) }, style: { fill: css("--s1"), opacity: bandOpacity() + 0.06 } }; },
          encode: { x: [0, 1], y: [2, 3] } },
        { type: "line", step: "end", silent: true, showSymbol: false, z: 2, lineStyle: { width: 1.6, color: css("--s1") }, data: [...ranged.map((d) => [d.release_date, d.range_high]), [today, ranged[ranged.length - 1].range_high]] },
        { type: "scatter", z: 3, data: moves.map((d) => ({ value: [d.release_date, d.range_high], d, symbolRotate: d.action < 0 ? 180 : 0, itemStyle: { color: color(d.action), borderColor: css("--surface"), borderWidth: 1.5 } })),
          symbol: "triangle", symbolSize: (v, p) => 9 + Math.min(4, Math.abs(p.data.d.change_bp) / 25) * 2,
          tooltip: { formatter: (p) => { const d = p.data.d; return `${fmt.date(d.release_date)}<br>${d.action > 0 ? "Hike" : "Cut"} ${fmt.signed(d.change_bp, 0)} bp to ${rangeTxt(d.range_low, d.range_high)}${d.d2y_bp !== null ? `<br>2-year ${fmt.signed(d.d2y_bp, 1)} bp over the window` : ""}`; } } },
      ],
    }));
    // wording change as a lollipop: every decision a quiet stem, the moves a triangle on top, so holds recede
    const changed = list.filter((d) => d.similarity !== null);
    const biggest = [...changed].sort((a, b) => a.similarity - b.similarity).slice(0, 2).map((d) => d.doc_id);
    const cc = fresh($("#c-change"));
    const changeTip = { formatter: (p) => { const d = p.data.d; return `${fmt.date(d.release_date)} &middot; ${d.action > 0 ? "hike" : d.action < 0 ? "cut" : "hold"}<br><b>${pct(1 - d.similarity)}</b> of the wording changed<br>+${d.words_added} / &minus;${d.words_removed} words`; } };
    cc.setOption(base({
      grid: { left: 46, right: 44, top: 24, bottom: 24 }, tooltip: tip,
      xAxis: { type: "time", min: list[0].release_date, max: today, ...axis({ splitLine: { show: false } }) },
      yAxis: { type: "value", min: 0, max: 100, interval: 50, ...axis({ axisLabel: { color: css("--text-2"), formatter: (v) => v + "%" } }) },
      dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false }],
      series: [
        { type: "bar", barWidth: 1.5, cursor: "pointer", data: changed.map((d) => ({ value: [d.release_date, 100 * (1 - d.similarity)], d,
          itemStyle: { color: d.action ? color(d.action) : css("--muted"), opacity: d.action ? 0.9 : 0.45 } })), tooltip: changeTip },
        { type: "scatter", symbol: "triangle", symbolSize: 9, z: 3, cursor: "pointer", tooltip: changeTip,
          data: changed.filter((d) => d.action || biggest.includes(d.doc_id)).map((d) => ({ value: [d.release_date, 100 * (1 - d.similarity)], d,
            symbol: d.action ? "triangle" : "circle", symbolSize: d.action ? 9 : 6, symbolRotate: d.action < 0 ? 180 : 0,
            itemStyle: { color: d.action ? color(d.action) : css("--muted"), borderColor: css("--surface"), borderWidth: 1.5 },
            label: biggest.includes(d.doc_id) ? { show: true, position: "top", distance: 4, color: css("--text-2"), fontSize: 11,
              formatter: () => `${new Date(d.release_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" })} \u00b7 ${pct(1 - d.similarity)}` } : { show: false } })) },
      ],
    }));
    rc.group = cc.group = "tracker"; echarts.connect("tracker");
    [rc, cc].forEach((ch) => ch.on("click", (p) => { if (p.data && p.data.d) select(p.data.d.doc_id, true); }));
    table();
    select(trState.sel);
  },
};

// ----------------------------------------------------------------------- label
const labState = { annotator: local.get("annotator", ""), item: null, busy: false };
const LAB_KEYS = { d: -1, n: 0, h: 1 };
pages.label = {
  title: "Team labels", sub: "Optional human validation tool; the post-cutoff human test was not run for the submitted study.",
  async render(view) {
    const [sum, st] = await Promise.all([api("/api/labels/summary"), api("/api/settings")]);
    state.settings = st;
    if (!sum.items) { view.innerHTML = `<div class="card">${empty("No sentences to label yet", "Sample a post-cutoff set with " + code("fomc label-sample --n 150"))}</div>`; return; }
    const ro = !sum.writable;
    view.innerHTML = `
      <div class="grid label-grid">
        <div class="card">
          ${ro ? '<div class="callout" style="margin-bottom:14px"><span><b>Read-only demo.</b> Labeling writes to the store, so it runs in the local workspace (<span class="mono">make serve</span>). The sentences and the agreement statistics are shown here as they stand.</span></div>' : ""}
          <div class="toolbar">
            <label class="field"><span>Annotator</span><input id="lab-name" placeholder="Your initials" maxlength="40" value="${esc(labState.annotator)}" style="width:170px" ${ro ? "disabled" : ""}></label>
            <div style="flex:1 1 240px"><div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-2);margin-bottom:6px"><span>Progress</span><span id="lab-count">${dash}</span></div><div class="progress"><span id="lab-bar" style="width:0%"></span></div></div>
          </div>
          <div id="lab-box"></div>
          <details class="guide"><summary>How to label</summary><ul>
            <li><b>Hawkish:</b> points to tighter policy: inflation too high or sticky, rates higher or for longer, less accommodation, upside risks to prices.</li>
            <li><b>Dovish:</b> points to easier policy: a softening labor market or growth, downside risks, lower rates or more accommodation.</li>
            <li><b>Neutral:</b> factual or balanced, procedural, or not about the policy outlook. When unsure, neutral.</li>
            <li>Judge the sentence on its own; the grey context is only there to resolve references. Keys: <kbd>D</kbd> <kbd>N</kbd> <kbd>H</kbd>, <kbd>U</kbd> to undo.</li>
            <li>Every label is saved to ${code("data/labels/<your initials>.csv")}; commit that file to share your labels. Teammates’ files load on the next ${code("make serve")} or ${code("make run")}.</li></ul></details>
        </div>
        <div class="card" id="lab-side"></div>
      </div>`;
    const side = (s) => {
      $("#lab-side").innerHTML = `<h2>Agreement so far</h2><div class="sub">${fmt.int(s.items)} sentences: ${[...s.by_type].sort((a, b) => b.n - a.n).map((t) => `${t.n} from ${(TYPES[t.doc_type] || t.doc_type).toLowerCase()}`).join(", ")}; ${fmt.int(s.labels)} labels so far</div>
        <div class="section-title">Annotators</div>${s.annotators.length ? s.annotators.map((a) => `<div class="inline-bar"><span>${esc(a.annotator)}</span><span class="track"><span style="width:${Math.min(100, (100 * a.n) / s.items)}%"></span></span><span class="n">${a.n}</span></div>`).join("") : '<p class="small muted">Nobody yet.</p>'}
        <div class="section-title">Between people (Cohen's kappa)</div>${s.pairs.length ? s.pairs.map((p) => `<div class="inline-bar"><span>${esc(p.a)} &middot; ${esc(p.b)}</span><span class="track"><span style="width:${Math.max(0, p.kappa) * 100}%"></span></span><span class="n">${fmt.num(p.kappa)}</span></div>`).join("") : '<p class="small muted">Needs two people with 10 sentences in common.</p>'}
        <div class="section-title">Methods against the majority</div>${s.methods.length ? s.methods.map((m) => `<div class="inline-bar"><span>${esc(methodLabel(m.method))}</span><span class="track"><span style="width:${m.macro_f1 * 100}%"></span></span><span class="n">F1 ${fmt.num(m.macro_f1)}</span></div>`).join("") : '<p class="small muted">Appears once 10 sentences have a majority label.</p>'}
        <p class="small muted" style="margin-top:14px">Same numbers from the command line: ${code("fomc label-report")}</p>`;
    };
    side(sum);
    const show = (res) => {
      labState.item = res.item;
      const pr = res.progress;
      $("#lab-count").textContent = pr ? `${fmt.int(pr.done)} of ${fmt.int(pr.total)}` : dash;
      $("#lab-bar").style.width = pr && pr.total ? (100 * pr.done) / pr.total + "%" : "0%";
      const it = res.item;
      if (!it) { $("#lab-box").innerHTML = `<div class="sentence-box">${empty("All done", "Every sentence has your label. Thank you.")}</div>`; return; }
      const dis = ro || !labState.annotator ? "disabled" : "";
      $("#lab-box").innerHTML = `<div class="sentence-box">
          <div class="meta">${typeBadge(it.doc_type)}<span>${fmt.date(it.release_date)}</span>${it.speaker ? `<span>&middot; ${esc(it.speaker)}</span>` : ""}<a href="#" data-open="${esc(it.doc_id)}" style="margin-left:auto">open document</a></div>
          ${it.context_before ? `<p class="ctx">${esc(it.context_before)}</p>` : ""}
          <p class="main">${esc(it.sentence)}</p>
          ${it.context_after ? `<p class="ctx">${esc(it.context_after)}</p>` : ""}
        </div>
        <div class="label-actions">
          <button class="lab-btn dove" data-lab="-1" ${dis}>Dovish <kbd>D</kbd></button>
          <button class="lab-btn neutral" data-lab="0" ${dis}>Neutral <kbd>N</kbd></button>
          <button class="lab-btn hawk" data-lab="1" ${dis}>Hawkish <kbd>H</kbd></button>
          <button class="lab-btn ghost" data-undo ${ro || !labState.annotator ? "disabled" : ""}>Undo <kbd>U</kbd></button>
        </div>
        ${!ro && !labState.annotator ? '<p class="small muted" style="margin-top:10px">Enter your initials to start; labels are stored per annotator.</p>' : ""}`;
    };
    const load = async () => {
      if (!labState.annotator) { show({ item: (await api("/api/labels/next?annotator=" + encodeURIComponent("—preview"))).item, progress: null }); return; }
      show(await api("/api/labels/next?annotator=" + encodeURIComponent(labState.annotator)));
    };
    const act = async (label, btn) => {
      if (labState.busy || ro || !labState.annotator || !labState.item) return;
      labState.busy = true; btn?.classList.add("flash");
      try {
        const res = await api("/api/labels", { method: "POST", body: JSON.stringify({ item_id: labState.item.item_id, annotator: labState.annotator, label }) });
        show(res);
        if (res.progress.done % 5 === 1 || !res.item) side(await api("/api/labels/summary"));
      } catch (e) { toast(e.message); } finally { labState.busy = false; }
    };
    const undo = async () => {
      if (labState.busy || ro || !labState.annotator) return;
      labState.busy = true;
      try { const res = await api("/api/labels/undo", { method: "POST", body: JSON.stringify({ annotator: labState.annotator }) });
        if (res.item) { show(res); toast("Last label removed"); side(await api("/api/labels/summary")); } else toast("Nothing to undo");
      } catch (e) { toast(e.message); } finally { labState.busy = false; }
    };
    $("#lab-box").onclick = (e) => {
      const b = e.target.closest("[data-lab]"); if (b && !b.disabled) act(Number(b.dataset.lab), b);
      if (e.target.closest("[data-undo]")) undo();
      const o = e.target.closest("[data-open]"); if (o) { e.preventDefault(); openDoc(o.dataset.open); }
    };
    const name = $("#lab-name");
    if (name) name.onchange = () => { labState.annotator = name.value.trim(); local.set("annotator", labState.annotator); load(); side(sum); };
    pages.label.key = (e) => {
      const k = e.key.toLowerCase();
      if (k in LAB_KEYS) { e.preventDefault(); act(LAB_KEYS[k], $(`[data-lab="${LAB_KEYS[k]}"]`)); }
      else if (k === "u") { e.preventDefault(); undo(); }
    };
    load();
  },
};
document.addEventListener("keydown", (e) => {
  if (state.page !== "label" || !pages.label.key || e.metaKey || e.ctrlKey || e.altKey) return;
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "") || !$("#palette").hidden || !$("#drawer").hidden) return;
  pages.label.key(e);
});

// ---------------------------------------------------------------- data & system
const mb = (b) => (b / 1e6).toFixed(b > 1e8 ? 0 : 1) + " MB";  // decimal megabytes, as in the docs and the deck
const ICON = {
  db: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
};
pages.system = {
  usesMethod: false,
  title: "Data", sub: "Where the data lives, how much of it there is, and what makes reruns cheap.",
  async render(view) {
    const s = await api("/api/system");
    const totalRows = s.tables.reduce((a, t) => a + t.rows, 0);
    const maxRows = Math.max(...s.tables.map((t) => t.rows), 1);
    const runs = Object.fromEntries(s.runs.map((r) => [r.stage, r]));
    const skipped = s.runs.filter((r) => r.status === "skipped").length;
    const llm = s.llm_store;
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="label">SQLite store</div><div class="value">${mb(s.db.bytes)}</div><div class="foot">${s.db.path} &middot; schema v${s.db.schema_version} &middot; WAL mode</div></div>
        <div class="card kpi"><div class="label">Rows across ${s.tables.length} tables</div><div class="value">${fmt.int(totalRows)}</div><div class="foot">documents, yields, scores, results, run log</div></div>
        <div class="card kpi"><div class="label">Market data through</div><div class="value">${s.yields_through ? fmt.date(s.yields_through) : dash}</div><div class="foot keep" ${s.yield_source && !s.yield_source.startsWith("FRED") ? 'style="color:var(--warn-ink)"' : ""}>${!s.yield_source ? "run fomc market" : s.yield_source.startsWith("FRED") ? "Treasury yields from FRED (H.15)" : "from the U.S. Treasury: FRED was unavailable on the last run"}</div></div>
        <div class="card kpi"><div class="label">Raw download cache</div><div class="value">${fmt.int(s.raw_cache.files)}<small class="of"> files</small></div><div class="foot">${s.raw_cache.live ? `files, ${mb(s.raw_cache.bytes)}; reruns make no network calls` : "files cached by the last full run; this demo ships only the store"}</div></div>
      </div>
      <div class="card"><div class="card-head"><div><h2>Storage architecture</h2><div class="sub">One direction of flow; every stage writes to the store, the API only reads (except Settings)</div></div></div>
        <div class="system-map">
          <div class="box"><h3>Sources</h3><p>federalreserve.gov calendar, statements, minutes, transcripts, speech feed</p><p>U.S. Treasury par yields</p><p>Yahoo Finance ETFs</p></div>
          <div class="box"><h3>Raw cache</h3><p>data/raw/&lt;host&gt;/&lt;path&gt;</p><p>exact bytes behind every document, kept for provenance</p></div>
          <div class="box"><h3>Stages</h3><p>${STAGES.slice(0, 3).map((x) => x[1]).join(" &middot; ")}</p><p>${STAGES.slice(3, 5).map((x) => x[1]).join(" &middot; ")}</p><p>${STAGES.slice(5).map((x) => x[1]).join(" &middot; ")}</p></div>
          <div class="box"><h3>SQLite + FTS5</h3><p>data/fomc.db: ${s.tables.length} tables, versioned schema, indexed joins</p><p>LLM records mirrored from data/llm/*.json</p></div>
          <div class="box"><h3>Serve</h3><p>FastAPI REST (/api/*, OpenAPI at /docs)</p><p>this dashboard, CSV export, CLI</p></div>
        </div></div>
      <div class="card"><div class="card-head"><div><h2>Stage timings</h2><div class="sub keep">Seconds for the last full run of each stage, in pipeline order</div></div></div>
        <div class="legend-inline" style="margin-top:0"><span><i style="background:var(--s1)"></i>ran on the last run</span><span><i style="background:color-mix(in srgb, var(--muted) 45%, transparent)"></i>skipped: inputs unchanged (time of its last full run)</span></div>
        <div id="c-runs" class="chart"></div></div>
      <div class="card"><h2>Tables</h2><div class="sub keep">Rows in each table of the store, largest first</div>
        <div class="table-bars">${[...s.tables].sort((a, b) => b.rows - a.rows).map((t) => `<div class="inline-bar"><span class="mono">${t.table}</span><span class="track">${t.rows ? `<span style="width:${Math.max(0.6, (100 * t.rows) / maxRows)}%"></span>` : ""}</span><span class="n ${t.rows ? "" : "muted"}">${fmt.int(t.rows)}</span></div>`).join("")}</div></div>
      <div class="card"><h2>Efficiency built in</h2><div class="sub">Why a full rerun costs seconds and a re-score costs nothing</div>
        <div class="features" style="margin-top:12px">
          <div class="feature"><span class="ic">${ICON.layers}</span><div><b>HTTP cache</b><span>Every page is fetched once, stored by URL, and read from disk afterwards.</span></div><span class="metric">${fmt.int(s.raw_cache.files)} files</span></div>
          <div class="feature"><span class="ic">${ICON.bolt}</span><div><b>Incremental pipeline</b><span>Each stage fingerprints its inputs; an unchanged stage is skipped (<span class="mono">fomc run</span>, <span class="mono">--force</span> to override).</span></div><span class="metric">${skipped} of ${s.runs.length} skipped last run</span></div>
          <div class="feature"><span class="ic">${ICON.shield}</span><div><b>LLM record cache</b><span>A request is keyed by a hash of prompt, schema and text; an identical job is never sent twice.</span></div><span class="metric">${fmt.int(llm.records)} records</span></div>
          <div class="feature"><span class="ic">${ICON.clock}</span><div><b>Batch + prompt caching</b><span>Bulk scoring goes through Message Batches (50% off); the rubric prefix is cached across requests.</span></div><span class="metric">${llm.records ? Math.round((llm.batched / llm.records) * 100) + "% batched" : "ready"}</span></div>
          <div class="feature"><span class="ic">${ICON.search}</span><div><b>Full-text search</b><span>FTS5 virtual table with porter stemming and ranked, highlighted snippets.</span></div><span class="metric">${(s.words / 1e6).toFixed(1)}M words</span></div>
          <div class="feature"><span class="ic">${ICON.db}</span><div><b>Single-file store</b><span>Portable SQLite in WAL mode with indexes on type, date and method joins; export any table to CSV.</span></div><span class="metric">${mb(s.db.bytes)}</span></div>
        </div></div>`;
    const order = [...STAGES.map(([k, n]) => [k, n]), ["audit", "Audit"]].filter(([k]) => runs[k]);
    const secs = (v) => (v < 0.05 ? "<0.1 s" : v < 10 ? fmt.num(v, 1) + " s" : fmt.int(Math.round(v)) + " s");
    $("#c-runs").style.height = `${Math.max(180, order.length * 28 + 20)}px`;
    const c = mk($("#c-runs"));
    c.setOption(base({
      grid: { left: 8, right: 64, top: 4, bottom: 4, containLabel: true },
      tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text") },
        formatter: (p) => { const r = runs[order[p.dataIndex][0]]; return `${order[p.dataIndex][1]} &middot; <b>${secs(r.seconds || 0)}</b>${r.last_ok_at ? `<br>last full run ${fmt.date(r.last_ok_at)}` : ""}${r.status === "skipped" ? "<br>skipped on its last run: inputs unchanged" : ""}`; } },
      xAxis: { type: "value", show: false }, yAxis: { type: "category", inverse: true, data: order.map(([, n]) => n), ...axis({ splitLine: { show: false }, axisLine: { show: false }, axisLabel: { color: css("--text"), fontSize: 12 } }) },
      series: [{ type: "bar", barWidth: 14, data: order.map(([k]) => ({ value: Math.max(0, runs[k].seconds || 0),
        itemStyle: { color: runs[k].status === "skipped" ? css("--muted") : css("--s1"), opacity: runs[k].status === "skipped" ? 0.45 : 1, borderRadius: [0, 4, 4, 0] } })),
        label: { show: true, position: "right", color: css("--text-2"), fontSize: 11, formatter: (p) => secs(p.value) } }],
    }));
  },
};

// -------------------------------------------------------------------- pipeline
const STAGES = [
  ["collect", "Collect", "Fed calendar, statements, minutes, press transcripts, Board speeches; release times.", "fomc collect"],
  ["market", "Market data", "Treasury par yields (3:30 p.m.) and Treasury ETFs (4:00 p.m.).", "fomc market"],
  ["events", "Align", "No-look-ahead release windows, trade entry dates, and the decision in every statement.", "fomc events"],
  ["baselines", "Baselines", "Dictionary, TF-IDF classifier and sentence embeddings; validity on human labels.", "fomc baselines"],
  ["llm-sync", "Claude scores", "Rubric scores with verified evidence, from your API key.", "fomc llm-sync"],
  ["evaluate", "Event study", "Term structure, placebo, drift, surprise controls, splits, FDR, response curves.", "fomc evaluate"],
  ["backtest", "Backtest", "Duration tilt, costs, Newey-West, shuffled placebo, deflated Sharpe.", "fomc backtest"],
  ["forecast", "Next decision", "Exploratory: does tone add to what the market prices about the next decision?", "fomc forecast"],
  ["forward", "Forward test", "The frozen rules on data after the freeze: the trade, and each release's 2-year move.", "fomc forward"],
];
const LLM_STEPS = [
  ["1 Key", "Add your Anthropic key (Settings page or CLI).", "fomc key set"],
  ["2 Estimate", "Exact token count and cost per model, free.", "fomc llm-estimate"],
  ["3 Pilot", "Score 8 documents synchronously; read the evidence.", "fomc llm-pilot --n 8"],
  ["4 Batch", "Submit the corpus as one Message Batch (50% off).", "fomc llm-submit --what level"],
  ["5 Collect", "Write records, re-run refusals with fallback.", "fomc llm-collect --batch-id <id>"],
  ["6 Audit", "Masked identification and invariance checks.", "fomc llm-submit --what identify"],
];
pages.pipeline = {
  usesMethod: false,
  title: "Pipeline", sub: "Inputs, readers and evaluation, with the recorded state of each stage.",
  async render(view) {
    const r=await api("/api/pipeline"),by=Object.fromEntries(r.stages.map(x=>[x.stage,x]));
    const item=([key,name,desc,cmd])=>{
      const record=by[key], status=!record?"Not run":record.status==="skipped"?(record.detail?.reason?.includes("frozen")?"Frozen":"Cached"):record.status==="ok"?"Complete":record.status==="running"?"Running":"Failed";
      const details=record?.detail?Object.entries(record.detail).filter(([,v])=>typeof v!=="object").slice(0,4):[];
      const labels=k=>["team_labels","team_predictions"].includes(k)?"Model predictions on sample":k.replace(/_/g," ");
      return `<details class="pipeline-item"><summary><span class="stage-number">${STAGES.findIndex(x=>x[0]===key)+1}</span><b>${name}</b><span class="pill-mini ${["Complete","Cached","Frozen"].includes(status)?"ok":status==="Failed"?"warn":""}">${status}</span></summary>
        <div class="pipeline-item-body"><p>${desc}</p>${record?`<p class="small muted">Last recorded ${fmt.ago(record.finished_at||record.started_at)}</p>`:""}${details.length?`<dl>${details.map(([k,v])=>`<div><dt>${labels(k)}</dt><dd>${esc(String(v))}</dd></div>`).join("")}</dl>`:""}<div class="command-stack">${code(cmd)}</div></div></details>`;
    };
    view.innerHTML=`<div class="card"><div class="card-head"><div><h2>Research pipeline</h2><p class="sub keep">Research frozen ${esc(r.research_freeze)}. Cached means inputs were unchanged, not that market data is current.</p></div><div class="command-stack pipeline-run">${code("fomc run")}</div></div>
      <div class="pipeline-phases">${[["Acquire",STAGES.slice(0,3)],["Read",STAGES.slice(3,5)],["Evaluate",STAGES.slice(5)]].map(([name,items])=>`<section class="pipeline-phase"><h3>${name}</h3>${items.map(item).join("")}</section>`).join("")}</div></div>
      <details class="card scoring-guide"><summary><b>Scoring new documents with Claude</b><span class="muted small">Own API key required</span></summary><div class="scoring-instructions">${LLM_STEPS.map(([name,desc,cmd])=>`<section><h3>${name}</h3><p>${desc}</p><div class="command-stack">${code(cmd)}</div></section>`).join("")}</div></details>
      <div class="card"><div class="card-head"><div><h2>Message batches</h2><p class="sub keep">Model jobs and their recorded states. These are model predictions, not team annotations.</p></div></div>${r.batches.length?`<div class="table-wrap"><table class="table"><thead><tr><th>Mode</th><th>Status</th><th class="wide-only">Batch</th><th>Created</th></tr></thead><tbody>${r.batches.map(b=>`<tr><td>${esc(b.mode)}</td><td><span class="pill-mini">${esc(b.status)}</span></td><td class="mono small wide-only">${esc(b.batch_id)}</td><td>${fmt.ago(b.created_at)}</td></tr>`).join("")}</tbody></table></div>`:empty("No batches yet","No model jobs are recorded.")}</div>`;
  },
};

// -------------------------------------------------------------------- settings
pages.settings = {
  usesMethod: false,
  title: "Settings", sub: "Connect your Claude API key and choose the scoring model.",
  async render(view) {
    const st = (state.settings = await api("/api/settings"));
    if (st.read_only) {
      view.innerHTML = `<div class="grid cols-2">
        <div class="card"><h2>Public read-only deployment</h2><div class="sub">This copy of FOMC Tone Lab is hosted for viewing. Keys and models are managed by the owner through environment variables, never through this page.</div>
          <div class="meta-grid"><div><span>Scoring model</span><b>${esc(st.model)}</b></div><div><span>Effort</span><b>${esc(st.effort)}</b></div><div><span>Live scoring</span><b>${st.score_enabled ? (st.score_token_required ? "token required" : "on") : "off"}</b></div></div>
          <div class="callout ok"><span><b>Nothing you type here is stored.</b> Search, documents, results and charts are all available; only actions that spend Claude credits are locked.</span></div></div>
        <div class="card"><h2>Run it with your own key</h2><div class="sub">Five minutes from clone to dashboard; the free pipeline needs no key.</div>
          <div class="command-stack">${code("git clone <repo> && cd fomc-tone-duration")}${code("make setup && make serve")}${code("fomc key set")}</div>
          <p class="small muted" style="margin-top:12px">Then open Settings locally to paste the key and estimate the cost (free).</p><div class="command-stack">${code("fomc llm-estimate")}</div><p class="small muted">Pilot 8 documents before a full run.</p></div></div>`;
      return;
    }
    view.innerHTML = `
      <div class="grid cols-2">
        <div class="card"><h2>Claude API key</h2><div class="sub">Stored in <span class="mono">.env</span> on this machine (git-ignored, file mode 600). Sent only to api.anthropic.com. Never shown again in full.</div>
          <div class="callout ${st.key_configured ? "ok" : "warn"}" style="margin:14px 0"><span>${st.key_configured ? `<b>Connected.</b> Key ${esc(st.key_hint || "from SDK credentials")}` : "<b>No key configured.</b> The free pipeline works without one; Claude scoring needs it."}</span></div>
          <label class="field"><span>API key</span><input id="key" type="password" placeholder="sk-ant-..." autocomplete="off"></label>
          <div class="toolbar key-actions" style="margin-top:12px"><button class="btn" id="key-save">Save key</button><button class="btn ghost" id="key-test" ${st.key_configured ? "" : "disabled"}>Test connection</button><button class="btn danger" id="key-clear" ${st.key_configured ? "" : "disabled"}>Remove key</button></div>
          <p class="small muted" style="margin-top:12px">Set the key from the command line:</p><div class="command-stack">${code("fomc key set")}</div><p class="small muted">Or set <span class="mono">ANTHROPIC_API_KEY</span> in your shell.</p></div>
        <div class="card"><h2>Scoring model</h2><div class="sub">Saved to config/local.yaml (yours only). Changing the model starts a separate set of records; nothing is overwritten.</div>
          <div class="toolbar" style="margin-top:14px">
            <label class="field"><span>Model</span><select id="model">${st.models_available.map((m) => `<option value="${esc(m)}" ${m === st.model ? "selected" : ""}>${esc(methodLabel("llm:" + m))}</option>`).join("")}</select></label>
            <label class="field"><span>Effort</span><select id="effort">${[["low", "Low"], ["medium", "Medium"], ["high", "High"], ["xhigh", "Extra high"], ["max", "Max"]].map(([e, label]) => `<option value="${e}" ${e === st.effort ? "selected" : ""}>${label}</option>`).join("")}</select></label>
            <button class="btn" id="model-save">Save</button></div>
          <div class="section-title">Before a full run</div>
          <p class="small muted">Estimate the cost first (free):</p><div class="command-stack">${code("fomc llm-estimate")}</div><p class="small muted">Then pilot 8 documents and read the evidence before submitting the batch.</p></div>
      </div>`;
    const done = async (msg) => { toast(msg); await refreshPill(); route(); };
    $("#key-save").onclick = async () => {
      const key = $("#key").value.trim(); if (!key) { toast("Paste a key first"); return; }
      try { await api("/api/settings", { method: "POST", body: JSON.stringify({ api_key: key }) }); $("#key").value = "";
        const chk = await api("/api/settings/check", { method: "POST" }); await done(chk.ok ? "Saved and verified: " + chk.display_name : "Saved, but check failed: " + chk.error);
      } catch (e) { toast(e.message); }
    };
    $("#key-test").onclick = async () => { const r = await api("/api/settings/check", { method: "POST" }); toast(r.ok ? "Connected: " + r.display_name : "Failed: " + r.error); };
    $("#key-clear").onclick = async () => { if (!confirm("Remove the API key from .env?")) return; await api("/api/settings", { method: "POST", body: JSON.stringify({ clear_key: true }) }); done("Key removed"); };
    $("#model-save").onclick = async () => { await api("/api/settings", { method: "POST", body: JSON.stringify({ model: $("#model").value, effort: $("#effort").value }) }); done("Model settings saved"); };
  },
};

// ---------------------------------------------------------------------- story
// The project in ten 16:9 slides, built from /api/story (the same source `fomc slides` turns into PowerPoint).
// Slides are laid out on a fixed 1600 x 900 stage and scaled to the screen, so they look the same on a
// laptop, a projector and in the exported images. Charts render at half size and are scaled up 2x so
// their labels stay readable from the back of a room.
const STAGE = { w: 1600, h: 900, chart: 2 };
const story = { i: 0, data: null, notes: local.get("notes", false), idle: null, presenter: false, t0: 0, timer: null, sync: null };
// A presenter view and the window that opened it stay on the same slide: whichever moves tells the other, on a
// channel only the two of them share, so other story tabs (a slide link opened elsewhere) never move the projector.
let storyChannel = null;
function syncWith(id) {
  if (!id || !("BroadcastChannel" in window) || storyChannel?.name === `fomc-story-${id}`) return;
  storyChannel?.close();
  storyChannel = new BroadcastChannel(`fomc-story-${id}`);
  storyChannel.onmessage = (e) => { if (state.page === "story" && story.data && Number.isInteger(e.data?.i) && e.data.i !== story.i) showSlide(e.data.i, { broadcast: false }); };
}
function openPresenter() {
  story.sync = story.sync || Math.random().toString(36).slice(2, 10);
  syncWith(story.sync);
  const deck = story.deck === "technical" ? "deck=technical&" : "";
  window.open(`${location.pathname}${location.search}#/story?${deck}s=${story.i + 1}&presenter=1&sync=${story.sync}`, "fomc-presenter", "popup,width=1280,height=800");
}
function presenterSide(i) {
  const list = story.data.slides; const next = list[i + 1];
  $("#pv-count").textContent = `${i + 1} / ${list.length}`;
  $("#pv-next").innerHTML = next
    ? `<span class="k">Next &middot; ${next.n} / ${list.length}</span><b>${esc(next.title)}</b>${next.number ? `<span class="num">${esc(next.number)}</span>` : ""}`
    : '<span class="k">Next</span><b>End of the deck</b>';
}
const TYPE_COLORS = () => ({ statement: css("--t-statement"), minutes: css("--t-minutes"), presser: css("--t-presser"), speech: css("--t-speech") });

function chartHost(box) { box.innerHTML = '<div class="chart-host"></div>'; return box.firstChild; }
function storyAxis(extra = {}) { return axis(extra); }
function storyCorpus(el, v) {
  const colors = TYPE_COLORS();
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 40, right: 8, top: 30, bottom: 22 },
    legend: { top: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: css("--text-2"), fontSize: 10 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 } },
    xAxis: { type: "category", data: v.years, ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10,
      interval: (i) => (v.years.length - 1 - i) % 3 === 0, formatter: (y) => (String(y) === String(new Date().getFullYear()) ? `${y} YTD` : y) } }) },
    yAxis: { type: "value", ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    series: Object.entries(v.series).map(([t, data]) => ({ type: "bar", stack: "n", name: TYPES[t], data, barWidth: "62%", itemStyle: { color: colors[t], borderColor: css("--surface"), borderWidth: 0.6 } })) }));
}
function storyTone(el, v) {
  const pts = v.points || []; const last = pts[pts.length - 1];
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 40, right: 12, top: 14, bottom: 22 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => `${fmt.date(p.data[0])}<br>tone <b>${fmt.signed(p.data[1])}</b>` },
    xAxis: { type: "time", ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    yAxis: { type: "value", min: -1, max: 1, interval: 0.5, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, formatter: (t) => fmt.signed(t, 1).replace(/^\+0\.0$/, "0") } }) },
    series: [
      { type: "scatter", symbolSize: 5, itemStyle: { color: css("--muted"), opacity: 0.55 }, data: pts.map((p) => [p.date, p.score]) },
      { type: "line", showSymbol: false, lineStyle: { width: 2, color: css("--s1") }, data: pts.filter((p) => p.smooth !== null).map((p) => [p.date, p.smooth]), z: 3 },
      ...(last ? [{ type: "scatter", symbolSize: 11, z: 4, itemStyle: { color: css("--hawk"), borderColor: css("--surface"), borderWidth: 2 }, data: [[last.date, last.score]],
        label: { show: true, position: "left", color: css("--text"), fontSize: 10, fontWeight: 600, formatter: "latest" } }] : []),
    ] }));
}
function storyRange(el, v) {
  const today = new Date().toISOString().slice(0, 10); const path = v.path;
  const spans = path.map((d, i) => [d.date, (path[i + 1] || { date: today }).date, d.low, d.high]);
  const moves = path.filter((d) => d.change_bp);
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 34, right: 10, top: 12, bottom: 22 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 } },
    xAxis: { type: "time", min: path[0]?.date, max: today, ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    yAxis: { type: "value", min: 0, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, formatter: (x) => x + "%" } }) },
    series: [
      { type: "custom", silent: true, data: spans, encode: { x: [0, 1], y: [2, 3] },
        renderItem: (params, a) => { const p1 = a.coord([a.value(0), a.value(3)]); const p2 = a.coord([a.value(1), a.value(2)]);
          return { type: "rect", shape: { x: p1[0], y: p1[1], width: Math.max(1, p2[0] - p1[0]), height: Math.max(2, p2[1] - p1[1]) }, style: { fill: css("--s1"), opacity: 0.28 } }; } },
      { type: "line", step: "end", silent: true, showSymbol: false, lineStyle: { width: 1.6, color: css("--s1") }, data: [...path.map((d) => [d.date, d.high]), [today, path[path.length - 1]?.high]] },
      { type: "scatter", symbol: "triangle", symbolSize: 9, z: 3, data: moves.map((d) => ({ value: [d.date, d.high], symbolRotate: d.change_bp < 0 ? 180 : 0, itemStyle: { color: d.change_bp > 0 ? css("--hawk") : css("--dove"), borderColor: css("--surface"), borderWidth: 1 } })),
        tooltip: { formatter: (p) => `${fmt.date(p.data.value[0])}: ${p.data.value[1].toFixed(2)}%` } },
    ] }));
}
// every decision's share of the statement rewritten, the target range above it; the decision on the slide labeled
function storyWording(el, v) {
  const today = new Date().toISOString().slice(0, 10);
  const ds = v.decisions; const color = (a) => (a > 0 ? css("--hawk") : a < 0 ? css("--dove") : css("--muted"));
  const steps = [...ds.filter((d) => d.high !== null).map((d) => [d.date, d.high]), [today, (ds[ds.length - 1] || {}).high]];
  const x = (i) => ({ type: "time", gridIndex: i, min: ds[0]?.date, max: today, ...storyAxis({ splitLine: { show: false }, axisLabel: { show: i === 1, color: css("--text-2"), fontSize: 10 } }) });
  mk(el).setOption(base({ toolbox: { show: false },
    grid: [{ left: 44, right: 84, top: 8, height: "22%" }, { left: 44, right: 84, top: "36%", bottom: 22 }],
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => (p.data && p.data.d ? `${fmt.date(p.data.d.date)}<br><b>${fmt.num(p.data.d.changed, 0)}%</b> of the wording changed` : "") },
    xAxis: [x(0), x(1)],
    yAxis: [
      { type: "value", gridIndex: 0, min: 0, splitNumber: 2, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 9, formatter: (t) => t + "%" } }) },
      { type: "value", gridIndex: 1, min: 0, max: 100, interval: 25, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, formatter: (t) => t + "%" } }) },
    ],
    series: [
      { type: "line", xAxisIndex: 0, yAxisIndex: 0, step: "end", showSymbol: false, silent: true, data: steps, lineStyle: { width: 1.5, color: css("--s1") }, areaStyle: { color: css("--s1"), opacity: 0.12 } },
      { type: "bar", xAxisIndex: 1, yAxisIndex: 1, barWidth: 1.4, silent: true, data: ds.map((d) => ({ value: [d.date, d.changed], itemStyle: { color: color(d.action), opacity: d.action ? 0.9 : 0.4 } })),
        markLine: { silent: true, symbol: "none", lineStyle: { color: css("--text-2"), type: "dashed", width: 1 }, label: { formatter: `median ${v.median}%`, position: "end", color: css("--text-2"), fontSize: 10 }, data: [{ yAxis: v.median }] } },
      { type: "scatter", xAxisIndex: 1, yAxisIndex: 1, z: 3, data: ds.filter((d) => d.action || d.doc_id === v.current).map((d) => ({ value: [d.date, d.changed], d,
        symbol: d.action ? "triangle" : "circle", symbolRotate: d.action < 0 ? 180 : 0, symbolSize: d.doc_id === v.current ? 12 : 6,
        itemStyle: { color: color(d.action), borderColor: css("--surface"), borderWidth: 1 },
        label: d.doc_id === v.current ? { show: true, position: "top", distance: 6, color: css("--text"), fontSize: 11, fontWeight: 700,
          formatter: () => `${new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" })}: ${fmt.num(d.changed, 0)}%` } : { show: false } })) },
    ] }));
}
function storySharpes(el, v) {
  const bars = v.bars;
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 36, right: 10, top: 30, bottom: 18 },
    legend: { top: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: css("--text-2"), fontSize: 10 }, data: ["Tone level", "Tone shift", "Pre-registered"] },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => { const b = bars[p.dataIndex]; return b ? `${esc(runName(b.run_id))}<br>Sharpe <b>${fmt.num(b.sharpe)}</b> &middot; DSR ${pct(b.dsr)}` : ""; } },
    xAxis: { type: "category", data: bars.map((b, i) => i + 1), ...storyAxis({ axisLabel: { show: false }, splitLine: { show: false } }), name: "variants, best to worst", nameLocation: "middle", nameGap: 6, nameTextStyle: { color: css("--text-2"), fontSize: 10 } },
    yAxis: { type: "value", max: (e) => Math.ceil(10 * (Math.max(e.max, v.hurdle) + 0.1)) / 10, name: "Sharpe ratio", nameTextStyle: { color: css("--text-2"), fontSize: 10 },
      ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    series: [
      { type: "bar", name: "Tone level", barGap: "-100%", barWidth: "70%", data: bars.map((b) => (b.signal === "shift" || b.is_primary ? null : b.sharpe)), itemStyle: { color: css("--s1"), borderRadius: [2, 2, 0, 0] } },
      { type: "bar", name: "Pre-registered", barGap: "-100%", barWidth: "70%", z: 4, data: bars.map((b) => (b.is_primary ? b.sharpe : null)), itemStyle: { color: css("--text"), borderRadius: [2, 2, 0, 0] },
        label: { show: true, position: "top", distance: 8, color: css("--text"), fontSize: 9, fontWeight: 700, formatter: (p) => (p.value === null || p.value === undefined ? "" : "pre-registered") } },
      { type: "bar", name: "Tone shift", barWidth: "70%", data: bars.map((b) => (b.signal === "shift" ? b.sharpe : null)), itemStyle: { color: css("--s2"), borderRadius: [2, 2, 0, 0] },
        markLine: { silent: true, symbol: "none", lineStyle: { color: css("--text"), type: "dashed", width: 1.4 },
          label: { formatter: `luck hurdle ${v.hurdle.toFixed(2)}`, color: css("--text"), fontSize: 10, position: "insideEndTop" }, data: [{ yAxis: v.hurdle }] } },
    ] }));
}
function storyPolicy(el, v) {
  const today = new Date().toISOString().slice(0, 10);
  const start = v.rates.length ? v.rates[0].date : v.yields[0]?.date;
  const path = [...v.range_before.map((r) => ({ ...r, release_date: start })), ...v.path];
  const spans = path.map((d, i) => [d.release_date < start ? start : d.release_date, (path[i + 1] || { release_date: today }).release_date, d.range_low, d.range_high]);
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 36, right: 10, top: 28, bottom: 22 },
    legend: { top: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: css("--text-2"), fontSize: 10 }, data: ["Target range", "Effective fed funds", "2-year Treasury"] },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (ps) => `${fmt.date(ps[0].axisValue)}<br>` + ps.filter((p) => p.seriesType === "line").map((p) => `${p.marker}${p.seriesName}: <b>${fmt.num(p.value[1])}%</b>`).join("<br>") },
    xAxis: { type: "time", min: start, max: today, ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    yAxis: { type: "value", scale: true, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, formatter: (x) => x + "%" } }) },
    series: [
      { type: "custom", name: "Target range", silent: true, itemStyle: { color: css("--s1"), opacity: 0.3 }, data: spans, encode: { x: [0, 1], y: [2, 3] },
        renderItem: (params, a) => { const p1 = a.coord([a.value(0), a.value(3)]); const p2 = a.coord([a.value(1), a.value(2)]);
          return { type: "rect", shape: { x: p1[0], y: p1[1], width: Math.max(1, p2[0] - p1[0]), height: Math.max(2, p2[1] - p1[1]) }, style: { fill: css("--s1"), opacity: 0.2 } }; } },
      { type: "line", name: "Effective fed funds", showSymbol: false, lineStyle: { width: 2, color: css("--s1") }, itemStyle: { color: css("--s1") }, data: v.rates.filter((r) => r.effr !== null).map((r) => [r.date, r.effr]) },
      { type: "line", name: "2-year Treasury", showSymbol: false, lineStyle: { width: 2, color: css("--s2") }, itemStyle: { color: css("--s2") }, data: v.yields.filter((r) => r.t2y !== null).map((r) => [r.date, r.t2y]) },
    ] }));
}
function storyValidity(el, v) {
  const rows = [...v.rows].sort((a, b) => a.macro_f1 - b.macro_f1);
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 118, right: 34, top: 26, bottom: 18 },
    legend: { top: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: css("--text-2"), fontSize: 10 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 } },
    xAxis: { type: "value", max: 1, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    yAxis: { type: "category", data: rows.map((r) => methodLabel(r.method)), ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text"), fontSize: 10 } }) },
    series: [
      { name: "Macro-F1", type: "bar", barWidth: 9, barGap: "30%", data: rows.map((r) => refBar(r, r.macro_f1, false)), itemStyle: { color: css("--text"), borderRadius: [0, 3, 3, 0] },
        label: { show: true, position: "right", fontSize: 9, color: css("--text-2"), formatter: (p) => p.value.toFixed(2) } },
      { name: "Cohen's kappa", type: "bar", barWidth: 9, data: rows.map((r) => refBar(r, r.cohen_kappa, true)), itemStyle: { color: css("--text"), opacity: 0.45, borderRadius: [0, 3, 3, 0] } },
    ] }));
}
function storyReaders(el, v) {
  const colors = TYPE_COLORS(); const order = ["statement", "minutes", "presser", "speech"];
  const series = []; const xAxis = []; const yAxis = []; const grid = []; const title = [];
  order.forEach((t, i) => {
    const right = i % 2; const bottom = i >= 2;
    const left = right ? "60%" : "10%"; const top = bottom ? "60%" : "13%";
    const points = v.points.filter((p) => p[0] === t).map((p) => [p[1], p[2]]);
    const r = v.r && v.r[t] !== undefined ? `; r = ${v.r[t].toFixed(2)}` : "";
    title.push({ text: `${TYPES[t]}: n = ${points.length}${r}`, left, top: bottom ? "52%" : "2%", padding: 0,
      textStyle: { color: css("--text"), fontSize: 10, fontWeight: 600 } });
    grid.push({ left, top, width: "34%", height: bottom ? "25%" : "29%" });
    xAxis.push({ type: "value", gridIndex: i, min: -1, max: 1, interval: 1,
      name: bottom ? "Claude's score" : "", nameLocation: "middle", nameGap: 20,
      nameTextStyle: { color: css("--text-2"), fontSize: 9 },
      ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 9 } }) });
    yAxis.push({ type: "value", gridIndex: i, min: -1, max: 1, interval: 1,
      name: !right ? "RoBERTa" : "", nameLocation: "middle", nameGap: 28,
      nameTextStyle: { color: css("--text-2"), fontSize: 9 },
      ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 9 } }) });
    series.push({ type: "line", xAxisIndex: i, yAxisIndex: i, silent: true, showSymbol: false,
      lineStyle: { color: css("--muted"), type: "dashed", width: 1 }, data: [[-1, -1], [1, 1]] });
    series.push({ type: "scatter", name: TYPES[t], xAxisIndex: i, yAxisIndex: i, symbolSize: 8,
      itemStyle: { color: colors[t], opacity: 0.75, borderColor: css("--surface"), borderWidth: 1 }, data: points });
  });
  mk(el).setOption(base({ toolbox: { show: false }, title, grid, xAxis, yAxis,
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => `${esc(p.seriesName)}<br>Claude <b>${fmt.signed(p.data[0])}</b> &middot; RoBERTa <b>${fmt.signed(p.data[1])}</b>` }, series }));
}
// Story intervals reuse the dashboard's error-bar renderer and the stored estimates only.
function storyIntervals(el, v) {
  const points = v.rows.map((r, i) => {
    const color = r.highlight ? css("--claude") : css("--text-2");
    const crosses = v.zero && r.low <= 0 && r.high >= 0;
    return { value: [r.value, i, r.low, r.high], row: r, color,
      itemStyle: { color: crosses ? css("--surface") : color, borderColor: color, borderWidth: 2 },
      symbol: r.highlight ? "diamond" : "circle" };
  });
  const digits = v.digits ?? 3;
  mk(el).setOption(base({ toolbox: { show: false },
    title: { text: v.interval, left: 0, top: 0, padding: 0, textStyle: { color: css("--text-2"), fontSize: 10, fontWeight: 400 } },
    grid: { left: 174, right: 42, top: 34, bottom: 42 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => { const r = p.data.row; return `${esc(r.label)}<br>${esc(v.axis)}: <b>${fmt.num(r.value, digits)}</b><br>${esc(v.interval)}: ${fmt.num(r.low, digits)} to ${fmt.num(r.high, digits)}<br>${esc(r.details || "")}`; } },
    xAxis: { type: "value", scale: true, name: v.axis, nameLocation: "middle", nameGap: 27,
      min: v.zero ? (e) => Math.min(0, e.min) : null,
      nameTextStyle: { color: css("--text-2"), fontSize: 10 },
      ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10 } }) },
    yAxis: { type: "category", inverse: true, data: v.rows.map((r) => r.label),
      ...storyAxis({ splitLine: { show: false }, axisLabel: { color: css("--text"), fontSize: 10, width: 162, overflow: "truncate" } }) },
    series: [...researchRangeSeries(points), ...(v.zero ? [zeroLine("xAxis")] : [])],
  }));
}
const DIM_NAMES = { policy_action: "Policy action", forward_guidance: "Forward guidance", inflation_assessment: "Inflation", activity_labor_assessment: "Activity and labor", risk_balance: "Balance of risks", balance_sheet: "Balance sheet" };
const VERDICT = { Supported: ["ok", "&#10003;"], "Not supported": ["no", "&#10007;"], Mixed: ["mixed", "&#8776;"] };
function storyPrimer(v) {
  const quote = (q) => `<div class="pq ${q.side}"><span class="k">${esc(q.label)}</span><span class="g">${esc(q.gloss)}</span>
    <q>${esc(q.text)}</q><span class="src">${esc(q.when)} &middot; Claude ${fmt.signed(q.score).replace("-", "&minus;")}</span></div>`;
  return `<div class="s-primer"><div class="pm-row">${v.steps.map((s, i) => `${i ? '<span class="arrow" aria-hidden="true">&rarr;</span>' : ""}<div class="pm"><span class="n">${String(i + 1).padStart(2, "0")}</span><b>${esc(s.title)}</b>
    ${s.formula ? `<span class="formula">${esc(s.formula)}</span>` : ""}${s.body ? `<p>${esc(s.body)}</p>` : ""}${(s.quotes || []).map(quote).join("")}
    ${s.foot ? `<span class="foot">${esc(s.foot)}</span>` : ""}</div>`).join("")}</div>
    ${v.question ? `<div class="pm-q"><b>The question</b><span>${esc(v.question)}</span></div>` : ""}</div>`;
}
function storyBrief(v) {
  return `<div class="s-brief"><div class="bh"><span></span><span>The brief asks for</span><span></span><span>What we built</span></div>
    ${v.rows.map(([ask, did], i) => `<div class="br"><span class="n">${i + 1}</span><span class="ask">${esc(ask)}</span><span class="arrow">&rarr;</span><span class="did"><i>&#10003;</i>${esc(did)}</span></div>`).join("")}</div>`;
}
function storyAgenda(v) {
  return `<div class="s-agenda">${v.sections.map(([n, t, d]) => `<div class="ag"><span class="num">${esc(n)}</span><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>`;
}
function storyContents(v) {
  return `<div class="s-contents">${v.rows.map(([name, about, range], i) => `<div class="ct"><span class="num">${String(i + 1).padStart(2, "0")}</span><b>${esc(name)}</b><span>${esc(about)}</span><span class="range">${esc(String(range).replace("-", "–"))}</span></div>`).join("")}</div>`;
}
function storyAnswers(v) {
  return `<div class="s-answers">${v.cards.map(([h, claim, verdict, metric]) => { const [cls, icon] = VERDICT[verdict] || VERDICT[verdict.split(" on ")[0]] || ["mixed", "&#8776;"];
    return `<div class="ans ${cls}"><span class="h">${esc(h)}</span><b>${esc(claim)}</b><span class="verdict"><i>${icon}</i>${esc(verdict)}</span><span class="metric">${esc(metric)}</span></div>`; }).join("")}</div>`;
}
function storyTimeline() {
  const x = (h, m) => 30 + ((h - 13.5) * 60 + m) * (660 / 180);  // 1:30 p.m. to 4:30 p.m. across 660 px
  const mark = (h, m, label, sub, cls = "") => `<div class="tl-mark ${cls}" style="left:${x(h, m)}px"><i></i><b>${label}</b><span>${sub}</span></div>`;
  return `<div class="s-timeline">
    <div class="tl-label">Release day, Eastern time</div>
    <div class="tl-axis"></div>
    <div class="tl-ticks">${[[13, 30, "1:30"], [14, 0, "2:00"], [14, 30, "2:30"], [15, 0, "3:00"], [15, 30, "3:30"], [16, 0, "4:00"], [16, 30, "4:30"]].map(([h, m, t]) => `<span style="left:${x(h, m)}px">${t}</span>`).join("")}</div>
    <div class="tl-bar" style="left:${x(14, 30)}px;width:${x(15, 30) - x(14, 30)}px">Press conference</div>
    ${mark(14, 0, "Statement", "2:00 p.m., priced within minutes", "accent")}
    ${mark(15, 30, "Treasury fix", "3:30 p.m.: statement window closes", "below to-left")}
    ${mark(16, 0, "ETF close", "4:00 p.m.: same-day entry", "below to-right")}
    <div class="tl-break" style="left:${x(16, 30) + 40}px">next day</div>
    <div class="tl-mark hawk" style="left:880px"><i></i><b>Pre-registered entry</b><span>4:00 p.m. the day after the release</span></div>
    <div class="tl-window" style="left:${x(13, 30) - 10}px;width:${x(15, 30) - x(13, 30) + 10}px"><span>Statement window: from the previous 3:30 fix to this one</span></div>
    <div class="tl-notes"><div><b>Minutes</b><span>Three weeks later at 2:00 p.m.: a one-day window, read more slowly</span></div>
      <div><b>Speeches</b><span>Feed timestamp; after 3:30 p.m. the window moves to the next fix</span></div>
      <div><b>Press conference</b><span>Straddles the 3:30 fix, so it gets a two-day window</span></div></div>
  </div>`;
}
function storyFlow() {
  const steps = [
    ["Document", "cleaned text, the Fed’s words only; no date or title shown"],
    ["Rubric v1", "six policy dimensions, stance, confidence; cached system prompt"],
    ["Claude Opus 5.5", "adaptive thinking, structured JSON output, Message Batches"],
    ["Verify", "checks every quote; stores matched spans and records unmatched exceptions"],
    ["Record", "JSON keyed by a hash of prompt, schema and text, with IDs and tokens"],
    ["Store", "scores, evidence and costs in SQLite; the dashboard reads them"],
  ];
  return `<div class="s-flow">${steps.map(([t, d], i) => `<div class="fl"><span class="n">${i + 1}</span><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>`;
}
function storyReading(v) {
  const spans = [...v.spans].sort((a, b) => a.start - b.start);
  let html = ""; let at = 0;
  spans.forEach((s) => { if (s.start < at) return; html += esc(v.text.slice(at, s.start)) + `<mark>${esc(v.text.slice(s.start, s.end))}</mark>`; at = s.end; });
  html += esc(v.text.slice(at));
  const stanceCls = v.stance > 0.15 ? "hawk" : v.stance < -0.15 ? "dove" : "";
  const dims = Object.entries(v.dims).map(([k, val]) => {
    const w = val === null || val === undefined ? 0 : Math.abs(val) * 25;
    const left = val >= 0 ? 50 : 50 - w;
    return `<div class="rd-dim"><span>${DIM_NAMES[k]}</span><span class="bar"><i style="left:${left}%;width:${w}%;background:${val >= 0 ? "var(--hawk)" : "var(--dove)"}"></i></span><b>${val === null || val === undefined ? dash : fmt.signed(val, 0)}</b></div>`;
  }).join("");
  return `<div class="s-reading"><div class="rd-text">${html.replace(/\n\n/g, "<br><br>")}</div>
    <div class="rd-side"><span class="rd-k">Claude’s reading</span><div class="rd-stance ${stanceCls}">${fmt.signed(v.stance)}</div>
      <span class="rd-sub">stance from &minus;1 dovish to +1 hawkish &middot; confidence ${fmt.num(v.confidence)}</span>
      <div class="rd-dims">${dims}</div><p class="rd-why">&ldquo;${esc(v.rationale)}&rdquo;</p></div></div>`;
}
function storyArchitecture(v) {
  return `<div class="s-arch">
    <div class="col"><span class="ch">Sources</span>${v.sources.map(([t, d]) => `<div class="box"><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>
    <div class="col stages"><span class="ch">Pipeline &middot; fomc run</span><div class="stage-grid">${v.stages.map(([t, d], i) => `<div class="box pst ${t === "Claude" ? "claude" : ""}"><b><i>${i + 1}</i>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div></div>
    <div class="col"><span class="ch">Store</span><div class="db"><b>data/fomc.db</b>${v.store.map((s) => `<span>${esc(s)}</span>`).join("")}</div></div>
    <div class="col"><span class="ch">Ways in</span>${v.serve.map(([t, d]) => `<div class="box"><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>
  </div>`;
}
function storyTiles(v) { return `<div class="s-tiles n${v.tiles.length}">${v.tiles.map(([k, d]) => `<div class="tile"><b>${esc(k)}</b><span>${esc(d)}</span></div>`).join("")}</div>`; }
function storyScreens(v) { return `<div class="s-screens">${v.shots.map(([t, src]) => `<figure><img src="${esc(src)}" alt="${esc(t)} page of the dashboard" loading="lazy"><figcaption>${esc(t)}</figcaption></figure>`).join("")}</div>`; }
function storyAudit(el, v) {
  mk(el).setOption(base({ toolbox: { show: false }, grid: { left: 52, right: 14, top: 26, bottom: 42 },
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--text"), fontSize: 11 },
      formatter: (p) => p.seriesType === "scatter" ? `raw ${fmt.signed(p.data[0])} &middot; masked ${fmt.signed(p.data[1])}` : "" },
    xAxis: { type: "value", min: -1, max: 1, name: "score on the original text", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: css("--text-2"), fontSize: 10, fontWeight: 400 }, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, fontWeight: 400 } }) },
    yAxis: { type: "value", min: -1, max: 1, name: "score with dates and names masked", nameLocation: "middle", nameGap: 38, nameTextStyle: { color: css("--text-2"), fontSize: 10, fontWeight: 400 }, ...storyAxis({ axisLabel: { color: css("--text-2"), fontSize: 10, fontWeight: 400 } }) },
    series: [
      { type: "line", silent: true, showSymbol: false, data: [[-1, -1], [1, 1]], lineStyle: { color: css("--muted"), type: "dashed", width: 1 } },
      { type: "scatter", symbolSize: 7, data: v.points, itemStyle: { color: css("--s1"), opacity: 0.8, borderColor: css("--surface"), borderWidth: 0.6 } },
    ] }));
}
// The technical appendix's plain visuals: a table, a block of code or formulas, confusion matrices.
function storyTable(v) {
  const cls = (i) => (v.align && v.align[i] === "r" ? ' class="r"' : "");
  const size = v.rows.length <= 5 ? "few" : v.rows.length <= 10 ? "mid" : "many";
  return `<div class="s-table ${size}"><table><thead><tr>${v.columns.map((h, i) => `<th${cls(i)}>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${v.rows.map((r, k) => `<tr${k === v.highlight ? ' class="hl"' : ""}>${r.map((x, i) => `<td${cls(i)}>${esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>${v.note ? `<p class="s-note">${esc(v.note)}</p>` : ""}</div>`;
}
function storyCode(v) {
  const line = (l) => { const i = l.indexOf("# "); return i < 0 ? esc(l) : `${esc(l.slice(0, i))}<span class="c">${esc(l.slice(i))}</span>`; };
  return `<div class="s-code"><pre>${v.lines.map(line).join("\n")}</pre></div>`;
}
function storyMatrices(v) {
  const table = (m) => `<table><thead><tr><th></th>${v.labels.map((l) => `<th>${esc(l)}</th>`).join("")}</tr></thead><tbody>${m.map((row, i) => {
    const total = row.reduce((a, b) => a + b, 0) || 1;
    return `<tr><th>${esc(v.labels[i])}</th>${row.map((n, j) => { const w = n / total; return `<td class="${i === j ? "d" : ""} ${w > 0.45 ? "hi" : ""}" style="--w:${Math.round(w * 85)}%">${n}</td>`; }).join("")}</tr>`; }).join("")}</tbody></table>`;
  return `<div class="s-matrices n${v.items.length}">${v.items.map((m) => `<figure><figcaption>${esc(m.title)}<small>rows: the experts' label &middot; columns: the reader's</small></figcaption>${table(m.m)}</figure>`).join("")}</div>`;
}
function storyHtmlVisual(s) {
  const v = s.visual;
  if (s.id === "agenda") return storyContents(v);
  const html = { primer: storyPrimer, brief: storyBrief, agenda: storyAgenda, answers: storyAnswers, timeline: storyTimeline, flow: storyFlow,
    reading: storyReading, architecture: storyArchitecture, tiles: storyTiles, screens: storyScreens, table: storyTable, code: storyCode, matrices: storyMatrices }[v.kind];
  if (html) return html(v);
  if (v.kind === "steps") return `<div class="s-steps n${v.steps.length}">${v.steps.map(([t, d], i) => `<div class="s-step"><span class="n">${i + 1}</span><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>`;
  if (v.kind === "cards") return `<div class="s-cards n${v.cards.length}">${v.cards.map(([t, d], i) => `<div class="s-card"><span class="n">${String(i + 1).padStart(2, "0")}</span><b>${esc(t)}</b><span>${esc(d)}</span></div>`).join("")}</div>`;
  return null;
}
function drawStoryVisual(box, s) {
  const v = s.visual; const html = storyHtmlVisual(s);
  if (html !== null) { box.innerHTML = html; return; }
  const host = chartHost(box);
  const draw = { corpus: storyCorpus, tone: storyTone, range: storyRange, wording: storyWording, sharpes: storySharpes, policy: storyPolicy, validity: storyValidity, readers: storyReaders, intervals: storyIntervals,
    curves: (el) => curveChart(el, v.data), coefs: (el) => groupChart(el, v.rows, v.methods), term: (el) => termChart(el, v.rows, v.methods), audit: storyAudit,
    forecast: (el) => forecastChart(el, v.meetings, true) }[v.kind];
  if (draw) draw(host, v);
  const inst = echarts.getInstanceByDom(host);
  // units sit beside the number, so most charts drop the y name; these keep it, their number says nothing about y
  if (inst) inst.setOption(["audit", "readers", "sharpes", "curves"].includes(v.kind) ? { toolbox: { show: false } } : { toolbox: { show: false }, yAxis: { name: "" } });
}
function partTitles(i) {
  const list = story.data.slides; const out = [];
  for (let j = i + 1; j < list.length && !["divider", "closing"].includes(list[j].layout) && !["takeaways", "limits", "closing"].includes(list[j].id); j++) out.push(list[j].title);
  return out;
}
function teamChips(team) { return `<div class="cover-team">${team.map((n) => `<span>${esc(n)}</span>`).join("")}</div>`; }
const LOGO = '<span class="logo cover-logo" aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M14 42c6-16 12-16 18-6s12 10 18-12" stroke="currentColor" stroke-width="5" fill="none" stroke-linecap="round"/><circle class="logo-dot" cx="50" cy="24" r="5.5"/></svg></span>';
function storyChapter(s) {
  const rows = story.data?.slides.find((p) => p.id === "agenda")?.visual?.rows;
  return Number.isInteger(s.part) && rows?.[s.part]
    ? { number: String(s.part + 1).padStart(2, "0"), title: rows[s.part][0] } : null;
}
function storyRail(s) {
  if (!Number.isInteger(s.part)) return "";
  return `<div class="s-rail" aria-hidden="true">${Array.from({ length: 5 }, (_, j) => `<i class="${j === s.part ? "on" : ""}"></i>`).join("")}</div>`;
}
function slideHtml(s, total, i) {
  if (s.layout === "cover") {
    return `<section class="slide cover editorial"><div class="cover-masthead">${LOGO}<span class="s-kicker">${esc(s.kicker)}</span></div>
      <div class="cover-copy"><h1 class="cover-title">${esc(s.title)}</h1><p class="cover-sub">${esc(s.subtitle)}</p></div>
      <div class="cover-pipeline">${[["Read", "Fed language"], ["Measure", "Policy tone"], ["Test", "Treasury yields"], ["Size", "Portfolio duration"]].map(([a,b],j)=>`<div><span>0${j+1} / ${a}</span><b>${b}</b></div>`).join("")}</div>
      <div class="cover-links">${(s.links || []).map(([a,b])=>`<div><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("")}</div>${teamChips(s.team)}</section>`;
  }
  if (s.layout === "closing") {
    return `<section class="slide cover closing editorial"><div class="cover-masthead">${LOGO}<span class="s-kicker">${esc(s.kicker)}</span></div>
      <div class="cover-copy"><h1 class="cover-title">${esc(s.title)}</h1><p class="cover-sub">${esc(s.subtitle)}</p>
      <div class="closing-links">${[s.url, s.repo].filter(Boolean).map((u)=>`<div class="closing-url">${esc(u)}</div>`).join("")}</div></div>${teamChips(s.team)}</section>`;
  }
  if (s.layout === "divider") {
    return `<section class="slide divider"><div class="dv-num">${esc(s.number)}</div><div class="dv-body"><span class="s-kicker">${esc(s.kicker)}</span>
      <h1 class="dv-title">${esc(s.title)}</h1><p class="dv-sub">${esc(s.subtitle)}</p>
      <ol class="dv-list">${partTitles(i).map((t) => `<li>${esc(t)}</li>`).join("")}</ol></div><span class="s-pager dv-pager">${s.n} / ${total}</span></section>`;
  }
  // a layout per slide: standard (the number, then the visual), mirror (the visual first), compare (two numbers set
  // against each other), banner (the number and its facts in a band over a full-width visual), wide (the visual only)
  const lay = ["wide", "mirror", "banner", "compare"].includes(s.layout) ? s.layout : "standard";
  const chips = (s.chips || []).filter(Boolean);
  const visual = '<div class="s-visual" id="s-visual"></div>';
  const lead = `<div class="s-number">${esc(s.number)}</div><div class="s-number-label">${esc(s.number_label || "")}</div>`;
  const left = `<div class="s-left">${lead}<div class="s-chips">${chips.map((c) => `<span>${esc(c)}</span>`).join("")}</div></div>`;
  const accent = s.compare_word === "but" ? 1 : 0;  // "but": the second number is the point; "against": the first
  const body = {
    wide: visual,
    standard: left + visual,
    mirror: visual + left,
    banner: `<div class="s-band"><div class="s-lead">${lead}</div><div class="s-facts">${chips.slice(0, 4).map((c) => `<span>${esc(c)}</span>`).join("")}</div></div>${visual}`,
    compare: `<div class="s-left s-compare">${(s.compare || []).map(([n, l], k) => `${k ? `<div class="cmp-word">${esc(s.compare_word || "against")}</div>` : ""}<div class="cmp ${k === accent ? "on" : ""}"><div class="s-number">${esc(n)}</div><div class="s-number-label">${esc(l)}</div></div>`).join("")}
      ${(() => { const said = (s.compare || []).map(([n]) => n); const fresh = chips.filter((c) => !said.some((n) => c.includes(n.replace(/^r = /, "")))).slice(0, 1);  // not a number already on the slide
        return fresh.length ? `<div class="s-chips">${fresh.map((c) => `<span>${esc(c)}</span>`).join("")}</div>` : ""; })()}</div>${visual}`,
  }[lay];
  const chapter = storyChapter(s);
  const starts = chapter && story.data.slides[i - 1]?.part !== s.part;
  return `<section class="slide editorial ${lay} ${starts ? "section-start" : ""} ${s.desk ? "" : "no-desk"} k-${esc(s.visual?.kind || "")} id-${esc(s.id)}">
    <header class="s-head"><span class="s-kicker">${chapter ? `<i>${chapter.number}</i>${esc(chapter.title)}` : esc(s.kicker)}</span><span class="s-pager">${s.n} / ${total}</span></header>
    <div class="s-titles"><h1 class="s-title" title="${esc(s.title)}">${esc(s.title)}</h1>${s.subtitle ? `<p class="s-sub">${esc(s.subtitle)}</p>` : ""}</div>
    <div class="s-body">${body}</div>
    ${s.desk ? `<div class="s-desk"><b>${esc(s.desk_label || "For the desk")}</b><span>${esc(s.desk)}</span></div>` : ""}
    <footer class="s-foot${s.source ? "" : " empty"}"><span>${s.source ? `Source: ${esc(s.source)}` : ""}</span><a href="${esc(s.link)}" class="s-open" data-story-open>Open in the app &rarr;</a></footer>${storyRail(s)}
  </section>`;
}
function fitStage() {
  const wrap = $("#stage-wrap"); const stage = $("#stage"); if (!wrap || !stage) return 1;
  const k = Math.min(wrap.clientWidth / STAGE.w, wrap.clientHeight / STAGE.h);
  stage.style.transform = `scale(${k})`;
  stage.style.left = `${(wrap.clientWidth - STAGE.w * k) / 2}px`; stage.style.top = `${(wrap.clientHeight - STAGE.h * k) / 2}px`;
  return k;
}
function showSlide(i, { push = true, broadcast = true } = {}) {
  const d = story.data; if (!d) return;
  story.i = Math.max(0, Math.min(d.slides.length - 1, i));
  const s = d.slides[story.i];
  clearCharts();
  const exportMode = viewParams().get("export");
  const k = exportMode === "visual" ? 1 : fitStage();
  state.chartDpr = (window.devicePixelRatio || 1) * STAGE.chart * Math.max(1, k);
  if (exportMode === "visual") { $("#stage").innerHTML = `<div class="s-visual export editorial ${esc(s.layout || "")} ${s.desk ? "" : "no-desk"}" id="s-visual"></div>`; }
  else $("#stage").innerHTML = slideHtml(s, d.slides.length, story.i);
  const box = $("#s-visual"); if (box && s.visual) drawStoryVisual(box, s);
  state.chartDpr = null;
  $("#story-count").textContent = `${story.i + 1} / ${d.slides.length}`;
  $("#story-bar").style.width = `${(100 * (story.i + 1)) / d.slides.length}%`;
  $("#notes-text").textContent = s.notes || "";
  $("#story-prev").disabled = story.i === 0; $("#story-next").disabled = story.i === d.slides.length - 1;
  if (story.presenter) presenterSide(story.i);
  if (push) setViewParams({ s: story.i + 1 });
  if (broadcast && !exportMode) storyChannel?.postMessage({ i: story.i });
}
function storyIdle() {
  const ui = $("#story-ui"); if (!ui) return;
  ui.classList.remove("idle"); clearTimeout(story.idle);
  story.idle = setTimeout(() => ui.classList.add("idle"), 2600);
}
pages.story = {
  title: "Story", sub: "The whole project as a presentation, built live from the data. Arrow keys move, F goes full screen, N shows the speaker notes, V opens the presenter view, Esc leaves.",
  async render(view) {
    const vp = viewParams(); const exportMode = vp.get("export");
    story.deck = vp.get("deck") === "technical" ? "technical" : "main";
    story.data = await api(story.deck === "technical" ? "/api/story?deck=technical" : "/api/story");
    story.presenter = vp.get("presenter") === "1" && !exportMode;
    if (story.presenter) syncWith(vp.get("sync"));
    clearInterval(story.timer);
    document.documentElement.classList.toggle("export-visual", exportMode === "visual");
    document.documentElement.classList.toggle("export-slide", exportMode === "slide");
    const side = story.presenter
      ? `<aside class="pv-side" aria-label="Presenter view">
          <div class="pv-top"><span class="pv-timer" id="pv-timer" aria-live="off">00:00</span><button class="btn small" id="pv-reset">Restart timer</button><span class="pv-count" id="pv-count"></span></div>
          <div class="pv-next" id="pv-next"></div>
          <div class="pv-notes"><b>Speaker notes</b><p id="notes-text"></p></div></aside>`
      : "";
    view.innerHTML = `<div class="story ${story.presenter ? "pv" : ""}">
      <div class="stage-wrap" id="stage-wrap"><div class="stage" id="stage"></div></div>${side}
      <div class="story-progress"><span id="story-bar"></span></div>
      <div class="story-ui" id="story-ui">
        <button class="icon-btn" id="story-exit" title="Leave the story (Esc)" aria-label="Leave the story"><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg></button>
        <span class="story-sep"></span>
        <button class="icon-btn" id="story-prev" title="Previous (left arrow)" aria-label="Previous slide"><svg class="ic" aria-hidden="true"><use href="#i-chevron-left"/></svg></button>
        <span id="story-count" class="story-count" aria-live="polite"></span>
        <button class="icon-btn" id="story-next" title="Next (right arrow)" aria-label="Next slide"><svg class="ic" aria-hidden="true"><use href="#i-chevron-right"/></svg></button>
        <span class="story-sep"></span>
        <button class="icon-btn ${story.notes ? "on" : ""}" id="story-notes" title="Speaker notes (N)" aria-label="Speaker notes" aria-pressed="${story.notes}" ${story.presenter ? "hidden" : ""}><svg class="ic" aria-hidden="true"><use href="#i-sticky-note"/></svg></button>
        <button class="icon-btn" id="story-presenter" title="Presenter view: notes, next slide and a timer in a second window (V)" aria-label="Open the presenter view" ${story.presenter ? "hidden" : ""}><svg class="ic" aria-hidden="true"><use href="#i-presentation"/></svg></button>
        <button class="icon-btn" id="story-full" title="Full screen (F)" aria-label="Full screen"><svg class="ic" aria-hidden="true"><use href="#i-maximize"/></svg></button>
        ${story.deck === "technical" ? '<span class="story-sep"></span><a class="story-deck" id="story-deck" href="#/story" title="Open the integrated presentation">Integrated presentation</a>' : ""}
      </div>
      ${story.presenter ? "" : `<aside class="story-notes" id="story-notes-panel" ${story.notes ? "" : "hidden"}><b>Speaker notes</b><p id="notes-text"></p></aside>`}
    </div>`;
    $("#story-prev").onclick = () => showSlide(story.i - 1);
    $("#story-next").onclick = () => showSlide(story.i + 1);
    $("#story-exit").onclick = () => { if (story.presenter && window.opener) window.close(); else location.hash = "#/overview"; };
    $("#story-presenter").onclick = openPresenter;
    if (story.presenter) {
      const tick = () => {
        const el = $("#pv-timer"); if (!el) { clearInterval(story.timer); return; }  // left the story
        const sec = Math.floor((Date.now() - story.t0) / 1000);
        el.textContent = `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
      };
      story.t0 = Date.now(); story.timer = setInterval(tick, 1000);
      $("#pv-reset").onclick = () => { story.t0 = Date.now(); tick(); };
    }
    $("#story-full").onclick = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.());
    $("#story-notes").onclick = () => { if (story.presenter) return; story.notes = !story.notes; local.set("notes", story.notes); $("#story-notes-panel").hidden = !story.notes; $("#story-notes").classList.toggle("on", story.notes); $("#story-notes").setAttribute("aria-pressed", story.notes); };
    $("#stage").addEventListener("click", (e) => {
      const a = e.target.closest("[data-story-open]"); if (!a) return;
      try { sessionStorage.setItem("fomc.storyReturn", String(story.i + 1) + (story.deck === "technical" ? "|technical" : "")); } catch { /* private mode */ }
    });
    view.querySelector(".story").addEventListener("pointermove", storyIdle);
    showSlide(Math.max(0, Number(vp.get("s") || 1) - 1), { push: false });
    storyIdle();
  },
};
window.addEventListener("resize", () => { if (state.page === "story" && story.data) showSlide(story.i, { push: false, broadcast: false }); });
document.addEventListener("keydown", (e) => {
  if (state.page !== "story" || !story.data || e.metaKey || e.ctrlKey || e.altKey) return;
  if (!$("#palette").hidden || !$("#drawer").hidden || $("#keys").open) return;
  const k = e.key;
  if (["ArrowRight", "PageDown", " ", "Enter"].includes(k)) { e.preventDefault(); showSlide(story.i + 1); }
  else if (["ArrowLeft", "PageUp", "Backspace"].includes(k)) { e.preventDefault(); showSlide(story.i - 1); }
  else if (k === "Home") { e.preventDefault(); showSlide(0); }
  else if (k === "End") { e.preventDefault(); showSlide(story.data.slides.length - 1); }
  else if (k.toLowerCase() === "f") { e.preventDefault(); $("#story-full").click(); }
  else if (k.toLowerCase() === "n") { e.preventDefault(); $("#story-notes").click(); }
  else if (k.toLowerCase() === "v" && !story.presenter) { e.preventDefault(); openPresenter(); }
  else if (k === "Escape" && !document.fullscreenElement) { e.preventDefault(); $("#story-exit").click(); }
  else return;
  storyIdle();
}, true);

// -------------------------------------------------------------- command palette
const PAGE_LIST = [["overview", "Home"], ["fed", "Fed now: rates and the Committee"], ["tracker", "Fed now: decisions"], ["documents", "Documents: search"],
  ["live", "Documents: score a text"], ["event-study", "Research: event study"], ["backtest", "Research: backtest"], ["forecast", "Research: next decision"], ["forward", "Research: forward test"], ["validity", "Research: validity"], ["label", "Research: team labels"],
  ["system", "System: data"], ["pipeline", "System: pipeline"], ["settings", "System: settings"]];
const pal = { items: [], sel: 0, timer: null };
function openPalette() { $("#palette").hidden = false; const q = $("#palette-q"); q.value = ""; renderPalette(""); setTimeout(() => q.focus(), 10); }
function closePalette() { $("#palette").hidden = true; }
async function renderPalette(q) {
  const box = $("#palette-results");
  const pages = PAGE_LIST.filter(([, n]) => !q || n.toLowerCase().includes(q.toLowerCase())).map(([k, n]) => ({ kind: "page", key: k, title: n }));
  let docs = [];
  if (q.trim().length >= 2) {
    try { docs = (await api("/api/documents?" + new URLSearchParams({ q, limit: 8 }))).items.map((d) => ({ kind: "doc", key: d.doc_id, d })); }
    catch { docs = []; }
  } else if (!q) {
    docs = (state.overview?.latest || []).slice(0, 5).map((d) => ({ kind: "doc", key: d.doc_id, d }));
  }
  pal.items = [...docs, ...pages]; pal.sel = 0;
  const docHtml = docs.length ? `<div class="grp">${q ? "Documents" : "Recent documents"}</div>` + docs.map((it, i) => `<div class="item" data-i="${i}">${typeBadge(it.d.doc_type)}
      <div><div class="t">${esc(it.d.title || ONE[it.d.doc_type])}</div><div class="s">${it.d.snippet || esc(it.d.speaker || "FOMC")}</div></div><div class="r">${fmt.date(it.d.release_date)}</div></div>`).join("") : (q.trim().length >= 2 ? `<div class="grp">No documents match</div>` : "");
  const pageHtml = pages.length ? `<div class="grp">Pages</div>` + pages.map((it, j) => `<div class="item" data-i="${docs.length + j}"><div class="t">${it.title}</div><div class="r">Go to page</div></div>`).join("") : "";
  box.innerHTML = docHtml + pageHtml;
  highlightPalette();
}
function highlightPalette() { $$("#palette-results .item").forEach((el) => el.classList.toggle("sel", Number(el.dataset.i) === pal.sel)); $(`#palette-results .item[data-i="${pal.sel}"]`)?.scrollIntoView({ block: "nearest" }); }
function choosePalette(i) {
  const it = pal.items[i]; if (!it) return;
  closePalette();
  if (it.kind === "page") location.hash = "#/" + it.key; else openDoc(it.key);
}
const GO = { h: "overview", o: "overview", f: "fed", d: "documents", t: "tracker", e: "event-study", b: "backtest", v: "validity", l: "label", s: "system", p: "pipeline" };
const keys = { g: 0 };
function openKeys() { const d = $("#keys"); if (!d.open) d.showModal(); }
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "") || document.activeElement?.isContentEditable;
  if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); openPalette(); return; }
  const free = !typing && !e.metaKey && !e.ctrlKey && !e.altKey && $("#palette").hidden && $("#drawer").hidden && !$("#keys").open && state.page !== "label";
  if (free && e.key === "?") { e.preventDefault(); openKeys(); return; }
  if (free && e.key.toLowerCase() === "t" && Date.now() - keys.g > 1200) { $("#theme-toggle").click(); return; }
  if (free && e.key === "[" && state.page !== "story") { toggleSidebar(); return; }
  if (free && e.key.toLowerCase() === "g") { keys.g = Date.now(); return; }
  if (free && Date.now() - keys.g < 1200 && GO[e.key.toLowerCase()]) { keys.g = 0; location.hash = "#/" + GO[e.key.toLowerCase()]; return; }
  if ($("#palette").hidden) return;
  if (e.key === "Escape") closePalette();
  else if (e.key === "ArrowDown") { e.preventDefault(); pal.sel = Math.min(pal.items.length - 1, pal.sel + 1); highlightPalette(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); pal.sel = Math.max(0, pal.sel - 1); highlightPalette(); }
  else if (e.key === "Enter") { e.preventDefault(); choosePalette(pal.sel); }
});
document.addEventListener("click", (e) => {
  if (e.target.closest("#keys-open")) openKeys();
  if (e.target.closest("[data-close-keys]") || e.target.id === "keys") $("#keys").close();
  if (e.target.closest("#copy-view")) navigator.clipboard?.writeText(location.href).then(() => toast("Link to this view copied"));
  if (e.target.closest("#open-palette")) openPalette();
  if (e.target.closest("[data-close-palette]")) closePalette();
  const it = e.target.closest("#palette-results .item"); if (it) choosePalette(Number(it.dataset.i));
});
document.addEventListener("input", (e) => {
  if (e.target.id !== "palette-q") return;
  clearTimeout(pal.timer); pal.timer = setTimeout(() => renderPalette(e.target.value), 160);
});

function renderStatusbar(ov) {
  const el = $("#data-through"); if (!el || !ov) return;
  el.textContent = ov.last_yield ? `Data through ${fmt.date(ov.last_yield.date)}` : "";
}

// ---------------------------------------------------------------------- shell
async function refreshPill() {
  try {
    const st = (state.settings = await api("/api/settings"));
    const pill = $("#api-pill");
    if (st.read_only) {
      pill.className = "pill ok"; pill.textContent = "Public demo";
    } else {
      pill.className = "pill " + (st.key_configured ? "ok" : "off");
      pill.textContent = st.key_configured ? "Claude connected" : "No API key";
    }
    $("#mode-label").textContent = st.read_only ? "read-only" : "local";
  } catch { /* server down */ }
}
function parseHash() {
  const raw = location.hash.replace(/^#\//, "");
  const [path, query] = raw.split("?");
  const params = new URLSearchParams(query || "");
  if (path.startsWith("doc/")) return { name: "documents", doc: decodeURIComponent(path.slice(4)) };
  return { name: pages[path] ? path : "overview", doc: params.get("doc"), member: params.get("member") };
}
let routeSeq = 0;  // the newest render owns the view; an older one that resumes after an await stays quiet
async function route({ force = false } = {}) {
  const { name, doc, member } = parseHash();
  const page = pages[name];
  const samePage = state.page === name && $("#view").dataset.page === name;
  state.page = name;
  document.documentElement.classList.toggle("presenting", name === "story");
  if (name !== "story") document.documentElement.classList.remove("export-visual", "export-slide");
  storyReturnPill(name);
  if (!doc && !member && !$("#drawer").hidden) { $("#drawer").hidden = true; state.doc = null; state.member = null; }
  if (force || !samePage || !doc) {
    const group = PAGE_GROUP[name] || "home"; const sec = NAV[group];
    $$("#nav a").forEach((a) => { const on = a.dataset.group === group; a.classList.toggle("active", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    clearCharts();
    $("#page-title").innerHTML = esc(sec.title) + " " + info(page.sub); $("#page-sub").textContent = "";
    const tabs = $("#page-tabs"); tabs.hidden = sec.pages.length < 2;
    tabs.innerHTML = sec.pages.map(([p, label]) => `<a href="#/${p}" class="${p === name ? "on" : ""}" ${p === name ? 'aria-current="page"' : ""}>${esc(label)}</a>`).join("");
    const onTab = tabs.querySelector("a.on"); if (onTab) tabs.scrollLeft = onTab.offsetLeft - (tabs.clientWidth - onTab.offsetWidth) / 2;
    $("#method-select")?.closest(".field")?.toggleAttribute("hidden", page.usesMethod === false);  // a page that shows no scores needs no reader
    // Each render owns its node. An older async renderer may finish after a
    // navigation, but its captured node is then detached and cannot replace the new page.
    const previousView = $("#view"), view = previousView.cloneNode(false);
    view.replaceChildren(...previousView.childNodes); previousView.replaceWith(view);
    tableWatch.disconnect(); tableWatch.observe(view, { childList: true, subtree: true });
    view.dataset.page = name; view.setAttribute("aria-busy", "true");
    const seq = ++routeSeq; const before = view.firstElementChild;
    // a skeleton only while nothing new is on screen: never over content the page has already drawn
    const slow = setTimeout(() => { if (seq === routeSeq && view.firstElementChild === before) view.innerHTML = SKELETON; }, 120);
    try { await page.render(view); if (seq === routeSeq) { tuck(view); enhance(view); sourceFooter(view,name); } }
    catch (e) { if (seq === routeSeq) view.innerHTML = `<div class="card">${empty("Could not load this page", esc(e.message) + '<br><button class="btn ghost small" data-retry style="margin-top:10px">Try again</button>')}</div>`; }
    finally { clearTimeout(slow); if (seq === routeSeq) view.removeAttribute("aria-busy"); }
    if (seq !== routeSeq) return;
    document.title = `${page.title} \u00b7 FOMC Tone Lab`;
  }
  if (doc && doc !== state.doc) openDoc(doc, { updateUrl: !location.hash.includes("?doc=") });
  else if (!doc && member && member !== state.member) openMember(member, { updateUrl: false });
}
function storyReturnPill(name) {
  let n = null; try { n = sessionStorage.getItem("fomc.storyReturn"); } catch { /* private mode */ }
  let pill = $("#story-return");
  if (!n || name === "story") { pill?.remove(); if (name === "story") try { sessionStorage.removeItem("fomc.storyReturn"); } catch { /* */ } return; }
  if (!pill) {
    pill = document.createElement("div"); pill.id = "story-return"; pill.className = "story-return";
    document.body.append(pill);
  }
  const [slide, deck] = n.split("|");
  pill.innerHTML = `<a href="#/story?${deck ? "deck=technical&" : ""}s=${esc(slide)}"><svg class="ic" aria-hidden="true"><use href="#i-arrow-left"/></svg>Back to the ${deck ? "technical appendix" : "story"}, slide ${esc(slide)}</a><button aria-label="Dismiss" data-dismiss-return><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg></button>`;
  pill.querySelector("[data-dismiss-return]").onclick = () => { try { sessionStorage.removeItem("fomc.storyReturn"); } catch { /* */ } pill.remove(); };
}
const SKELETON = `<div class="kpis">${'<div class="card skeleton sk-kpi"></div>'.repeat(4)}</div><div class="card skeleton sk-chart"></div>`;
document.addEventListener("click", (e) => { if (e.target.closest("[data-retry]")) { cache.clear(); route({ force: true }); } });

// ------------------------------------------------------------- enhancements
// Every table: sortable headers (aria-sort) and a CSV download; segmented controls report aria-pressed.
function cellValue(td) {
  const exact = td?.getAttribute("data-sort-value");
  if (exact !== null && exact !== undefined && Number.isFinite(Number(exact))) return Number(exact);
  const t = (td?.innerText || "").trim();
  const num = t.replace(/[,%\s]|bp|d$/g, "").replace(/[\u2212\u2013]/g, "-");
  if (/^[+-]?\d+(\.\d+)?$/.test(num)) return Number(num);
  const d = Date.parse(t.split("\n")[0]);
  return Number.isNaN(d) || !/\d{4}/.test(t) ? t.toLowerCase() : d;
}
function tableCsv(table) {
  const rows = [...table.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => `"${c.innerText.replace(/\s+/g, " ").trim().replace(/"/g, '""')}"`).join(","));
  return rows.join("\n");
}
function enhance(root) {
  root.querySelectorAll(".table-wrap").forEach((wrap) => {
    const table = wrap.querySelector("table"); if (!table || wrap.dataset.enhanced) return;
    wrap.dataset.enhanced = "1";
    const card = wrap.closest(".card");
    const titleNode = wrap.closest("[data-stat-view]")?.querySelector("h3") || card?.querySelector("h2");
    const title = (titleNode?.childNodes[0]?.textContent || state.page).trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const bar = document.createElement("div"); bar.className = "table-tools";
    const total = wrap.dataset.total;
    bar.innerHTML = `<span>${total ? fmt.int(Number(total)) + " documents" : fmt.int(table.tBodies[0]?.rows.length || 0) + " rows"}</span><button class="btn ghost small" type="button" title="${total ? "Download this page as CSV" : "Download as CSV"}"><svg class="ic" aria-hidden="true"><use href="#i-download"/></svg>CSV</button>`;
    bar.querySelector("button").onclick = () => {
      const blob = new Blob([tableCsv(table)], { type: "text/csv" });
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${title || "table"}.csv` });
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
    if (table.tHead) wrap.before(bar);
    if (wrap.hasAttribute("data-nosort") || !table.tHead) return;
    [...table.tHead.rows[0].cells].forEach((th, i) => {
      th.tabIndex = 0; th.classList.add("sortable"); th.setAttribute("aria-sort", "none");
      const sort = () => {
        const dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
        [...table.tHead.rows[0].cells].forEach((x) => x.setAttribute("aria-sort", "none"));
        th.setAttribute("aria-sort", dir);
        const body = table.tBodies[0];
        const rows = [...body.rows].sort((a, b) => {
          const x = cellValue(a.cells[i]); const y = cellValue(b.cells[i]);
          const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
          return dir === "ascending" ? c : -c;
        });
        body.append(...rows);
      };
      th.onclick = sort; th.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } };
    });
  });
  root.querySelectorAll(".seg").forEach((seg) => seg.setAttribute("role", "group"));
  root.querySelectorAll(".seg button, .chip").forEach((b) => b.setAttribute("aria-pressed", b.classList.contains("on")));
}
// tables rendered later (paging, filters) are enhanced as they appear; route() points this at each new view node
const tableWatch = new MutationObserver((list) => { if (list.some((m) => m.addedNodes.length)) enhance($("#view")); });
tableWatch.observe(document.getElementById("view"), { childList: true, subtree: true });
document.addEventListener("click", (e) => { if (e.target.closest(".seg button, .chip")) setTimeout(() => enhance($("#view")), 0); });

// ------------------------------------------------------------------ sidebar: drag its edge to resize, collapse it to an icon rail
const SIDEBAR = { min: 200, max: 360, base: 252, rail: 140 }; // dragged narrower than `rail`, it collapses
const sidebarCollapsed = () => document.documentElement.classList.contains("sidebar-collapsed");
function setSidebar({ width, collapsed } = {}) {
  const root = document.documentElement;
  if (width !== undefined) {
    root.style.setProperty("--sidebar-w", `${width}px`); local.set("sidebarW", width);
    $("#sidebar-resizer").setAttribute("aria-valuenow", width);
  }
  if (collapsed !== undefined) {
    root.classList.toggle("sidebar-collapsed", collapsed); local.set("sidebarCollapsed", collapsed);
    const t = $("#sidebar-toggle"); const label = collapsed ? "Expand the sidebar" : "Collapse the sidebar";
    t.setAttribute("aria-expanded", String(!collapsed)); t.setAttribute("aria-label", label); t.title = `${label} ([)`;
    t.querySelector("use").setAttribute("href", collapsed ? "#i-panel-left-open" : "#i-panel-left-close");
    // an icon rail names its items on hover
    $$("#nav a").forEach((a) => { if (collapsed) a.title = a.textContent.trim(); else a.removeAttribute("title"); });
    const search = $("#open-palette"); if (collapsed) search.title = search.getAttribute("aria-label"); else search.removeAttribute("title");
  }
  window.dispatchEvent(new Event("resize")); // charts follow the new width
}
function toggleSidebar() { setSidebar({ collapsed: !sidebarCollapsed() }); }
function initSidebar() {
  const saved = Number(local.get("sidebarW", SIDEBAR.base)) || SIDEBAR.base;
  setSidebar({ width: Math.max(SIDEBAR.min, Math.min(SIDEBAR.max, saved)), collapsed: !!local.get("sidebarCollapsed", false) });
  $("#sidebar-toggle").onclick = toggleSidebar;
  const bar = $("#sidebar-resizer");
  bar.addEventListener("pointerdown", (e) => {
    e.preventDefault(); bar.setPointerCapture(e.pointerId); document.documentElement.classList.add("resizing");
    const drag = new AbortController(); let frame = 0, width = null;
    bar.addEventListener("pointermove", (ev) => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => {
      if (ev.clientX < SIDEBAR.rail) { width = null; if (!sidebarCollapsed()) setSidebar({ collapsed: true }); return; }
      width = Math.round(Math.max(SIDEBAR.min, Math.min(SIDEBAR.max, ev.clientX)));
      if (sidebarCollapsed()) setSidebar({ collapsed: false });
      document.documentElement.style.setProperty("--sidebar-w", `${width}px`); // charts resize once, on release
    }); }, { signal: drag.signal });
    const end = () => { drag.abort(); cancelAnimationFrame(frame); document.documentElement.classList.remove("resizing"); if (width !== null) setSidebar({ width }); };
    bar.addEventListener("pointerup", end, { signal: drag.signal }); bar.addEventListener("pointercancel", end, { signal: drag.signal });
  });
  bar.addEventListener("dblclick", () => setSidebar({ width: SIDEBAR.base, collapsed: false }));
  bar.addEventListener("keydown", (e) => { // the WAI-ARIA window splitter: arrows resize, Enter collapses or expands
    const step = e.shiftKey ? 48 : 16; const w = Number(local.get("sidebarW", SIDEBAR.base)) || SIDEBAR.base;
    if (e.key === "Enter") toggleSidebar();
    else if (e.key === "ArrowLeft" && !sidebarCollapsed()) setSidebar(w - step < SIDEBAR.min ? { collapsed: true } : { width: w - step });
    else if (e.key === "ArrowRight") setSidebar(sidebarCollapsed() ? { collapsed: false } : { width: Math.min(SIDEBAR.max, w + step) });
    else return;
    e.preventDefault();
  });
}

async function init() {
  initSidebar();
  const toggle = $("#theme-toggle");
  const syncTheme = () => toggle.querySelectorAll("button").forEach((b) => {
    const active = b.dataset.themeChoice === document.documentElement.dataset.theme;
    b.classList.toggle("on", active); b.setAttribute("aria-pressed", String(active));
  });
  toggle.onclick = (e) => {
    const choice = e.target.closest("[data-theme-choice]");
    if (!choice && e.detail) return;  // a pointer click between the buttons; the T key sends a synthetic click (detail 0)
    const next = choice?.dataset.themeChoice || (document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    document.documentElement.dataset.theme = next; local.set("theme", next); syncTheme(); route({ force: true });
  };
  if (!document.documentElement.dataset.theme) {
    document.documentElement.dataset.theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  syncTheme();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (["light", "dark"].includes(local.get("theme", null)) || new URLSearchParams(location.search).has("theme")) return;
    document.documentElement.dataset.theme = e.matches ? "dark" : "light"; syncTheme(); route({ force: true });
  });
  window.addEventListener("hashchange", () => route());
  route();  // render right away; the shell data below loads in parallel
  try {
    const ov = (state.overview = await api("/api/overview"));
    $("#version").textContent = ov.version;
    const sel = $("#method-select");
    const methods = ov.methods.map((m) => m.method);
    if (!methods.includes(state.method)) state.method = ov.default_method;
    sel.innerHTML = methods.map((m) => `<option value="${esc(m)}" ${m === state.method ? "selected" : ""}>${esc(methodLabel(m))}</option>`).join("") || "<option>no scores yet</option>";
    sel.setAttribute("aria-label", "Scoring method");
    sel.onchange = () => { state.method = sel.value; local.set("method", state.method); cache.clear(); route({ force: true }); };
    renderStatusbar(ov);
  } catch (e) { toast("API not reachable: " + e.message); }
  await refreshPill();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
