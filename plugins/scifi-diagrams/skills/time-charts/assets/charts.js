/* time-charts 1.0.0 — one wrapper over the vendored uPlot 1.6.32 (vendor/, MIT). MIT, no other dependency.

   TimeCharts.plot(container, {xs, series: [{name, vals, color, fill, dash}], ref: {name, vals, color},
                               kind: "line" | "stack" | "bars" | "step", unit, ymax, height, endLabels, spanGaps, inset})
   -> the plot element (its `.uplot` is the uPlot instance; destroy it before redrawing the same host).
   TimeCharts.fromSpec(chart)  the pure half: a `time-charts/1` chart -> plot() options. Usable from Node.

   Readers drag across a chart to zoom, Ctrl+wheel or pinch to zoom, double-click to reset, and click a legend
   entry to hide a series. The crosshair tooltip shows raw (unstacked) values. Charts share no cursor-sync group:
   uPlot's sync also syncs the x scale, so charts with different ranges would drag each other. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api; else root.TimeCharts = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const VERSION = "1.0.0";
  const SLOTS = ["var(--t1)", "var(--t2)", "var(--t3)", "var(--t4)", "var(--t5)", "var(--t6)"];
  const KINDS = { line: "line", area: "stack", stack: "stack", bars: "bars", step: "step" };

  const fmt = v => v == null || isNaN(v) ? "–" : Math.abs(v) >= 100 ? Math.round(v).toString()
    : Math.abs(v) >= 10 ? v.toFixed(1).replace(/\.0$/, "") : v.toFixed(2).replace(/\.?0+$/, "");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // time-charts/1 chart -> plot() options. A series beyond the sixth folds to the neutral "other" hue.
  function fromSpec(c) {
    const xs = c.xs || [];
    return {
      xs, kind: KINDS[c.kind || "line"] || "line", unit: c.unit || "", ymax: c.ymax, height: c.height,
      series: (c.series || []).map((s, k) => ({ name: s.label, vals: s.values, color: s.color || SLOTS[k] || "var(--t-other)", dash: s.dash })),
      ref: typeof c.ref === "number" ? { name: c.refLabel || "target", vals: xs.map(() => c.ref) } : null,
      spanGaps: !!c.spanGaps,
    };
  }

  // ---- the browser half ----------------------------------------------------------------------------------------
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  // canvas cannot resolve var(--x): read it once from :root
  const color = c => { const m = /^var\((--[\w-]+)\)$/.exec(String(c || "").trim()); return m ? css(m[1]) : c; };
  const day = t => new Date(t * 1000).toISOString().slice(5, 10);
  const hour = t => new Date(t * 1000).toISOString().slice(11, 16) + "Z";

  const clampX = (u, lo, hi) => {
    const x0 = u.data[0][0], xN = u.data[0][u.data[0].length - 1];
    const span = Math.min(xN - x0, Math.max(hi - lo, (xN - x0) / 200));
    lo = Math.max(x0, Math.min(lo, xN - span));
    u.setScale("x", { min: lo, max: lo + span });
  };
  // Ctrl/⌘+wheel (a trackpad pinch sends this) zooms x around the cursor; a plain wheel scrolls the page.
  const wheelZoom = () => ({ hooks: { ready: u => {
    u.over.addEventListener("wheel", e => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const at = u.posToVal(e.offsetX, "x"), f = e.deltaY < 0 ? 0.8 : 1.25;
      clampX(u, at - (at - u.scales.x.min) * f, at + (u.scales.x.max - at) * f);
    }, { passive: false });
  } } });
  // Two fingers pinch x; one finger pans once zoomed in. Vertical page scroll stays the browser's.
  const touchZoom = () => ({ hooks: { ready: u => {
    const o = u.over; let g = null;
    o.style.touchAction = "pan-y";
    const pts = t => [...t].map(p => p.clientX - o.getBoundingClientRect().left);
    o.addEventListener("touchstart", e => {
      g = { min: u.scales.x.min, max: u.scales.x.max, p: pts(e.touches), w: o.clientWidth };
    }, { passive: true });
    o.addEventListener("touchmove", e => {
      if (!g) return;
      const p = pts(e.touches), span = g.max - g.min;
      if (p.length === 2 && g.p.length === 2) {
        e.preventDefault();
        const d0 = Math.abs(g.p[1] - g.p[0]) || 1, d1 = Math.abs(p[1] - p[0]) || 1;
        const c = g.min + ((g.p[0] + g.p[1]) / 2 / g.w) * span, ns = span * d0 / d1, at = (p[0] + p[1]) / 2 / g.w;
        clampX(u, c - at * ns, c - at * ns + ns);
      } else if (p.length === 1 && g.p.length === 1 && u.data[0][u.data[0].length - 1] - u.data[0][0] > span * 1.01) {
        const dx = ((p[0] - g.p[0]) / g.w) * span;
        clampX(u, g.min - dx, g.max - dx);
      }
    }, { passive: false });
    o.addEventListener("touchend", () => { g = null; });
  } } });
  // the value at i, or the series' last value before it (series on another time grid, or a step line)
  const hold = (vals, i) => { while (i >= 0 && vals[i] == null) i--; return i < 0 ? null : vals[i]; };
  const tooltip = (host, raw, ref, unit, spanGaps) => {
    const tip = document.createElement("div"); tip.className = "fc-tip"; host.appendChild(tip);
    return { hooks: { setCursor: u => {
      const i = u.cursor.idx;
      if (i == null || u.cursor.left < 0) { tip.style.display = "none"; return; }
      const t = u.data[0][i];
      tip.innerHTML = `<div>${day(t)} ${hour(t)}</div>` + raw.filter(s => u.series[s.slot].show)
        .map(s => `<div><i style="display:inline-block;width:8px;height:8px;margin-right:6px;background:${s.rgb}"></i>${esc(s.name)} <b>${fmt(spanGaps ? hold(s.vals, i) : s.vals[i])}${esc(unit)}</b></div>`).join("")
        + (ref ? `<div>${esc(ref.name)} <b>${fmt(hold(ref.vals, i))}${esc(unit)}</b></div>` : "");
      tip.style.display = "block";
      const hb = host.getBoundingClientRect(), ob = u.over.getBoundingClientRect();
      tip.style.left = `${Math.min(ob.left - hb.left + u.cursor.left + 14, hb.width - tip.offsetWidth - 8)}px`;
      tip.style.top = `${ob.top - hb.top + u.cursor.top + 12}px`;
    } } };
  };
  // Direct labels at the line ends, nudged apart.
  const endLabels = raw => ({ hooks: { draw: u => {
    const ctx = u.ctx, dpr = devicePixelRatio || 1;
    const ends = raw.filter(s => u.series[s.slot].show).map(s => {
      let i = s.vals.length - 1; while (i >= 0 && s.vals[i] == null) i--;
      return i < 0 ? null : { s, x: u.valToPos(u.data[0][i], "x", true), y: u.valToPos(s.vals[i], "y", true) };
    }).filter(Boolean).sort((a, b) => a.y - b.y);
    ends.forEach((e, k) => { if (k && e.y - ends[k - 1].y < 12 * dpr) e.y = ends[k - 1].y + 12 * dpr; });
    ctx.save(); ctx.font = `${10.5 * dpr}px "Share Tech Mono", monospace`; ctx.fillStyle = css("--ink");
    ctx.textBaseline = "middle"; ctx.textAlign = "left";
    ends.forEach(e => ctx.fillText(e.s.name.length > 13 ? e.s.name.slice(0, 12) + "…" : e.s.name, e.x + 6 * dpr, e.y));
    ctx.restore();
  } } });

  function plot(host, o) {
    const uPlot = (typeof self !== "undefined" ? self : globalThis).uPlot;
    const kind = o.kind || "line", stacked = kind === "stack" || kind === "bars", unit = o.unit || "";
    const series = o.series.map(s => Object.assign({}, s, { rgb: color(s.color) }));
    const ref = o.ref ? Object.assign({}, o.ref, { rgb: color(o.ref.color || "var(--tag-bad)") }) : null;
    const labels = o.endLabels != null ? o.endLabels : series.length > 1 && (kind === "line" || kind === "step");
    const acc = o.xs.map(() => 0);           // stacked kinds draw cumulative values; the tooltip keeps raw ones
    const cum = series.map(s => stacked ? s.vals.map((v, i) => (acc[i] += v || 0)) : s.vals);
    const ink = css("--dim"), grid = css("--line"), font = '10px "Share Tech Mono", monospace';
    // bars: the tallest stack segment is drawn first and the lower ones over it, so the order runs top-down
    const order = kind === "bars" ? series.map((_, k) => series.length - 1 - k) : series.map((_, k) => k);
    const uSeries = [{}], data = [o.xs];
    order.forEach(k => {
      const s = series[k];
      s.slot = uSeries.length;
      const u = { label: s.name, stroke: s.rgb, width: kind === "bars" ? 0 : stacked ? 1.5 : 2, points: { show: false },
                  spanGaps: !!o.spanGaps };
      if (s.dash) u.dash = String(s.dash).split(/\s+/).map(Number);
      if (kind === "bars") { u.paths = uPlot.paths.bars({ size: [0.72, 48], gap: 2 }); u.fill = s.rgb; }
      else if (kind === "step") u.paths = uPlot.paths.stepped({ align: 1 });
      if ((kind === "stack" && k === 0) || ((kind === "line" || kind === "step") && s.fill)) u.fill = s.rgb + (kind === "stack" ? "8c" : "38");
      uSeries.push(u); data.push(cum[k]);
    });
    if (ref) {
      uSeries.push({ label: ref.name, stroke: ref.rgb, width: 1.5, dash: [5, 4], spanGaps: true,
                     paths: uPlot.paths.stepped({ align: 1 }), points: { show: false } });
      data.push(ref.vals);
    }
    const bands = kind === "stack" ? series.slice(1).map((s, k) => ({ series: [s.slot, series[k].slot], fill: s.rgb + "8c" })) : [];
    const peak = Math.max(0, ...[].concat(...data.slice(1)).filter(v => v != null));
    const ymax = o.ymax || (unit === "%" && peak <= 100 ? 100 : peak > 0 ? peak * 1.08 : 1);
    const width = () => Math.max(240, host.clientWidth - (o.inset == null ? 32 : o.inset));
    const box = document.createElement("div"); box.className = "fc-plot";
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.appendChild(box);
    const u = new uPlot({
      width: width(), height: o.height || 230, padding: [8, labels ? 96 : 12, 0, 0],
      series: uSeries, bands,
      legend: { show: series.length > 1 || !!ref, live: false },
      cursor: { drag: { x: true, y: false, setScale: true }, points: { show: false } },   // no sync group (see the header)
      scales: { x: { time: true }, y: { range: () => [0, ymax] } },
      axes: [
        { stroke: ink, font, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 },
          values: (u, ts, _a, _s, step) => ts.map(t => step >= 86400 || t % 86400 === 0 ? day(t) : hour(t)) },   // midnight carries the date
        { stroke: ink, font, size: 48, grid: { stroke: grid, width: 1 }, ticks: { show: false }, values: (u, vs) => vs.map(v => fmt(v) + unit) },
      ],
      plugins: [wheelZoom(), touchZoom(), tooltip(host, series, ref, unit, !!o.spanGaps)].concat(labels ? [endLabels(series)] : []),
    }, data, box);
    box.querySelectorAll(".u-legend .u-marker").forEach(m => { m.style.background = m.style.borderColor; });  // solid keys
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => { const w = width(); if (Math.abs(w - u.width) > 2) u.setSize({ width: w, height: u.height }); }).observe(host);
    }
    const hint = document.createElement("div"); hint.className = "fc-hint";
    hint.textContent = "drag to zoom · ctrl+wheel or pinch · double-click resets";
    box.appendChild(hint);
    box.uplot = u;
    return box;
  }

  // A whole time-charts/1 document: one figure per chart, each with a table view of its numbers.
  function render(host, doc) {
    host.innerHTML = `<h1 class="tc-title">${esc(doc.title || "")}</h1>`
      + ((doc.notes || []).length ? `<div class="tc-notes">${doc.notes.map(s => `<div>${esc(s)}</div>`).join("")}</div>` : "")
      + `<div class="tc-deck"></div>`;
    const deck = host.querySelector(".tc-deck");
    return (doc.charts || []).map(c => {
      const fig = document.createElement("figure"); fig.className = "fc";
      fig.innerHTML = `<div class="fc-head"><span class="fc-title">${esc(c.title || "")}</span></div>`;
      deck.appendChild(fig);
      const o = fromSpec(c);
      if (!o.xs.length || !o.series.length) {
        fig.insertAdjacentHTML("beforeend", `<div class="fc-offline">N/D — no data</div>`);
        return null;
      }
      const box = plot(fig, o);
      const rows = o.xs.map((t, i) => `<tr><td>${esc(new Date(t * 1000).toISOString().slice(0, 16).replace("T", " "))}Z</td>`
        + o.series.map(s => `<td class="num">${fmt(s.vals[i])}</td>`).join("") + "</tr>").join("");
      fig.insertAdjacentHTML("beforeend", `<details class="sd-table"><summary>TABLE VIEW</summary><table><thead><tr><th>time</th>`
        + o.series.map(s => `<th>${esc(s.name)}${esc(o.unit ? " (" + o.unit + ")" : "")}</th>`).join("") + `</tr></thead><tbody>${rows}</tbody></table></details>`);
      return box;
    });
  }

  return { VERSION, fromSpec, plot, render, color, fmt };
});
