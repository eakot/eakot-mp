"""The Grafana HTTP API for the scripts here: one token reader and one preflight, so every script fails the same way
on a token that is not Grafana's.

The token comes from GRAFANA_TOKEN, or from the file GRAFANA_TOKEN_FILE names, never from argv (argv is visible to
every user in `ps`). It must be a Grafana service-account token (prefix `glsa_`). A gateway's token, such as the
one an MCP server in front of Grafana takes, is not one: Grafana answers it with 401 "Invalid API key".
"""
import json
import os
import urllib.error
import urllib.request


def token():
    t = os.environ.get("GRAFANA_TOKEN")
    if not t and os.environ.get("GRAFANA_TOKEN_FILE"):
        with open(os.environ["GRAFANA_TOKEN_FILE"]) as f:
            t = f.read().strip()
    return t or None


def base_of(url):
    """https://grafana.example/sub/d/uid/slug?kiosk -> https://grafana.example/sub"""
    u = url.split("?", 1)[0]
    return u.split("/d/", 1)[0].rstrip("/") if "/d/" in u else u.rstrip("/")


def call(base, path, tok, body=None, timeout=60):
    req = urllib.request.Request(base.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def preflight(base, tok):
    """Raise SystemExit with the reason when Grafana does not accept the token. Says which kind of token it
    looks like, not the token."""
    if not tok:
        return
    try:
        call(base, "/api/search?limit=1", tok)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            kind = "a service-account token" if tok.startswith("glsa_") else "NOT a Grafana service-account token"
            raise SystemExit(
                f"Grafana at {base} refused the token ({e.code}). It is {kind} (those start with glsa_). "
                + ("Check that it is not expired or revoked, and its role." if tok.startswith("glsa_") else
                   "A token for a gateway in front of Grafana (an MCP server's, say) does not work here: create a "
                   "service account in Grafana (Administration > Service accounts) and pass its token."))
        raise SystemExit(f"Grafana at {base}: HTTP {e.code} on the preflight")
    except urllib.error.URLError as e:
        raise SystemExit(f"Grafana at {base} is unreachable: {e.reason}")
