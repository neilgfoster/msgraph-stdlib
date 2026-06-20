#!/usr/bin/env python3
"""msgraph-stdlib kernel — read Outlook mail and author safe Outlook message rules.

Standard-library only (urllib + json + argparse), zero third-party dependencies, no
backend. Hand-rolls the OAuth 2.0 device-code flow against the Microsoft identity
platform. The module-level TOOLS catalog is the single source of truth for both
discovery (`describe`, the zero-backend equivalent of MCP tools/list) and argparse
dispatch.

Safety model (structural, not behavioural):
  - Read is Mail.Read-only — a read-only token carries no write grant, so even a bug
    cannot mutate mail.
  - Rule authoring requires a SEPARATE MailboxSettings.ReadWrite consent (the scope
    ratchet). Write verbs assert that scope before any call.
  - rule-create REFUSES unless the same predicate was verified read-only first
    (the catch-set verification marker).
  - Rule actions only file mail to a folder; nothing here ever deletes a message.

Secrets never live in the repo: the token cache and verification marker are written
0600 at ${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/, outside the project tree.
"""

import argparse
import hashlib
import json
import os
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
}
WRITE_SCOPE = "MailboxSettings.ReadWrite"  # rule authoring + master categories
SEARCHFOLDER_SCOPE = "Mail.ReadWrite"  # the new tier: create/remove virtual search folders

# --- Secrets live OUTSIDE the repo. Never write tokens into the project tree. -------------------
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "msgraph-stdlib"
TOKEN_PATH = STATE_DIR / "token.json"
MARKER_PATH = STATE_DIR / "verifications.json"  # sibling of the token cache (data-model: VerificationMarker)


