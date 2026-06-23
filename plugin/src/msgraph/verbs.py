"""msgraph-stdlib verb implementations — one cmd_* per catalog entry.

Reaches the runtime seam/state, Graph helpers, and rendering via `runtime.*` / `graph.*` /
`render.*` at call time (the load-bearing rule, feature 004 data-model: INV-1). Behaviour is
identical to the pre-split kernel — this is a pure structural move.
"""

import json
import sys
import time
import urllib.parse

from msgraph import graph, render, runtime
from msgraph.catalog import TOOLS


# ================================================================================================
# Verb implementations
# ================================================================================================
def _warn_scope_superset(requested: str, granted: str) -> None:
    """Warn (stderr) when the granted token carries write scopes beyond the requested mode.

    AAD consent is sticky/cumulative, so a read-mode sign-in on an account that ever consented to a
    write tier returns a write-capable token. Surfacing this keeps the docs' honesty promise: the
    "structural read-only" guarantee does NOT hold for such a token (feature 008, Issue 3 / ADR-0001).
    """
    extra = runtime._extra_write_scopes(requested, granted)
    if extra:
        print(
            "msgraph: note — this token also carries WRITE scope(s) from prior consent: "
            f"{' '.join(sorted(extra))}. Microsoft consent is cumulative, so structural read-only "
            "no longer holds for this account+client. Verbs still refuse without the scope they need, "
            "but the token itself is write-capable.",
            file=sys.stderr,
        )


def cmd_describe(args) -> int:
    """Emit the tool catalog as JSON so an agent can discover verbs, descriptions, and schemas."""
    if args.name:
        match = [t for t in TOOLS if t["name"] == args.name]
        if not match:
            names = ", ".join(t["name"] for t in TOOLS)
            raise runtime.SteerError(f"no such verb '{args.name}'. Available: {names}")
        print(json.dumps(match[0], indent=2))
    else:
        print(json.dumps({"tools": TOOLS}, indent=2))
    return 0


