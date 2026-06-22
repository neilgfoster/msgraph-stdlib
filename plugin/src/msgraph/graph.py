"""msgraph-stdlib Graph helpers — folder/category resolution above the runtime primitives.

Reaches the HTTP seam and constants via `runtime.<name>` at call time (never value-bound) so the
test seam is honoured across modules (feature 004 data-model: INV-1).
"""

import urllib.parse

from msgraph import runtime


def _resolve_folder_id(token: str, name: str) -> str:
    """Look up a mail folder id by display name for the move-to-folder action (data-model)."""
    data = runtime._graph_get(token, "/me/mailFolders", params={"$top": 100, "$select": "id,displayName"})
    for f in data.get("value", []):
        if f.get("displayName", "").casefold() == name.casefold():
            return f["id"]
    raise runtime.SteerError(
        f"No mail folder named '{name}' was found. Create it in Outlook first, or pass an "
        f"existing folder name (rule actions file mail to a folder; they never delete)."
    )


# Well-known folder names Graph accepts verbatim as a destinationId (no lookup needed).
_WELL_KNOWN_FOLDERS = {
    "inbox",
    "archive",
    "drafts",
    "sentitems",
    "deleteditems",
    "junkemail",
    "msgfolderroot",
    "clutter",
    "conflicts",
    "conversationhistory",
    "localfailures",
    "outbox",
    "recoverableitemsdeletions",
    "scheduled",
    "searchfolders",
    "serverfailures",
    "syncissues",
}


def _resolve_folder(token: str, dest: str) -> tuple[str, str]:
    """Resolve a folder reference to (folder_id, label). General-purpose: used for reads
    (mail-list --folder) and as a move destination (message-move) alike — it never names a
    delete target.

    Accepts a well-known folder name (used verbatim), a display name (resolved to its id, at any
    nesting depth, via the folder name map), or an opaque folder id (used verbatim when no name
    matches). Read-only resolution; the caller decides what to do with the resolved folder.
    """
    if dest.casefold() in _WELL_KNOWN_FOLDERS:
        return dest.casefold(), dest.casefold()
    # Invert id→name to resolve a display name to its id at any depth (covers nested folders).
    for fid, fname in _folder_name_map(token).items():
        if fname.casefold() == dest.casefold():
            return fid, fname
    # No name match — treat the value as an opaque id and let Graph validate it per request.
    return dest, dest


def _master_categories(token: str) -> list:
    """Return the mailbox master categories (id, displayName, color). Read-only."""
    return runtime._graph_get(token, "/me/outlook/masterCategories").get("value", [])


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
    return runtime._http(
        "POST",
        f"{runtime.GRAPH}/me/outlook/masterCategories",
        token=token,
        body={"displayName": name, "color": color},
    )


def _filter_query_for_category(name: str) -> str:
    """Build the OData filter for mail tagged a category, escaping single quotes by doubling."""
    return f"categories/any(c:c eq '{name.replace(chr(39), chr(39) * 2)}')"


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
            data = runtime._graph_get(token, pending.pop(), params=params)
            for f in data.get("value", []):
                fid = f.get("id")
                if not fid:
                    continue
                names[fid] = f.get("displayName", "")
                if f.get("childFolderCount", 0):
                    pending.append(f"/me/mailFolders/{urllib.parse.quote(fid, safe='')}/childFolders")
    except runtime.SteerError:
        pass  # partial map is fine — unresolved ids render as raw ids
    return names


# Fields fetched per mail folder for the folder tree (folder-list, feature: folder audit).
_FOLDER_TREE_SELECT = "id,displayName,parentFolderId,totalItemCount,unreadItemCount,childFolderCount"


# Well-known name of the virtual search-folder parent — excluded from the real-folder tree so
# folder-list never double-reports what searchfolder-list owns.
_SEARCHFOLDERS_NAME = "search folders"


def _folder_tree(token: str, include_hidden: bool = False) -> list:
    """Return the real mail-folder tree as nested nodes (data: folder audit).

    Each node carries displayName, id, parentFolderId, totalItemCount, unreadItemCount,
    childFolderCount and a ``children`` list. Recurses only into folders that report children, so the
    number of GETs is proportional to folders-with-children rather than the whole tree. Read-only —
    GET /me/mailFolders covers this with Mail.Read alone. Excludes the virtual ``Search Folders`` node
    (owned by searchfolder-list) so the two verbs never overlap.
    """
    params = {"$top": 200, "$select": _FOLDER_TREE_SELECT}
    if include_hidden:
        params["includeHiddenFolders"] = "true"

    def fetch(path: str) -> list:
        nodes = []
        for f in runtime._graph_get(token, path, params=params).get("value", []):
            fid = f.get("id")
            if not fid:
                continue
            node = {
                "id": fid,
                "displayName": f.get("displayName", ""),
                "parentFolderId": f.get("parentFolderId", ""),
                "totalItemCount": f.get("totalItemCount", 0),
                "unreadItemCount": f.get("unreadItemCount", 0),
                "childFolderCount": f.get("childFolderCount", 0),
                "children": [],
            }
            if node["childFolderCount"]:
                child_path = f"/me/mailFolders/{urllib.parse.quote(fid, safe='')}/childFolders"
                node["children"] = fetch(child_path)
            nodes.append(node)
        return nodes

    tree = fetch("/me/mailFolders")
    return [n for n in tree if n["displayName"].casefold() != _SEARCHFOLDERS_NAME]