# ================================================================================================
# The TOOLS catalog — single source of truth for `describe` and dispatch (contracts/tools.md).
# Flat JSON Schemas (no oneOf/allOf/anyOf); descriptions are onboarding-quality with when-to-use;
# annotations are advisory MCP hints (NOT security). Keep in sync with contracts/tools.md.
# ================================================================================================
TOOLS = [
    {
        "name": "describe",
        "description": (
            "Emit the tool catalog as JSON (all verbs, or one via --name). The zero-backend "
            "equivalent of MCP tools/list; use to discover verbs, descriptions, and input "
            "schemas at runtime."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Describe a single verb instead of the whole catalog.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "auth-login",
        "description": (
            "Sign in via OAuth device-code. Default mode requests Mail.Read MailboxSettings.Read "
            "(read-only: read mail and read existing rules, no write capability). Pass --mode rules "
            "to consent to MailboxSettings.ReadWrite for rule authoring (incl. categories), or "
            "--mode folders to consent to Mail.ReadWrite for creating search folders — each a "
            "separate, deliberate escalation. Run this first; the operator authorises in a browser."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["read", "rules", "folders"],
                    "default": "read",
                    "description": "read = Mail.Read + MailboxSettings.Read; "
                    "rules = + MailboxSettings.ReadWrite (rule authoring + categories); "
                    "folders = Mail.ReadWrite + MailboxSettings.Read (create search folders).",
                },
            },
            "required": [],
        },
        "scope": (
            "Mail.Read MailboxSettings.Read (read) | "
            "Mail.Read MailboxSettings.ReadWrite (rules) | "
            "Mail.ReadWrite MailboxSettings.Read (folders)"
        ),
    },
    {
        "name": "mail-list",
        "description": (
            "List recent inbox messages, agent-legibly. Use for triage/overview. concise (default) "
            "returns readable summaries; detailed adds IDs for follow-up calls. Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 25,
                    "description": "Max messages to return (pagination).",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = agent-legible summary; detailed = adds IDs.",
                },
            },
            "required": [],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "mail-get",
        "description": (
            "Fetch one message including its internet headers. Use when you need a message's full "
            "content or headers (e.g. to inspect List-Unsubscribe before proposing a rule). "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Graph message id (from mail-list --format detailed).",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = summary + headers; detailed = full JSON.",
                },
            },
            "required": ["message_id"],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "rule-list",
        "description": (
            "Enumerate existing inbox message rules with name, criteria, and target folder in "
            "readable terms. Use to understand current organisation before proposing changes. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = readable summary; detailed = full JSON incl. ids.",
                },
            },
            "required": [],
        },
        "scope": "MailboxSettings.Read",
    },
    {
        "name": "rule-verify",
        "description": (
            "Compute the read-only catch-set — the existing messages candidate criteria would "
            "match — WITHOUT writing anything. ALWAYS run before rule-create; it both previews "
            "intent and records the verification that rule-create requires. Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "header_contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Substrings matched (case-insensitively) against raw internet headers.",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = matches + count; detailed = full JSON.",
                },
            },
            "required": ["header_contains"],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "rule-create",
        "description": (
            "Install a rule that files matching mail to a folder and/or assigns a category. REFUSES "
            "unless the same predicate was verified first (run rule-verify). Actions are "
            "move-to-folder and/or assign-category only — never delete. Any assigned category is "
            "ensured to exist (coloured) first. Requires rule-authoring sign-in (auth-login --mode rules)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the rule."},
                "header_contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Predicate substrings — MUST match a prior rule-verify.",
                },
                "move_to_folder": {
                    "type": "string",
                    "description": "Optional target folder name for matching mail (filed, never deleted).",
                },
                "assign_category": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional category name(s) to assign to matching mail. Ensured to "
                    "exist (coloured) before install. At least one of move_to_folder/assign_category "
                    "required.",
                },
            },
            "required": ["name", "header_contains"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "rule-remove",
        "description": (
            "Delete a rule by id (the reversibility primitive). Removes only the rule; never deletes "
            "any messages. Requires rule-authoring sign-in."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_id": {
                    "type": "string",
                    "description": "Graph rule id (from rule-list --format detailed).",
                },
            },
            "required": ["rule_id"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "category-list",
        "description": (
            "List the mailbox's master categories (name + colour), read-only. Use to see which "
            "labels exist before authoring an assign-category rule or a category search folder. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = name + colour; detailed = full JSON.",
                },
            },
            "required": [],
        },
        "scope": "MailboxSettings.Read",
    },
    {
        "name": "category-ensure",
        "description": (
            "Ensure a named master category exists: create it with a colour if absent, no-op if "
            "present. Use before assigning a category so the label renders with a colour. "
            "Requires rule-authoring sign-in (auth-login --mode rules)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Category display name (unique, immutable once created).",
                },
                "color": {
                    "type": "string",
                    "default": "preset9",
                    "description": "categoryColor preset, e.g. preset0..preset24 or none.",
                },
            },
            "required": ["name"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "searchfolder-list",
        "description": (
            "List virtual search folders (name, filter, source-folder scope, id), read-only. Search "
            "folders never move or delete mail. Use to find a folder's id before removing it. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = name + filter + scope; detailed = full JSON.",
                },
            },
            "required": [],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "searchfolder-create",
        "description": (
            "Create a virtual search folder: a saved filtered view (e.g. all mail tagged a category) "
            "over chosen source folders. Non-destructive — it never moves or deletes mail. Requires "
            "the SEPARATE search-folder sign-in (auth-login --mode folders), a distinct write tier "
            "from rule authoring."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the search folder."},
                "category": {
                    "type": "string",
                    "description": "Convenience: builds filter categories/any(c:c eq '<name>').",
                },
                "filter_query": {
                    "type": "string",
                    "description": "Explicit OData filter; overrides category if both given.",
                },
                "source_folders": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Folder names/well-known names to mine. Default ['inbox'].",
                },
                "include_nested": {
                    "type": "boolean",
                    "default": True,
                    "description": "true = deep-search source subtrees; false = shallow.",
                },
            },
            "required": ["name"],
        },
        "scope": "Mail.ReadWrite",
    },
    {
        "name": "searchfolder-remove",
        "description": (
            "Delete a search folder by id (the reversibility primitive for search folders). Removes "
            "only the virtual folder; never deletes any messages. Requires search-folder sign-in "
            "(auth-login --mode folders)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "Search folder id (from searchfolder-list --format detailed).",
                },
            },
            "required": ["folder_id"],
        },
        "scope": "Mail.ReadWrite",
    },
]


# ================================================================================================
# Errors that steer the agent (FR-016) — never a raw traceback.
# ================================================================================================
class SteerError(Exception):
    """Raised with an actionable, agent-legible message; printed to stderr, exit 1."""


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
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (trusted Microsoft hosts)
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
    return _store_token_response(resp, fallback_scope=tok.get("scope", ""))


def _authed_token(needed) -> dict:
    """Load → assert scopes → refresh if near expiry. The standard preamble for every API verb."""
    tok = load_token()
    _require_scopes(tok, needed)
    return _refresh_if_needed(tok)


