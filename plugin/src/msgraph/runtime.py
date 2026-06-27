#!/usr/bin/env python3
"""msgraph-stdlib runtime — the low-level seam: HTTP, token cache, markers, Graph primitives.

This module owns the single mockable boundary (`_http`) and the mutable on-disk state paths
(`STATE_DIR`/`TOKEN_PATH`/`MARKER_PATH`), plus the kernel constants, the OAuth token cache, the
verification markers + catch-set logic, and the `_graph_url`/`_graph_get` primitives. Tests patch
`runtime._http` and the state paths here; everything else in the package reaches them via
`runtime.<name>` at call time so a patch is always honoured (feature 004 data-model: INV-1).

Imports only the standard library — it is the leaf of the package dependency DAG.
"""

import hashlib
import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP = "msgraph"


# Microsoft identity platform + Graph endpoints. Tenant from env (personal accounts use
# "consumers"; "common" covers work/school + personal). Client id from env — never hardcoded.
GRAPH = "https://graph.microsoft.com/v1.0"


def _tenant() -> str:
    return os.environ.get("MSGRAPH_TENANT_ID", "consumers")


def _client_id() -> str:
    return os.environ.get("MSGRAPH_CLIENT_ID", "")


def _authority() -> str:
    return f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0"


# The auth modes are the scope ratchet (research D2 / feature 003 R4). offline_access yields a refresh
# token for silent renewal. read mode includes MailboxSettings.Read so rule-list works while holding
# NO write capability (MailboxSettings.Read != MailboxSettings.ReadWrite). rules mode adds the rule-
# authoring write scope (also covers master-category create). folders mode is a SEPARATE, deliberate
# tier: Mail.ReadWrite is the least-privileged grant for creating a mailSearchFolder (no lower option
# exists) — kept distinct so a read/rules token can never create a search folder (FR-008/FR-012).
SCOPES = {
    "read": "Mail.Read MailboxSettings.Read offline_access",
    "rules": "Mail.Read MailboxSettings.ReadWrite offline_access",
    "folders": "Mail.ReadWrite MailboxSettings.Read offline_access",
    "messages": "Mail.ReadWrite MailboxSettings.Read offline_access",
}


WRITE_SCOPE = "MailboxSettings.ReadWrite"  # rule authoring + master categories


SEARCHFOLDER_SCOPE = "Mail.ReadWrite"  # the search-folder tier: create/remove virtual search folders


MESSAGE_WRITE_SCOPE = "Mail.ReadWrite"  # the message-move tier: relocate messages between folders (MOVE only)


# --- Secrets live OUTSIDE the repo. Never write tokens into the project tree. -------------------
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "msgraph-stdlib"


TOKEN_PATH = STATE_DIR / "token.json"


MARKER_PATH = STATE_DIR / "verifications.json"  # sibling of the token cache (data-model: VerificationMarker)


# ================================================================================================
# Errors that steer the agent (FR-016) — never a raw traceback.
# ================================================================================================
class SteerError(Exception):
    """Raised with an actionable, agent-legible message; printed to stderr, exit 1."""


# ================================================================================================
# Bounded, IPv4-first connect (feature 008, Issue 1/2) — happy-eyeballs-lite over the stdlib.
#
# On a host where DNS returns both A and AAAA records but the IPv6 route is blackholed, a bare
# `socket.create_connection` tries each address with the FULL operation timeout and in the OS order
# (often IPv6 first), so the whole call hangs on the dead address — breaking first sign-in AND the
# silent refresh (both flow through `_http`). We resolve addresses ourselves, prefer IPv4, and bound
# the *connect* phase per address so a dead address fails fast to a reachable one (mirrors curl).
# ================================================================================================
def _connect_timeout() -> float:
    try:
        return float(os.environ.get("MSGRAPH_CONNECT_TIMEOUT", "5"))
    except ValueError:
        return 5.0


def _ordered_addrinfo(host: str, port: int) -> list:
    """Resolve host:port to addrinfo tuples, IPv4 first (dodges a blackholed IPv6 route).

    `MSGRAPH_FORCE_IPV4` (any truthy value) restricts to IPv4 only — the documented stopgap for
    badly broken dual-stack hosts — falling back to the full list only if no IPv4 address exists.
    """
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if os.environ.get("MSGRAPH_FORCE_IPV4"):
        infos = [i for i in infos if i[0] == socket.AF_INET] or infos
    infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)
    return infos


