---
name: "rule-verify"
description: "Compute the read-only CATCH-SET of a candidate rule — the existing inbox messages its header_contains criteria would currently match — WITHOUT writing anything. This is the safety keystone: ALWAYS run it before rule-create. It does two jobs: (1) previews exactly what the rule would catch so a coarse substring predicate is never trusted in the abstract, and (2) records the verification marker that rule-create requires (rule-create refuses unverified criteria). Read-only (Mail.Read). Pass the same header_contains substrings you intend to install. Requires a prior read sign-in (run /msgraph-auth-login)."
argument-hint: "--header_contains SUBSTR [SUBSTR ...] [--format concise|detailed]"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: true
  destructiveHint: false
  idempotentHint: true
  openWorldHint: true
---

## What this does

Fetches recent **Inbox** messages **with their internet headers** read-only and applies the same
coarse case-insensitive substring matching Outlook's `headerContains` predicate uses, returning the
exact set of messages (and a count) the proposed rule would match right now. The catch-set is
**inbox-only by design** — native message rules act on inbox arrivals, so the count reflects mail
currently in the Inbox, not matches already filed away in other folders (there is no flag to broaden
it). It performs **only GETs** — nothing is written to the mailbox (SC-002).

It also records a small **verification marker** (a hash of the normalised predicate set) next to the
token cache. `rule-create` checks for that marker and **refuses** to install a rule whose criteria
were not verified first — so "verify-then-install" is enforced across separate invocations, not left
to trust. Always run `rule-verify` with the *same* `header_contains` substrings you will pass to
`rule-create`.

An empty catch-set (count 0) is a valid, explicitly-reported result — worth knowing before you
install a rule that would currently catch nothing.

## Discoverability

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name rule-verify
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" rule-verify --header_contains "List-Unsubscribe"
# multiple substrings → ALL must be present in a message's headers to match
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" rule-verify --header_contains "List-Id" "newsletter"
# or:  python3 -m msgraph.client rule-verify --header_contains "List-Unsubscribe" --format detailed
```

## Output (agent-legible)

```
Catch-set for header_contains ['List-Unsubscribe']: 7 message(s)
- "Weekly Newsletter" from news@example.com  (received: 2026-06-19T08:01:00Z)
  ...
Verified. You may now run rule-create with these exact criteria.
```

## Errors steer the agent

```
error: not signed in — run /msgraph-auth-login first, then retry.
```
