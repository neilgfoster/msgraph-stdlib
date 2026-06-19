---
name: "rule-remove"
description: "Delete an Outlook inbox message rule by id — the reversibility primitive that undoes what rule-create installed. Removes ONLY the rule; it never deletes any messages, and mail already filed by that rule stays exactly where it is. Requires rule-authoring sign-in (run /msgraph-auth-login --mode rules; MailboxSettings.ReadWrite). Get the rule_id from rule-list --format detailed. Use to retract a rule that is over- or under-catching, or to clean up after experimenting."
argument-hint: "--rule_id <id>"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: true      # removes a rule (advisory) — but NEVER deletes mail
  idempotentHint: false      # a retry targets a gone id and 404s
  openWorldHint: true
---

## What this does

Issues `DELETE /me/mailFolders/inbox/messageRules/{id}` — removing a single rule and nothing else.
This is the **reversibility primitive** of the whole plugin: because `rule-create` only ever files
mail (move-to-folder, never delete), deleting the rule undoes the organisation while every message it
previously filed stays put. No verb in this plugin deletes a message.

Requires `MailboxSettings.ReadWrite` (run `/msgraph-auth-login --mode rules`). The
`destructiveHint: true` is advisory — it reflects "removes a rule", not any risk to your mail.

Find the `rule_id` with `rule-list --format detailed`.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name rule-remove
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" rule-list --format detailed   # find the id
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" rule-remove --rule_id <id>
# or:  python3 -m msgraph.client rule-remove --rule_id <id>
```

## Output

```
Removed rule AAMk.... No messages were deleted; any mail already filed stays put.
```

## Errors steer the agent

```
error: This action needs rule-authoring permission … run /msgraph-auth-login --mode rules.
error: Graph request failed (404 …): the rule id may already be gone (rule-remove is not retry-safe).
```
