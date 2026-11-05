/* goal-map 1.0.1 — goals as a pan/zoom star map (schema goal-map/1). MIT, no dependencies.

     GoalMap.render(hostElement, data)   draws the map, the HUD, the readout and the table view
     GoalMap.prepare(data)               the pure half (topics, progress, layout), usable from Node

   One sector per topic around a core. Each goal is a body in its topic's sector: its size is its number of
   sub-goals, its ring is how much of it is done, and its distance to the core is how far it has to go — a finished
   goal has reached the core. A goal with a parent orbits it as a moon. Colour is the topic and never changes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api; else root.GoalMap = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const VERSION = "1.0.1";
  const SLOTS = 6;
  const WORLD = 1320, R_CORE = 70, R_IN = 120, R_OUT = 500;

  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // http(s), or a same-origin path; `//host` and `javascript:` are dropped (the same rule as page.SAFE_URL)
  const safeUrl = u => (/^(https?:\/\/|\/(?!\/)|\.\.?\/|#)/i.test(String(u || "")) ? String(u) : "");
  const pct = v => (v == null || isNaN(v) ? "–" : `${Math.round(v)} %`);
  const bodyR = g => 9 + 3.2 * Math.sqrt(Math.max(g.total, 1));
  // Progress is distance to the core: a finished goal has reached it. sqrt spreads the crowd near done.
  const radiusOf = p => R_IN + 40 + Math.sqrt(Math.max(0, 1 - p / 100)) * (R_OUT - R_IN - 90);

  // ---- the pure half -------------------------------------------------------------------------------------------
  function prepare(data) {
    const d = data || {};
    const topicList = (d.topics || []).slice(0, SLOTS).map((t, k) => ({ id: t.id, label: t.label || t.id, slot: k + 1 }));
    const slotOf = new Map(topicList.map(t => [t.id, t.slot]));
    const goals = [], byId = new Map();
    for (const raw of d.goals || []) {
      if (!raw || raw.id == null || byId.has(String(raw.id))) continue;
      const total = Math.max(0, Number(raw.total) || 0), completed = Math.min(total, Math.max(0, Number(raw.completed) || 0));
      const g = Object.assign({}, raw, { id: String(raw.id), total, completed, kids: (raw.kids || []).slice() });
      g.slot = slotOf.get(g.topic) || 0;
      g.sector = g.slot ? g.topic : "other";
      g.label = g.label || g.id;
      g.title = g.title || "";
      g.pct = total ? (100 * completed) / total : g.state === "closed" ? 100 : 0;
      goals.push(g); byId.set(g.id, g);
    }
    for (const g of goals) {
      let p = g.parent != null ? byId.get(String(g.parent)) : null, a = p, loop = false;
      while (a) { if (a === g) { loop = true; break; } a = a.parent != null ? byId.get(String(a.parent)) : null; }
      g.parent = p && !loop ? p.id : "";
      g.ready = g.state !== "closed" && g.total > 0 && g.completed === g.total;
    }
    const sectors = layout(goals, topicList);
    const tops = goals.filter(g => !g.parent);
    const totals = { done: tops.reduce((a, g) => a + g.completed, 0), all: tops.reduce((a, g) => a + g.total, 0),
                     goals: goals.length, closed: goals.filter(g => g.state === "closed").length };
    return { data: d, goals, byId, sectors, topics: topicList, totals };
  }

  function layout(goals, topicList) {
    const tops = goals.filter(g => !g.parent);
    const ids = [...topicList.map(t => t.id), "other"];
    const label = new Map(topicList.map(t => [t.id, t.label]));
    const sectors = ids.map(t => ({ t, label: t === "other" ? "other" : label.get(t), slot: t === "other" ? 0 : topicList.find(x => x.id === t).slot,
                                    goals: tops.filter(g => g.sector === t) }))
      .filter(s => s.t !== "other" || s.goals.length);
    const weight = s => 1.2 + s.goals.length;
    const total = sectors.reduce((a, s) => a + weight(s), 0);
    let a = -Math.PI / 2;
    for (const s of sectors) {
      s.a0 = a; s.a1 = a + (2 * Math.PI * weight(s)) / total; a = s.a1;
      s.goals.sort((p, q) => p.id.localeCompare(q.id, undefined, { numeric: true })).forEach((g, i) => {
        g.sec = s; g.r0 = radiusOf(g.pct);
        const ang = s.a0 + ((i + 0.5) / s.goals.length) * (s.a1 - s.a0);
        g.x = g.r0 * Math.cos(ang); g.y = g.r0 * Math.sin(ang);
      });
    }
    // Room for each body, its moons and its label; then relax overlaps, kept inside the sector and near the goal's
    // own progress radius so position still reads as progress.
    const moons = g => goals.filter(q => q.parent === g.id);
    for (const g of tops) g.room = bodyR(g) + (moons(g).length ? 2 * Math.max(...moons(g).map(bodyR)) + 30 : 0) + 22;
    for (let it = 0; it < 300; it++) {
      for (let i = 0; i < tops.length; i++) for (let j = i + 1; j < tops.length; j++) {
        const p = tops[i], q = tops[j], dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 0.01, need = p.room + q.room;
        if (d < need) { const k = (need - d) / d / 2; p.x -= dx * k; p.y -= dy * k; q.x += dx * k; q.y += dy * k; }
      }
      for (const g of tops) {
        let r = Math.hypot(g.x, g.y), ang = Math.atan2(g.y, g.x);
        while (ang < g.sec.a0 - 0.0001) ang += 2 * Math.PI;
        while (ang > g.sec.a1 + 0.0001) ang -= 2 * Math.PI;
        const m = Math.min(0.4 * (g.sec.a1 - g.sec.a0), g.room / Math.max(r, 1));
        ang = Math.max(g.sec.a0 + m, Math.min(g.sec.a1 - m, ang));
        r = Math.max(R_CORE + g.room + 4, Math.max(g.r0 - 40, Math.min(g.r0 + 150, r)));   // crowding pushes outward
        g.x = r * Math.cos(ang); g.y = r * Math.sin(ang); g.ang = ang;
      }
    }
    // Moons orbit their parent, one level at a time, so a moon of a moon waits for its parent's place.
    let pending = goals.filter(g => g.parent);
    while (pending.length) {
      const ready = pending.filter(g => { const p = goals.find(q => q.id === g.parent); return p && p.x != null; });
      if (!ready.length) { pending.forEach(g => { g.parent = ""; g.x = g.y = 0; g.ang = 0; }); break; }
      for (const g of ready) {
        const p = goals.find(q => q.id === g.parent), sibs = moons(p);
        const k = sibs.indexOf(g), ang = p.ang + Math.PI / 2 + (k * 2 * Math.PI) / Math.max(sibs.length, 3);
        const d = bodyR(p) + bodyR(g) + 48;   // clear of the parent's satellites and its label
        g.x = p.x + d * Math.cos(ang); g.y = p.y + d * Math.sin(ang); g.ang = p.ang; g.sec = p.sec;
      }
      pending = pending.filter(g => !ready.includes(g));
    }
    return sectors;
  }

  // ---- the browser half ----------------------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  const hue = slot => `var(--t${slot || "-other"})`;
  function arc(r0, r1, a0, a1) {
    const p = (r, a) => `${(r * Math.cos(a)).toFixed(1)},${(r * Math.sin(a)).toFixed(1)}`;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    return `M${p(r0, a0)} L${p(r1, a0)} A${r1},${r1} 0 ${big} 1 ${p(r1, a1)} L${p(r0, a1)} A${r0},${r0} 0 ${big} 0 ${p(r0, a0)} Z`;
  }
  const ring = (r, frac) => {             // a completion arc from 12 o'clock, clockwise
    if (frac >= 0.999) return null;
    const a = -Math.PI / 2 + 2 * Math.PI * Math.max(0.001, frac);
    return `M0,${-r} A${r},${r} 0 ${frac > 0.5 ? 1 : 0} 1 ${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`;
  };

  function render(host, data) {
    const m = prepare(data), goals = m.goals;
    host.classList.add("gm");
    host.innerHTML = `
      <div class="gm-hud"><span class="gm-hud-title">${esc(data.title || "GOAL MAP")}</span>
        <span class="gm-status">${m.totals.goals} GOALS · ${m.totals.closed} CLOSED · ${m.totals.done}/${m.totals.all} DONE</span>
        ${data.generated ? `<span class="gm-clock">${esc(data.generated)}</span>` : ""}
        <div class="gm-chips" role="group" aria-label="Focus a topic"></div>
        <button type="button" class="sd-btn gm-reset" title="Reset the view (0)">⟲ reset</button></div>
      ${(data.notes || []).length ? `<div class="gm-notes">${data.notes.map(s => `<div>${esc(s)}</div>`).join("")}</div>` : ""}
      <div class="gm-main"><div class="gm-map" tabindex="0" aria-label="Goal map. Drag to pan, wheel or pinch to zoom, double-click to fly in, 0 to reset.">
        <div class="gm-canvas"></div><span class="gm-zoom"></span><div class="gm-tip" role="tooltip"></div></div>
        <div class="gm-readout" role="complementary" aria-label="Goal readout"><div class="gm-readout-head">READOUT</div><div class="gm-readout-body"></div></div></div>
      <details class="sd-table"><summary>TABLE VIEW · ${goals.length} goals</summary><div class="gm-table-body"></div></details>`;
    const $ = s => host.querySelector(s);
    const box = $(".gm-canvas");
    const svg = el("svg", { class: "gm-svg", role: "group", "aria-label": "Goal map: goals by topic, nearer the core = closer to done" }, box);
    const defs = el("defs", {}, svg);
    const glow = el("filter", { id: "gm-glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
    el("feGaussianBlur", { stdDeviation: "3", result: "b" }, glow);
    const mg = el("feMerge", {}, glow); el("feMergeNode", { in: "b" }, mg); el("feMergeNode", { in: "SourceGraphic" }, mg);
    const world = el("g", {}, svg);
    let selected = null, focusTopic = null;

    const grid = el("g", { class: "gm-grid" }, world);     // range rings
    [100, 90, 75, 50, 0].forEach(v => {
      const r = radiusOf(v);
      el("circle", { r, class: v === 100 ? "gm-ring gm-ring-done" : "gm-ring" }, grid);
      el("text", { x: 4, y: -r - 3, class: "gm-ring-label" }, grid).textContent = `${v} %`;
    });
    for (const s of m.sectors) {
      const g = el("g", { class: "gm-sector", "data-topic": s.t }, world);
      el("path", { d: arc(R_IN, R_OUT, s.a0 + 0.006, s.a1 - 0.006), fill: hue(s.slot), class: "gm-wedge" }, g);
      const mid = (s.a0 + s.a1) / 2, lr = R_OUT + 22, lx = lr * Math.cos(mid);
      const t = el("text", { x: lx, y: lr * Math.sin(mid), class: "gm-sector-label",
                             "text-anchor": Math.cos(mid) > 0.2 ? "start" : Math.cos(mid) < -0.2 ? "end" : "middle" }, g);
      const done = s.goals.reduce((a, q) => a + q.completed, 0), all = s.goals.reduce((a, q) => a + q.total, 0);
      t.innerHTML = `<tspan fill="${hue(s.slot)}">■ </tspan>${esc(String(s.label).toUpperCase())}`
        + `<tspan class="gm-sector-sub" x="${lx.toFixed(1)}" dy="15">${s.goals.length ? `${s.goals.length} goals · ${done}/${all}` : "no goals"}</tspan>`;
      t.addEventListener("click", () => setFocus(focusTopic === s.t ? null : s.t));
    }
    // the core: everything, done over total
    const D = m.totals.done, T = m.totals.all;
    const core = el("g", { class: "gm-core" }, world);
    el("circle", { r: R_CORE, class: "gm-core-disc" }, core);
    el("circle", { r: R_CORE - 8, class: "gm-core-track" }, core);
    const cr = ring(R_CORE - 8, T ? D / T : 0);
    if (cr) el("path", { d: cr, class: "gm-core-arc" }, core); else el("circle", { r: R_CORE - 8, class: "gm-core-arc" }, core);
    el("text", { y: -4, class: "gm-core-num" }, core).textContent = T ? `${Math.round((100 * D) / T)}%` : "–";
    el("text", { y: 16, class: "gm-core-sub" }, core).textContent = `${D}/${T} DONE`;

    const layer = el("g", {}, world);
    for (const g of [...goals].sort((a, b) => (a.parent ? 1 : 0) - (b.parent ? 1 : 0))) {
      const r = bodyR(g);
      const gg = el("g", { class: `gm-goal${g.state === "closed" ? " is-closed" : ""}${g.ready ? " is-ready" : ""}${g.parent ? " is-moon" : ""}`,
                           transform: `translate(${g.x.toFixed(1)},${g.y.toFixed(1)})`, tabindex: 0, role: "button",
                           "data-id": g.id, "data-topic": g.sector,
                           "aria-label": `${g.label} ${g.title}: ${g.completed} of ${g.total} done${g.state === "closed" ? ", closed" : ""}` }, layer);
      g.el = gg;
      if (g.parent) {
        const p = m.byId.get(g.parent);
        el("line", { x1: 0, y1: 0, x2: (p.x - g.x).toFixed(1), y2: (p.y - g.y).toFixed(1), class: "gm-tether" }, gg);
      }
      el("circle", { r: r + 10, class: "gm-hit" }, gg);
      el("circle", { r, class: "gm-body", fill: hue(g.slot) }, gg);
      el("circle", { r: r + 4, class: "gm-track" }, gg);
      const d = ring(r + 4, g.pct / 100);
      el(d ? "path" : "circle", d ? { d, class: "gm-arc", stroke: hue(g.slot) } : { r: r + 4, class: "gm-arc", stroke: hue(g.slot) }, gg);
      // satellites: one per sub-goal, drawn now, shown only when zoomed in (CSS by zoom level)
      const sat = el("g", { class: "gm-sats" }, gg);
      g.kids.forEach((c, i) => {
        const a = -Math.PI / 2 + (i / g.kids.length) * 2 * Math.PI, rr = r + 13;
        const s = el("circle", { cx: (rr * Math.cos(a)).toFixed(2), cy: (rr * Math.sin(a)).toFixed(2), r: 2.2,
                                 class: c.done ? "gm-sat done" : "gm-sat", stroke: hue(g.slot) }, sat);
        el("title", {}, s).textContent = `${c.label || c.id} ${c.done ? "✓" : "○"} ${c.title || ""}`;
      });
      el("text", { y: r + 26, class: "gm-goal-num" }, gg).textContent = g.label;
      el("text", { y: r + 38, class: "gm-goal-title" }, gg).textContent = g.title.length > 34 ? g.title.slice(0, 33) + "…" : g.title;
      el("text", { y: 4, class: "gm-goal-pct" }, gg).textContent = g.total ? `${Math.round(g.pct)}` : "";
      gg.addEventListener("click", ev => { ev.stopPropagation(); select(g); });
      gg.addEventListener("dblclick", ev => { ev.stopPropagation(); select(g); fly(g.x, g.y, 220); });
      gg.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(g); fly(g.x, g.y, 220); } });
      gg.addEventListener("mouseenter", ev => tip(ev, g)); gg.addEventListener("mousemove", ev => tip(ev, g));
      gg.addEventListener("mouseleave", () => { $(".gm-tip").style.display = "none"; });
    }

    function tip(ev, g) {
      const t = $(".gm-tip"), b = $(".gm-map").getBoundingClientRect();
      t.innerHTML = `<div><i class="sd-sw" style="background:${hue(g.slot)}"></i>${esc(g.sec ? g.sec.label : g.sector)} · ${esc(g.label)}</div>`
        + `<div class="gm-tip-title">${esc(g.title)}</div><div><b>${g.completed}/${g.total}</b> done · <b>${pct(g.pct)}</b>${g.state === "closed" ? " · CLOSED" : g.ready ? " · READY TO CLOSE" : ""}</div>`;
      t.style.display = "block";
      t.style.left = `${Math.min(ev.clientX - b.left + 16, b.width - t.offsetWidth - 8)}px`;
      t.style.top = `${Math.min(ev.clientY - b.top + 14, b.height - t.offsetHeight - 8)}px`;
    }

    // ---- pan / zoom: drag, wheel at the cursor, pinch, double-click to fly, keys -------------------------------
    const view = { x: -WORLD / 2, y: -WORLD / 2, w: WORLD, h: WORLD };
    const zoomOf = () => WORLD / view.w;
    function applyView() {
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      const z = zoomOf();
      svg.dataset.lod = z >= 4 ? "3" : z >= 2.2 ? "2" : z >= 1.4 ? "1" : "0";
      $(".gm-zoom").textContent = `×${z.toFixed(1)}`;
    }
    function zoomAt(px, py, f) {                 // px,py in world units
      const w = Math.min(WORLD * 1.4, Math.max(WORLD / 12, view.w / f));
      const k = w / view.w;
      view.x = px - (px - view.x) * k; view.y = py - (py - view.y) * k; view.w = view.h = w;
      applyView();
    }
    let anim = 0;
    function fly(cx, cy, w) {
      cancelAnimationFrame(anim);
      const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
      const from = Object.assign({}, view), to = { x: cx - w / 2, y: cy - w / 2, w, h: w }, t0 = performance.now();
      const step = now => {
        const t = reduce ? 1 : Math.min(1, (now - t0) / 450), e = 1 - Math.pow(1 - t, 3);
        for (const k of ["x", "y", "w", "h"]) view[k] = from[k] + (to[k] - from[k]) * e;
        applyView(); if (t < 1) anim = requestAnimationFrame(step);
      };
      anim = requestAnimationFrame(step);
    }
    const toWorld = (cx, cy) => {
      const b = svg.getBoundingClientRect(), s = Math.min(b.width, b.height);   // viewBox is square, centred (meet)
      const ox = b.left + (b.width - s) / 2, oy = b.top + (b.height - s) / 2;
      return [view.x + ((cx - ox) / s) * view.w, view.y + ((cy - oy) / s) * view.h];
    };
    const pts = new Map(); let last = null, pinch = 0, moved = false;
    svg.addEventListener("wheel", ev => { ev.preventDefault(); const [x, y] = toWorld(ev.clientX, ev.clientY);
      zoomAt(x, y, Math.exp(-ev.deltaY * 0.0015)); }, { passive: false });
    svg.addEventListener("pointerdown", ev => { pts.set(ev.pointerId, [ev.clientX, ev.clientY]); last = [ev.clientX, ev.clientY]; moved = false;
      if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); } });
    svg.addEventListener("pointermove", ev => {
      if (!pts.has(ev.pointerId)) return;
      pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
      const b = svg.getBoundingClientRect(), s = Math.min(b.width, b.height);
      if (pts.size === 2) {
        const [p, q] = [...pts.values()], d = Math.hypot(p[0] - q[0], p[1] - q[1]);
        const [x, y] = toWorld((p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
        if (pinch) zoomAt(x, y, d / pinch); pinch = d; moved = true; return;
      }
      const dx = ev.clientX - last[0], dy = ev.clientY - last[1];
      if (!moved && Math.abs(dx) + Math.abs(dy) > 3) { moved = true; svg.setPointerCapture(ev.pointerId); svg.classList.add("is-panning"); }
      if (moved) { view.x -= (dx / s) * view.w; view.y -= (dy / s) * view.h; applyView(); }
      last = [ev.clientX, ev.clientY];
    });
    const up = ev => { pts.delete(ev.pointerId); pinch = 0; svg.classList.remove("is-panning"); };
    svg.addEventListener("pointerup", up); svg.addEventListener("pointercancel", up);
    svg.addEventListener("click", () => { if (!moved) select(null); });
    svg.addEventListener("dblclick", ev => { const [x, y] = toWorld(ev.clientX, ev.clientY); zoomAt(x, y, 2); });
    host.addEventListener("keydown", ev => {
      if (ev.target.closest("input,select,textarea")) return;
      if (ev.key === "+" || ev.key === "=") zoomAt(view.x + view.w / 2, view.y + view.h / 2, 1.5);
      else if (ev.key === "-") zoomAt(view.x + view.w / 2, view.y + view.h / 2, 1 / 1.5);
      else if (ev.key === "0") reset();
    });
    function reset() { setFocus(null); select(null); fly(0, 0, WORLD); }
    $(".gm-reset").addEventListener("click", reset);

    const chips = $(".gm-chips");
    for (const s of m.sectors) {
      const c = document.createElement("button");
      c.type = "button"; c.className = "sd-btn gm-chip"; c.dataset.topic = s.t; c.setAttribute("aria-pressed", "false");
      c.innerHTML = `<i class="sd-sw" style="background:${hue(s.slot)}"></i>${esc(s.label)}`;
      c.addEventListener("click", () => setFocus(focusTopic === s.t ? null : s.t));
      chips.appendChild(c);
    }
    function setFocus(t) {
      focusTopic = t;
      host.querySelectorAll(".gm-chip").forEach(c => c.setAttribute("aria-pressed", String(c.dataset.topic === t)));
      svg.querySelectorAll("[data-topic]").forEach(n => n.classList.toggle("is-dim", !!t && n.dataset.topic !== t));
      if (t) {
        const gs = goals.filter(g => g.sector === t);
        if (gs.length) {
          const xs = gs.map(g => g.x), ys = gs.map(g => g.y);
          const w = Math.max(260, Math.max(...xs) - Math.min(...xs) + 200, Math.max(...ys) - Math.min(...ys) + 200);
          fly((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, w);
        }
      }
      select(selected);
    }

    // ---- the readout ---------------------------------------------------------------------------------------------
    const link = (url, text) => { const u = safeUrl(url); return u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${text} ↗</a>` : text; };
    function select(g) {
      selected = g;
      svg.querySelectorAll(".gm-goal").forEach(n => n.classList.toggle("is-selected", !!g && n.dataset.id === g.id));
      const box = $(".gm-readout-body");
      if (!g) {
        const open = goals.filter(q => q.state !== "closed" && !q.parent && (!focusTopic || q.sector === focusTopic)).sort((a, b) => b.pct - a.pct);
        box.innerHTML = `<p class="gm-hint">Select a goal. Nearer the core is nearer done. Drag to pan, wheel or pinch to zoom, double-click to fly in, <kbd>0</kbd> to reset.</p>`
          + `<ol class="gm-top">${open.slice(0, 8).map(q => `<li data-id="${esc(q.id)}"><i class="sd-sw" style="background:${hue(q.slot)}"></i>`
          + `<span class="gm-top-pct">${q.ready ? "READY" : pct(q.pct)}</span> ${esc(q.label)} ${esc(q.title.slice(0, 60))}</li>`).join("")}</ol>`;
        box.querySelectorAll("li").forEach(li => li.addEventListener("click", () => {
          const q = m.byId.get(li.dataset.id); select(q); fly(q.x, q.y, 220); }));
      } else {
        const parent = g.parent ? m.byId.get(g.parent) : null;
        box.innerHTML = `<div class="gm-ro-topic"><i class="sd-sw" style="background:${hue(g.slot)}"></i>${esc(g.sec ? g.sec.label : g.sector)}`
          + `${parent ? ` · part of ${esc(parent.label)}` : ""}</div>`
          + `<h3 class="gm-ro-title">${link(g.url, `${esc(g.label)} ${esc(g.title)}`)}</h3>`
          + `<div class="gm-meter"><div class="gm-meter-fill" style="width:${g.pct}%;background:${hue(g.slot)}"></div></div>`
          + `<div class="gm-ro-nums"><b>${g.completed}</b> of <b>${g.total}</b> done · <b>${pct(g.pct)}</b>${g.state === "closed" ? " · <b>GOAL CLOSED</b>" : g.ready ? " · <b>all done — ready to close</b>" : ""}</div>`
          + `<ul class="gm-kids">${g.kids.map(c => `<li class="${c.done ? "done" : ""}"><span>${c.done ? "✓" : "○"}</span>`
          + `${link(c.url, esc(c.label || c.id))} ${esc(c.title || "")}</li>`).join("")}</ul>`;
      }
    }

    // ---- table view --------------------------------------------------------------------------------------------
    $(".gm-table-body").innerHTML = `<table><thead><tr><th>goal</th><th>title</th><th>topic</th><th>state</th><th>done</th><th>%</th></tr></thead><tbody>`
      + [...goals].sort((a, b) => a.sector.localeCompare(b.sector) || b.pct - a.pct).map(g =>
        `<tr><td>${g.parent ? "· " : ""}${link(g.url, esc(g.label))}</td><td>${esc(g.title)}</td><td>${esc(g.sec ? g.sec.label : g.sector)}</td>`
        + `<td>${g.state === "closed" ? "closed" : g.ready ? "ready" : "open"}</td><td class="num">${g.completed}/${g.total}</td><td class="num">${pct(g.pct)}</td></tr>`).join("")
      + `</tbody></table>`;

    applyView(); select(null);
    return m;
  }

  return { VERSION, prepare, render, radiusOf };
});