def _bounded_connect(host: str, port: int, overall_timeout: float | None) -> socket.socket:
    """Connect to the first reachable address, bounding each attempt by the connect timeout.

    A failing/stalled address raises within `MSGRAPH_CONNECT_TIMEOUT` (default 5s) and we move on,
    rather than letting one dead address consume the whole operation window. On success the socket
    timeout is reset to the overall operation timeout so the read phase is not throttled.
    """
    connect_to = _connect_timeout()
    last_err: Exception | None = None
    for af, socktype, proto, _canon, sa in _ordered_addrinfo(host, port):
        sock = socket.socket(af, socktype, proto)
        try:
            sock.settimeout(connect_to)
            sock.connect(sa)
            sock.settimeout(overall_timeout)
            return sock
        except OSError as e:  # timeout, unreachable, refused — try the next address
            last_err = e
            sock.close()
    raise last_err or OSError(f"could not connect to {host}:{port}")


class _BoundedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection whose connect() uses the bounded, IPv4-first path (no proxy/tunnel support)."""

    def connect(self) -> None:
        self.sock = _bounded_connect(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _BoundedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_BoundedHTTPSConnection, req)


# One opener reused for every request; only HTTPS is reached (Microsoft hosts are all TLS).
_opener = urllib.request.build_opener(_BoundedHTTPSHandler())


# ================================================================================================
# The single HTTP seam — the one mockable boundary (research D8). All Graph + token traffic
# flows through here so unit tests patch exactly one function and stay network-free.
# ================================================================================================
def _http(method: str, url: str, token: str = None, body=None, form: bool = False) -> dict:
    """Perform one HTTP request and return parsed JSON ({} on empty 2xx body).

    body + form=True → urlencoded form (token endpoints); body + form=False → JSON (Graph writes).
    Non-2xx raises SteerError with a concise message (never a raw traceback).
    """
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # Bounded, IPv4-first connect (feature 008): the opener's HTTPS connection fails fast on a
        # dead address instead of hanging the whole 30s window. Read phase keeps the 30s op timeout.
        with _opener.open(req, timeout=30) as r:  # noqa: S310 (trusted Microsoft hosts)
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("error", {})
            detail = detail if isinstance(detail, str) else detail.get("message", "")
        except Exception:
            pass
        if e.code in (401, 403):
            raise SteerError(
                f"Graph denied the request ({e.code}). Your token may lack the required scope or "
                f"have expired — re-run /msgraph-auth-login (use --mode rules for rule authoring)."
            ) from e
        raise SteerError(f"Graph request failed ({e.code} {method} {url}): {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise SteerError(f"Could not reach Microsoft Graph: {e.reason}") from e


# ================================================================================================
# Token cache (data-model: TokenCache) — JSON 0600, outside the repo. Scopes are the mode marker.
# ================================================================================================
def load_token() -> dict:
    """Load the cached token from the XDG path. Returns {} if absent."""
    if not TOKEN_PATH.exists():
        return {}
    return json.loads(TOKEN_PATH.read_text())


def save_token(tok: dict) -> None:
    """Persist the token JSON 0600, outside the repo tree. Never logged or committed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok))
    os.chmod(TOKEN_PATH, 0o600)


def _scopes_of(tok: dict) -> set:
    return set((tok.get("scope") or "").split())


def _require_scopes(tok: dict, needed) -> None:
    """Assert the cached token carries every needed scope, else steer the agent (FR-004/FR-013).

    needed: a scope string or iterable of scope strings. Absence is a structural refusal — the
    read-only token literally has no write grant — not a policy decline.
    """
    if not tok:
        raise SteerError("Not signed in — run /msgraph-auth-login first, then retry.")
    have = _scopes_of(tok)
    need = {needed} if isinstance(needed, str) else set(needed)
    missing = need - have
    if missing:
        if WRITE_SCOPE in missing:
            raise SteerError(
                "This action needs rule-authoring permission, which the current read-only sign-in "
                "does not hold. Escalate deliberately: run /msgraph-auth-login --mode rules."
            )
        if MESSAGE_WRITE_SCOPE in missing:  # Mail.ReadWrite — message-move or search folders
            raise SteerError(
                "This action needs mail-write permission (Mail.ReadWrite), which the current sign-in "
                "does not hold. Escalate deliberately: run /msgraph-auth-login --mode messages (to move "
                "messages) or --mode folders (to create search folders)."
            )
        raise SteerError(
            f"Current sign-in is missing scope(s): {' '.join(sorted(missing))}. Re-run /msgraph-auth-login."
        )


def _refresh_if_needed(tok: dict) -> dict:
    """Silently renew via the refresh token when within skew of expiry (offline_access)."""
    if not tok:
        raise SteerError("Not signed in — run /msgraph-auth-login first, then retry.")
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok
    rt = tok.get("refresh_token")
    if not rt:
        raise SteerError("Session expired and no refresh token — run /msgraph-auth-login again.")
    resp = _http(
        "POST",
        f"{_authority()}/token",
        form=True,
        body={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": _client_id(),
            "scope": tok.get("scope", ""),
        },
    )
    renewed = _store_token_response(resp, fallback_scope=tok.get("scope", ""), prev_tok=tok)
    # Make silent refresh observable (feature 008, Issue 2): the user perceives "expired every
    # session" when refresh fails silently; a stderr note shows it actually working. stdout stays
    # machine-clean.
    print("msgraph: renewed access token silently", file=sys.stderr)
    return renewed


