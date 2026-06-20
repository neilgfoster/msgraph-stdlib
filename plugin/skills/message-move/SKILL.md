---
name: "message-move"
description: "Move one or more Outlook messages to a destination mail folder via POST /me/messages/{id}/move (Graph v1.0 GA). MOVE only — it NEVER deletes, and the move is reversible (move the message back). Use it to re-file backlog mail that incoming-only message rules cannot touch (rules fire on arriving mail; existing mail needs a direct move). ALWAYS preview first with --dry_run true: it resolves the destination and lists the exact messages that WOULD move while writing nothing, so a caller can gate the move on the shown set. Batch-safe: each id reports its own outcome, so one stale id never aborts the rest. Requires the SEPARATE message-write sign-in (/msgraph-auth-login --mode messages; Mail.ReadWrite) — a distinct, deliberately-escalated write tier from read, rule authoring, and search folders; a token from those modes structurally cannot move a message."
argument-hint: "--message_ids <id> [<id> ...] --destination_folder <name|well-known|id> [--dry_run true|false]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false
  destructiveHint: false     # MOVE only; never deletes — fully reversible
  idempotentHint: true       # moving an already-moved message is a no-op-ish re-file, reported per id
  openWorldHint: true
---

## What this does

Relocates each given message to a destination mail folder with Graph's `move` action
(`POST /me/messages/{id}/move` with `{ "destinationId": "<folder>" }`). The destination may be a
folder **display name**, a **well-known name** (`inbox`, `archive`, `deleteditems`, `junkemail`, …),
or an opaque **folder id**. Mail is **filed, never deleted** — `move` is recoverable (move it back),
which is exactly why this plugin opens per-message mutation here and nowhere else.

**Why its own scope tier.** Moving a message is the first time this plugin writes to mail *content*
(`Mail.ReadWrite`). So it sits behind a separate, deliberate escalation:
`/msgraph-auth-login --mode messages`. It is **not** folded into the read or rule-authoring tiers — a
token from those modes lacks `Mail.ReadWrite` and the move refuses **structurally**. No delete-capable
scope is ever requested anywhere in this plugin; deletion stays impossible by construction.

**Preview, then move.** Run with `--dry_run true` first: it resolves the destination and prints the
exact set that would move, writing nothing — mirror of the rule-verify "compute the set, write
nothing" gate. Re-run without `--dry_run` to perform the move.

**Batch-safe.** Each id is moved independently; a bad/stale id reports `✗` and the batch continues.
The output pairs each source id with its new id so the caller can log and reverse the operation.

## Typical flow

```bash
/msgraph-mail-list --format detailed                 # get message ids
/msgraph-auth-login --mode messages                  # separate write tier (Mail.ReadWrite)
/msgraph-message-move --message_ids AAA BBB \
    --destination_folder "Archive" --dry_run true     # preview — writes nothing
/msgraph-message-move --message_ids AAA BBB \
    --destination_folder "Archive"                    # perform the move
```

Reverse any move by moving the same messages back to their source folder.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name message-move
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" message-move \
  --message_ids AAMkADk... AAMkADl... --destination_folder archive --dry_run true
# then, to commit:
python3 -m msgraph.client message-move --message_ids AAMkADk... --destination_folder "Archive"
```

## Output

```
DRY RUN — would move 2 message(s) to "Archive". Nothing was written.
  - "Your receipt" from billing@example.com  [AAMkADk...]
  - "Weekly digest" from news@example.com  [AAMkADl...]

Re-run without --dry_run to perform the move (reversible: move back to the source folder).
```

```
Moved 2/2 message(s) to "Archive". MOVE only — nothing deleted.
  ✓ AAMkADk... → new id AAMkARCH1...
  ✓ AAMkADl... → new id AAMkARCH2...

Reversible: move these back with message-move --destination_folder <source folder>.
```

## Errors steer the agent

```
error: This action needs mail-write permission (Mail.ReadWrite) … run /msgraph-auth-login --mode messages.
```

A destination that matches no well-known name and no folder display name is passed to Graph verbatim
as a folder id; if it is not a real folder, each message reports a `✗` with the Graph error (the batch
is unaffected). Run `--dry_run true` first, or `/msgraph-folder-list`, to confirm the destination.
