# eakot-mp

A [Claude Code plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces) of things
worth sharing. Every plugin here works in any repository and names none.

```
/plugin marketplace add eakot/eakot-mp
/plugin install grafana-sitrep@eakot-mp
```

| Plugin | What it does |
|---|---|
| [`grafana-sitrep`](plugins/grafana-sitrep/skills/sitrep-dashboard/SKILL.md) | Refactors a Grafana dashboard into "sitrep" status sheets: a monospace mission briefing whose first line is the verdict and the move, then a table of contents of every number (`label ..... value [OK/WARN/ACT]`), every repo, PR, issue, commit and workflow a link, beside history charts that cannot draw an impossible peak. The agent works in the operator's role: it asks the questions a reader asks of each panel and answers them from live data, and brings the human only the rulings (thresholds, what "today" means, what idle is intended). Needs Grafana 11.3 and the Business Text panel: see [requirements](#grafana-sitrep-requirements). |

### `grafana-sitrep` requirements

| Component | Version | Needed for |
|---|---|---|
| Grafana OSS | **11.3** (tested on 11.3.0) | the page. Status sheets are HTML plus JavaScript in a panel, so a newer major release needs a re-test |
| [Business Text](https://grafana.com/grafana/plugins/marcusolsson-dynamictext-panel/) panel (`marcusolsson-dynamictext-panel`) | **6.2.0** | every status sheet. 6.2.0 is the newest release that supports Grafana 11.x; 6.2.3 and later need Grafana 12.3 |
| [Infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/) datasource (`yesoreyeram-infinity-datasource`) | **3.7.1** | only sheets that read a live JSON table (a repo registry, a work feed). 3.7.1 is the last release that loads on 11.3 |
| [VictoriaMetrics](https://victoriametrics.com/) as the PromQL datasource | any current release | `sitrep.today()` puts a computed timestamp after `@` (`@ (time() - time() % 86400)`), which VictoriaMetrics accepts and Prometheus does not: Prometheus allows only a fixed timestamp, `start()` or `end()`. On Prometheus, rewrite `today()` before using it |
| Python | 3, standard library only | `scripts/sitrep.py` and the generators |
| [Playwright](https://playwright.dev/python/) with Chromium | any current release | only `scripts/render_check.py`: `pip install playwright && playwright install chromium` |
| [Node.js](https://nodejs.org/) | any current release | only `scripts/sheet_harness.py`, which runs every sheet against live data before deploying |

Pin both Grafana plugins in the install, for example in Docker Compose:

```yaml
GF_INSTALL_PLUGINS: "marcusolsson-dynamictext-panel 6.2.0,yesoreyeram-infinity-datasource 3.7.1"
GF_DATE_FORMATS_DEFAULT_TIMEZONE: browser   # every timestamp in the reader's zone
```

The sheet font (Share Tech Mono) loads from Google Fonts and falls back to the system monospace.

## What a sitrep page looks like

![Two sitrep status sheets: the lanes' numbers on the left, the nodes in flight on the right](docs/sitrep-dashboard.png)

A live operator page made with `grafana-sitrep`, one row of two sheets:

- **The SITREP line comes first** (left). It names the verdict and the move: the supervisor is silent on an
  open day, so restart the driver.
- **Every number is a contents line**: `label ..... value [TAG]`. The tags mean the same on every sheet:
  `OK` fine, `WARN` look, `ACT` someone must act. Only `ACT` blinks.
- **Fixed-width fields lead each list line** (right): node id, lane, model, topic. The title then starts
  at the same column on every line, and the full task text shows on hover instead of being cut off.
- **Every id, PR and issue is a link**, dimmed when it is secondary. Colour means state and nothing else.
  The background is flat, and nothing decorative crosses the text.

## Adding a plugin

One directory under `plugins/<name>/` with a `.claude-plugin/plugin.json`, plus one entry in
`.claude-plugin/marketplace.json`. Run `claude plugin validate .` before pushing. A plugin that only makes
sense in one repository belongs in that repository's `.claude/`, not here.

## License

MIT — see [LICENSE](LICENSE).
