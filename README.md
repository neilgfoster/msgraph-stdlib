# msgraph-stdlib

A Claude Code plugin for Microsoft Graph (Outlook) that is **stdlib-only, zero-dependency, and
zero-backend** by design — just `urllib` + `json`, no SDK, no server process, no install friction.

It gives an agent two capabilities, with safety built into the *structure*, not the behaviour:

1. **Read Outlook mail** — list/get messages and their headers, read-only.
2. **Author native Outlook message rules** — create / list / verify / remove server-side
   `messageRule`s, so deterministic mail organisation lives *in Outlook* (runs even when nothing
   else is, visible and editable in Outlook's own UI, reversible by deleting one rule).

## Why stdlib / zero-backend

The Microsoft Graph + Outlook plugin space is crowded — but it is almost entirely Node MCP servers
and SDK-based Python. A plugin you can read top-to-bottom, that pulls in nothing and runs nothing in
the background, is the empty niche. The constraint is the differentiator: portable, auditable, and
with no supply-chain surface beyond the standard library.

## Safety model (least privilege + verify-then-reversible)

- **Read-only by default.** Auth requests **`Mail.Read` only**. The plugin physically cannot move,
  archive, or delete a message — the token carries no write grant. Safety is structural.
- **Scope ratchet.** Writing rules requires the *separate* `MailboxSettings.ReadWrite` scope,
  granted only when you opt into rule authoring. Escalation is deliberate and auditable (the OAuth
  consent is the record).
- **Verify before install.** A candidate rule's **real catch-set is computed read-only** and shown
  *before* the rule is created — a rule is never trusted in the abstract (Graph `headerContains` is
  coarse substring matching, so it must be checked against actual mail).
- **Reversible by construction.** Rules file mail to a folder; they never delete. Removing one rule
  undoes the organisation.

## Layout

```
.claude-plugin/plugin.json        # manifest
skills/<subject>-<verb>/SKILL.md  # agent-facing commands (auth, mail-read, rule-*)
src/msgraph/client.py             # stdlib kernel — importable + runnable, exposes a `describe` catalog
docs/AGENT-FRIENDLY.md            # REQUIRED READING before adding/changing a skill
DEFINITION_OF_DONE.md             # what "working" means — the build target
CLAUDE.md                         # grounding + build plan for a Claude Code session in this repo
```

## Prerequisite (one-time, free)

An **Azure AD app registration** (public client, device-code flow enabled). Add the delegated
permission `Mail.Read` (and `MailboxSettings.ReadWrite` only if you want rule authoring). No cost,
no admin consent for personal accounts. Set the resulting client/tenant IDs via environment before
first auth — see `CLAUDE.md`.

## Status

Scaffolded; skills built spec-first (`/speckit-specify` → `clarify` → `plan` → `tasks` →
`implement`). See `DEFINITION_OF_DONE.md` for the target and `CLAUDE.md` for the build plan.

## License

MIT.
