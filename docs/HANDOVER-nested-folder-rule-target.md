# Handover: `rule-create --move_to_folder` cannot target a nested folder

**Status:** OPEN — raised 2026-06-22.
**Repo context:** kypr `/kypr-triage` session surfaced this during live rule authoring.

## The problem

`rule-create` resolves its `--move_to_folder <name>` target via `_resolve_folder_id`
(`src/msgraph/graph.py:12`), which queries only the **top-level** folder collection:

```python
data = runtime._graph_get(token, "/me/mailFolders", params={"$top": 100, "$select": "id,displayName"})
for f in data.get("value", []):
    if f.get("displayName", "").casefold() == name.casefold():
        return f["id"]
raise runtime.SteerError(f"No mail folder named '{name}' was found. ...")
```

`GET /me/mailFolders` returns only the immediate children of the mailbox root. It does
**not** recurse into `childFolders`. So any folder nested under another (e.g.
`Inbox/Newsletters`, `Inbox/School`) is invisible to the lookup and `rule-create`
fails with "No mail folder named '<name>' was found" — even though the folder plainly
exists.

This bites the two-tier folder model directly: the intended layout puts the filing
subfolders **under Inbox** (transient tier), so by design the move targets are nested —
exactly the case the resolver can't see.

Note: existing rules that already target a nested folder keep working, because a rule
stores the resolved folder **id** and Graph fires on the id regardless of where the
folder now sits. The failure is only at *creation* time, when resolving a name.

## The asymmetry (and the fix it points to)

The codebase already has a depth-aware resolver: `_resolve_folder` (`graph.py:46`) uses
`_folder_name_map` (`graph.py:100`) to match a display name "at any nesting depth". It
backs `message-move --destination_folder` and `mail-list --folder`, both of which
resolve nested folders fine.

`rule-create` simply uses the older top-level-only `_resolve_folder_id` instead.

**Fix direction:** have `rule-create`'s move-target resolution go through the recursive
folder name map (reuse `_folder_name_map` / `_resolve_folder`) so it matches a folder at
any depth — bringing `rule-create` into line with `message-move` and `mail-list`.
Preserve the existing well-known-name fast path and the steering error when the name
genuinely doesn't exist anywhere.

## Reproduce

1. Mailbox with a folder nested under Inbox, e.g. `Inbox/Newsletters`.
2. `rule-create --name "kypr:newsletters:example" --header_contains "example.com" --move_to_folder "Newsletters"`
3. Observe: `error: No mail folder named 'Newsletters' was found.`
4. `folder-list` confirms `Newsletters` exists (nested under `Inbox`); `message-move
   --destination_folder "Newsletters" --dry_run true` resolves it fine — proving the
   depth-aware resolver already handles it.

## Acceptance

- `rule-create --move_to_folder <name>` resolves a folder at any nesting depth.
- A genuinely non-existent name still raises the existing steering error.
- Regression test constructs the nested-folder case (mock `childFolders`) and asserts the
  rule's `moveToFolder` action gets the nested folder's id.