def _store_token_response(resp: dict, fallback_scope: str) -> dict:
    """Shape a Microsoft token response into our cache record and persist it (data-model TokenCache)."""
    tok = {
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token", ""),
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
# Output shaping — agent-legible (concise) vs detailed (IDs/JSON for follow-up).
# ================================================================================================
def _sender_of(msg: dict) -> str:
    frm = (msg.get("from") or {}).get("emailAddress") or {}
    return frm.get("address") or frm.get("name") or "(unknown)"


def _render_messages(items: list, fmt: str) -> str:
    if fmt == "detailed":
        return json.dumps(items, indent=2)
    if not items:
        return "No messages."
    lines = [
        f'- "{m.get("subject", "(no subject)")}" from {_sender_of(m)}'
        f"  (received: {m.get('receivedDateTime', '?')})"
        for m in items
    ]
    lines.append(f"{len(items)} message(s). Pass --format detailed for IDs needed by follow-up commands.")
    return "\n".join(lines)


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


def _resolve_folder_id(token: str, name: str) -> str:
    """Look up a mail folder id by display name for the move-to-folder action (data-model)."""
    data = _graph_get(token, "/me/mailFolders", params={"$top": 100, "$select": "id,displayName"})
    for f in data.get("value", []):
        if f.get("displayName", "").casefold() == name.casefold():
            return f["id"]
    raise SteerError(
        f"No mail folder named '{name}' was found. Create it in Outlook first, or pass an "
        f"existing folder name (rule actions file mail to a folder; they never delete)."
    )


def _master_categories(token: str) -> list:
    """Return the mailbox master categories (id, displayName, color). Read-only."""
    return _graph_get(token, "/me/outlook/masterCategories").get("value", [])


def _find_category(cats: list, name: str) -> dict:
    """Case-insensitive match of a category by displayName, or {} if absent."""
    for c in cats:
        if c.get("displayName", "").casefold() == name.casefold():
            return c
    return {}


def _ensure_category(token: str, name: str, color: str = "preset9") -> dict:
    """Create the named master category (coloured) if absent; return it. No-op if present (FR-005).

    Requires MailboxSettings.ReadWrite (same as rule authoring). The displayName is immutable once
    created, so an existing category is returned unchanged regardless of the requested colour.
    """
    existing = _find_category(_master_categories(token), name)
    if existing:
        return existing
    return _http(
        "POST",
        f"{GRAPH}/me/outlook/masterCategories",
        token=token,
        body={"displayName": name, "color": color},
    )


def _filter_query_for_category(name: str) -> str:
    """Build the OData filter for mail tagged a category, escaping single quotes by doubling."""
    return f"categories/any(c:c eq '{name.replace(chr(39), chr(39) * 2)}')"


# Action keys whose value is an opaque folder id we can resolve to a display name (read-only).
_FOLDER_ACTION_KEYS = ("moveToFolder", "copyToFolder")


def _folder_name_map(token: str) -> dict:
    """id→displayName for all mail folders at any nesting depth.

    Lets rule-list show move/copy-to-folder targets by name. Walks the folder tree breadth-first,
    descending only into folders that report children (``childFolderCount``) so the number of GETs is
    proportional to the folders-with-children, not the whole tree. Read-only; failures degrade
    silently, leaving unresolved ids to fall back to the raw id so output never lies about the target.
    """
    names: dict = {}
    params = {"$top": 200, "$select": "id,displayName,childFolderCount"}
    # Queue of folder-listing paths to fetch; seed with the top level.
    pending = ["/me/mailFolders"]
    try:
        while pending:
            data = _graph_get(token, pending.pop(), params=params)
            for f in data.get("value", []):
                fid = f.get("id")
                if not fid:
                    continue
                names[fid] = f.get("displayName", "")
                if f.get("childFolderCount", 0):
                    pending.append(f"/me/mailFolders/{urllib.parse.quote(fid, safe='')}/childFolders")
    except SteerError:
        pass  # partial map is fine — unresolved ids render as raw ids
    return names


# ================================================================================================
# Verb implementations
# ================================================================================================
def cmd_describe(args) -> int:
    """Emit the tool catalog as JSON so an agent can discover verbs, descriptions, and schemas."""
    if args.name:
        match = [t for t in TOOLS if t["name"] == args.name]
        if not match:
            names = ", ".join(t["name"] for t in TOOLS)
            raise SteerError(f"no such verb '{args.name}'. Available: {names}")
        print(json.dumps(match[0], indent=2))
    else:
        print(json.dumps({"tools": TOOLS}, indent=2))
    return 0


def cmd_auth_login(args) -> int:
    """OAuth 2.0 device-code flow (research D1). Display the code, poll for consent, cache the token."""
    if not _client_id():
        raise SteerError(
            "MSGRAPH_CLIENT_ID is not set. Register a free Azure AD public client (device-code "
            "flow enabled), then export MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID. See skills/auth-login."
        )
    scope = SCOPES[args.mode]
    dc = _http(
        "POST", f"{_authority()}/devicecode", form=True, body={"client_id": _client_id(), "scope": scope}
    )
    print(
        dc.get("message") or f"To sign in, open {dc['verification_uri']} and enter code {dc['user_code']}",
        file=sys.stderr,
    )

    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        try:
            resp = _http(
                "POST",
                f"{_authority()}/token",
                form=True,
                body={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": _client_id(),
                    "device_code": dc["device_code"],
                },
            )
        except SteerError:
            # authorization_pending is reported as an HTTP 400 by the token endpoint; keep polling.
            continue
        if resp.get("access_token"):
            _store_token_response(resp, fallback_scope=scope)
            mode_note = {
                "rules": "rule-authoring (write)",
                "folders": "search-folder (mail write)",
            }.get(args.mode, "read-only")
            print(f"Signed in ({mode_note}). Scopes: {resp.get('scope') or scope}")
            return 0
    raise SteerError("Device-code sign-in timed out before authorisation. Run /msgraph-auth-login again.")


def cmd_mail_list(args) -> int:
    """List recent inbox messages (GET /me/messages), shaped concise/detailed (FR-005)."""
    tok = _authed_token("Mail.Read")
    sel = "id,subject,from,receivedDateTime"
    data = _graph_get(
        tok["access_token"],
        "/me/messages",
        params={"$top": args.limit, "$select": sel, "$orderby": "receivedDateTime desc"},
    )
    print(_render_messages(data.get("value", []), args.format))
    return 0


def cmd_mail_get(args) -> int:
    """Fetch one message including internet headers (FR-006)."""
    tok = _authed_token("Mail.Read")
    sel = "id,subject,from,receivedDateTime,body,internetMessageHeaders"
    mid = urllib.parse.quote(args.message_id, safe="")
    msg = _graph_get(tok["access_token"], f"/me/messages/{mid}", params={"$select": sel})
    if args.format == "detailed":
        print(json.dumps(msg, indent=2))
    else:
        print(f"Subject: {msg.get('subject', '(no subject)')}")
        print(f"From:    {_sender_of(msg)}")
        print(f"Received: {msg.get('receivedDateTime', '?')}")
        headers = msg.get("internetMessageHeaders") or []
        print(f"\nInternet headers ({len(headers)}):")
        for h in headers:
            print(f"  {h.get('name')}: {h.get('value')}")
    return 0


def _fetch_messages_with_headers(token: str, limit: int = 100) -> list:
    """Read messages + their internet headers for catch-set evaluation (read-only, GETs only)."""
    sel = "id,subject,from,receivedDateTime,internetMessageHeaders"
    data = _graph_get(
        token,
        "/me/messages",
        params={"$top": limit, "$select": sel, "$orderby": "receivedDateTime desc"},
    )
    return data.get("value", [])


def cmd_rule_verify(args) -> int:
    """Compute the read-only catch-set for candidate predicates and record the marker (FR-008)."""
    tok = _authed_token("Mail.Read")
    messages = _fetch_messages_with_headers(tok["access_token"])
    matches = compute_catch_set(messages, args.header_contains)
    record_verification(args.header_contains, len(matches))
    if args.format == "detailed":
        print(json.dumps({"count": len(matches), "matches": matches}, indent=2))
    else:
        print(
            f"Catch-set for header_contains {args.header_contains}: {len(matches)} message(s)"
            + (" (none currently match)" if not matches else "")
        )
        print(_render_messages(matches, "concise"))
        print("\nVerified. You may now run rule-create with these exact criteria.")
    return 0


def _humanize_key(key: str) -> str:
    """Turn a camelCase predicate/action name into spaced lower-case words (agent-legible)."""
    return "".join(f" {c.lower()}" if c.isupper() else c for c in key).strip()


def _humanize_value(value) -> str:
    """Render a Graph predicate/action value (list, recipient list, bool, enum, range) legibly."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):  # recipient: {"emailAddress": {"name", "address"}}
                addr = item.get("emailAddress") or {}
                parts.append(addr.get("address") or addr.get("name") or json.dumps(item))
            else:
                parts.append(str(item))
        return ", ".join(parts)
    if isinstance(value, dict):  # e.g. withinSizeRange {minimumSize, maximumSize}
        return ", ".join(f"{_humanize_key(k)} {v}" for k, v in value.items())
    return str(value)


def _summarize_clauses(clauses: dict, folders: dict | None = None) -> list:
    """Summarize whichever conditions/actions are present, skipping empty/false ones.

    ``folders`` (id→displayName) resolves move/copy-to-folder action ids to legible names; an
    unresolved id falls back to the raw id so the output never misrepresents the target.
    """
    folders = folders or {}
    lines = []
    for key, value in (clauses or {}).items():
        if value in (None, [], {}, "", False):
            continue  # absent predicate/action — don't pretend it's set
        if key in _FOLDER_ACTION_KEYS and isinstance(value, str) and value in folders:
            rendered = f'"{folders[value]}"'
        else:
            rendered = _humanize_value(value)
        lines.append(f"{_humanize_key(key)}: {rendered}")
    return lines


def _render_rules(rules: list, fmt: str, folders: dict | None = None) -> str:
    if fmt == "detailed":
        return json.dumps(rules, indent=2)
    if not rules:
        return "No inbox message rules."
    out = []
    for r in rules:
        conds = _summarize_clauses(r.get("conditions") or {}, folders)
        actions = _summarize_clauses(r.get("actions") or {}, folders)
        line = (
            f'- "{r.get("displayName", "(unnamed)")}"'
            f"{'  enabled' if r.get('isEnabled', True) else '  disabled'}"
            f"\n    if   {'; '.join(conds) or '(no conditions)'}"
            f"\n    then {'; '.join(actions) or '(no actions)'}"
        )
        out.append(line)
    out.append(f"{len(rules)} rule(s). Pass --format detailed for ids needed by rule-remove.")
    return "\n".join(out)


def cmd_rule_list(args) -> int:
    """Enumerate existing inbox message rules (FR-007). Rules are mailbox settings (MailboxSettings.Read)."""
    tok = _authed_token("MailboxSettings.Read")
    data = _graph_get(tok["access_token"], "/me/mailFolders/inbox/messageRules")
    rules = data.get("value", [])
    # Resolve folder ids to names only when needed for the legible (concise) view.
    folders = _folder_name_map(tok["access_token"]) if args.format != "detailed" and rules else {}
    print(_render_rules(rules, args.format, folders))
    return 0


def cmd_rule_create(args) -> int:
    """Install a verified rule that files to a folder and/or assigns a category.

    Refuses without write scope, without a prior verify, or with no action (FR-009/FR-010).
    """
    tok = _authed_token(WRITE_SCOPE)
    move_to_folder = getattr(args, "move_to_folder", None)
    assign_category = getattr(args, "assign_category", None) or []
    if not move_to_folder and not assign_category:
        raise SteerError(
            "Refusing to create this rule: no action given. Pass --move_to_folder and/or "
            "--assign_category so the rule files and/or labels matching mail (it never deletes)."
        )
    marker = read_verification(args.header_contains)
    if not marker:
        raise SteerError(
            "Refusing to create this rule: its criteria were not verified first. Run "
            f"rule-verify --header_contains {args.header_contains} to preview the catch-set, "
            "then retry. (verify-then-install is a hard safety gate.)"
        )
    # Build actions conditionally — only move-to-folder and/or assign-category; never a delete-style
    # action (FR-009/FR-012). Each assigned category is ensured to exist (coloured) first (FR-005).
    actions: dict = {"stopProcessingRules": False}
    summary = []
    if move_to_folder:
        actions["moveToFolder"] = _resolve_folder_id(tok["access_token"], move_to_folder)
        summary.append(f'files it into "{move_to_folder}"')
    if assign_category:
        for cat in assign_category:
            _ensure_category(tok["access_token"], cat)
        actions["assignCategories"] = list(assign_category)
        summary.append(f"assigns category {assign_category}")
    body = {
        "displayName": args.name,
        "sequence": 1,
        "isEnabled": True,
        "conditions": {"headerContains": list(args.header_contains)},
        "actions": actions,
    }
    created = _http(
        "POST", f"{GRAPH}/me/mailFolders/inbox/messageRules", token=tok["access_token"], body=body
    )
    print(
        f'Created rule "{args.name}" (id: {created.get("id", "?")}). For mail whose headers '
        f"contain {args.header_contains}, it {' and '.join(summary)}. "
        f"Verified catch-set was {marker.get('count', '?')} message(s). "
        f"Reverse anytime with rule-remove."
    )
    return 0


def cmd_rule_remove(args) -> int:
    """Delete a rule by id (the reversibility primitive). Never touches messages (FR-011/FR-012)."""
    tok = _authed_token(WRITE_SCOPE)
    _http("DELETE", f"{GRAPH}/me/mailFolders/inbox/messageRules/{args.rule_id}", token=tok["access_token"])
    print(f"Removed rule {args.rule_id}. No messages were deleted; any mail already filed stays put.")
    return 0


def cmd_category_list(args) -> int:
    """List the mailbox master categories, agent-legibly (name + colour). Read-only (FR-005)."""
    tok = _authed_token("MailboxSettings.Read")
    cats = _master_categories(tok["access_token"])
    if args.format == "detailed":
        print(json.dumps(cats, indent=2))
        return 0
    if not cats:
        print("No master categories. Create one with category-ensure (rule-authoring sign-in).")
        return 0
    for c in cats:
        print(f'- "{c.get("displayName", "(unnamed)")}"  ({c.get("color", "no colour")})')
    print(f"{len(cats)} categor(y/ies).")
    return 0


def cmd_category_ensure(args) -> int:
    """Create the named master category (coloured) if absent; no-op if present (FR-005)."""
    tok = _authed_token(WRITE_SCOPE)
    existing = _find_category(_master_categories(tok["access_token"]), args.name)
    if existing:
        colour = existing.get("color", "no colour")
        print(f'Category "{args.name}" already exists ({colour}); no change.')
        return 0
    created = _ensure_category(tok["access_token"], args.name, args.color)
    colour = created.get("color", args.color)
    print(f'Created category "{args.name}" ({colour}). It now renders with a colour.')
    return 0


def cmd_searchfolder_list(args) -> int:
    """List virtual search folders (name, filter, source scope, id). Read-only (FR-007/FR-009)."""
    tok = _authed_token("Mail.Read")
    data = _graph_get(tok["access_token"], "/me/mailFolders/searchfolders/childFolders")
    folders = data.get("value", [])
    if args.format == "detailed":
        print(json.dumps(folders, indent=2))
        return 0
    if not folders:
        print("No search folders. Create one with searchfolder-create (auth-login --mode folders).")
        return 0
    for f in folders:
        scope = "deep" if f.get("includeNestedFolders") else "shallow"
        n_src = len(f.get("sourceFolderIds") or [])
        print(
            f'- "{f.get("displayName", "(unnamed)")}"  (id: {f.get("id", "?")})'
            f"\n    filter: {f.get('filterQuery', '(none)')}  [{scope} over {n_src} source folder(s)]"
        )
    print(f"{len(folders)} search folder(s). Pass --format detailed for full ids.")
    return 0


def cmd_searchfolder_create(args) -> int:
    """Create a virtual mailSearchFolder (a saved filtered view). Never moves/deletes mail (FR-006/FR-009).

    Requires the separate Mail.ReadWrite tier (auth-login --mode folders) — a read/rules token lacks
    the grant, so this refuses structurally (FR-008/FR-012).
    """
    tok = _authed_token(SEARCHFOLDER_SCOPE)
    filter_query = args.filter_query or (_filter_query_for_category(args.category) if args.category else None)
    if not filter_query:
        raise SteerError(
            "Refusing to create this search folder: no filter given. Pass --category NAME "
            "(builds a category filter) or an explicit --filter_query (OData)."
        )
    source_names = args.source_folders or ["inbox"]
    # Well-known names (inbox, archive, …) are accepted verbatim by Graph; resolve any others to ids.
    _WELL_KNOWN = {"inbox", "archive", "drafts", "sentitems", "deleteditems", "junkemail", "msgfolderroot"}
    source_ids = [
        n if n.casefold() in _WELL_KNOWN else _resolve_folder_id(tok["access_token"], n) for n in source_names
    ]
    body = {
        "@odata.type": "microsoft.graph.mailSearchFolder",
        "displayName": args.name,
        "includeNestedFolders": bool(args.include_nested),
        "sourceFolderIds": source_ids,
        "filterQuery": filter_query,
    }
    created = _http(
        "POST", f"{GRAPH}/me/mailFolders/searchfolders/childFolders", token=tok["access_token"], body=body
    )
    print(
        f'Created search folder "{args.name}" (id: {created.get("id", "?")}). It presents a filtered '
        f"view (filter: {filter_query}) over {source_names}; it is virtual — no mail is moved or "
        f"deleted. Remove anytime with searchfolder-remove."
    )
    return 0


def cmd_searchfolder_remove(args) -> int:
    """Delete a search folder by id. Removes only the virtual folder, never mail (FR-007/FR-009)."""
    tok = _authed_token(SEARCHFOLDER_SCOPE)
    _http("DELETE", f"{GRAPH}/me/mailFolders/{args.folder_id}", token=tok["access_token"])
    print(f"Removed search folder {args.folder_id}. No messages were affected; it was only a filtered view.")
    return 0


# ================================================================================================
# Dispatch — built from the TOOLS catalog so discovery and execution read from one source.
# ================================================================================================
_HANDLERS = {
    "describe": cmd_describe,
    "auth-login": cmd_auth_login,
    "mail-list": cmd_mail_list,
    "mail-get": cmd_mail_get,
    "rule-list": cmd_rule_list,
    "rule-verify": cmd_rule_verify,
    "rule-create": cmd_rule_create,
    "rule-remove": cmd_rule_remove,
    "category-list": cmd_category_list,
    "category-ensure": cmd_category_ensure,
    "searchfolder-list": cmd_searchfolder_list,
    "searchfolder-create": cmd_searchfolder_create,
    "searchfolder-remove": cmd_searchfolder_remove,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP, description="msgraph-stdlib kernel (stdlib only).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for tool in TOOLS:
        p = sub.add_parser(tool["name"], help=tool["description"].split(".")[0])
        p.set_defaults(func=_HANDLERS[tool["name"]])

    sub.choices["describe"].add_argument("--name", help="describe a single verb instead of the catalog")
    sub.choices["auth-login"].add_argument(
        "--mode",
        choices=["read", "rules", "folders"],
        default="read",
        help="read (default), rules (rule-authoring escalation), or folders (search-folder escalation)",
    )
    for verb in ("mail-list",):
        sub.choices[verb].add_argument("--limit", type=int, default=25, help="max items (pagination)")
    for verb in ("mail-list", "mail-get", "rule-list", "rule-verify", "category-list", "searchfolder-list"):
        sub.choices[verb].add_argument("--format", choices=["concise", "detailed"], default="concise")
    sub.choices["mail-get"].add_argument("--message_id", required=True, help="Graph message id")
    sub.choices["rule-verify"].add_argument(
        "--header_contains", nargs="+", required=True, metavar="SUBSTR", help="header substrings to match"
    )
    sub.choices["rule-create"].add_argument("--name", required=True, help="rule display name")
    sub.choices["rule-create"].add_argument(
        "--header_contains",
        nargs="+",
        required=True,
        metavar="SUBSTR",
        help="predicate substrings (must match a prior verify)",
    )
    sub.choices["rule-create"].add_argument(
        "--move_to_folder", help="optional target folder name (files matching mail there)"
    )
    sub.choices["rule-create"].add_argument(
        "--assign_category", nargs="+", metavar="NAME", help="optional category name(s) to assign"
    )
    sub.choices["rule-remove"].add_argument("--rule_id", required=True, help="Graph rule id")

    sub.choices["category-ensure"].add_argument("--name", required=True, help="category display name")
    sub.choices["category-ensure"].add_argument("--color", default="preset9", help="categoryColor preset")

    sfc = sub.choices["searchfolder-create"]
    sfc.add_argument("--name", required=True, help="search folder display name")
    sfc.add_argument("--category", help="build a category filter for this name")
    sfc.add_argument("--filter_query", help="explicit OData filter (overrides --category)")
    sfc.add_argument("--source_folders", nargs="+", metavar="FOLDER", help="folders to mine (default: inbox)")
    sfc.add_argument(
        "--include_nested",
        type=lambda v: str(v).lower() not in ("false", "0", "no"),
        default=True,
        help="deep-search source subtrees (default true)",
    )
    sub.choices["searchfolder-remove"].add_argument("--folder_id", required=True, help="search folder id")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SteerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
