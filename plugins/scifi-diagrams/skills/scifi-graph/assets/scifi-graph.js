/* scifi-graph 1.0.1 — a plan drawn as an RPG skill tree (schema scifi-graph/1). MIT, no dependencies.
 *
 *   SciFiGraph.render(hostElement, graph)   draws the map, the HUD, the readout and the table view
 *   SciFiGraph.prepare(graph)                the pure half (states, roll-ups, layout), usable from Node
 *
 * Containment (`parent`) nests task -> epic -> goal; an edge runs prerequisite -> dependent. Every container is
 * laid out once, as a layered DAG inside its own region, and zoom decides how deep the map is drawn: a region shows
 * its summary until it is big enough on screen for its children to be read, and then it opens.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api; else root.SciFiGraph = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const VERSION = "1.0.1";
  const SLOTS = 6;                                  // topic hues, fixed order; the 7th topic and later are "other"
  const ORDER = { unlocked: 0, active: 1, available: 2, locked: 3 };
  const WORD = { unlocked: "UNLOCKED", active: "ACTIVE", available: "AVAILABLE", locked: "LOCKED" };
  const ICON = { unlocked: "✓", active: "▶", available: "◇", locked: "⊘" };

  // World units. A task card's text is FS units high; CW is the mono advance, so wrapping by characters is exact.
  const LEAF_W = 210, LEAF_H = 66, FS = 12, CW = 0.6, GAP_X = 64, GAP_Y = 16, PAD = 26, HEAD = 60;
  const STAR_W = 280, BAND_GAP = 90, LEGIBLE_PX = 8;

  // ---- the pure half -------------------------------------------------------------------------------------------
  const num = v => (typeof v === "number" && isFinite(v) && v >= 0 ? v : null);   // a bad number is N/D, never 0
  const str = v => (typeof v === "string" ? v : v == null ? "" : String(v));
  const strList = v => (Array.isArray(v) ? v.filter(x => typeof x === "string") : []);
  const MAX_DEPTH = 32;

  function parseGain(text) {
    const m = /^\s*\+(\d+(?:\.\d+)?)\s*/.exec(text);
    return m ? { weight: Number(m[1]), text: text.slice(m[0].length) } : { weight: 1, text: text.replace(/^\s*\+\s*/, "") };
  }

  function wrap(text, maxChars, maxLines) {
    const words = String(text || "").split(/\s+/).filter(Boolean), lines = [];
    let cur = "";
    for (const w0 of words) {
      let w = w0;
      while (w.length > maxChars) {                  // a word longer than the line is cut, not overflowed
        if (cur) { lines.push(cur); cur = ""; }
        lines.push(w.slice(0, maxChars)); w = w.slice(maxChars);
      }
      if (!cur) cur = w; else if (cur.length + 1 + w.length <= maxChars) cur += " " + w; else { lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    if (lines.length > maxLines) {
      const keep = lines.slice(0, maxLines);
      const last = keep[maxLines - 1];
      keep[maxLines - 1] = (last.length >= maxChars ? last.slice(0, maxChars - 1) : last) + "…";
      return keep;
    }
    return lines.length ? lines : [""];
  }

  function prepare(graph) {
    // Whatever arrives, nothing below throws: anything malformed is dropped or shown as N/D (check reports it).
    const g = graph && typeof graph === "object" ? graph : {};
    const list = v => (Array.isArray(v) ? v.filter(x => x && typeof x === "object") : []);
    const topics = list(g.topics).filter(t => typeof t.id === "string");
    const topicIds = topics.map(t => t.id);
    const topicLabel = new Map(topics.map(t => [t.id, str(t.label) || t.id]));
    const nodes = new Map();
    for (const raw of list(g.nodes)) {
      if (raw.id == null || typeof raw.id === "object" || nodes.has(String(raw.id))) continue;
      const cost = raw.cost && typeof raw.cost === "object" ? raw.cost : null;
      nodes.set(String(raw.id), Object.assign({}, raw, {
        id: String(raw.id), kind: ["goal", "epic", "task"].includes(raw.kind) ? raw.kind : "task",
        state: ["done", "active", "open"].includes(raw.state) ? raw.state : "open", title: str(raw.title), label: str(raw.label), status: str(raw.status), url: str(raw.url),
        topic: typeof raw.topic === "string" ? raw.topic : "", parent: typeof raw.parent === "string" ? raw.parent : null,
        closed: str(raw.closed), cost, gains: strList(raw.gains), decides: strList(raw.decides),
        kids: [], pre: [], post: [], up: null }));
    }
    // A node on a parent loop, or hanging off one, keeps no parent. One memoised walk per chain: linear in nodes.
    const onLoop = new Map();
    for (const n of nodes.values()) {
      const path = [], at = new Set();
      let a = n;
      while (a && !onLoop.has(a) && !at.has(a)) { path.push(a); at.add(a); a = a.parent != null ? nodes.get(a.parent) : null; }
      const bad = a ? (at.has(a) ? true : onLoop.get(a)) : false;
      for (const x of path) onLoop.set(x, bad);
    }
    for (const n of nodes.values()) {
      const p = n.parent != null ? nodes.get(n.parent) : null;
      if (p && !onLoop.get(n)) { n.up = p; p.kids.push(n); }
    }
    // the layout recurses once per level: past MAX_DEPTH a subtree is drawn as its own top region instead
    const depth = new Map();
    const depthOf = n => {                            // iterative, memoised: a 20,000-deep chain is linear
      const path = [];
      let a = n;
      while (a && !depth.has(a)) { path.push(a); a = a.up; }
      let d = a ? depth.get(a) : -1;
      for (let i = path.length - 1; i >= 0; i--) depth.set(path[i], ++d);
      return depth.get(n);
    };
    const cut = [...nodes.values()].filter(n => { const d = depthOf(n); return d > 0 && d % (MAX_DEPTH + 1) === 0; });
    for (const n of cut) { const p = n.up; p.kids.splice(p.kids.indexOf(n), 1); n.up = null; }
    const edges = [];
    for (const e of list(g.edges)) {
      if (typeof e.from === "object" || typeof e.to === "object") continue;
      const a = nodes.get(String(e.from)), b = nodes.get(String(e.to));
      if (!a || !b || a === b) continue;
      edges.push({ from: a, to: b, kind: e.kind || "needs" });
      b.pre.push(a); a.post.push(b);
    }
    const tops = [...nodes.values()].filter(n => !n.up);
    // topic: own, else inherited; slot by the topics list, else in order of first appearance
    const slotOf = new Map();
    topicIds.forEach(t => { if (slotOf.size < SLOTS) slotOf.set(t, slotOf.size + 1); });
    const visit = (n, inherited) => {
      n.topic = n.topic || inherited || "";
      if (n.topic && !slotOf.has(n.topic) && slotOf.size < SLOTS && !topicIds.length) slotOf.set(n.topic, slotOf.size + 1);
      n.kids.forEach(k => visit(k, n.topic));
    };
    tops.forEach(n => visit(n, ""));
    for (const n of nodes.values()) {
      n.slot = slotOf.get(n.topic) || 0;             // 0 = other
      n.topicLabel = topicLabel.get(n.topic) || n.topic || "other";
    }
    // tree state: done -> unlocked; active stays; open -> available when every prerequisite is done, else locked
    // a container is done only when it says so AND nothing inside it is open: an Accepted ADR with open work is not
    // yet unlocked
    const openInside = n => n.kids.some(k => k.state !== "done" || openInside(k));
    const doneMap = new Map([...nodes.values()].map(n => [n, n.state === "done" && !openInside(n)]));
    const done = n => doneMap.get(n);
    for (const n of nodes.values()) {
      n.tree = done(n) ? "unlocked" : n.state === "active" ? "active" : n.pre.every(done) ? "available" : "locked";
    }
    // roll-ups: spent (actual), to go (estimate) with range, N/D counts, progress over leaves; points from gains
    const roll = n => {
      n.kids.forEach(roll);
      const own = num(n.cost && n.cost.actual);
      const r = { spent: own || 0, spentKnown: own != null, spentNd: 0, togo: 0, low: 0, high: 0, togoNd: 0,
                  leaves: 0, doneLeaves: 0 };
      if (!n.kids.length && n.kind === "goal") { /* a goal with no work yet: point B alone, no task to count */ }
      else if (!n.kids.length) {
        r.leaves = 1; r.doneLeaves = done(n) ? 1 : 0;
        if (done(n)) { if (own == null) r.spentNd = 1; }
        else {
          const e = num(n.cost && n.cost.estimate);
          if (e == null) r.togoNd = 1;
          else { r.togo = e; r.low = num(n.cost.low) != null ? n.cost.low : e; r.high = num(n.cost.high) != null ? n.cost.high : e; }
        }
      }
      for (const k of n.kids) {
        const q = k.roll;
        r.spent += q.spent; r.spentKnown = r.spentKnown || q.spentKnown; r.spentNd += q.spentNd;
        r.togo += q.togo; r.low += q.low; r.high += q.high; r.togoNd += q.togoNd;
        r.leaves += q.leaves; r.doneLeaves += q.doneLeaves;
      }
      n.roll = r;
      n.gainList = n.gains.map(parseGain);
      n.points = n.gainList.reduce((a, x) => a + x.weight, 0);
    };
    tops.forEach(roll);
    const goals = [...nodes.values()].filter(n => n.kind === "goal");
    const totals = {
      points: goals.reduce((a, n) => a + n.points, 0),
      pointsUnlocked: goals.filter(n => n.tree === "unlocked").reduce((a, n) => a + n.points, 0),
      spent: tops.reduce((a, n) => a + n.roll.spent, 0), spentKnown: tops.some(n => n.roll.spentKnown),
      togo: tops.reduce((a, n) => a + n.roll.togo, 0), low: tops.reduce((a, n) => a + n.roll.low, 0),
      high: tops.reduce((a, n) => a + n.roll.high, 0), togoNd: tops.reduce((a, n) => a + n.roll.togoNd, 0),
      leaves: tops.reduce((a, n) => a + n.roll.leaves, 0), doneLeaves: tops.reduce((a, n) => a + n.roll.doneLeaves, 0),
      goals: goals.length, goalsUnlocked: goals.filter(n => n.tree === "unlocked").length,
    };
    const model = { graph: g, nodes, edges, tops, totals, slotOf, bands: [] };
    layout(model);
    return model;
  }

  // ---- layout: nested layered DAGs -----------------------------------------------------------------------------
  function ownerIn(set, n) { while (n && !set.has(n)) n = n.up; return n; }

  // Rank `items` by dependency (longest path from a source) and order each rank: the past first (unlocked, by close
  // date), then active, available, locked; then by the barycentre of their prerequisites.
  function ranking(model, items) {
    const set = new Set(items), preds = new Map(items.map(i => [i, new Set()]));
    for (const e of model.edges) {
      const a = ownerIn(set, e.from), b = ownerIn(set, e.to);
      if (a && b && a !== b) preds.get(b).add(a);
    }
    const rank = new Map(), busy = new Set();
    const rk = i => {
      if (rank.has(i)) return rank.get(i);
      if (busy.has(i)) return 0;                     // a cycle (check rejects it): break it here
      busy.add(i);
      let r = 0; for (const p of preds.get(i)) r = Math.max(r, rk(p) + 1);
      busy.delete(i); rank.set(i, r); return r;
    };
    items.forEach(rk);
    const byRank = [];
    for (const i of items) (byRank[rank.get(i)] = byRank[rank.get(i)] || []).push(i);
    const pos = new Map();
    for (const group of byRank) {
      if (!group) continue;
      const bc = i => { const ps = [...preds.get(i)].map(p => pos.get(p)).filter(v => v != null); return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : 1e9; };
      group.sort((a, b) => ORDER[a.tree] - ORDER[b.tree] || bc(a) - bc(b)
        || String(a.closed || "").localeCompare(String(b.closed || "")) || a.id.localeCompare(b.id, undefined, { numeric: true }));
      group.forEach((i, k) => pos.set(i, k));
    }
    return byRank.map(g => g || []);
  }

  // A rank too tall for the region wraps into sub-columns, so a pile of independent tasks reads as a grid.
  const chunks = (group, cap) => { const out = []; for (let k = 0; k < group.length; k += cap) out.push(group.slice(k, k + cap)); return out; };
  const stackH = c => c.reduce((a, i) => a + i.h, 0) + GAP_Y * (c.length - 1);

  // Lay `items` (already measured) out left to right by rank. Sets item.rx/ry; returns the box size.
  function layered(model, items) {
    const cap = Math.max(3, Math.ceil(Math.sqrt(items.length * 1.4)));
    const cols = [].concat(...ranking(model, items).map(g => chunks(g, cap)));
    const colH = cols.map(stackH), H = Math.max(0, ...colH);
    let x = 0;
    cols.forEach((c, ci) => {
      const w = Math.max(...c.map(i => i.w));
      let y = (H - colH[ci]) / 2;
      for (const i of c) { i.rx = x + (w - i.w) / 2; i.ry = y; y += i.h + GAP_Y; }
      x += w + GAP_X;
    });
    return { w: Math.max(0, x - GAP_X), h: H };
  }

  function starBox(n) {
    const lines = Math.max(1, (n.gainList.length || (n.decides || []).length || 1));
    return { w: STAR_W, h: 128 + Math.min(lines, 8) * 2 * (FS + 4) };
  }

  function measure(model, n) {
    if (n.kind === "goal") n.star = starBox(n);
    if (!n.kids.length && n.kind !== "goal") { n.w = LEAF_W; n.h = LEAF_H; return; }
    n.kids.forEach(k => measure(model, k));
    const box = n.kids.length ? layered(model, n.kids) : { w: 0, h: 0 };
    const starW = n.star ? n.star.w + (box.w ? PAD : 0) : 0, starH = n.star ? n.star.h : 0;
    let w = box.w + starW + 2 * PAD, h = Math.max(box.h, starH) + HEAD + PAD;
    // the summary a closed region shows: text scaled to the region, never past what fits. A region too small for its
    // summary at the kind's floor grows to fit it, so a goal with little work still reads beside a big one.
    const lines = n.kind === "goal" ? 7 + Math.min(3, n.gainList.length || (n.decides || []).length) : 6;
    const floor = n.kind === "goal" ? 26 : 14;
    w = Math.max(w, floor * 24, LEAF_W + 2 * PAD); h = Math.max(h, floor * (lines * 1.45 + 1.2));
    n.w = w; n.h = h;
    n.sumFs = Math.max(FS, Math.min(w / 24, h / (lines * 1.45 + 1.2)));
    // children centred in what the star leaves; point B centred on the right edge
    n.innerX = PAD + (w - 2 * PAD - starW - box.w) / 2;
    n.innerY = HEAD + (h - HEAD - PAD - box.h) / 2;
    if (n.star) { n.star.rx = w - PAD - n.star.w; n.star.ry = HEAD + (h - HEAD - PAD - starH) / 2; }
  }

  function place(n, x, y) {
    n.x = x; n.y = y;
    for (const k of n.kids) place(k, x + n.innerX + k.rx, y + n.innerY + k.ry);
    if (n.star) { n.star.x = x + n.star.rx; n.star.y = y + n.star.ry; }
  }

  // The map: one band per topic (a branch of the tree), stacked; each band is a layered DAG of its top nodes.
  function layout(model) {
    model.tops.forEach(n => measure(model, n));
    for (const n of model.nodes.values()) {
      if (!n.kids.length) { n.openS = Infinity; continue; }
      const fs = n.kids.map(k => (k.kids.length || k.kind === "goal" ? k.sumFs : FS)).sort((a, b) => a - b);
      n.openS = LEGIBLE_PX / fs[Math.floor(fs.length / 2)];   // the scale at which the median child reads
    }
    const bandOf = n => n.slot || 0;
    const ids = [...new Set(model.tops.map(bandOf))].sort((a, b) => (a || 99) - (b || 99));
    const byRank = ranking(model, model.tops);          // one rank axis for every band
    const TOP_GAP = GAP_X * 2, cap = 3;
    const cells = ids.map(slot => byRank.map(g => chunks(g.filter(n => bandOf(n) === slot), cap)));
    const cellW = cs => cs.reduce((a, c) => a + Math.max(...c.map(i => i.w)), 0) + TOP_GAP * Math.max(0, cs.length - 1);
    const rankW = byRank.map((_, r) => Math.max(0, ...cells.map(b => cellW(b[r]))));
    const rankX = []; rankW.reduce((x, w, r) => (rankX[r] = x, x + w + (w ? TOP_GAP : 0)), 0);
    let y = 0, W = 0;
    model.bands = ids.map((slot, bi) => {
      const items = model.tops.filter(n => bandOf(n) === slot);
      const h = Math.max(0, ...cells[bi].map(cs => Math.max(0, ...cs.map(stackH))));
      let right = 0;
      cells[bi].forEach((cs, r) => {
        let x = rankX[r];
        for (const c of cs) {
          const w = Math.max(...c.map(i => i.w));
          let yy = y + (h - stackH(c)) / 2;
          for (const n of c) { place(n, x + (w - n.w) / 2, yy); yy += n.h + GAP_Y; right = Math.max(right, x + w); }
          x += w + TOP_GAP;
        }
      });
      const band = { slot, label: items[0].topicLabel, y, h, w: right, items };
      y += h + BAND_GAP; W = Math.max(W, right);
      return band;
    });
    model.bands.forEach(b => { b.w = W; });
    model.world = { x: -PAD * 4, y: -PAD * 3, w: W + PAD * 8, h: Math.max(LEAF_H, y - BAND_GAP) + PAD * 6 };
  }

  // ---- formatting ----------------------------------------------------------------------------------------------
  const SYM = { USD: "$", EUR: "€", GBP: "£", RUB: "₽" };
  function moneyFmt(cur) {
    const s = SYM[cur || "USD"] || `${cur} `;
    return v => s + (v >= 100 ? Math.round(v).toLocaleString("en-US") : v >= 10 ? v.toFixed(1) : v.toFixed(2));
  }
  function costLine(n, money) {
    const r = n.roll, parts = [];
    if (r.spentKnown) parts.push(`${money(r.spent)} spent`); else if (r.doneLeaves) parts.push("spent N/D");
    if (r.leaves > r.doneLeaves) {
      if (r.togo > 0 || r.togoNd === 0) {
        const range = r.high > r.low ? ` (${money(r.low)}–${money(r.high)})` : "";
        parts.push(`≈${money(r.togo)} to go${range}`);
      }
      if (r.togoNd) parts.push(r.togo > 0 ? `+${r.togoNd} N/D` : "to go N/D");
    }
    return parts.join(" · ");
  }
  const leafCost = (n, money) => {
    if (n.state === "done") return num(n.cost && n.cost.actual) != null ? money(n.cost.actual) : "N/D";
    const e = num(n.cost && n.cost.estimate);
    if (e == null) return "≈ N/D";
    const lo = num(n.cost.low), hi = num(n.cost.high);
    return `≈${money(e)}` + (lo != null && hi != null && hi > lo ? ` (${money(lo)}–${money(hi)})` : "");
  };
  const pctOf = n => (n.roll.leaves ? Math.round((100 * n.roll.doneLeaves) / n.roll.leaves) : n.tree === "unlocked" ? 100 : 0);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // http(s), or a same-origin path; `//host` and `javascript:` are dropped (the same rule as page.SAFE_URL)
  const safeUrl = u => (/^(https?:\/\/|\/(?!\/)|\.\.?\/|#)/i.test(String(u || "")) ? String(u) : "");

  // ---- the browser half ----------------------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(parent, x, y, str, cls, fs, extra) {
    const t = el("text", Object.assign({ x: x.toFixed(1), y: y.toFixed(1), class: cls, "font-size": fs.toFixed(2) }, extra || {}), parent);
    t.textContent = str; return t;
  }
  const hue = n => `var(--t${n.slot || "-other"})`;

  function render(host, graph) {
    const m = prepare(graph), money = moneyFmt(graph.currency);
    const T = m.totals;
    host.classList.add("sg");
    host.innerHTML = `
      <div class="sg-hud">
        <span class="sg-title">${esc(graph.title || "SKILL TREE")}</span>
        <span class="sg-stat"><b>${T.pointsUnlocked}</b>/<b>${T.points}</b> PTS</span>
        <span class="sg-stat"><b>${T.goalsUnlocked}</b>/<b>${T.goals}</b> GOALS</span>
        <span class="sg-stat"><b>${T.doneLeaves}</b>/<b>${T.leaves}</b> NODES</span>
        <span class="sg-stat">${T.spentKnown ? `<b>${money(T.spent)}</b> SPENT` : "SPENT N/D"}</span>
        <span class="sg-stat">${T.leaves > T.doneLeaves ? `≈<b>${money(T.togo)}</b> TO GO${T.high > T.low ? ` (${money(T.low)}–${money(T.high)})` : ""}${T.togoNd ? ` · ${T.togoNd} N/D` : ""}` : "NOTHING TO GO"}</span>
        <span class="sg-chips"></span>
        <button class="sd-btn sg-reset" type="button" title="Fit the whole map (0)">FIT</button>
      </div>
      <div class="sg-notes">${(graph.notes || []).map(s => `<div>${esc(s)}</div>`).join("")}${graph.generated ? `<div>generated ${esc(graph.generated)}</div>` : ""}</div>
      <div class="sg-main">
        <div class="sg-map" tabindex="0" aria-label="Skill tree map. Drag to pan, wheel or pinch to zoom, Enter on a node to fly in, Escape to go out.">
          <div class="sg-level"></div><div class="sg-tip" role="tooltip"></div>
          <div class="sg-legend">${["unlocked", "active", "available", "locked"].map(s => `<span class="st-${s}"><i>${ICON[s]}</i>${WORD[s]}</span>`).join("")}<span class="sg-lg-edge">─ prerequisite done</span><span class="sg-lg-edge dim">┄ prerequisite open</span></div>
        </div>
        <div class="sg-readout" role="complementary" aria-label="Readout"><div class="sg-readout-head">READOUT</div><div class="sg-readout-body"></div></div>
      </div>
      <details class="sd-table"><summary>TABLE VIEW · ${m.nodes.size} nodes</summary><div class="sg-table-body"></div></details>`;
    const $ = s => host.querySelector(s);
    const mapBox = $(".sg-map");
    const svg = el("svg", { class: "sg-svg", role: "group", "aria-label": `${graph.title || "Skill tree"}: ${T.goals} goals` }, mapBox);
    const defs = el("defs", {}, svg);
    const glow = el("filter", { id: "sg-glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
    el("feGaussianBlur", { stdDeviation: "3", result: "b" }, glow);
    const mg = el("feMerge", {}, glow); el("feMergeNode", { in: "b" }, mg); el("feMergeNode", { in: "SourceGraphic" }, mg);
    for (const [id, cls] of [["sg-ah", "sg-ah"], ["sg-ah-dim", "sg-ah dim"]]) {
      const mk = el("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0,0 L10,5 L0,10 z", class: cls }, mk);
    }
    const world = el("g", {}, svg);
    const bandLayer = el("g", { class: "sg-bands" }, world);
    const edgeLayer = el("g", { class: "sg-edges" }, world);
    const tree = el("g", {}, world);

    for (const b of m.bands) {
      const g = el("g", { class: "sg-band", "data-slot": b.slot }, bandLayer);
      el("rect", { x: -PAD * 2, y: b.y - PAD, width: b.w + PAD * 4, height: b.h + PAD * 2, class: "sg-band-bg", fill: `var(--t${b.slot || "-other"})` }, g);
      text(g, -PAD * 2, b.y - PAD - 12, `▸ ${b.label.toUpperCase()}`, "sg-band-label", 26);
    }

    const conts = [];
    const drawNode = (n, parent) => {
      const g = el("g", { class: `sg-node st-${n.tree} k-${n.kind || "task"}${n.kids.length ? " sg-cont" : " sg-leaf"}`, "data-id": n.id, tabindex: 0, role: "button",
                          "aria-label": `${n.kind || "task"} ${n.title || n.id}: ${WORD[n.tree]}` }, parent);
      n.el = g;
      if (!n.kids.length && n.kind !== "goal") { drawLeaf(n, g); return; }
      conts.push(n);
      el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 6, class: "sg-frame", stroke: hue(n) }, g);
      drawSummary(n, el("g", { class: "sg-sum" }, g));
      const open = el("g", { class: "sg-open" }, g);
      drawHeader(n, open);
      if (n.star) drawStar(n, open);
      // flow into the region's exit: children that unlock nothing inside it feed point B (goal) or the right edge
      const inside = new Set(n.kids);
      const feeds = n.kids.filter(k => !m.edges.some(e => ownerIn(inside, e.from) === k && ownerIn(inside, e.to) && ownerIn(inside, e.to) !== k));
      const ex = n.star ? n.star.x : n.x + n.w, ey = n.star ? n.star.y + n.star.h / 2 : n.y + n.h / 2;
      for (const k of feeds) {
        el("path", { d: curve(k.x + k.w, k.y + k.h / 2, ex, ey), class: `sg-flow${k.tree === "unlocked" ? " is-lit" : ""}` }, open);
      }
      n.kids.forEach(k => drawNode(k, open));
    };

    function drawLeaf(n, g) {
      el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 4, class: "sg-card" }, g);
      el("rect", { x: n.x, y: n.y, width: 5, height: n.h, class: "sg-stripe", fill: hue(n) }, g);
      const x = n.x + 12, chars = Math.floor((n.w - 20) / (FS * CW));
      text(g, x, n.y + 16, `${ICON[n.tree]} ${n.label || shortId(n.id)}`, "sg-l1", FS);
      text(g, n.x + n.w - 8, n.y + 16, WORD[n.tree], "sg-word", FS * 0.8, { "text-anchor": "end" });
      wrap(n.title, chars, 2).forEach((s, i) => text(g, x, n.y + 33 + i * (FS + 2), s, "sg-l2", FS));
      text(g, x, n.y + n.h - 7, leafCost(n, money), "sg-l3", FS * 0.9);
    }

    function drawSummary(n, g) {
      const fs = n.sumFs, x = n.x + fs * 1.1, chars = Math.max(8, Math.floor((n.w - fs * 2.2) / (fs * CW)));
      let y = n.y + fs * 1.6;
      const line = (s, cls, k) => { text(g, x, y, s, cls, fs * (k || 1)); y += fs * (k || 1) * 1.45; };
      el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 6, class: "sg-sum-bg" }, g);
      line(`${ICON[n.tree]} ${(n.kind || "node").toUpperCase()} ${n.label || shortId(n.id)} · ${WORD[n.tree]}`, "sg-s-head", 0.8);
      wrap(n.title, chars, 2).forEach(s => line(s, "sg-s-title"));
      const p = pctOf(n), bw = n.w - fs * 2.2;
      el("rect", { x, y: y - fs * 0.6, width: bw, height: fs * 0.45, class: "sg-bar" }, g);
      el("rect", { x, y: y - fs * 0.6, width: (bw * p) / 100, height: fs * 0.45, class: "sg-bar-fill", fill: hue(n) }, g);
      y += fs * 0.5;
      line(`${n.roll.doneLeaves}/${n.roll.leaves} done · ${p}%`, "sg-s-sub", 0.8);
      line(costLine(n, money) || "cost N/D", "sg-s-sub", 0.8);
      if (n.kind === "goal") {
        line(n.gainList.length ? `★ POINT B · +${n.points} pts${n.tree === "unlocked" ? " unlocked" : ""}` : "★ POINT B · decides", "sg-s-pts", 0.9);
        const list = n.gainList.length ? n.gainList.map(x => `+${x.weight} ${x.text}`) : (n.decides || []);
        list.slice(0, 3).forEach(s => line(wrap(s, Math.floor(chars / 0.8), 1)[0], "sg-s-gain", 0.8));
      }
    }

    function drawHeader(n, g) {
      const chars = Math.floor((n.w - 2 * PAD) / (18 * CW));
      text(g, n.x + PAD, n.y + 26, `${ICON[n.tree]} ${(n.kind || "").toUpperCase()} ${n.label || shortId(n.id)} — ${wrap(n.title, Math.max(10, chars - 20), 1)[0]}`, "sg-h1", 18);
      text(g, n.x + PAD, n.y + 46, `${WORD[n.tree]} · ${n.roll.doneLeaves}/${n.roll.leaves} done · ${costLine(n, money) || "cost N/D"}${n.status ? " · " + n.status : ""}`, "sg-h2", 12);
    }

    function drawStar(n, g) {
      const s = n.star, cx = s.x + 46, cy = s.y + 52;
      el("rect", { x: s.x, y: s.y, width: s.w, height: s.h, rx: 6, class: "sg-star-box", stroke: hue(n) }, g);
      el("path", { d: starPath(cx, cy, 30, 13), class: "sg-star", fill: n.tree === "unlocked" ? hue(n) : "none", stroke: hue(n) }, g);
      text(g, s.x + 88, s.y + 40, "POINT B", "sg-pb", 16);
      text(g, s.x + 88, s.y + 62, n.gainList.length ? `+${n.points} pts${n.tree === "unlocked" ? " · UNLOCKED" : ""}` : "decides", "sg-pts", 15);
      text(g, s.x + 88, s.y + 80, n.status ? wrap(n.status, 30, 1)[0] : WORD[n.tree], "sg-h2", 11);
      let y = s.y + 116;
      const list = n.gainList.length ? n.gainList.map(x => `+${x.weight} ${x.text}`) : (n.decides || []).map(d => `· ${d}`);
      for (const item of list.slice(0, 8)) for (const ln of wrap(item, Math.floor((s.w - 28) / (FS * CW)), 2)) { text(g, s.x + 14, y, ln, "sg-gain", FS); y += FS + 4; }
      if (list.length > 8) text(g, s.x + 14, y, `… ${list.length - 8} more in the readout`, "sg-h2", 11);
    }

    m.tops.forEach(n => drawNode(n, tree));

    // ---- view: viewBox pan/zoom; zoom opens regions -------------------------------------------------------------
    const view = { x: m.world.x, y: m.world.y, w: m.world.w, h: m.world.h };
    let pxW = 1, pxH = 1;
    const scale = () => pxW / view.w;
    function fitTo(box, animate) {
      const asp = pxH / pxW, w = Math.max(box.w * 1.08, (box.h * 1.08) / asp), h = w * asp;
      const to = { x: box.x + box.w / 2 - w / 2, y: box.y + box.h / 2 - h / 2, w, h };
      animate === false ? (Object.assign(view, to), apply()) : fly(to);
    }
    let anim = 0;
    function fly(to) {
      cancelAnimationFrame(anim);
      const from = Object.assign({}, view), t0 = performance.now();
      const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
      const step = now => {
        const t = reduce ? 1 : Math.min(1, (now - t0) / 480), e = 1 - Math.pow(1 - t, 3);
        for (const k of ["x", "y", "w", "h"]) view[k] = from[k] + (to[k] - from[k]) * e;
        apply(); if (t < 1) anim = requestAnimationFrame(step);
      };
      anim = requestAnimationFrame(step);
    }
    function zoomAt(px, py, f) {
      const minW = LEAF_W * 1.6, maxW = m.world.w * 1.6;
      const w = Math.min(maxW, Math.max(minW, view.w / f)), k = w / view.w;
      view.x = px - (px - view.x) * k; view.y = py - (py - view.y) * k; view.w = w; view.h = w * (pxH / pxW);
      apply();
    }
    let openKey = "";
    function apply() {
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      const s = scale();
      let deepest = 0;
      const vis = (n, depth) => {
        if (!n.kids.length && n.kind !== "goal") return;
        const onScreen = n.x < view.x + view.w && n.x + n.w > view.x && n.y < view.y + view.h && n.y + n.h > view.y;
        // a goal without children opens as soon as its star reads; a container opens when its median child reads
        n.open = !n.kids.length ? s >= LEGIBLE_PX / FS : s >= n.openS && s * n.w >= 200 && onScreen;
        if (n.open) { deepest = Math.max(deepest, depth + 1); n.kids.forEach(k => vis(k, depth + 1)); }
      };
      m.tops.forEach(n => vis(n, 0));
      const key = conts.map(n => (n.open ? 1 : 0)).join("");
      if (key !== openKey) {
        openKey = key;
        for (const n of conts) n.el.classList.toggle("is-open", !!n.open);
        drawEdges();
      }
      $(".sg-level").textContent = `L${Math.min(2, deepest)} · ×${(s * (m.world.w / pxW)).toFixed(1)}`;
    }
    const visibleRep = n => {             // the outermost closed container holding n, else n itself
      const chain = []; for (let a = n; a; a = a.up) chain.unshift(a);
      for (const a of chain) if (a !== n && (a.kids.length || a.kind === "goal") && !a.open) return a;
      return n;
    };
    const isAnc = (a, b) => { for (let x = b.up; x; x = x.up) if (x === a) return true; return false; };
    function drawEdges() {
      edgeLayer.textContent = "";
      const seen = new Map();
      for (const e of m.edges) {
        const a = visibleRep(e.from), b = visibleRep(e.to);
        if (a === b || isAnc(a, b) || isAnc(b, a)) continue;
        const k = a.id + "\u0000" + b.id, lit = e.from.tree === "unlocked";
        const prev = seen.get(k);
        if (prev) { prev.n++; prev.lit = prev.lit && lit; continue; }
        seen.set(k, { a, b, n: 1, lit, kind: e.kind });
      }
      for (const { a, b, n, lit, kind } of seen.values()) {
        const p = el("path", { d: curve(a.x + a.w, a.y + a.h / 2, b.x, b.y + b.h / 2),
                               class: `sg-edge${lit ? " is-lit" : ""} kind-${kind}`, "marker-end": `url(#${lit ? "sg-ah" : "sg-ah-dim"})` }, edgeLayer);
        el("title", {}, p).textContent = `${a.title || a.id} → ${b.title || b.id}${n > 1 ? ` (${n} links)` : ""}`;
      }
    }
    function resize() {
      const r = mapBox.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const cx = view.x + view.w / 2, cy = view.y + view.h / 2;
      pxW = r.width; pxH = r.height; view.h = view.w * (pxH / pxW); view.y = cy - view.h / 2; view.x = cx - view.w / 2;
      apply();
    }
    const toWorld = (cx, cy) => {
      const b = svg.getBoundingClientRect();
      return [view.x + ((cx - b.left) / b.width) * view.w, view.y + ((cy - b.top) / b.height) * view.h];
    };

    // gestures: drag pans, wheel or pinch zooms at the pointer, double-click flies into a region
    const pts = new Map(); let last = null, pinch = 0, moved = false;
    svg.addEventListener("wheel", ev => { ev.preventDefault(); const [x, y] = toWorld(ev.clientX, ev.clientY); zoomAt(x, y, Math.exp(-ev.deltaY * 0.0015)); }, { passive: false });
    svg.addEventListener("pointerdown", ev => {
      pts.set(ev.pointerId, [ev.clientX, ev.clientY]); last = [ev.clientX, ev.clientY]; moved = false;
      if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
    });
    svg.addEventListener("pointermove", ev => {
      if (!pts.has(ev.pointerId)) return;
      pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
      if (pts.size === 2) {
        const [p, q] = [...pts.values()], d = Math.hypot(p[0] - q[0], p[1] - q[1]);
        const [x, y] = toWorld((p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
        if (pinch) zoomAt(x, y, d / pinch); pinch = d; moved = true; return;
      }
      const dx = ev.clientX - last[0], dy = ev.clientY - last[1];
      if (!moved && Math.abs(dx) + Math.abs(dy) > 3) { moved = true; svg.setPointerCapture(ev.pointerId); svg.classList.add("is-panning"); }
      if (moved) { view.x -= (dx / pxW) * view.w; view.y -= (dy / pxH) * view.h; apply(); }
      last = [ev.clientX, ev.clientY];
    });
    const up = ev => { pts.delete(ev.pointerId); pinch = 0; svg.classList.remove("is-panning"); };
    svg.addEventListener("pointerup", up); svg.addEventListener("pointercancel", up);
    const nodeOf = target => { const g = target.closest && target.closest(".sg-node"); return g ? m.nodes.get(g.dataset.id) : null; };
    // the innermost node under the pointer that is drawn: a closed region answers for everything inside it
    const hit = target => { const n = nodeOf(target); return n ? visibleRep(n) : null; };
    svg.addEventListener("click", ev => { if (moved) return; select(hit(ev.target)); });
    svg.addEventListener("dblclick", ev => {
      const n = hit(ev.target);
      if (n) { select(n); focus = n; fitTo(n); } else { const [x, y] = toWorld(ev.clientX, ev.clientY); zoomAt(x, y, 2); }
    });
    let focus = null;
    mapBox.addEventListener("keydown", ev => {
      const n = ev.target.closest && ev.target.closest(".sg-node") ? hit(ev.target) : null;
      if ((ev.key === "Enter" || ev.key === " ") && n) { ev.preventDefault(); select(n); focus = n; fitTo(n); }
      else if (ev.key === "Escape") { focus = focus && focus.up; focus ? fitTo(focus) : fitTo(m.world); }
      else if (ev.key === "+" || ev.key === "=") zoomAt(view.x + view.w / 2, view.y + view.h / 2, 1.5);
      else if (ev.key === "-") zoomAt(view.x + view.w / 2, view.y + view.h / 2, 1 / 1.5);
      else if (ev.key === "0") { focus = null; fitTo(m.world); }
    });
    $(".sg-reset").addEventListener("click", () => { focus = null; select(null); fitTo(m.world); });

    // tooltip
    const tipBox = $(".sg-tip");
    svg.addEventListener("pointermove", ev => {
      const n = pts.size ? null : hit(ev.target);
      if (!n) { tipBox.style.display = "none"; return; }
      tipBox.innerHTML = `<div><i class="sd-sw" style="background:${hue(n)}"></i>${esc(n.topicLabel)} · ${esc((n.kind || "task").toUpperCase())} ${esc(n.label || shortId(n.id))}</div>`
        + `<div class="sg-tip-title">${esc(n.title || n.id)}</div><div>${ICON[n.tree]} ${WORD[n.tree]} · ${n.roll.doneLeaves}/${n.roll.leaves} · ${esc(n.kids.length ? costLine(n, money) || "cost N/D" : leafCost(n, money))}</div>`;
      tipBox.style.display = "block";
      const b = mapBox.getBoundingClientRect();
      tipBox.style.left = `${Math.min(ev.clientX - b.left + 16, b.width - tipBox.offsetWidth - 8)}px`;
      tipBox.style.top = `${Math.min(ev.clientY - b.top + 14, b.height - tipBox.offsetHeight - 8)}px`;
    });
    svg.addEventListener("pointerleave", () => { tipBox.style.display = "none"; });

    // topic chips: focus one branch, dim the rest
    const chips = $(".sg-chips");
    for (const b of m.bands) {
      const c = document.createElement("button");
      c.type = "button"; c.className = "sd-btn"; c.setAttribute("aria-pressed", "false");
      c.innerHTML = `<i class="sd-sw" style="background:var(--t${b.slot || "-other"})"></i>${esc(b.label)}`;
      c.addEventListener("click", () => {
        const on = c.getAttribute("aria-pressed") !== "true";
        chips.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", "false"));
        c.setAttribute("aria-pressed", String(on));
        svg.querySelectorAll(".sg-band, .sg-node").forEach(x => x.classList.remove("is-dim"));
        if (on) {
          m.tops.filter(n => (n.slot || 0) !== b.slot).forEach(n => n.el.classList.add("is-dim"));
          svg.querySelectorAll(".sg-band").forEach(x => x.classList.toggle("is-dim", Number(x.dataset.slot) !== b.slot));
          fitTo({ x: -PAD * 2, y: b.y - PAD * 2, w: b.w + PAD * 4, h: b.h + PAD * 4 });
        }
      });
      chips.appendChild(c);
    }

    // ---- readout -----------------------------------------------------------------------------------------------
    const ro = $(".sg-readout-body");
    const link = n => { const u = safeUrl(n.url); return u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(n.label || shortId(n.id))} ↗</a>` : esc(n.label || shortId(n.id)); };
    const item = n => `<li class="st-${n.tree}" data-id="${esc(n.id)}"><span>${ICON[n.tree]}</span> ${link(n)} ${esc(n.title || "")}</li>`;
    // what is left before a goal unlocks: its ≈cost, N/D, or — work all done — only the decision itself
    const toGo = q => (!q.roll.leaves ? "NO WORK FILED" : q.roll.leaves === q.roll.doneLeaves ? "WORK DONE · decide"
      : q.roll.togoNd && !q.roll.togo ? "N/D" : "≈" + money(q.roll.togo) + (q.roll.togoNd ? ` +${q.roll.togoNd} N/D` : ""));
    function select(n) {
      svg.querySelectorAll(".is-selected").forEach(x => x.classList.remove("is-selected"));
      if (!n) {
        const next = [...m.nodes.values()].filter(q => q.kind === "goal" && q.tree !== "unlocked")
          .sort((a, b) => ((!a.roll.leaves) - (!b.roll.leaves)) || (a.roll.togoNd - b.roll.togoNd) || (a.roll.togo - b.roll.togo) || (b.points - a.points));
        ro.innerHTML = `<p class="sg-hint">Each goal is a <b>point B</b>: the gains it unlocks and the work that leads to it. Lit = done (the past), dim = still to do (the future). Zoom in and every region opens one level: goals → epics → tasks.</p>`
          + `<p class="sg-hint">Drag to pan · wheel or pinch to zoom · double-click or <kbd>Enter</kbd> to fly in · <kbd>Esc</kbd> out · <kbd>0</kbd> fit.</p>`
          + `<div class="sg-ro-sub">NEAREST UNLOCKS — least ≈cost to go</div><ol class="sg-list">${next.slice(0, 10).map(q =>
              `<li data-id="${esc(q.id)}"><i class="sd-sw" style="background:${hue(q)}"></i>${toGo(q)} · ${q.points ? "+" + q.points + " pts · " : ""}${esc(q.title || q.id)}</li>`).join("")}</ol>`;
      } else {
        n.el.classList.add("is-selected");
        const path = []; for (let a = n.up; a; a = a.up) path.unshift(a);
        const gains = n.gainList.length ? n.gainList.map(x => `<li>+${x.weight} ${esc(x.text)}</li>`).join("") : (n.decides || []).map(d => `<li>· ${esc(d)}</li>`).join("");
        ro.innerHTML = `<div class="sg-ro-path">${path.map(a => `<a href="#" data-id="${esc(a.id)}">${esc(a.label || shortId(a.id))}</a>`).join(" ▸ ") || "MAP"}</div>`
          + `<div class="sg-ro-topic"><i class="sd-sw" style="background:${hue(n)}"></i>${esc(n.topicLabel)} · ${esc((n.kind || "task").toUpperCase())} · <span class="st-${n.tree}">${ICON[n.tree]} ${WORD[n.tree]}</span></div>`
          + `<h3 class="sg-ro-title">${link(n)} ${esc(n.title || "")}</h3>`
          + (n.status ? `<div class="sg-ro-nums">${esc(n.status)}</div>` : "")
          + `<div class="sg-meter"><div style="width:${pctOf(n)}%;background:${hue(n)}"></div></div>`
          + `<div class="sg-ro-nums"><b>${n.roll.doneLeaves}</b>/<b>${n.roll.leaves}</b> done · ${esc(n.kids.length ? costLine(n, money) || "cost N/D" : leafCost(n, money))}</div>`
          + (n.kind === "goal" ? `<div class="sg-ro-sub">★ POINT B ${n.gainList.length ? `· +${n.points} pts` : "· decides (no ## Gains yet)"}</div><ul class="sg-gains">${gains || "<li>N/D</li>"}</ul>` : "")
          + (n.pre.length ? `<div class="sg-ro-sub">NEEDS</div><ul class="sg-list">${n.pre.map(item).join("")}</ul>` : "")
          + (n.post.length ? `<div class="sg-ro-sub">UNLOCKS</div><ul class="sg-list">${n.post.map(item).join("")}</ul>` : "")
          + (n.kids.length ? `<div class="sg-ro-sub">INSIDE · ${n.kids.length}</div><ul class="sg-list">${[...n.kids].sort((a, b) => ORDER[a.tree] - ORDER[b.tree]).slice(0, 30).map(item).join("")}</ul>` : "");
      }
      ro.querySelectorAll("[data-id]").forEach(x => x.addEventListener("click", ev => {
        if (ev.target.closest("a[target]")) return;
        ev.preventDefault();
        const q = m.nodes.get(x.dataset.id); if (q) { select(q); focus = q; fitTo(q); }
      }));
    }

    // ---- table view: every node, the same numbers, no colour needed --------------------------------------------
    const rows = [];
    const walk = (n, d) => { rows.push([n, d]); [...n.kids].sort((a, b) => ORDER[a.tree] - ORDER[b.tree]).forEach(k => walk(k, d + 1)); };
    m.tops.forEach(n => walk(n, 0));
    $(".sg-table-body").innerHTML = `<table><thead><tr><th>node</th><th>title</th><th>topic</th><th>state</th><th>done</th><th>spent</th><th>≈ to go</th><th>pts</th></tr></thead><tbody>${rows.map(([n, d]) =>
      `<tr><td>${"· ".repeat(d)}${esc((n.kind || "task"))} ${link(n)}</td><td>${esc(n.title || "")}</td><td>${esc(n.topicLabel)}</td><td>${ICON[n.tree]} ${WORD[n.tree]}</td>`
      + `<td class="num">${n.roll.doneLeaves}/${n.roll.leaves}</td><td class="num">${n.roll.spentKnown ? money(n.roll.spent) : "N/D"}</td>`
      + `<td class="num">${n.roll.leaves > n.roll.doneLeaves ? (n.roll.togo || !n.roll.togoNd ? "≈" + money(n.roll.togo) : "N/D") + (n.roll.togoNd && n.roll.togo ? ` +${n.roll.togoNd} N/D` : "") : "–"}</td>`
      + `<td class="num">${n.kind === "goal" && n.gainList.length ? n.points : ""}</td></tr>`).join("")}</tbody></table>`;

    if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(mapBox); else window.addEventListener("resize", resize);
    const r0 = mapBox.getBoundingClientRect(); pxW = r0.width || 1000; pxH = r0.height || 700;
    fitTo(m.world, false);
    select(null);
    return m;
  }

  function curve(x1, y1, x2, y2) {
    if (x2 < x1 + 30) {                               // backward: an S through the gap between rows, no loop
      const dy = Math.max(60, Math.abs(y2 - y1) / 2) * (y2 >= y1 ? 1 : -1);
      return `M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + 50).toFixed(1)},${(y1 + dy).toFixed(1)} ${(x2 - 50).toFixed(1)},${(y2 - dy).toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
    }
    const d = Math.max(40, Math.abs(x2 - x1) / 2);
    return `M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + d).toFixed(1)},${y1.toFixed(1)} ${(x2 - d).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  }
  function starPath(cx, cy, R, r) {
    let d = "";
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r : R;
      d += `${i ? "L" : "M"}${(cx + rr * Math.cos(a)).toFixed(1)},${(cy + rr * Math.sin(a)).toFixed(1)} `;
    }
    return d + "Z";
  }
  // "repo#123" and "adr:repo/0018" read as "#123" and "ADR 0018"; anything else is shown whole
  function shortId(id) {
    let m = /#(\d+)$/.exec(id); if (m) return "#" + m[1];
    m = /^adr:(?:.*\/)?(\d{3,5})$/i.exec(id); if (m) return "ADR " + m[1];
    return id;
  }

  return { VERSION, prepare, render, wrap, parseGain, shortId };
});
