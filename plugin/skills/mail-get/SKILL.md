---
name: "mail-get"
description: "Fetch ONE Outlook message by id, including its full internet headers. Read-only (Mail.Read). Use when you need a single message's content or — crucially — its raw headers, e.g. to inspect List-Unsubscribe, Sender, or List-Id before proposing a header-based rule with rule-verify/rule-create. Get the message_id from mail-list --format detailed. concise (default) prints subject/sender/received plus the header list; detailed returns the full JSON. Requires a prior read sign-in (run /msgraph-auth-login)."
argument-hint: "--message_id <id> [--format concise|detailed]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: true
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Fetches a single message via `GET /me/messages/{id}` with `internetMessageHeaders` selected, so you
can read the raw headers Outlook rules match against. Read-only (`Mail.Read`) — reaches no write
endpoint.

This is the natural precursor to **rule-verify**: inspect a representative message's headers here to
choose the right `header_contains` substrings, then verify the catch-set read-only before installing
anything.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name mail-get
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" mail-get --message_id <id> --format concise
# or:  python3 -m msgraph.client mail-get --message_id <id> --format detailed
```

Get `<id>` from `mail-list --format detailed`.

## Output (agent-legible)

```
Subject: Weekly Newsletter
From:    news@example.com
Received: 2026-06-19T08:01:00Z

Internet headers (12):
  List-Unsubscribe: <mailto:unsubscribe@example.com>
  List-Id: Example Newsletter <news.example.com>
  ...
```

`--format detailed` returns the full message JSON.

## Errors steer the agent

```
error: not signed in — run /msgraph-auth-login first, then retry.
```
