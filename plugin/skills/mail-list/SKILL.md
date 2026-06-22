---
name: "mail-list"
description: "List recent messages from one Outlook folder, agent-legibly, for triage or to find a message to inspect. Defaults to the Inbox — what actually needs triage, not already-filed mail across every folder. Read-only (Mail.Read). Use when you need an overview of what's in the inbox — e.g. before proposing a rule, or to locate a message id for mail-get; pass --folder to inspect a different folder. concise (default) returns readable summaries (subject, sender, received time); detailed adds Graph ids needed for follow-up calls. Bounded by --limit (default 25) so it never dumps the whole mailbox. Requires a prior read sign-in (run /msgraph-auth-login)."
argument-hint: "[--limit N] [--format concise|detailed] [--folder NAME]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: true
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Fetches recent messages from a single folder via `GET /me/mailFolders/{folder}/messages` (newest
first), resolving the sender to a readable address and shaping the output for an agent. It defaults
to the **Inbox**, so the listing reflects true triage stragglers rather than mail already filed in
Newsletters/Archive/etc. Pass `--folder <well-known-or-name>` (e.g. `--folder archive`) to list
elsewhere; an unresolvable folder steers rather than erroring obscurely. It reads only — it holds
`Mail.Read` and reaches no write endpoint, so it cannot move, archive, or delete anything.

Reach for this for **triage/overview**. When you need one message's full content or its internet
headers (e.g. to inspect `List-Unsubscribe` before proposing a rule), follow up with **mail-get**
using an id from `--format detailed`.

## Discoverability

The kernel's `TOOLS` catalog is the source of truth for arguments — ask at runtime rather than
trusting this doc:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name mail-list
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" mail-list --limit 10 --format concise
# inbox by default; inspect another folder:
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" mail-list --folder archive
# or:  python3 -m msgraph.client mail-list ...
```

## Output (agent-legible)

`concise` returns readable summaries; pass `--format detailed` only when you need ids for a
follow-up call (`mail-get`):

```
- "Weekly Newsletter" from news@example.com  (received: 2026-06-19T08:01:00Z)
- "Receipt #4471" from billing@example.com   (received: 2026-06-18T22:14:00Z)
2 message(s). Pass --format detailed for IDs needed by follow-up commands.
```

## Errors steer the agent

```
error: not signed in — run /msgraph-auth-login first, then retry.
```
