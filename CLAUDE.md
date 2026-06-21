# CLAUDE.md

Grounding **and the build plan** for any Claude Code session working in this repository. This repo was
scaffolded from `neilgfoster/claude-plugin-template`. It is a standalone, public, MIT plugin — it has
**no dependency on, and needs no knowledge of, any private consumer.** Everything required to build it
is in this repo. The plugin has shipped (v0.4.0) — all 14 verbs (+ `describe`) are live and the suite
is green; `describe` and `CHANGELOG.md` are the live source of truth for what's built.

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
- **Scope ratchet.** Each write capability is a **separate**, distinctly-consented tier in its own auth
  mode, so a read-only user never holds write capability: rule/category authoring
  (`MailboxSettings.ReadWrite`, `--mode rules`), search folders (`Mail.ReadWrite`, `--mode folders`),
  and message move (`Mail.ReadWrite`, `--mode messages`). Escalating is a deliberate, auditable act
  (the OAuth consent grant is the record).
- **Verify-then-install.** Before creating a rule, compute its **real catch-set read-only** (which
  messages it would match) and surface that for confirmation. `headerContains` is coarse substring
  matching over raw headers, so a rule is **never trusted in the abstract** — always checked against
  actual mail first.
- **Reversible by construction, and never delete.** Rule actions **file to a folder; never delete** —
  removing one rule undoes the organisation. The one imperative per-message action, `message-move`, is
  **move-only and reversible** (move it back) behind its own `--mode messages` tier. **No verb deletes
  a message and no delete-capable scope is ever requested**, so deletion is structurally impossible.

## Capabilities (the verbs — all shipped)

14 verbs (+ `describe`) live as skills under `plugin/skills/<subject>-<verb>/`, all backed by the
`plugin/src/msgraph/` kernel. `describe` is the live source of truth for this list:

| Skill | Scope (auth mode) | Notes |
|---|---|---|
| `auth-login` | tiered: `Mail.Read + MailboxSettings.Read` (read, default) · `+ MailboxSettings.ReadWrite` (`--mode rules`) · `Mail.ReadWrite` (`--mode folders`) · `Mail.ReadWrite` (`--mode messages`) | device-code flow; cache token at the XDG path; refresh via refresh-token |
| `mail-list` / `mail-get` | `Mail.Read` | list/get messages incl. headers (`internetMessageHeaders`); concise/detailed; pagination default |
| `message-move` | `Mail.ReadWrite` (`--mode messages`) | move message(s) to a folder (`POST /me/messages/{id}/move`); MOVE-only, reversible, never delete; `--dry_run` preview; batch-safe per-message outcome |
| `rule-list` | `MailboxSettings.Read` *(rules are mailbox settings; included in read-only mode)* | enumerate existing `messageRule`s, agent-legible |
| `rule-verify` | `Mail.Read` | given candidate predicates (e.g. `headerContains: ["List-Unsubscribe"]`), compute and return the **read-only catch-set** — no write |
| `rule-create` | `MailboxSettings.ReadWrite` | install a verified rule (predicate → move-to-folder **and/or assign-category** action). Refuse unless a catch-set was verified |
| `rule-remove` | `MailboxSettings.ReadWrite` | delete a rule by id (the reversibility primitive) |
| `category-list` / `category-ensure` | `MailboxSettings.Read` / `MailboxSettings.ReadWrite` | list master categories; create-if-absent a coloured category (idempotent) |
| `folder-list` | `Mail.Read` | list real mail folders as a nested tree (counts), read-only |
| `searchfolder-list` / `searchfolder-create` / `searchfolder-remove` | `Mail.Read` / `Mail.ReadWrite` (`--mode folders`) | list / create / remove virtual `mailSearchFolder` views; never move or delete mail |

Graph endpoints are simple REST over `urllib`; `messageRule` lives under
`/me/mailFolders/inbox/messageRules`. `messageRulePredicates.headerContains` is **Graph v1.0 GA**.

## Prerequisite the human must do once (free)

Azure AD **app registration**: public client, device-code/public-client flow enabled, delegated
permissions `Mail.Read` + `MailboxSettings.Read` (read-only: read mail and list rules) (+
`MailboxSettings.ReadWrite` for rule/category authoring, + `Mail.ReadWrite` for search folders and
message move). Personal accounts need no admin consent. The session should read `MSGRAPH_CLIENT_ID` / `MSGRAPH_TENANT_ID` (default tenant
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
5. Validate against the safety model and CI (stdlib-only guard, offline suite green). Open a PR for review.

## Where things are

| Path | Purpose |
|---|---|
| `CHANGELOG.md` | **What's shipped** — the release history (single source of truth alongside `describe`) |
| `.claude-plugin/marketplace.json` | Marketplace entry — plugin `source` points at `./plugin` |
| `plugin/.claude-plugin/plugin.json` | Plugin manifest (lives inside the shippable payload) |
| `plugin/skills/<subject>-<verb>/SKILL.md` | Agent-facing commands |
| `plugin/src/msgraph/` | Stdlib kernel package (importable AND runnable). `client.py` = thin CLI entrypoint owning dispatch + `describe`; `runtime.py` = HTTP seam + token cache + markers + Graph primitives (patch the seam here); `catalog.py` = TOOLS; `render.py`/`graph.py`/`verbs.py` = shaping/helpers/verbs |
| `docs/AGENT-FRIENDLY.md` | **Required reading** — agent-tool design principles |
| `pyproject.toml`, `tests/`, `.github/` | Dev tooling, tests, CI/release — never shipped in `plugin/` |

**Two-tier layout.** `plugin/` is the shippable payload (its own `.claude-plugin/plugin.json` +
`skills/`, `src/`, `hooks/`); the repo root is the build/distribution repo. Inside the plugin,
reference bundled files via `${CLAUDE_PLUGIN_ROOT}/...` — it resolves to `plugin/`.

<!-- SPECKIT START -->
Active feature plan: `specs/005-docs-refresh/plan.md` (documentation-only refresh to match shipped
0.3.0 — add `message-move` + the `--mode messages` tier across the docs, describe the layered package,
and HONESTLY reconcile the docs' "No imperative per-message mutation" constraint to its
true narrower guarantee: move-only, never-delete, reversible, separately consented; no code change,
suite stays green; research/data-model/contracts/doc-claims.md/quickstart alongside it). Prior feature
plans: `specs/004-split-client-module/plan.md` (pure structural refactor — split the ~1519-line
`client.py` god module into a layered `msgraph` package: `runtime.py` owns the `_http` seam + mutable
state + token/marker/catch-set + `_graph_*` primitives; `catalog.py` = TOOLS; `render.py`; `graph.py`;
`verbs.py`; `client.py` thin entrypoint; one-way DAG; tests re-point the four rebound seam/state names
to `runtime.*`). Prior feature plans:
`specs/003-categorise-and-search-folders/plan.md` (category rules + search folders + `--mode folders`;
note message-move `--mode messages` shipped after, on `main`), `specs/002-fix-graph-query-encoding/plan.md`
(percent-encode Graph query params + real-URL coverage), `specs/001-msgraph-mail-rules/plan.md`
(foundation: stdlib-only device-code design, `TOOLS` catalog contract, safety-model decisions) — read
them for the technical context before implementing.
<!-- SPECKIT END -->
