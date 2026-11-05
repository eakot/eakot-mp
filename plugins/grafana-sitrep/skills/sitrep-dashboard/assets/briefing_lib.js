// ---- sitrep renderer: shared by every status sheet on the page ----
// Generated into each Business Text panel by scripts/sitrep.py. Edit assets/briefing_lib.js and regenerate;
// a hand edit inside one panel drifts from the other sheets.
const HB = context.handlebars;
const SERIES = (context.panelData && context.panelData.series) || [];
const arr = (v) => (Array.isArray(v) ? v : v && v.toArray ? v.toArray() : []);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
// every number field of every frame of a refId, as {labels, value}: the shape of a Prometheus instant query
const rows = (ref) => SERIES.filter((f) => f.refId === ref).flatMap((f) =>
  f.fields.filter((x) => x.type === 'number').map((x) => {
    const v = arr(x.values);
    return { labels: x.labels || {}, value: v.length ? v[v.length - 1] : null };
  })).filter((r) => r.value != null && !Number.isNaN(r.value));
const one = (ref) => { const r = rows(ref); return r.length ? r[0].value : null; };
// a table frame (Infinity, SQL), as row objects keyed by column name
const table = (ref) => {
  const f = SERIES.find((x) => x.refId === ref);
  if (!f) return [];
  const cols = f.fields.map((x) => [x.name, arr(x.values)]);
  const n = cols.length ? cols[0][1].length : 0;
  return Array.from({ length: n }, (_, i) => Object.fromEntries(cols.map(([k, v]) => [k, v[i]])));
};

