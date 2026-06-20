---
name: "searchfolder-list"
description: "List the mailbox's virtual search folders (each folder's name, OData filter, source-folder scope, and id), read-only, via GET /me/mailFolders/searchfolders/childFolders. Requires read sign-in (/msgraph-auth-login; Mail.Read). Search folders are virtual filtered views — they never move or delete mail. Use to confirm a search folder exists and to get its id before removing it with searchfolder-remove. concise (default) shows name + filter + scope; detailed returns full JSON with ids."
argument-hint: "[--format concise|detailed]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: true
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Enumerates the search folders under the well-known `searchfolders` parent
(`GET /me/mailFolders/searchfolders/childFolders`). Read-only; needs only `Mail.Read`. Each entry
shows the display name, the `filterQuery`, whether the search is deep/shallow over its source folders,
and the id you pass to `searchfolder-remove`.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name searchfolder-list
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" searchfolder-list
# or:  python3 -m msgraph.client searchfolder-list --format detailed
```

## Output

```
- "Needs attention"  (id: AAMk...)
    filter: categories/any(c:c eq 'Needs attention')  [deep over 1 source folder(s)]
1 search folder(s). Pass --format detailed for full ids.
```
