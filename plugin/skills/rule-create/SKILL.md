---
name: "rule-create"
description: "Install a native Outlook message rule that FILES matching mail to a folder (move-to-folder only — never delete). Requires rule-authoring sign-in (run /msgraph-auth-login --mode rules; MailboxSettings.ReadWrite). REFUSES unless the exact same header_contains criteria were verified first with rule-verify — verify-then-install is a hard safety gate, not a convention. Use after you have inspected headers (mail-get) and confirmed the catch-set (rule-verify). The rule appears in Outlook's own Rules UI and is fully reversible: remove it with rule-remove and any mail already filed stays put. Pass a name, the verified header_contains substrings, and an existing target folder name."
argument-hint: "--name <rule name> --header_contains SUBSTR [SUBSTR ...] --move_to_folder <folder name>"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: false     # move-to-folder is additive/reversible — never deletes mail
  idempotentHint: false
  openWorldHint: true
---

## What this does

Creates a server-side `messageRule` under `POST /me/mailFolders/inbox/messageRules` with a
`headerContains` predicate and a **`moveToFolder` action only**. No delete-style action is ever
constructed, so installing a rule only ever *files* mail — removing the rule undoes the organisation
and mail already filed stays put.

**Two gates must pass, or it refuses (this is the heart of the safety model):**

1. **Scope ratchet** — the cached token must hold `MailboxSettings.ReadWrite`. A read-only sign-in
   structurally cannot reach here; escalate deliberately with `/msgraph-auth-login --mode rules`.
2. **Verify-then-install** — the *same* `header_contains` set must have been verified by `rule-verify`
   (which records the marker this command checks). Unverified criteria → refusal steering you to
   `rule-verify`. A coarse substring rule is never trusted in the abstract.

The target folder must already exist in Outlook (the command resolves its name to an id); rules file
mail to a folder, they never create or delete one.

## Typical flow

```bash
/msgraph-mail-get --message_id <id> --format detailed          # inspect headers (optional)
/msgraph-rule-verify --header_contains "List-Unsubscribe"      # preview catch-set + record marker
/msgraph-auth-login --mode rules                               # escalate (separate consent)
/msgraph-rule-create --name "Newsletters" \
    --header_contains "List-Unsubscribe" --move_to_folder "Newsletters"
```

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name rule-create
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" rule-create \
  --name "Newsletters" --header_contains "List-Unsubscribe" --move_to_folder "Newsletters"
# or:  python3 -m msgraph.client rule-create ...
```

## Output

```
Created rule "Newsletters" (id: AAMk...). It files mail whose headers contain ['List-Unsubscribe']
into "Newsletters". Verified catch-set was 7 message(s). Reverse anytime with rule-remove.
```

## Errors steer the agent

```
error: This action needs rule-authoring permission … run /msgraph-auth-login --mode rules.
error: Refusing to create this rule: its criteria were not verified first. Run rule-verify … then retry.
error: No mail folder named 'X' was found. Create it in Outlook first, or pass an existing folder name.
```
