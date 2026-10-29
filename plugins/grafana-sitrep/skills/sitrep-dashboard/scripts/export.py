#!/usr/bin/env python3
"""Export a dashboard from Grafana to a file: the original a generator reads (step 1).

    GRAFANA_TOKEN_FILE=/path/to/token python3 export.py https://grafana.example <uid> orig.json [--force]

The JSON goes from Grafana to the file, never through the model: a copy retyped from a tool result can drop one
escape in a long SQL query, and the generator, coverage() and the hand-over then all work from a wrong original.
The token is read and checked as deploy.py reads it (see grafana_api.py); Viewer is enough. The URL may be a
dashboard link (`.../d/<uid>/slug?kiosk`). An existing file is kept unless --force: it may be the only original.

It writes the `dashboard` object as Grafana's own "Export > Save to file" does (indent 2, UTF-8), and prints the
panel and query counts to compare with what the page shows.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grafana_api  # noqa: E402
import sitrep  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grafana_url")
    ap.add_argument("uid")
    ap.add_argument("out")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() and not a.force:
        raise SystemExit(f"{out} exists: it may be the original a generator reads. Pass --force to overwrite it")
    base, tok = grafana_api.base_of(a.grafana_url), grafana_api.token()
    if not tok:
        raise SystemExit("no token: set GRAFANA_TOKEN or GRAFANA_TOKEN_FILE")
    grafana_api.preflight(base, tok)
    try:
        r = grafana_api.call(base, f"/api/dashboards/uid/{urllib.parse.quote(a.uid)}", tok)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"reading dashboard {a.uid}: HTTP {e.code}" + (" (no such uid here)" if e.code == 404 else ""))
    except OSError as e:
        raise SystemExit(f"reading dashboard {a.uid}: {getattr(e, 'reason', e)}")
    d = r["dashboard"]
    out.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    panels = [p for p in sitrep.walk(d.get("panels", [])) if p.get("type") != "row"]
    queries = sum(1 for p in panels for t in p.get("targets", []) if t.get("expr") or t.get("rawSql"))
    print(f"{out}: {d.get('title')!r} version {d.get('version')}, {len(panels)} panel(s), {queries} quer(ies), "
          f"{out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