// ---- links: every git entity on a sheet is one ----
// repo label -> owner/name. A live registry wins: a table frame refId 'RP' with columns label, slug. Otherwise the
// static map the generator wrote below. A Map, never a plain object: `constructor#5` must not find Object.prototype.
const FORGE = /*FORGE*/'https://github.com';
const REPOS_STATIC = /*REPOS*/{};
const RP = table('RP');
const SLUGS = new Map(RP.length ? RP.filter((r) => r.label && r.slug).map((r) => [r.label, r.slug]) : Object.entries(REPOS_STATIC));
// an unknown repo stays plain text: a guessed URL 404s, and a dead link is worse than none
const repoUrl = (repo) => (SLUGS.has(repo) ? `${FORGE}/${SLUGS.get(repo)}` : null);
const a = (href, text, cls) => `<a href="${esc(href)}" target="_blank" rel="noopener"${cls ? ` class="${cls}"` : ''}>${text}</a>`;
const via = (repo, path, text, cls) => { const u = repoUrl(repo); return u ? a(u + path, text, cls) : text; };
const repoA = (repo) => via(repo, '', `<span class="rp">${esc(repo)}</span>`);
const prA = (repo, n, text) => via(repo, `/pull/${n}`, text || `#${esc(n)}`, text ? '' : 'id');
const commitA = (repo, sha) => via(repo, `/commit/${sha}`, esc(String(sha).slice(0, 7)), 'id');
const fileA = (repo, path, text, ref) => via(repo, `/blob/${ref || 'main'}/${path}`, text || esc(path), text ? '' : 'id');
const wfA = (repo, wf, text) => via(repo, `/actions?query=${encodeURIComponent(`workflow:"${wf}" branch:main`)}`, text || esc(wf));
// "api#297" -> that repo, "owner/name#3" -> as written, a bare "#2607" -> `dflt`'s
const refA = (ref, dflt) => {
  const m = String(ref || '').match(/^(?:([\w.-]+\/[\w.-]+)|([\w.-]+))?#(\d+)$/);
  if (!m) return esc(ref || '');
  if (m[1]) return a(`${FORGE}/${m[1]}/issues/${m[3]}`, esc(ref), 'id');
  return via(m[2] || dflt, `/issues/${m[3]}`, esc(ref), 'id');
};
// free text -> escaped HTML whose issue/PR refs are links. Escape FIRST, then link: the lookbehind's `&` keeps the
// `#39` inside an escaped apostrophe (`&#39;`) from becoming a link to issue 39.
const linkify = (text, repo) => esc(text)
  .replace(/(?<![\w#\/.&-])(?:[\w.-]+\/[\w.-]+|[a-z][\w-]*)?#\d+\b/g, (m) => refA(m, repo));

// ---- values ----
const DAY = new Date().toISOString().slice(0, 10); // the UTC day: say so in the description of any "today" number
const dur = (s) => {
  if (s == null) return '—';
  s = Math.max(0, Math.round(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${String(h).padStart(2, '0')}h` : h ? `${h}h ${String(m).padStart(2, '0')}m` : m ? `${m}m` : `${s}s`;
};
// A duration in a COLUMN: one width for every value, so "22 h" and " 5 h" line up. Two units, each number padded
// to two places with a FIGURE SPACE (a digit's width in any font, and never collapsed by HTML), the whole value
// right-aligned to 9: "17 d  7 h", " 9 h 57 m", "     45 m". `dur` stays for a value inside a sentence.
const FIG = '\u2007';
const durCol = (s) => {
  if (s == null) return '—'.padStart(9, FIG);
  s = Math.max(0, Math.round(s));
  const p2 = (n) => String(n).padStart(2, FIG);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  const v = d ? `${p2(d)} d ${p2(h)} h` : h ? `${p2(h)} h ${p2(m)} m` : m ? `${p2(m)} m` : `${p2(s)} s`;
  return v.padStart(9, FIG);
};
const pct = (x, d) => (x == null ? '—' : `${(x * 100).toFixed(d == null ? 0 : d)}%`);
const num = (x, d) => (x == null ? '—' : Number(x).toFixed(d || 0));
const usd = (x) => (x == null ? '—' : x >= 100 ? `$${Math.round(x).toLocaleString('en-US')}` : `$${x.toFixed(2)}`);
// A size in bytes, base 1024 (as pg_size_pretty and `du -h`; say so in the (i)): "512 B", "5.3 GB", "123 GB". One
// decimal below 100. In a column: fxr(8, bytes(x)).
const bytes = (x) => {
  if (x == null || Number.isNaN(Number(x))) return '—';
  const U = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = Math.abs(Number(x)), i = 0;
  while (v >= 1024 && i < U.length - 1) { v /= 1024; i++; }
  let s = i === 0 || v >= 99.95 ? String(Math.round(v)) : v.toFixed(1);
  if (Number(s) >= 1024 && i < U.length - 1) { s = '1.0'; i++; } // 1023.7 KB rounds to 1.0 MB, not "1024 KB"
  return `${x < 0 ? '-' : ''}${s} ${U[i]}`;
};
// A whole number with the sheet's digit grouping (sheet(locale=...)): 12 345 in ru-RU, 12,345 in en-US.
const LOCALE = /*LOCALE*/'en-US';
const int = (x) => { if (x == null) return '—'; const r = Math.round(x); return (r === 0 ? 0 : r).toLocaleString(LOCALE); }; // never "-0"; NaN stays NaN
// The word that goes with n, in the sheet's language: forms = [one, other] (English) or [one, few, many] (Russian
// and the other Slavic languages): `${int(n)} ${plural(n, ['человек', 'человека', 'человек'])}`.
const plural = (n, forms) => {
  n = Math.abs(Math.round(n));
  if (forms.length < 3) return forms[n === 1 ? 0 : 1];
  const d = n % 10, dd = n % 100;
  return forms[d === 1 && dd !== 11 ? 0 : d >= 2 && d <= 4 && (dd < 12 || dd > 14) ? 1 : 2];
};

// ---- the sheet ----
// ok = fine · warn = look · bad = someone must act · info = idle on purpose · nd = no data (never shown as 0) · idle = context
const TAG = { ok: 'OK', warn: 'WARN', bad: 'ACT', info: 'INFO', idle: '····', nd: 'N/D' };
// level from thresholds: [[limit, level], ...] ascending; the first level applies below the first limit
const lvl = (x, steps) => { if (x == null) return 'nd'; let l = steps[0][1]; for (const [lim, s] of steps.slice(1)) if (x >= lim) l = s; return l; };
// one table-of-contents line: label .......... value [TAG]
const ln = (label, value, state, note) =>
  `<div class="ln s-${state || 'idle'}"><span class="lb">${label}</span><span class="dt"></span><span class="v">${value}</span><span class="tg">${TAG[state || 'idle']}</span></div>` +
  (note ? `<div class="nt">${note}</div>` : '');
const sub = (text) => `<div class="sh">▸ ${text}</div>`;
// A list line. `tip` is text too long for the line: it shows whole on hover instead of being cut by the ellipsis.
const item = (text, state, wrap, tip) =>
  `<div class="it s-${state || 'idle'}${wrap ? ' wrap' : ''}"${tip ? ` title="${esc(tip)}"` : ''}>${text}</div>`;
// A fixed-width column, `w` in ch. Fixed fields lead a line, so every line's free text starts at the same column.
// min-width, not width: an unexpected long value pushes the line instead of being clipped.
const fx = (w, html) => `<span class="fx dim" style="min-width:${w}ch">${html}</span>`;
// A number in a fixed-width column, right-aligned: padded with figure spaces (a digit's width, never collapsed), so
// the last digits line up like durCol's. Not dim: in a table the numbers are the point. `v` is plain TEXT (a number,
// int(n), durCol(s)), escaped here, unlike fx()'s html.
const fxr = (w, v) => `<span class="fx fxr" style="min-width:${w}ch">${esc((v == null ? '—' : String(v)).padStart(w, FIG))}</span>`;
// A TABLE inside a contents box: the one way to put columns on a sheet. The title is its own sub() line; the
// column names are the header row, drawn from the same width spec as every row, so the two cannot drift apart.
//   const T = cols([[24, 'tool'], [6, 'calls', 'r'], [9, 'p95', 'r'], [0, 'client']], { tag: true });
//   sub('airflow — 754 calls') + T.hdr + list.map((r) => T.line([esc(r.tool), int(r.calls), durCol(r.p95), esc(r.client)], r.state)).join('')
// w > 0: a fixed column of w ch, widened to fit its title. A left cell is clipped with an ellipsis (whole on hover),
//   so a long value never pushes the columns after it; a right ('r') cell, a number, is never clipped: size w to the
//   longest value.
// w = 0: free text, the LAST column only: a free column in the middle moves every column after it, so cols() throws.
// opt.tag: the state tag (OK, WARN, ...) gets its own column at the right edge, the same on every line.
// Every cell has one font size in the header and the rows, so a ch is one width everywhere, and cells are joined by
// a space of the line's font, the same in both: a gap that a full cell cannot close. Left cells are HTML, escaped by
// the caller, as with fx(); right cells are text, as with fxr(). T.line(values, state, tip) is the whole line;
// T.row(values) is only its cells, for item().
// A ch is a digit of the sheet's font, Share Tech Mono, which has no Cyrillic (nor Greek, CJK, ...): those letters
// come from a fallback font and are up to 1.15 ch wide. `chW(text)` is the width text needs, in ch.
const CH_WIDE = 1.15;
const chW = (text) => {
  const t = [...String(text)];
  return Math.ceil(t.length * (t.some((c) => { const n = c.codePointAt(0); return n > 0x24f && (n < 0x2000 || n > 0x206f); }) ? CH_WIDE : 1));
};
const cols = (spec, opt) => {
  const free = spec.findIndex(([w]) => !w);
  if (free >= 0 && free < spec.length - 1) throw new Error(`cols(): column ${free + 1} (${spec[free][1]}) has w = 0; only the last column may be free text`);
  // the one width spec: a title never clips, and the header and the rows read the same widths
  const S = spec.map(([w, title, al]) => [w ? Math.max(w, chW(title)) : 0, title, al]);
  const tag = !!(opt && opt.tag);
  const plain = (h) => String(h).replace(/<[^>]*>/g, ''); // still escaped: fit for an attribute
  // clip = a left cell: a fixed width, an ellipsis, and the whole text on hover when it may be cut
  const box = (w, cls, h, clip) => {
    const tip = clip && chW(plain(h).replace(/&[^;\s]+;/g, '_')) > w ? ` title="${plain(h)}"` : '';
    return `<span class="tc${clip ? ' tcl' : ''}${cls}" style="${clip ? 'width' : 'min-width'}:${w}ch"${tip}>${h}</span>`;
  };
  const lead = new RegExp(`^${FIG}+`);
  const cell = ([w, , al], v) => {
    if (al === 'r') {
      // TEXT, escaped here. No figure-space padding: text-align does it, and a padding glyph from a fallback font
      // could be wider than a ch and push the cell
      const t = esc(v == null ? '—' : String(v).replace(lead, ''));
      return w ? box(w, ' tcr', t) : `<span class="tc tf">${t}</span>`;
    }
    const h = v == null ? '—' : String(v);
    return w ? box(w, '', h, true) : `<span class="tc tf">${h}</span>`;
  };
  // a title is text: escaped here; its cell is as wide as the column's, so it sits over it
  const head = ([w, title, al]) => (w ? box(w, al === 'r' ? ' tcr' : '', esc(title), true) : `<span class="tc tf">${esc(title)}</span>`);
  const row = (values) => S.map((c, i) => cell(c, values[i])).join(' ');
  return {
    hdr: `<div class="it ch${tag ? ' tl' : ''}">${S.map(head).join(' ')}</div>`,
    row,
    line: (values, state, tip) => `<div class="it${tag ? ' tl' : ''} s-${state || 'idle'}"${tip ? ` title="${esc(tip)}"` : ''}>` +
      row(values) + (tag ? ` <span class="tg">${TAG[state || 'idle']}</span>` : '') + '</div>',
  };
};
// The verdict line. Its label is the sheet's (sheet(brief_label=...)); null drops it, and the yellow rule on the left
// still marks the line: a page read outside the team does not need the jargon.
const BRIEF_LABEL = /*BRIEF_LABEL*/'SITREP';
const brief = (text) => `<div class="br">${BRIEF_LABEL ? `<span class="bl">${esc(BRIEF_LABEL)}</span> ` : ''}${text}</div>`;
const foot = (text) => `<div class="ft">${text}</div>`;
// A file shown as written. Its newlines go in as &#10;: a literal one would be stripped by page(), and a blank line
// would end the panel's HTML block, so the markdown pass would turn the rest of the file into headings and lists.
const raw = (text) => `<pre class="raw">${esc(text).replace(/\n/g, '&#10;')}</pre>`;
const page = (no, title, body) => `<div class="bp"><div class="hd"><span class="no">${no}</span><span class="ti">${title}</span></div>${body}</div>`.replace(/\n\s*/g, '');
const worst = (states) => ['bad', 'warn', 'nd', 'ok', 'info', 'idle'].find((s) => states.includes(s)) || 'idle';

// ---- graph views: rectangles in rows ----
// A graph is rows of RECTANGLES, read left to right: one row per lane / queue, nodes in their real order.
// The text sits INSIDE the box (fixed fields first: id, then the name, then the topic); the state reads ONCE,
// UNDER the box, in its state colour. Grafana's Node Graph draws circles, with the state inside and the name
// under them, so it is not used for a sitrep graph.
//   rows  = [{label, nodes: [{key, html, state, below, tip, col}]}]   html = the box's inside (escape it!); link the name
//   INSIDE it with a(), never wrap the box in <a>: a block inside a link loses the sheet's font.
//   edges = [{from, to, kind}]   kind = a CSS class: 'next' (order in the row), 'after' (a dependency), 'land'
// The edges are drawn by afterRender (sitrep.py), because the panel's sanitizer keeps no <svg> in html.
const flowKey = (k) => 'fk-' + String(k).replace(/[^\w-]/g, '_');
// opt.w = box width in ch (30), opt.lines = box height in lines (3). Inside the html, `<div class="w2">` wraps a long
// text (a task, a verdict, a title) over two lines and clips the rest; put the whole text in the node's `tip`.
const flow = (rows, edges, opt) => {
  const w = (opt && opt.w) || 30, lines = (opt && opt.lines) || 3;
  const box = (n) => {
    return `<div class="fn ${flowKey(n.key)}"${n.tip ? ` title="${esc(n.tip)}"` : ''}>` +
      `<div class="fb s-${n.state || 'idle'}" style="width:${w}ch;height:${(lines * 1.45).toFixed(2)}em">${n.html}</div>` +
      `<div class="fs s-${n.state || 'idle'}">${esc(n.below || '')}</div></div>`;
  };
  // `col` (optional) pins a node under a column of the rows above, so a dependency is a short vertical arrow;
  // a taken column moves the node to the next free one, and empty columns keep their width.
  const place = (nodes) => {
    if (!nodes.some((n) => Number.isInteger(n.col))) return nodes.map(box).join('');
    const at = [];
    nodes.forEach((n) => { let c = Number.isInteger(n.col) ? n.col : at.length; while (at[c]) c++; at[c] = n; });
    return Array.from(at, (n) => (n ? box(n) : `<div class="fn fgap" style="width:${w}ch"></div>`)).join('');
  };
  const body = rows.filter((r) => r.nodes.length).map((r) =>
    `<div class="fr"><div class="fl">${esc(r.label)}</div><div class="fns">${place(r.nodes)}</div></div>`).join('');
  const keys = new Set(rows.flatMap((r) => r.nodes.map((n) => flowKey(n.key))));
  const E = (edges || []).map((e) => [flowKey(e.from), flowKey(e.to), e.kind || 'next']).filter(([a, b]) => keys.has(a) && keys.has(b));
  return `<div class="flow">${body}<span class="fe" style="display:none">${esc(JSON.stringify(E))}</span></div>`;
};