# Write scopes that grant mutation capability — the basis of the sign-in superset warning (Issue 3).
_WRITE_SCOPES = {"Mail.ReadWrite", "MailboxSettings.ReadWrite"}


def _extra_write_scopes(requested: str, granted: str) -> set:
    """Write scopes the token was GRANTED beyond what the requested mode asked for (feature 008).

    AAD consent is sticky/cumulative: once a write tier has ever been consented for the account+
    client, the token endpoint returns those write scopes on every token — even a read-mode request.
    A non-empty result means the cached token can write despite the requested mode, so the headline
    "structural read-only" no longer holds and the caller must say so.
    """
    return (_WRITE_SCOPES & set((granted or "").split())) - set((requested or "").split())


def _authed_token(needed) -> dict:
    """Load → assert scopes → refresh if near expiry. The standard preamble for every API verb."""
    tok = load_token()
    _require_scopes(tok, needed)
    return _refresh_if_needed(tok)


def _store_token_response(resp: dict, fallback_scope: str, *, prev_tok: dict | None = None) -> dict:
    """Shape a Microsoft token response into our cache record and persist it (data-model TokenCache)."""
    tok = {
        "access_token": resp["access_token"],
        # RFC 6749 §6: the server MAY omit refresh_token (meaning "keep the old one").
        "refresh_token": resp.get("refresh_token") or (prev_tok or {}).get("refresh_token", ""),
        "scope": resp.get("scope") or fallback_scope,
        "expires_at": int(time.time()) + int(resp.get("expires_in", 3600)),
        "account": resp.get("account", ""),
    }
    save_token(tok)
    return tok


# ================================================================================================
# Verification marker (data-model: VerificationMarker) — the cross-invocation gate (research D6).
# ================================================================================================
def normalize_predicate(header_contains) -> list:
    """Trimmed, case-folded, order-independent set of substrings — the basis of the marker (D6)."""
    return sorted({s.strip().casefold() for s in header_contains if s and s.strip()})


def predicate_hash(header_contains) -> str:
    """Stable hash of the normalized predicate set; identifies a verification across invocations."""
    norm = normalize_predicate(header_contains)
    return hashlib.sha256(json.dumps(norm).encode()).hexdigest()


def _load_markers() -> dict:
    if not MARKER_PATH.exists():
        return {}
    return json.loads(MARKER_PATH.read_text())


def record_verification(header_contains, count: int) -> None:
    """Persist that this predicate set was verified read-only (sibling of the token cache, 0600)."""
    markers = _load_markers()
    markers[predicate_hash(header_contains)] = {"verified_at": int(time.time()), "count": count}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MARKER_PATH.write_text(json.dumps(markers))
    os.chmod(MARKER_PATH, 0o600)


def read_verification(header_contains) -> dict:
    """Return the marker for this predicate set, or {} if it was never verified."""
    return _load_markers().get(predicate_hash(header_contains), {})


# ================================================================================================
# Pure catch-set logic (data-model: CatchSet; research D6) — zero writes, fully offline-testable.
# ================================================================================================
def compute_catch_set(messages: list, header_contains) -> list:
    """Return messages whose internet headers contain ALL given substrings (case-insensitive).

    Mirrors Graph's coarse headerContains substring semantics so the preview reflects what the
    installed rule will match. Pure function — performs no I/O, no writes (SC-002).
    """
    needles = [s.strip().casefold() for s in header_contains if s and s.strip()]
    matched = []
    for m in messages:
        blob = " ".join(
            f"{h.get('name', '')}: {h.get('value', '')}" for h in (m.get("internetMessageHeaders") or [])
        ).casefold()
        if all(n in blob for n in needles):
            matched.append(m)
    return matched


# ================================================================================================
# Graph helpers
# ================================================================================================
def _graph_url(path: str, params: dict | None = None) -> str:
    """Build a Graph URL, percent-encoding query values so the URL is valid for urllib/http.client.

    OData values routinely contain spaces (``$orderby=receivedDateTime desc``) and other reserved
    characters; an unencoded space raises ``http.client.InvalidURL`` on first live use. ``$`` and
    ``,`` are kept literal because Graph expects them verbatim in option names (``$top``, ``$orderby``)
    and ``$select`` lists; everything else (notably spaces → ``%20``) is percent-encoded.
    """
    url = f"{GRAPH}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="$,")
    return url


def _graph_get(token: str, path: str, params: dict | None = None) -> dict:
    return _http("GET", _graph_url(path, params), token=token)
