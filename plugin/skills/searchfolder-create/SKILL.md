---
name: "searchfolder-create"
description: "Create a virtual Outlook search folder — a saved filtered view (e.g. all mail tagged a category) — via POST /me/mailFolders/searchfolders/childFolders with @odata.type microsoft.graph.mailSearchFolder. Non-destructive: a search folder never moves or deletes mail, it only presents a filtered view. Requires the SEPARATE search-folder sign-in (/msgraph-auth-login --mode folders; Mail.ReadWrite) — a distinct, deliberately-escalated write tier from read and from rule authoring; a read or rules token structurally cannot create one. Pass --name and either --category NAME (builds a categories filter) or an explicit --filter_query (OData); optionally --source_folders (default inbox) and --include_nested (default true). Fully reversible with searchfolder-remove."
argument-hint: "--name <folder name> (--category <name> | --filter_query <odata>) [--source_folders FOLDER ...] [--include_nested true|false]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: false     # virtual folder; never moves or deletes mail
  idempotentHint: false
  openWorldHint: true
---

## What this does

Creates a `mailSearchFolder` under the well-known `searchfolders` parent: a virtual folder that
presents whichever mail matches its `filterQuery`, across the chosen `sourceFolderIds` (deep or
shallow). It owns no mail — creating it moves and deletes **nothing**, and removing it later is clean.

**Why its own scope tier.** Although a search folder is non-destructive, *creating* one is the first
time this plugin needs a write grant on mail itself (`Mail.ReadWrite` — the least-privileged
permission Graph offers for this, with no lower option). So it sits behind a separate, deliberate
escalation: `/msgraph-auth-login --mode folders`. This is **not** folded into the read or
rule-authoring tiers — a token from those modes lacks `Mail.ReadWrite` and the create refuses
structurally. That separation is the scope ratchet, the heart of the safety model.

**Filter.** `--category "Needs attention"` builds `categories/any(c:c eq 'Needs attention')` for you;
or pass `--filter_query` to supply any OData filter directly (it overrides `--category`).
`--source_folders` accepts well-known names (`inbox`, `archive`, …) or folder display names; default
is `inbox`. `--include_nested true` (default) deep-searches subfolders.

## Typical flow

```bash
/msgraph-category-list                                   # confirm the label exists
/msgraph-auth-login --mode folders                       # separate write tier (Mail.ReadWrite)
/msgraph-searchfolder-create --name "Needs attention" \
    --category "Needs attention" --source_folders inbox --include_nested true
/msgraph-searchfolder-list                               # see it (and its id)
```

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name searchfolder-create
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" searchfolder-create \
  --name "Needs attention" --category "Needs attention"
# or:  python3 -m msgraph.client searchfolder-create --name "Big" --filter_query "hasAttachments eq true"
```

## Output

```
Created search folder "Needs attention" (id: AAMk...). It presents a filtered view
(filter: categories/any(c:c eq 'Needs attention')) over ['inbox']; it is virtual — no mail is
moved or deleted. Remove anytime with searchfolder-remove.
```

## Errors steer the agent

```
error: This action needs … run /msgraph-auth-login --mode folders.
error: Refusing to create this search folder: no filter given. Pass --category NAME or --filter_query.
error: No mail folder named 'X' was found. Create it in Outlook first, or pass an existing folder name.
```