def cmd_auth_login(args) -> int:
    """OAuth 2.0 device-code flow (research D1). Display the code, poll for consent, cache the token."""
    if not runtime._client_id():
        raise runtime.SteerError(
            "MSGRAPH_CLIENT_ID is not set. Register a free Azure AD public client (device-code "
            "flow enabled), then export MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID. See skills/auth-login."
        )
    tok = runtime.load_token()
    if tok and tok.get("expires_at", 0) > time.time() + 60:
        needed = set(runtime.SCOPES[args.mode].split())
        if not (needed - runtime._scopes_of(tok)):
            mode_note = {
                "rules": "rule-authoring (write)",
                "folders": "search-folder (mail write)",
            }.get(args.mode, "read-only")
            print(f"Already signed in ({mode_note}). Scopes: {tok.get('scope') or runtime.SCOPES[args.mode]}")
            _warn_scope_superset(runtime.SCOPES[args.mode], tok.get("scope", ""))
            return 0
    scope = runtime.SCOPES[args.mode]
    dc = runtime._http(
        "POST",
        f"{runtime._authority()}/devicecode",
        form=True,
        body={"client_id": runtime._client_id(), "scope": scope},
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
            resp = runtime._http(
                "POST",
                f"{runtime._authority()}/token",
                form=True,
                body={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": runtime._client_id(),
                    "device_code": dc["device_code"],
                },
            )
        except runtime.SteerError:
            # authorization_pending is reported as an HTTP 400 by the token endpoint; keep polling.
            continue
        if resp.get("access_token"):
            runtime._store_token_response(resp, fallback_scope=scope)
            mode_note = {
                "rules": "rule-authoring (write)",
                "folders": "search-folder (mail write)",
            }.get(args.mode, "read-only")
            print(f"Signed in ({mode_note}). Scopes: {resp.get('scope') or scope}")
            _warn_scope_superset(scope, resp.get("scope") or scope)
            return 0
    raise runtime.SteerError(
        "Device-code sign-in timed out before authorisation. Run /msgraph-auth-login again."
    )


def cmd_mail_list(args) -> int:
    """List recent messages from a single folder, shaped concise/detailed (FR-005).

    Defaults to the Inbox (GET /me/mailFolders/inbox/messages) so the listing reflects what actually
    needs triage, not already-filed mail across every folder. An optional --folder (well-known name
    or display name) scopes the listing elsewhere; an unresolvable folder steers rather than 404s.
    """
    tok = runtime._authed_token("Mail.Read")
    token = tok["access_token"]
    folder = getattr(args, "folder", None) or "inbox"
    folder_id, label = graph._resolve_folder(token, folder)
    sel = "id,subject,from,receivedDateTime"
    fid = urllib.parse.quote(folder_id, safe="")
    try:
        data = runtime._graph_get(
            token,
            f"/me/mailFolders/{fid}/messages",
            params={"$top": args.limit, "$select": sel, "$orderby": "receivedDateTime desc"},
        )
    except runtime.SteerError as e:
        raise runtime.SteerError(
            f'Could not list folder "{label}": {e} '
            "Check the folder name (run folder-list to see available folders)."
        ) from e
    print(render._render_messages(data.get("value", []), args.format))
    return 0


def cmd_mail_get(args) -> int:
    """Fetch one message including internet headers (FR-006)."""
    tok = runtime._authed_token("Mail.Read")
    sel = "id,subject,from,receivedDateTime,body,internetMessageHeaders"
    mid = urllib.parse.quote(args.message_id, safe="")
    msg = runtime._graph_get(tok["access_token"], f"/me/messages/{mid}", params={"$select": sel})
    if args.format == "detailed":
        print(json.dumps(msg, indent=2))
    else:
        print(f"Subject: {msg.get('subject', '(no subject)')}")
        print(f"From:    {render._sender_of(msg)}")
        print(f"Received: {msg.get('receivedDateTime', '?')}")
        headers = msg.get("internetMessageHeaders") or []
        print(f"\nInternet headers ({len(headers)}):")
        for h in headers:
            print(f"  {h.get('name')}: {h.get('value')}")
    return 0


def _message_summary(token: str, mid: str) -> dict:
    """Fetch one message's subject/sender for preview/audit (read-only). {} if it cannot be read."""
    try:
        q = urllib.parse.quote(mid, safe="")
        return runtime._graph_get(token, f"/me/messages/{q}", params={"$select": "id,subject,from"})
    except runtime.SteerError:
        return {}


def cmd_message_move(args) -> int:
    """Move message(s) to a destination folder (POST /me/messages/{id}/move). MOVE only; reversible.

    --dry_run resolves the destination and lists what WOULD move, writing nothing (the gate). The real
    move is batch-safe: each id is moved independently and reports its own outcome, so one failure
    (e.g. a stale id) never aborts the batch. Returns enough per-message detail (old id → new id) to
    log and reverse. Requires the message-write tier (Mail.ReadWrite, auth-login --mode messages).
    """
    tok = runtime._authed_token(runtime.MESSAGE_WRITE_SCOPE)
    token = tok["access_token"]
    ids = list(dict.fromkeys(args.message_ids))  # de-dupe, preserve order
    dest_id, dest_label = graph._resolve_folder(token, args.destination_folder)

    if args.dry_run:
        previews = [{"id": mid, **_message_summary(token, mid)} for mid in ids]
        if args.format == "detailed":
            print(json.dumps({"dry_run": True, "destination": dest_label, "would_move": previews}, indent=2))
            return 0
        print(f'DRY RUN — would move {len(ids)} message(s) to "{dest_label}". Nothing was written.')
        for p in previews:
            subj = p.get("subject", "(unreadable — id may be stale)")
            print(f'  - "{subj}" from {render._sender_of(p)}  [{p["id"]}]')
        print("\nRe-run without --dry_run to perform the move (reversible: move back to the source folder).")
        return 0

    results = []
    for mid in ids:
        q = urllib.parse.quote(mid, safe="")
        try:
            url = f"{runtime.GRAPH}/me/messages/{q}/move"
            moved = runtime._http("POST", url, token=token, body={"destinationId": dest_id})
            results.append({"source_id": mid, "new_id": moved.get("id", "?"), "ok": True})
        except runtime.SteerError as e:
            results.append({"source_id": mid, "ok": False, "error": str(e)})

    if args.format == "detailed":
        print(json.dumps({"destination": dest_label, "results": results}, indent=2))
        return 0
    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    print(f'Moved {len(ok)}/{len(results)} message(s) to "{dest_label}". MOVE only — nothing deleted.')
    for r in ok:
        print(f"  ✓ {r['source_id']} → new id {r['new_id']}")
    for r in failed:
        print(f"  ✗ {r['source_id']}: {r['error']}")
    if ok:
        print("\nReversible: move these back with message-move --destination_folder <source folder>.")
    return 1 if failed and not ok else 0


def _fetch_messages_with_headers(token: str, limit: int = 100) -> list:
    """Read inbox messages + their internet headers for catch-set evaluation (read-only, GETs only).

    Inbox-scoped: native message rules act on inbox arrivals, so the catch-set must count only the
    mail that currently sits in the Inbox — not matches already filed away in other folders.
    """
    sel = "id,subject,from,receivedDateTime,internetMessageHeaders"
    data = runtime._graph_get(
        token,
        "/me/mailFolders/inbox/messages",
        params={"$top": limit, "$select": sel, "$orderby": "receivedDateTime desc"},
    )
    return data.get("value", [])


def cmd_rule_verify(args) -> int:
    """Compute the read-only catch-set for candidate predicates and record the marker (FR-008)."""
    tok = runtime._authed_token("Mail.Read")
    messages = _fetch_messages_with_headers(tok["access_token"])
    matches = runtime.compute_catch_set(messages, args.header_contains)
    runtime.record_verification(args.header_contains, len(matches))
    if args.format == "detailed":
        print(json.dumps({"count": len(matches), "matches": matches}, indent=2))
    else:
        print(
            f"Catch-set for header_contains {args.header_contains}: {len(matches)} message(s)"
            + (" (none currently match)" if not matches else "")
        )
        print(render._render_messages(matches, "concise"))
        print("\nVerified. You may now run rule-create with these exact criteria.")
    return 0


def cmd_rule_list(args) -> int:
    """Enumerate existing inbox message rules (FR-007). Rules are mailbox settings (MailboxSettings.Read)."""
    tok = runtime._authed_token("MailboxSettings.Read")
    data = runtime._graph_get(tok["access_token"], "/me/mailFolders/inbox/messageRules")
    rules = data.get("value", [])
    # Resolve folder ids to names only when needed for the legible (concise) view.
    folders = graph._folder_name_map(tok["access_token"]) if args.format != "detailed" and rules else {}
    print(render._render_rules(rules, args.format, folders))
    return 0


def cmd_rule_create(args) -> int:
    """Install a verified rule that files to a folder and/or assigns a category.

    Refuses without write scope, without a prior verify, or with no action (FR-009/FR-010).
    """
    tok = runtime._authed_token(runtime.WRITE_SCOPE)
    move_to_folder = getattr(args, "move_to_folder", None)
    assign_category = getattr(args, "assign_category", None) or []
    if not move_to_folder and not assign_category:
        raise runtime.SteerError(
            "Refusing to create this rule: no action given. Pass --move_to_folder and/or "
            "--assign_category so the rule files and/or labels matching mail (it never deletes)."
        )
    marker = runtime.read_verification(args.header_contains)
    if not marker:
        raise runtime.SteerError(
            "Refusing to create this rule: its criteria were not verified first. Run "
            f"rule-verify --header_contains {args.header_contains} to preview the catch-set, "
            "then retry. (verify-then-install is a hard safety gate.)"
        )
    # Build actions conditionally — only move-to-folder and/or assign-category; never a delete-style
    # action (FR-009/FR-012). Each assigned category is ensured to exist (coloured) first (FR-005).
    actions: dict = {"stopProcessingRules": False}
    summary = []
    if move_to_folder:
        actions["moveToFolder"] = graph._resolve_folder_id(tok["access_token"], move_to_folder)
        summary.append(f'files it into "{move_to_folder}"')
    if assign_category:
        for cat in assign_category:
            graph._ensure_category(tok["access_token"], cat)
        actions["assignCategories"] = list(assign_category)
        summary.append(f"assigns category {assign_category}")
    body = {
        "displayName": args.name,
        "sequence": 1,
        "isEnabled": True,
        "conditions": {"headerContains": list(args.header_contains)},
        "actions": actions,
    }
    created = runtime._http(
        "POST", f"{runtime.GRAPH}/me/mailFolders/inbox/messageRules", token=tok["access_token"], body=body
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
    tok = runtime._authed_token(runtime.WRITE_SCOPE)
    runtime._http(
        "DELETE",
        f"{runtime.GRAPH}/me/mailFolders/inbox/messageRules/{args.rule_id}",
        token=tok["access_token"],
    )
    print(f"Removed rule {args.rule_id}. No messages were deleted; any mail already filed stays put.")
    return 0


def cmd_category_list(args) -> int:
    """List the mailbox master categories, agent-legibly (name + colour). Read-only (FR-005)."""
    tok = runtime._authed_token("MailboxSettings.Read")
    cats = graph._master_categories(tok["access_token"])
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
    tok = runtime._authed_token(runtime.WRITE_SCOPE)
    existing = graph._find_category(graph._master_categories(tok["access_token"]), args.name)
    if existing:
        colour = existing.get("color", "no colour")
        print(f'Category "{args.name}" already exists ({colour}); no change.')
        return 0
    created = graph._ensure_category(tok["access_token"], args.name, args.color)
    colour = created.get("color", args.color)
    print(f'Created category "{args.name}" ({colour}). It now renders with a colour.')
    return 0


def cmd_folder_list(args) -> int:
    """List real mail folders as a nested tree (name + counts). Read-only; needs Mail.Read."""
    tok = runtime._authed_token("Mail.Read")
    tree = graph._folder_tree(
        tok["access_token"], include_hidden=bool(getattr(args, "include_hidden", False))
    )
    if args.format == "detailed":
        print(json.dumps(tree, indent=2))
        return 0
    if not tree:
        print("No mail folders found.")
        return 0

    count = 0

    def render(nodes, depth=0):
        nonlocal count
        for n in nodes:
            count += 1
            indent = "  " * depth
            print(
                f'{indent}- "{n["displayName"] or "(unnamed)"}"  '
                f"({n['totalItemCount']} total, {n['unreadItemCount']} unread)"
            )
            render(n["children"], depth + 1)

    render(tree)
    print(f"{count} mail folder(s). Pass --format detailed for ids + parentFolderId.")
    return 0


def cmd_searchfolder_list(args) -> int:
    """List virtual search folders (name, filter, source scope, id). Read-only (FR-007/FR-009)."""
    tok = runtime._authed_token("Mail.Read")
    data = runtime._graph_get(tok["access_token"], "/me/mailFolders/searchfolders/childFolders")
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
    tok = runtime._authed_token(runtime.SEARCHFOLDER_SCOPE)
    filter_query = args.filter_query or (
        graph._filter_query_for_category(args.category) if args.category else None
    )
    if not filter_query:
        raise runtime.SteerError(
            "Refusing to create this search folder: no filter given. Pass --category NAME "
            "(builds a category filter) or an explicit --filter_query (OData)."
        )
    source_names = args.source_folders or ["inbox"]
    # Well-known names (inbox, archive, …) are accepted verbatim by Graph; resolve any others to ids.
    _WELL_KNOWN = {"inbox", "archive", "drafts", "sentitems", "deleteditems", "junkemail", "msgfolderroot"}
    source_ids = [
        n if n.casefold() in _WELL_KNOWN else graph._resolve_folder_id(tok["access_token"], n)
        for n in source_names
    ]
    body = {
        "@odata.type": "microsoft.graph.mailSearchFolder",
        "displayName": args.name,
        "includeNestedFolders": bool(args.include_nested),
        "sourceFolderIds": source_ids,
        "filterQuery": filter_query,
    }
    created = runtime._http(
        "POST",
        f"{runtime.GRAPH}/me/mailFolders/searchfolders/childFolders",
        token=tok["access_token"],
        body=body,
    )
    print(
        f'Created search folder "{args.name}" (id: {created.get("id", "?")}). It presents a filtered '
        f"view (filter: {filter_query}) over {source_names}; it is virtual — no mail is moved or "
        f"deleted. Remove anytime with searchfolder-remove."
    )
    return 0


def cmd_searchfolder_remove(args) -> int:
    """Delete a search folder by id. Removes only the virtual folder, never mail (FR-007/FR-009)."""
    tok = runtime._authed_token(runtime.SEARCHFOLDER_SCOPE)
    runtime._http("DELETE", f"{runtime.GRAPH}/me/mailFolders/{args.folder_id}", token=tok["access_token"])
    print(f"Removed search folder {args.folder_id}. No messages were affected; it was only a filtered view.")
    return 0
