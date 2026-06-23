# ADR 0001 — Scope isolation: one app registration vs per-tier apps

**Status:** Accepted — 2026-06-23
**Context source:** `docs/HANDOVER-runtime-and-scope.md` (Part B), kypr `005-session-triage` T017
**Decision owner:** neilgfoster
**Supersedes:** the unqualified "structural read-only" wording in the auth-login skill doc + README

## Context

The plugin presents four sign-in tiers — `read` / `rules` / `folders` / `messages` — as a
least-privilege **safety ratchet**, and the docs claimed:

> "A read-only token *structurally* carries no write grant, so even a bug cannot change the mailbox."

All four modes authenticate through **one and the same Azure app registration** (a single client id).
Because of how Microsoft Entra (AAD) consent works, once the user has consented to a write scope for
that client **even once**, the token endpoint returns **all previously-consented scopes on every
token**, regardless of the `scope` requested at a later sign-in.

Observed live (T017): an `auth-login` with the default `read` mode returned a cached token whose
scope was `Mail.Read MailboxSettings.Read MailboxSettings.ReadWrite Mail.ReadWrite` — i.e. a
"read-only sign-in" yielded a token that structurally **can** write, because earlier sessions had
consented the write tiers on that account.

**Therefore the runtime `--mode` flag does not structurally bound the issued token.** It controls what
the app *requests* (and so what the *first-ever* consent grants), but it cannot *narrow* a token below
what the account has already consented to for that client. The "structural" claim holds only in the
narrow window before any write mode is ever consented; after that it is documentation, not structure.
The real security boundary is the app registration + consent history, which the mode flag cannot
tighten.

## Decision

**Adopt Option 1: keep a single app registration; reframe `--mode` honestly as consent-shaping
ergonomics plus a runtime guardrail — not structural isolation.**

Concretely:

1. **One app registration** (one client id) remains, as today.
2. **Docs are reconciled** (this ADR; `plugin/skills/auth-login/SKILL.md`; `README.md`): `--mode`
   shapes which scopes are *requested at consent*; Microsoft consent is **sticky/cumulative**; a
   read-mode token is structurally write-incapable **only before any write mode has ever been
   consented** for the account+client.
3. **The runtime surfaces the truth:** at sign-in, when the granted scope is a write-capable superset
   of the requested mode, the plugin prints a **stderr warning** (`runtime._extra_write_scopes` +
   `_warn_scope_superset`). The token's real capability is never hidden.
4. **`_require_scopes` stays** — it refuses any verb whose needed scope is absent — but it is framed as
   a **guardrail** (it prevents *invoking* a write verb without the scope), not as proof the token
   cannot write.

## Alternatives considered

### Option 2 — Separate app registrations per tier (rejected)

A distinct client id for read vs write (`MSGRAPH_CLIENT_ID_READ` / `…_WRITE`) would bound each token
by *its own* app's declared/consented permissions, so a read-app token genuinely could not carry write
grants — restoring the structural guarantee.

**Rejected because:** it roughly doubles the one-time human setup (two Entra app registrations + env
wiring) for a personal-mailbox tool whose threat model is "don't let a bug mutate mail." The verb-level
guardrail (`_require_scopes`) plus the honesty warning already prevent accidental writes in practice;
the structural purity is not worth the setup tax here. Kept on record as the path to take **if** strict
least-privilege isolation ever becomes load-bearing (e.g. multi-user or untrusted-agent contexts).

### Option 3 — Per-session scope-down (rejected as non-viable)

Requesting fewer scopes does not shrink the returned token under AAD; narrowing requires revoking and
re-consenting. Not a runtime control. Noted and rejected.

## Consequences

- **Honest docs.** The "structurally cannot write" overclaim is removed; the real, qualified guarantee
  is stated wherever the modes are described (Constitution III — Honesty, No Overclaim).
- **Observable capability.** Users see a stderr warning when their read token is write-capable from
  prior consent, instead of being misled.
- **Unchanged ergonomics.** No new app registration, no new env, no new scope; the modes remain a
  convenient way to request the smallest consent that fits.
- **Reversible.** If Option 2 is ever needed, this ADR is superseded by a follow-up that adds per-tier
  client ids; nothing here blocks that.
