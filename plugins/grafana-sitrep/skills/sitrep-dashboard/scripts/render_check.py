#!/usr/bin/env python3
"""Render a dashboard headless and report what an operator would trip on. Needs `pip install playwright` and
`playwright install chromium`.

    GRAFANA_TOKEN=... python3 render_check.py 'https://grafana.example/d/uid/slug?kiosk' shot.png
    GRAFANA_TOKEN_FILE=/path/to/token python3 render_check.py ...

The token is read from the environment or from the file GRAFANA_TOKEN_FILE names, never from argv (argv is
visible to every user in `ps`). The file form lets the check reuse the token an MCP server already keeps on
disk (mcp-grafana's GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE) without the token passing through a shell or a log.
For a templated page, put the variables in the URL (`&var-node=...`); the page otherwise opens on its default. Exit 1 if any
check fails; the screenshot is written either way, so read it with the operator's eyes after the numbers pass.
"""
import asyncio
import collections
import os
import sys

from playwright.async_api import async_playwright

CHECKS = """() => {
  const sheets = [...document.querySelectorAll('.bp')];
  const links = [...document.querySelectorAll('.bp a')];
  const text = sheets.map((s) => s.innerText).join('\\n');
  return {
    sheets: sheets.length,
    links: links.length,
    hosts: links.map((l) => (l.getAttribute('href') || '').split('/').slice(0, 5).join('/')),
    sameTab: links.filter((l) => l.getAttribute('target') !== '_blank').map((l) => l.getAttribute('href')),
    junk: (text.match(/\\bundefined\\b|\\bNaN\\b|\\[object Object\\]/g) || []).length,
    noSitrep: sheets.filter((s) => !s.querySelector('.br')).map((s) => s.querySelector('.ti')?.innerText),
    noData: [...document.querySelectorAll('[data-testid="data-testid Panel header"], .panel-container')]
      .filter((p) => /No data/.test(p.innerText)).map((p) => p.innerText.split('\\n')[0]),
  };
}"""


async def main(url, shot):
    token = os.environ.get("GRAFANA_TOKEN")
    if not token and os.environ.get("GRAFANA_TOKEN_FILE"):
        with open(os.environ["GRAFANA_TOKEN_FILE"]) as f:
            token = f.read().strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1800, "height": 3400}, extra_http_headers=headers)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:300]))
        await pg.goto(url, wait_until="load", timeout=90000)
        await pg.wait_for_timeout(8000)
        # Grafana renders a panel only once it scrolls into view: wheel through the page, or every panel below the
        # fold is missing from the checks (and blank in the screenshot)
        await pg.mouse.move(900, 600)
        for _ in range(60):
            await pg.mouse.wheel(0, 1200)
            await pg.wait_for_timeout(700)
        await pg.wait_for_timeout(8000)  # queries and the panel helpers run after a panel mounts
        await pg.screenshot(path=shot, full_page=True)
        r = await pg.evaluate(CHECKS)
        await b.close()
    print(f"{r['sheets']} sheets, {r['links']} links")
    for host, n in collections.Counter(r["hosts"]).most_common(10):
        print(f"  {n:4d}  {host}")
    fails = []
    if not r["sheets"]:
        fails.append("no status sheet rendered (plugin missing, or a helper threw)")
    if r["sameTab"]:
        fails.append(f"{len(r['sameTab'])} link(s) open in the dashboard's tab: {r['sameTab'][:3]}")
    if r["junk"]:
        fails.append(f"{r['junk']} undefined/NaN string(s) on the sheets")
    if r["noSitrep"]:
        fails.append(f"sheets without a SITREP line: {r['noSitrep']}")
    if r["noData"]:
        fails.append(f"panels reading 'No data': {r['noData']}")
    if errors:
        fails.append(f"page errors: {errors[:3]}")
    for f in fails:
        print("FAIL", f)
    print("screenshot:", shot)
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
