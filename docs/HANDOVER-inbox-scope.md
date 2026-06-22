# Handover: `rule-verify` and `mail-list` search all folders, not inbox-only

**Status:** RESOLVED 2026-06-22 — feature `006-inbox-scope` (see `specs/006-inbox-scope/`, CHANGELOG
[Unreleased]). Both verbs now read `GET /me/mailFolders/inbox/messages`; `mail-list` gained an
optional `--folder` flag; `rule-verify` is always inbox-only.

**Raised:** 2026-06-22  
**Repo context:** kypr `/kypr-triage` session surfaced this during live use.

## The problem

Both `mail-list` and `rule-verify` call `GET /me/messages`, which Microsoft Graph
returns messages from **all mail folders** — Inbox, Archive subfolders, Newsletters,
Shopping, etc. — sorted by `receivedDateTime desc`.

This causes two concrete failures in the triage flow:

1. **`mail-list` triage overview is misleading.** It shows the 30 most recent messages
   across the whole mailbox. Already-filed mail (in Newsletters, School, etc.) appears
   alongside true inbox stragglers, making it impossible to tell what actually needs
   attention.

2. **`rule-verify` catch-set is not inbox-scoped.** When proposing a new rule, the
   point is to know "how many messages currently sitting in the inbox would this catch?"
   Instead it returns matches from wherever the message lives now. A predicate that
   returns 4 hits may have 0 in the inbox — all 4 already filed. This produces false
   confidence in a rule's value and can mislead the approve/gate step.

## Expected behaviour

| Verb | Expected scope | Current scope |
|------|---------------|---------------|
| `mail-list` | Inbox only (default); optionally `--folder <name>` | All folders |
| `rule-verify` | Inbox only (where unprocessed mail lives) | All folders |

## Fix

Switch both verbs from `GET /me/messages` to
`GET /me/mailFolders/inbox/messages` for the default (no-argument) case.

For `mail-list`, consider adding an optional `--folder <well-known-or-name>` flag
so callers can explicitly request a different folder. `rule-verify` should always
be inbox-only (no flag needed — rules act on inbox arrivals).

Relevant code:

- `plugin/src/msgraph/verbs.py` — `cmd_mail_list` (line ~93) and
  `_fetch_messages_with_headers` (line ~184); both use `"/me/messages"`.
- Tests: `tests/` — any test mocking `_graph_get` at `"/me/messages"` will need
  the expected URL updated to `"/me/mailFolders/inbox/messages"`.

## Acceptance

- `mail-list` (no args) returns only Inbox messages.
- `rule-verify` catch-set count matches what you see in the Outlook inbox UI.
- `mail-list --folder newsletters` (or equivalent) returns messages from that folder.
- Existing tests pass; new test asserts the inbox-scoped URL is called.
