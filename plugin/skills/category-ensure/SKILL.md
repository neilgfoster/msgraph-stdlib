---
name: "category-ensure"
description: "Ensure a named Outlook master category exists: create it with a colour if absent (POST /me/outlook/masterCategories), no-op if it already exists. Idempotent. Requires rule-authoring sign-in (/msgraph-auth-login --mode rules; MailboxSettings.ReadWrite). Use to pre-create a label with a specific colour before assigning it; rule-create already ensures any category it assigns, so calling this first is optional unless you want to choose the colour. A category's display name is immutable once created. Pass --name and an optional --color preset (default preset9)."
argument-hint: "--name <category name> [--color presetN]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Create-if-absent for a master category. Lists the master categories, matches `--name`
case-insensitively, and if missing creates it (`POST /me/outlook/masterCategories` with
`{displayName, color}`). If present, it reports a no-op. Needs `MailboxSettings.ReadWrite` — the same
rule-authoring tier; no new scope.

Use it when you want a label to render with a **specific colour**. `rule-create --assign_category`
ensures categories automatically (defaulting the colour to `preset9`), so this verb is only needed
for colour control or to seed labels ahead of time. The display name cannot be changed after creation.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name category-ensure
```

## How it runs

```bash
/msgraph-auth-login --mode rules
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" category-ensure --name "Needs attention" --color preset9
# or:  python3 -m msgraph.client category-ensure --name "Receipts" --color preset5
```

## Output

```
Created category "Needs attention" (preset9). It now renders with a colour.
Category "Receipts" already exists (preset5); no change.
```

## Errors steer the agent

```
error: This action needs rule-authoring permission … run /msgraph-auth-login --mode rules.
```
