#!/usr/bin/env python3
"""Deploy a generated dashboard to Grafana: one POST to /api/dashboards/db.

    GRAFANA_TOKEN_FILE=/path/to/token python3 deploy.py out.json https://grafana.example [--folder <uid>] [-m "why"]

The JSON goes from the file to Grafana, so its size does not matter (a dozen sheets is well over 100 KB, too large
to pass reliably as a tool-call argument), and the token never passes through the model, a shell or argv: it is
read from GRAFANA_TOKEN or the file GRAFANA_TOKEN_FILE names, and checked first (see grafana_api.py). The token
needs the Editor role on the folder.

Without --folder, a dashboard that exists stays in its folder; a new one goes to the General folder. The
dashboard keeps its uid, so links to it still work; its numeric id is left to Grafana.
"""
import argparse
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grafana_api  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard")
    ap.add_argument("grafana_url")
    ap.add_argument("--folder", help="folder uid; default: where the dashboard is now")
    ap.add_argument("-m", "--message", default="sitrep regenerate", help="the version-history note")
    a = ap.parse_args()
    d = json.loads(Path(a.dashboard).read_text())
    if not d.get("uid"):
        raise SystemExit("the dashboard has no uid: keep the original's, so links to it still work")
    base, tok = grafana_api.base_of(a.grafana_url), grafana_api.token()
    if not tok:
        raise SystemExit("no token: set GRAFANA_TOKEN or GRAFANA_TOKEN_FILE")
    grafana_api.preflight(base, tok)
    folder = a.folder
    if folder is None:
        try:
            folder = grafana_api.call(base, f"/api/dashboards/uid/{d['uid']}", tok)["meta"].get("folderUid") or ""
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise SystemExit(f"reading the current dashboard: HTTP {e.code}")
            folder = ""
        except OSError as e:  # URLError, a timeout, a reset: the network, not the request
            raise SystemExit(f"reading the current dashboard: {getattr(e, 'reason', e)}")
    d = dict(d, id=None)
    body = {"dashboard": d, "overwrite": True, "message": a.message, **({"folderUid": folder} if folder else {})}
    try:
        r = grafana_api.call(base, "/api/dashboards/db", tok, body)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"deploy refused: HTTP {e.code} {e.read()[:300].decode(errors='replace')}")
    except OSError as e:
        raise SystemExit(f"deploy failed, Grafana not reached: {getattr(e, 'reason', e)}. Nothing was saved, or check "
                         "the dashboard's version history before retrying")
    print(f"{r.get('status')}: {base}{r.get('url')} version {r.get('version')} ({len(json.dumps(d)) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
