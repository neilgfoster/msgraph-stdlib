---
name: "auth-login"
description: "Sign in to Microsoft Graph via the OAuth device-code flow so the other msgraph verbs can reach the mailbox. Run this FIRST, before any mail-* or rule-* command. Default mode is read-only (Mail.Read + MailboxSettings.Read): read mail and list existing rules, with NO capability to change anything. Pass --mode rules only when you need to author rules — it consents to MailboxSettings.ReadWrite as a separate, deliberate escalation. Caches the token outside the repo (0600) and refreshes it silently. Use when a command reports 'not signed in' or 'escalate'. Requires MSGRAPH_CLIENT_ID / MSGRAPH_TENANT_ID in the environment (one-time Azure app registration; see below)."
argument-hint: "[--mode read|rules]  (default read)"
user-invocable: true
disable-model-invocation: false
annotations:
  readOnlyHint: false       # writes the local token cache (not the mailbox)
  destructiveHint: false
  idempotentHint: false     # each login mints a fresh token
  openWorldHint: true       # talks to the Microsoft identity platform
---

## What this does

Performs the OAuth 2.0 **device authorization grant** by hand (stdlib `urllib` only — no `msal`, no
SDK): it prints a short user code + a `microsoft.com/devicelogin` URL, you authorise in a browser,
and the kernel polls until consent and caches the resulting token at
`${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/token.json` (`0600`, outside the repo, never
committed). The refresh token (`offline_access`) is used to renew silently on later calls.

**The two modes are the safety ratchet — choose the smallest that fits the task:**

| Mode | Scopes granted | Lets you | Cannot |
|---|---|---|---|
| `read` (default) | `Mail.Read` + `MailboxSettings.Read` | `mail-list`, `mail-get`, `rule-list`, `rule-verify` | create/remove rules, mutate any mail |
| `rules` | `Mail.Read` + `MailboxSettings.ReadWrite` | the above **plus** `rule-create`, `rule-remove` | mutate individual messages (no verb does) |

A read-only token *structurally* carries no write grant, so even a bug cannot change the mailbox.
Escalating to `--mode rules` is a separate browser consent — the OAuth grant is the audit record.
Stay in `read` until you actually need to install or remove a rule.

## One-time prerequisite (free, human)

Register a free **Azure AD app** (public client, device-code/public-client flow **enabled**) with
delegated permissions `Mail.Read` + `MailboxSettings.Read` (+ `MailboxSettings.ReadWrite` for rule
authoring). Personal Microsoft accounts need no admin consent. Then export, before first sign-in:

```bash
export MSGRAPH_CLIENT_ID="<application (client) id>"
export MSGRAPH_TENANT_ID="consumers"   # or "common" for work/school + personal
```

These are read from the environment and never hardcoded. If `MSGRAPH_CLIENT_ID` is unset, the verb
returns a steering error explaining this.

## Discoverability

The kernel's `TOOLS` catalog is the single source of truth for every verb's arguments — don't rely
on this doc staying in sync, ask at runtime:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe                  # all verbs
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" describe --name auth-login # this verb
```

## How it runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" auth-login                 # read-only (default)
python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" auth-login --mode rules    # escalate to write
# or, as a module:  python3 -m msgraph.client auth-login [--mode rules]
```

## Output

The device code + verification URL are printed to stderr; on success a one-line confirmation names
the mode and granted scopes. The access token itself is never printed.

## Errors steer the agent

```
error: MSGRAPH_CLIENT_ID is not set. Register a free Azure AD public client … then export
       MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID.
error: Device-code sign-in timed out before authorisation. Run /msgraph-auth-login again.
```
