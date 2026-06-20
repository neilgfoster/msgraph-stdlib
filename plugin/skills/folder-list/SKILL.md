---
name: "folder-list"
description: "List the mailbox's real mail folders as a nested tree (each folder's name, total/unread message counts, child count, and — in detailed mode — id + parentFolderId), read-only, via GET /me/mailFolders recursed through childFolders. Requires read sign-in (/msgraph-auth-login; Mail.Read). Use to audit and understand the folder layout — e.g. before proposing move-to-folder rules that target it. These are real mail folders, not virtual search folders (use searchfolder-list for those). concise (default) prints an indented tree with counts; detailed returns full JSON with the ids you need for follow-up calls."
argument-hint: "[--format concise|detailed] [--include_hidden true|false]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: true
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Enumerates the mailbox's real mail-folder tree (`GET /me/mailFolders`, recursing
`/{id}/childFolders` for folders that report children). Read-only; needs only `Mail.Read` — no write
escalation. Each node carries the display name, `totalItemCount`, `unreadItemCount`,
`childFolderCount`, `id`, and `parentFolderId`. The virtual `Search Folders` node is excluded — list
those with `searchfolder-list` instead.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name folder-list
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" folder-list
# or:  python3 -m msgraph.client folder-list --format detailed
# include hidden folders:  ... folder-list --include_hidden true
```

## Output

```
- "Inbox"  (1280 total, 37 unread)
  - "Receipts"  (412 total, 0 unread)
- "Archive"  (8901 total, 0 unread)
3 mail folder(s). Pass --format detailed for ids + parentFolderId.
```

`--format detailed` returns the full nested JSON (with `id` and `parentFolderId`) for follow-up calls.
