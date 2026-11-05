---
name: time-charts
description: Draw zoomable sci-fi time-series charts — lines, stacked areas, stacked bars and step lines — as one self-contained HTML page, or as live charts fed by a PromQL range query from the reader's browser. Built on vendored uPlot 1.6.32 (22 KB gz) with drag-to-zoom, Ctrl+wheel and pinch zoom, a raw-value crosshair tooltip, end labels and a table view. Use when asked for a time chart, a telemetry deck, a burn-up, a metric over time, "charts like Grafana but in a page", or interactive / zoomable graphs of a series.
---

# Time charts

A chart here answers **how a number moved over time**. One JSON file (schema `time-charts/1`) holds every chart
on the page; `scripts/time_charts.py` checks it and builds one HTML file that makes no network request. uPlot is
inlined from `assets/vendor/` (MIT, checksums in `VERSION.txt`).

Requirements: Python 3.9+ (stdlib only). Optional: Node to run the JS test; Playwright to screenshot.

## The schema

```json
{"schema": "time-charts/1", "title": "HELIX — refit telemetry", "notes": ["one line each, under the title"],
 "charts": [{"title": "CO₂ by deck", "unit": "%", "kind": "line", "ymax": 0.6, "ref": 0.5, "refLabel": "limit",
             "xs": [1999395600, 1999399200],
             "series": [{"label": "Deck A", "values": [0.41, null]}]}]}
```

| Field | Meaning |
|---|---|
| `xs` | unix **seconds**, strictly increasing (milliseconds are rejected) |
| `series[].values` | one per x; `null` is "no sample" and draws a gap. Never write 0 for a missing value |
| `kind` | `line` (default), `area` (stacked), `bars` (stacked), `step` (a value that holds until it changes) |
| `unit` | appended to every value (`"%"` caps the axis at 100 unless the data goes above) |
| `ref`, `refLabel` | a dashed threshold line |
| `ymax` | the axis top; the default is the peak + 8 % |

At most six series take a hue (the theme's `--t1`…`--t6`, in order, and the colour follows the series, never its
rank); a seventh is "other". More than six is a warning: fold the tail into "other" or split the chart. One axis
per chart, always: two measures of different scale are two charts.

## Procedure

1. **Gather the series** and write the JSON. Align series on one `xs` grid; where a series has no sample, `null`.
2. `python3 scripts/time_charts.py check series.json` — fix every error.
3. `python3 scripts/time_charts.py build series.json -o page.html`.
4. **Look at it.** Open or screenshot the page; drag across a chart (it zooms, its neighbours do not move),
   hover (the tooltip shows raw, unstacked values), double-click (it resets). The checker checks data, not layout.

## What a reader can do

Drag across a chart to zoom x; Ctrl+wheel (or a trackpad pinch) zooms at the cursor; two fingers pinch on a
phone, one finger pans once zoomed; double-click resets; a legend click hides a series; **TABLE VIEW** opens the
numbers. Midnight ticks carry the date, the rest the hour (UTC).

## Live data: a PromQL range query from the browser

`assets/charts.js` works without the build script. Load the theme, `vendor/uPlot.min.css`, `charts.css`,
`vendor/uPlot.iife.min.js` and `charts.js` in a page, then call `TimeCharts.plot(container, options)` with the
result of a range query. The metrics server must send CORS headers for the page's origin (on
VictoriaMetrics/Prometheus behind a proxy, `Access-Control-Allow-Origin`).

```js
async function range(base, q, hours = 24, step = 300) {
  const end = Math.floor(Date.now() / 1000), start = end - hours * 3600;
  const r = await fetch(`${base}/api/v1/query_range?${new URLSearchParams({ query: q, start, end, step })}`);
  const j = await r.json();
  if (j.status !== "success") throw new Error(j.error);
  const xs = []; for (let t = start - (start % step); t <= end; t += step) xs.push(t);   // one grid for all series
  const series = j.data.result.map((s, k) => {
    const at = new Map(s.values.map(([t, v]) => [Math.round(t), Number(v)]));
    return { name: s.metric.job || JSON.stringify(s.metric), vals: xs.map(t => at.has(t) ? at.get(t) : null),
             color: `var(--t${k + 1})` };
  });
  return { xs, series };
}
const { xs, series } = await range("https://metrics.example.org", "sum by (job)(up)");
const box = TimeCharts.plot(document.querySelector("#up"), { xs, series, kind: "line", unit: "" });
// before redrawing the same container: box.uplot.destroy(); box.remove();
```

`plot()` options: `xs`, `series: [{name, vals, color, fill, dash}]`, `ref: {name, vals, color}`,
`kind: "line" | "stack" | "bars" | "step"`, `unit`, `ymax`, `height`, `endLabels`, `spanGaps` (the tooltip then
carries the last value forward), `inset`. An empty result is **N/D**, not a flat zero: show the `fc-offline`
box instead of plotting `or vector(0)` unless zero is true.

## Traps

- **Never put charts with different x ranges in one uPlot `cursor.sync` group.** uPlot's sync also syncs the x
  scale, so zooming one chart drags every other chart to the same window. `charts.js` uses no sync group.
- **Seconds, not milliseconds.** uPlot's time scale is in seconds here; `check` rejects millisecond `xs`.
- **Stacked kinds draw cumulative values;** the tooltip and table keep the raw ones. A negative value in a stack
  is an error.
- **Canvas cannot read CSS variables.** `TimeCharts.color("var(--t1)")` resolves one from `:root`; pass colours
  through it when drawing on a canvas yourself.

## Relation to the other skills

`scifi-graph` draws what leads to what and what it costs; `goal-map` how far along each goal is; this skill how a
number moved. All three share `shared/theme.css` and look like one system.
