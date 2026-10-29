"""The Grafana HTTP API for the scripts here: one token reader and one preflight, so every script fails the same way
on a token that is not Grafana's.

The token comes from GRAFANA_TOKEN, or from the file GRAFANA_TOKEN_FILE names, never from argv (argv is visible to
every user in `ps`). It must be a Grafana service-account token (prefix `glsa_`). A gateway's token, such as the
one an MCP server in front of Grafana takes, is not one: Grafana answers it with 401 "Invalid API key".
"""
import json
import os
import sys
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib would carry the Authorization header to wherever a redirect points: refuse instead
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirected to {newurl}: refused, the token would follow. "
                                     "Give the final URL (https, the right host)", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def urlopen(req, timeout=60):
    """urllib.request.urlopen that never follows a redirect while the request carries a token."""
    if req.has_header("Authorization"):
        return _OPENER.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def token():
    t = os.environ.get("GRAFANA_TOKEN")
    if not t and os.environ.get("GRAFANA_TOKEN_FILE"):
        with open(os.environ["GRAFANA_TOKEN_FILE"]) as f:
            t = f.read().strip()
    return t or None


def token_source():
    """Where token() read it from, for a message: the variable, or the file's path. Never the token."""
    if os.environ.get("GRAFANA_TOKEN"):
        return "GRAFANA_TOKEN"
    if os.environ.get("GRAFANA_TOKEN_FILE"):
        return f"GRAFANA_TOKEN_FILE={os.environ['GRAFANA_TOKEN_FILE']}"
    return "no GRAFANA_TOKEN or GRAFANA_TOKEN_FILE"


def token_class(tok):
    """The token's prefix class, the only part of it a message may show."""
    return "empty" if not tok else "glsa_ (a service-account token)" if tok.startswith("glsa_") else \
        "other (NOT a Grafana service-account token)"


def base_of(url):
    """https://grafana.example/sub/d/uid/slug?kiosk -> https://grafana.example/sub"""
    u = url.split("?", 1)[0]
    return u.split("/d/", 1)[0].rstrip("/") if "/d/" in u else u.rstrip("/")


def call(base, path, tok, body=None, timeout=60):
    if tok and base.startswith("http://") and base.split("/")[2].split(":")[0] not in ("localhost", "127.0.0.1"):
        warn_cleartext(base)
    req = urllib.request.Request(base.rstrip("/") + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urlopen(req, timeout=timeout) as r:
        return json.load(r)


_warned = set()


def warn_cleartext(base):
    if base not in _warned:
        _warned.add(base)
        print(f"warning: {base} is plain http: the token crosses the network in clear text (fine on a private "
              "mesh, not on the internet)", file=sys.stderr)


def preflight(base, tok):
    """Raise SystemExit with the reason when Grafana does not accept the token. Says which kind of token it
    looks like, not the token."""
    if not tok:
        return
    try:
        call(base, "/api/search?limit=1", tok)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            host = base.split("/")[2] if "://" in base else base
            glsa = tok.startswith("glsa_")
            raise SystemExit(
                f"Grafana at {base} refused the token ({e.code}).\n"
                f"  host tried:   {host}\n"
                f"  token from:   {token_source()}\n"
                f"  token prefix: {token_class(tok)}\n"
                + ("A glsa_ token is valid on the one Grafana it was created on: if this is not that instance, it is "
                   "the wrong token, not a broken one. Otherwise check that it is not expired or revoked, and its role."
                   if glsa else
                   "A token for a gateway in front of Grafana (an MCP server's, say) does not work here: create a "
                   "service account in Grafana (Administration > Service accounts) and pass its token."))
        raise SystemExit(f"Grafana at {base}: HTTP {e.code} on the preflight ({e.msg})")
    except urllib.error.URLError as e:
        raise SystemExit(f"Grafana at {base} is unreachable: {e.reason}")
