---
name: "searchfolder-remove"
description: "Delete a virtual Outlook search folder by id (DELETE /me/mailFolders/{id}) — the reversibility primitive for search folders. Removes ONLY the virtual folder; it never deletes any messages, because a search folder is just a saved filtered view. Uses an ordinary (recoverable) delete, never permanentDelete. Requires the search-folder sign-in (/msgraph-auth-login --mode folders; Mail.ReadWrite), the same tier used to create one. Get the id from searchfolder-list --format detailed. Pass --folder_id."
argument-hint: "--folder_id <search folder id>"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: true       # deletes the folder (not mail); reversible by re-creating
  idempotentHint: false
  openWorldHint: true
---

## What this does

Deletes a search folder (`DELETE /me/mailFolders/{id}`). Because the folder is virtual, removal
affects **no mail** — the messages it presented stay exactly where they are. This is the clean,
reversible undo for `searchfolder-create` (re-create the folder to bring the view back). Uses a normal
delete (recoverable), never `permanentDelete`. Needs the `folders` tier (`Mail.ReadWrite`).

## Typical flow

```bash
/msgraph-searchfolder-list --format detailed     # find the id
/msgraph-auth-login --mode folders               # if not already signed in to this tier
/msgraph-searchfolder-remove --folder_id AAMk...
```

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name searchfolder-remove
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" searchfolder-remove --folder_id AAMk...
# or:  python3 -m msgraph.client searchfolder-remove --folder_id AAMk...
```

## Output

```
Removed search folder AAMk.... No messages were affected; it was only a filtered view.
```

## Errors steer the agent

```
error: This action needs … run /msgraph-auth-login --mode folders.
error: Graph request failed (404 …): the folder id may be wrong — check searchfolder-list.
```
