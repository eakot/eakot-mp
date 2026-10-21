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
const pct = (x, d) => (x == null ? '—' : `${(x * 100).toFixed(d == null ? 0 : d)}%`);
const num = (x, d) => (x == null ? '—' : Number(x).toFixed(d || 0));
const usd = (x) => (x == null ? '—' : x >= 100 ? `$${Math.round(x).toLocaleString('en-US')}` : `$${x.toFixed(2)}`);

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
const item = (text, state, wrap) => `<div class="it s-${state || 'idle'}${wrap ? ' wrap' : ''}">${text}</div>`;
const brief = (text) => `<div class="br"><span class="bl">SITREP</span> ${text}</div>`;
const foot = (text) => `<div class="ft">${text}</div>`;
// A file shown as written. Its newlines go in as &#10;: a literal one would be stripped by page(), and a blank line
// would end the panel's HTML block, so the markdown pass would turn the rest of the file into headings and lists.
const raw = (text) => `<pre class="raw">${esc(text).replace(/\n/g, '&#10;')}</pre>`;
const page = (no, title, body) => `<div class="bp"><div class="hd"><span class="no">${no}</span><span class="ti">${title}</span></div>${body}</div>`.replace(/\n\s*/g, '');
const worst = (states) => ['bad', 'warn', 'nd', 'ok', 'info', 'idle'].find((s) => states.includes(s)) || 'idle';
