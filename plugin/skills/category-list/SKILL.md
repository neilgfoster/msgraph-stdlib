---
name: "category-list"
description: "List the mailbox's Outlook master categories (each label's name and colour), read-only, via GET /me/outlook/masterCategories. Requires read sign-in (/msgraph-auth-login; MailboxSettings.Read). Use to see which labels already exist before authoring an assign-category rule (rule-create --assign_category) or a category search folder (searchfolder-create --category). Pairs with category-ensure, which create-if-absent a named category. concise (default) shows name + colour; detailed returns full JSON."
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

Lists the mailbox master category list (`GET /me/outlook/masterCategories`) — the named, coloured
labels Outlook uses. Read-only; needs only `MailboxSettings.Read` (the default read sign-in). Use it
to discover existing labels before you assign one in a rule or filter on one in a search folder.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name category-list
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" category-list
# or:  python3 -m msgraph.client category-list --format detailed
```

## Output

```
- "Needs attention"  (preset9)
- "Receipts"  (preset5)
2 categor(y/ies).
```

## Errors steer the agent

```
error: Not signed in — run /msgraph-auth-login first, then retry.
```
