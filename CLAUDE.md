# CLAUDE.md

Grounding **and the build plan** for any Claude Code session working in this repository. This repo was
scaffolded from `neilgfoster/claude-plugin-template`. It is a standalone, public, MIT plugin — it has
**no dependency on, and needs no knowledge of, any private consumer.** Everything required to build it
to "done" is in this repo. The target is `DEFINITION_OF_DONE.md`; read it first.

## What this plugin is

`msgraph-stdlib` — a Claude Code plugin that lets an agent **read Outlook mail** and **author native
Outlook message rules** via Microsoft Graph, with no third-party dependencies and no backend.

The `plugin/src/example/` package and `plugin/skills/example-subject-verb/` skill are the **inert
template reference pattern**. Your first build step is to replace them (see "Build plan" below). Keep them as
a reference while you work; delete them once the real skills exist.

## Non-negotiable conventions (inherited from the template — do not relax)

- **stdlib only, zero third-party dependencies, no backend/server.** `urllib` for HTTP, `json` for
  parsing. Hand-roll the OAuth device-code dance (~30 lines). If you reach for `msal`/`azure-*`/
  `requests`, stop — the constraint *is* the product (portable, auditable, no supply-chain surface).
- **Secrets/tokens NEVER live in the repo.** Cache the token outside the tree at
  `${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/token.json`, `0600`. Never committed, not even
  encrypted. Do not add an in-repo secrets path or any git-crypt dependency.
- **Agent-friendly by design.** Every skill follows `docs/AGENT-FRIENDLY.md` (read it before writing
  a skill): onboarding-quality `description` (what + *when to use*), flat JSON-schema inputs
  (no `oneOf`/`allOf`/`anyOf`), agent-legible output (resolve IDs to names; concise/detailed modes),
  steering error messages, accurate behavioural `annotations`, and a runtime `describe` catalog
  (the zero-backend equivalent of MCP `tools/list`).

## Safety model — build it into the structure, not the behaviour

This is the heart of the plugin; do not weaken it for convenience.

- **Read is `Mail.Read`-only.** Requesting only `Mail.Read` makes "cannot mutate mail" *structural*:
  even a bug cannot archive/move/delete, because the token carries no write grant.
- **Scope ratchet.** Rule authoring needs the **separate** `MailboxSettings.ReadWrite` scope. Keep
  the two scopes in distinct auth modes so a read-only user never holds write capability. Escalating
  is a deliberate, auditable act (the OAuth consent grant is the record).
- **Verify-then-install.** Before creating a rule, compute its **real catch-set read-only** (which
  messages it would match) and surface that for confirmation. `headerContains` is coarse substring
  matching over raw headers, so a rule is **never trusted in the abstract** — always checked against
  actual mail first.
- **Reversible by construction.** Rule actions **file to a folder; never delete.** Removing one rule
  undoes the organisation. No imperative per-message mutation anywhere in this plugin.

## Capabilities to build (the verbs)

Group into skills under `plugin/skills/<subject>-<verb>/`, all backed by the `plugin/src/msgraph/` kernel:

| Skill | Scope | Notes |
|---|---|---|
| `auth-login` | `Mail.Read + MailboxSettings.Read` (default read-only) or `Mail.Read + MailboxSettings.ReadWrite` (opt-in) | device-code flow; cache token at the XDG path; refresh via refresh-token |
| `mail-list` / `mail-get` | `Mail.Read` | list/get messages incl. headers (`internetMessageHeaders`); concise/detailed; pagination default |
| `rule-list` | `MailboxSettings.Read` *(rules are mailbox settings; included in read-only mode — resolved during `plan`)* | enumerate existing `messageRule`s, agent-legible |
| `rule-verify` | `Mail.Read` | given candidate predicates (e.g. `headerContains: ["List-Unsubscribe"]`), compute and return the **read-only catch-set** — no write |
| `rule-create` | `MailboxSettings.ReadWrite` | install a verified rule (predicate → move-to-folder action). Refuse unless a catch-set was verified |
| `rule-remove` | `MailboxSettings.ReadWrite` | delete a rule by id (the reversibility primitive) |

Graph endpoints are simple REST over `urllib`; `messageRule` lives under
`/me/mailFolders/inbox/messageRules`. `messageRulePredicates.headerContains` is **Graph v1.0 GA**.

## Prerequisite the human must do once (free)

Azure AD **app registration**: public client, device-code/public-client flow enabled, delegated
permissions `Mail.Read` + `MailboxSettings.Read` (read-only: read mail and list rules) (+
`MailboxSettings.ReadWrite` for rule authoring). Personal accounts need no admin consent. The session should read `MSGRAPH_CLIENT_ID` / `MSGRAPH_TENANT_ID` (default tenant
`consumers` or `common`) from the environment — never hardcode them. Document this in
`plugin/skills/auth-login` and the README. **This is not blocking** for `specify`/`clarify`/`plan`/`tasks`
or for offline-testable code; only live auth/integration testing needs it.

## Build plan (spec-first; this is the work)

This repo uses Spec-Driven Development locally. The SDD scaffolding (`.specify/`, `specs/`, `.tredl/`)
is **gitignored on purpose** (see `.gitignore`) — keep the public surface minimal; do not commit it
or advertise it.

1. **Initialise SDD/tredl locally** if not already present (the tredl on-ramp / `/speckit-*`
   commands). This makes the build observable from the first edit.
2. `/speckit-specify` — one feature: **Graph device-code auth + Outlook mail read + message-rule
   CRUD with read-only catch-set verification.** Carry the safety model above as hard requirements.
3. `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
4. Replace `plugin/src/example/` → `plugin/src/msgraph/` (update `APP`); replace the example skill
   with the real ones; make `python3 -m msgraph.client describe` emit the `TOOLS` catalog.
5. Validate against `DEFINITION_OF_DONE.md`. Open a PR for review.

## Where things are

| Path | Purpose |
|---|---|
| `DEFINITION_OF_DONE.md` | **The build target** — read first |
| `.claude-plugin/marketplace.json` | Marketplace entry — plugin `source` points at `./plugin` |
| `plugin/.claude-plugin/plugin.json` | Plugin manifest (lives inside the shippable payload) |
| `plugin/skills/<subject>-<verb>/SKILL.md` | Agent-facing commands |
| `plugin/src/msgraph/client.py` | Stdlib kernel — importable AND runnable; owns the `describe` catalog |
| `docs/AGENT-FRIENDLY.md` | **Required reading** — agent-tool design principles |
| `pyproject.toml`, `tests/`, `.github/` | Dev tooling, tests, CI/release — never shipped in `plugin/` |

**Two-tier layout.** `plugin/` is the shippable payload (its own `.claude-plugin/plugin.json` +
`skills/`, `src/`, `hooks/`); the repo root is the build/distribution repo. Inside the plugin,
reference bundled files via `${CLAUDE_PLUGIN_ROOT}/...` — it resolves to `plugin/`.

<!-- SPECKIT START -->
Active feature plan: `specs/001-msgraph-mail-rules/plan.md` (spec, research, data-model,
contracts/tools.md, quickstart alongside it). Read it for the technical context, the stdlib-only
device-code design, the `TOOLS` catalog contract, and the safety-model decisions before implementing.
<!-- SPECKIT END -->
