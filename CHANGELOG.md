# Changelog

All notable changes to this plugin are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this plugin uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0, breaking changes may land on a
minor bump and are called out explicitly.

The `version` in `plugin/.claude-plugin/plugin.json` is the single source of truth; the release
workflow refuses to publish a tag that disagrees with it.

## [Unreleased]

<!--
Add notes here under Added / Changed / Fixed / Removed. On release, move them under a new
## [X.Y.Z] - YYYY-MM-DD heading and bump plugin/.claude-plugin/plugin.json to match.
-->

## [0.3.0] - 2026-06-21

### Added

- **Per-message move** — `message-move` relocates one or more messages to a destination folder
  (`POST /me/messages/{id}/move`). MOVE only — it never deletes, and no delete-capable scope is ever
  requested, so deletion stays structurally impossible; a move is reversible (move it back). Batched
  over `--message_ids` with a per-message outcome (one stale id never aborts the rest), and a
  `--dry_run` preview that resolves the destination and lists what *would* move while writing nothing.
  Behind a new, separately-consented `Mail.ReadWrite` tier via `auth-login --mode messages` — distinct
  from the read, rule-authoring, and search-folder tiers. Re-files backlog mail that incoming-only
  rules cannot touch.

### Changed

- **Kernel restructured into a layered package** (no behavioural change, identical CLI/discovery
  contract). The single ~1519-line `plugin/src/msgraph/client.py` is split into `runtime.py` (the HTTP
  seam, token cache, markers + catch-set, Graph primitives), `catalog.py` (the `TOOLS` catalog),
  `render.py`, `graph.py`, `verbs.py`, and a thin `client.py` entrypoint — a one-way dependency graph
  that is far easier to read and extend. Both `python3 -m msgraph.client …` and the file-path form
  still work and emit the identical 15-verb catalog.

## [0.2.0] - 2026-06-20

### Added

- **Folder audit** — `folder-list` enumerates the mailbox's real mail folders as a nested tree (each
  folder's name, total/unread message counts, child count; ids + `parentFolderId` in detailed mode),
  read-only under the existing `Mail.Read` tier. `GET /me/mailFolders` recursed through `childFolders`,
  with `--include_hidden` for hidden folders. Distinct from `searchfolder-list`: the virtual
  Search Folders node is excluded so the two verbs never double-report.

## [0.1.0] - 2026-06-20

First release. A stdlib-only, zero-backend Claude Code plugin for Microsoft Graph (Outlook): read
mail and author safe, verified, reversible Outlook message rules, plus category labelling and virtual
category search folders. No third-party dependencies (just `urllib` + `json`), no backend — the
constraint is the product: portable, auditable, no supply-chain surface.

### Added

- **Auth** — OAuth 2.0 device-code sign-in; token cached `0600` outside the repo at the XDG path and
  silently refreshed. A three-tier scope ratchet: read-only (`Mail.Read + MailboxSettings.Read`,
  default), rule authoring (`+ MailboxSettings.ReadWrite`, `--mode rules`), and search folders
  (`Mail.ReadWrite`, `--mode folders`) — each a separate, deliberate, auditable escalation.
- **Mail read** — `mail-list` and `mail-get` (including internet headers like `List-Unsubscribe`),
  concise/detailed output, pagination default.
- **Rules** — `rule-list` (agent-legible), `rule-verify` (read-only catch-set), `rule-create` (files
  to a folder **and/or** assigns a coloured category; refuses unless a catch-set was verified and an
  action is given), `rule-remove` (the reversibility primitive).
- **Categories** — `category-list` and `category-ensure` (create-if-absent coloured master category)
  so assigned labels always render with a colour, under the rule-authoring scope.
- **Search folders** — `searchfolder-create` / `searchfolder-list` / `searchfolder-remove` for virtual
  `mailSearchFolder` views (e.g. all mail tagged a category) behind the separate `Mail.ReadWrite` tier;
  creating or removing one never moves or deletes mail.
- **Discovery** — `python3 -m msgraph.client describe` emits the runtime `TOOLS` catalog (the
  zero-backend equivalent of MCP `tools/list`).

### Safety model

- Read-only by default — the token carries no write grant, so even a bug cannot mutate mail.
- Verify-then-act: a rule is checked against real mail before it can be installed.
- Reversible by construction: rules file or label (never delete); search folders are virtual views;
  no imperative per-message mutation anywhere.

### Quality

- Offline unit tests over a single mockable HTTP seam **plus** real-URL construction coverage; ruff
  lint + format clean; a stdlib-only import guard enforced in CI. All capabilities live-proven against
  a real mailbox and reverted cleanly.
