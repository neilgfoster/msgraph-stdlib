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

**The modes are the safety ratchet — choose the smallest that fits the task:**

| Mode | Scopes granted | Lets you | Cannot |
|---|---|---|---|
| `read` (default) | `Mail.Read` + `MailboxSettings.Read` | `mail-list`, `mail-get`, `rule-list`, `rule-verify`, `category-list`, `folder-list`, `searchfolder-list` | create/remove rules, mutate any mail |
| `rules` | `Mail.Read` + `MailboxSettings.ReadWrite` | the above **plus** `rule-create`, `rule-remove`, `category-ensure` | mutate individual messages, create search folders |
| `folders` | `Mail.ReadWrite` + `MailboxSettings.Read` | the read verbs **plus** `searchfolder-create`, `searchfolder-remove` | author rules |
| `messages` | `Mail.ReadWrite` + `MailboxSettings.Read` | the read verbs **plus** `message-move` (MOVE only, never delete) | author rules; **delete a message** (no verb does, no scope grants it) |

A read-only token *structurally* carries no write grant, so even a bug cannot change the mailbox.
Each escalation (`--mode rules` / `folders` / `messages`) is a separate browser consent — the OAuth
grant is the audit record. No mode ever grants a delete capability. Stay in `read` until you actually
need to write.

## One-time prerequisite (free, human)

You register a free **Azure AD (Entra) app** once. The app registration and tenant are Entra-level
and **free forever** — only the steps to *get* a tenant trip people up, so follow these exactly. (All
verified during the first live run.)

**0. A personal Microsoft account has NO tenant by default.** It sits in the shared "Microsoft
Services" directory, where app registration is impossible. You must create your own tenant first.

**1. Create a tenant.** Per Microsoft docs the prerequisite is an Azure subscription — start the free
trial at <https://azure.microsoft.com/free>. It requires **card verification** (~£1 reversible hold,
no auto-charge; the trial subscription is *disabled* at 30 days, not upgraded). Durability: once the
tenant exists, the app registration and token issuance keep working at **zero cost** after the trial
subscription is disabled — the subscription is only needed to create the tenant, not to run the app.

**2. Use the Entra admin center — <https://entra.microsoft.com>, NOT portal.azure.com.** A tenant with
no active subscription makes the Azure portal default to the wrong directory (error `AADSTS160021`).

**3. Register the app** (Entra → App registrations → New registration):

| Setting | Value |
|---|---|
| Supported account types | **Personal Microsoft accounts only** (this makes `MSGRAPH_TENANT_ID="consumers"` correct) |
| Redirect URI | **leave blank** (device-code flow needs none) |
| Authentication → **Allow public client flows** | **Yes** — REQUIRED, or device-code fails. In the new "Authentication (Preview)" tab this toggle lives under the **Settings** sub-tab (no longer under "Advanced settings" — docs that say otherwise are outdated). |
| API permissions (delegated) | `Mail.Read`, `MailboxSettings.Read` (+ `MailboxSettings.ReadWrite` for rule authoring). Personal accounts need **no admin consent** — consent happens in-browser at sign-in. The default `User.Read` can stay; the kernel never requests it. |

**4. Export the values** before first sign-in:

```bash
export MSGRAPH_CLIENT_ID="<application (client) id>"   # a public client's id is NOT a secret — plaintext is fine
export MSGRAPH_TENANT_ID="consumers"                   # "Personal Microsoft accounts only" ⇒ consumers
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
