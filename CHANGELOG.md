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

## [0.6.1] - 2026-06-27

### Fixed

- **Refresh token lost after silent renewal** — per RFC 6749 §6, a token-endpoint response MAY
  omit `refresh_token` (meaning "keep using the previous one"). `_store_token_response` was
  storing `""` in that case, so the very next expiry would raise "no refresh token — run
  auth-login again" and force a full re-authentication. The old refresh token is now preserved
  when the response does not supply a new one.

## [0.6.0] - 2026-06-23

### Fixed

- `rule-create --move_to_folder` (and `searchfolder-create` source folders) now resolve a
  folder name at **any nesting depth** via the recursive folder name map, matching
  `message-move`/`mail-list`. Previously only immediate children of the mailbox root were
  searched, so a folder nested under Inbox (e.g. `Inbox/Newsletters`) failed with "No mail
  folder named '<name>' was found". A genuinely non-existent name still raises the steering
  error. No scope change.
- **Dual-stack connect hang (auth + silent refresh)** — every HTTP call went through a bare
  `urllib.request.urlopen`, which on a host with a blackholed IPv6 route tried the dead address
  with the full operation timeout and hung indefinitely (no device code, reads never return, and
  the silent refresh hung too — the likely cause of "re-auth every session"). `runtime._http` now
  connects via a bounded, **IPv4-first** path (happy-eyeballs-lite over `socket`/`http.client`):
  each address is tried with a short connect timeout (`MSGRAPH_CONNECT_TIMEOUT`, default 5s) so a
  dead address fails fast to a reachable one. `MSGRAPH_FORCE_IPV4=1` restricts to IPv4. Stdlib
  only; the 30s read timeout and the single `_http` seam are unchanged.
- **Silent refresh is now observable** — a successful token renewal prints
  `msgraph: renewed access token silently` to stderr, so occasional users can see refresh working
  rather than assuming the session expired.

### Added

- **Scope-superset warning at sign-in** — Microsoft consent is sticky/cumulative, so a `--mode read`
  sign-in on an account that previously consented to a write tier returns a write-capable token.
  `auth-login` now warns on stderr when the granted scopes are a write-capable superset of the
  requested mode, so the read-mode token's true capability is never hidden.

### Changed

- **Honest scope-model documentation** — added `docs/adr/0001-scope-isolation-one-app-vs-per-tier.md`
  recording the decision to keep one app registration and frame `--mode` as consent-shaping +
  guardrail (rejecting per-tier app registrations). Reconciled the `auth-login` skill doc and README:
  the unqualified "structurally cannot write" claim is replaced with the true, qualified guarantee
  (structural read-only holds only before any write mode has ever been consented). Source:
  `docs/HANDOVER-runtime-and-scope.md` (feature `008-runtime-and-scope`; the two-phase agent sign-in,
  Issue 4, is deferred).

## [0.5.0] - 2026-06-22

### Fixed

- **Inbox-scoped reads** — `mail-list` and `rule-verify` previously queried `GET /me/messages`, which
  returns messages across **all** mail folders, so the triage overview mixed already-filed mail with
  true inbox stragglers and the rule catch-set counted matches no longer in the inbox (false
  confidence in a rule's value). Both now read the Inbox via `GET /me/mailFolders/inbox/messages`.
  `rule-verify` is always inbox-only (rules act on inbox arrivals; no flag). No new OAuth scope —
  stays `Mail.Read`. Source: `docs/HANDOVER-inbox-scope.md` (feature `006-inbox-scope`).

### Added

- **`mail-list --folder <well-known-or-name>`** — optional flag to list a folder other than the
  Inbox (default `inbox`), reusing the existing folder resolver; an unresolvable folder steers
  rather than returning a raw 404.

## [0.4.1] - 2026-06-22

### Fixed

- **`auth-login` idempotency** — `cmd_auth_login` now checks the cached token before initiating a
  new device-code flow. If the token is present, non-expired, and covers all scopes required by the
  requested mode, it returns immediately with `"Already signed in (<mode>). Scopes: …"` and exits 0
  without making any HTTP requests or opening a browser. Falls through to the full flow only when
  the token is absent, expired, or insufficient for the requested mode (e.g. a read token asked to
  escalate to `--mode rules`). Fixes repeated browser-consent prompts during multi-step triage
  sessions. Four unit tests added covering each fall-through boundary.

## [0.4.0] - 2026-06-21

### Removed

- **`DEFINITION_OF_DONE.md`** and all references to it. The build target it described has been met —
  the plugin has shipped with all 14 verbs (+ `describe`), a green offline suite, and the full safety
  model in place. Going forward, `CHANGELOG.md` (release history) and the runtime `describe` catalog
  are the source of truth for what's built; `CLAUDE.md`, `README.md`, and `CONTRIBUTING.md` no longer
  point at the retired document.

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
