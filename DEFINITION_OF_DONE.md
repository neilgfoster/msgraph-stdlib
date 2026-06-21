# Definition of Done — msgraph-stdlib

The build target. A Claude Code session (and the local SDD/tredl observer) builds *toward this*. The
plugin is "done" for its first release when **every** box below is true. Read `CLAUDE.md` for the why.

## Capability

- [ ] **Auth** — device-code login works end-to-end; token cached at
      `${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/token.json` (`0600`, outside the repo) and
      transparently refreshed. Four distinct modes (the scope ratchet): read-only
      (`Mail.Read + MailboxSettings.Read`), rule-authoring (`+ MailboxSettings.ReadWrite`),
      search-folder (`Mail.ReadWrite`, `--mode folders`), and message-move (`Mail.ReadWrite`,
      `--mode messages`).
- [ ] **Mail read** — `mail-list` and `mail-get` return messages and their internet headers,
      read-only, with concise/detailed output and a sane pagination default.
- [ ] **Rule read** — `rule-list` enumerates existing Outlook `messageRule`s, agent-legibly.
- [ ] **Rule verify** — `rule-verify` takes candidate predicates and returns the **read-only
      catch-set** (the messages the rule would match) without writing anything.
- [ ] **Rule create** — `rule-create` installs a predicate→move-to-folder **and/or assign-category**
      rule, and **refuses** unless a catch-set has been verified for it (and unless it has an action).
- [ ] **Rule remove** — `rule-remove` deletes a rule by id (the reversibility primitive).
- [ ] **Categories** — `category-list` enumerates the mailbox master categories; `category-ensure`
      create-if-absent a named category (coloured), under the rule-authoring scope. `rule-create`
      ensures any category it assigns so labels always render with a colour.
- [ ] **Search folders** — `searchfolder-create` makes a virtual `mailSearchFolder` (a saved,
      category-filtered view; never moves/deletes mail) under the **separate** `Mail.ReadWrite` tier;
      `searchfolder-list` enumerates them agent-legibly; `searchfolder-remove` deletes one by id
      (reversibility primitive — affects only the virtual folder, never mail).
- [ ] **Per-message move** — `message-move` files one or more messages to a destination folder
      (`POST /me/messages/{id}/move`), **move-only and reversible** (move them back), under the
      **separate** message-write tier (`Mail.ReadWrite`, `--mode messages`). `--dry_run` previews the
      exact set that would move without writing; the batch is per-message (one stale id never aborts
      the rest). It never deletes, and no delete-capable scope is requested anywhere.

## Constraints (any failure = not done)

- [ ] **Zero third-party dependencies.** `pipdeptree`/imports show only the standard library.
      No `msal`, `azure-*`, `requests`, etc. No backend or long-running process.
- [ ] **No secrets in the repo.** No token/credential file under version control; `git log -p` and
      the working tree are clean of secrets; storage is the external XDG path only. No git-crypt
      dependency.
- [ ] **A read token cannot mutate.** Read-only mode holds `Mail.Read + MailboxSettings.Read` only; no
      write endpoint is reachable from any read skill. Write capability exists *only* after explicit
      opt-in, and each write tier is a **separate, distinctly-consented** scope: rule/category authoring
      (`MailboxSettings.ReadWrite`), search-folder creation (`Mail.ReadWrite`, `--mode folders`), and
      message move (`Mail.ReadWrite`, `--mode messages`) are independent ratchet steps — a read or
      rule-authoring token can neither create a search folder nor move a message.
- [ ] **Move is the only per-message mutation — and it can never delete.** `message-move` is the sole
      imperative per-message action; it **files messages to a folder (move-only) and is reversible**
      (move them back), gated behind its own separately-consented `Mail.ReadWrite` tier
      (`--mode messages`). **No verb deletes a message and no delete-capable scope is ever requested**,
      so deletion stays *structurally* impossible — a bug cannot delete because the token carries no
      such grant. Rules still only file or label (never delete); search folders are **virtual saved
      views** — creating or removing one moves/deletes no mail.
- [ ] **Agent-friendly.** Every skill meets `docs/AGENT-FRIENDLY.md`: onboarding-quality
      `description` (incl. when-to-use), flat JSON-schema inputs, agent-legible output (IDs resolved
      to names; concise/detailed), steering error messages, accurate `annotations`.
- [ ] **Discoverable.** `python3 -m msgraph.client describe` (and `--name <verb>`) emits the single
      `TOOLS` catalog — name + description + input schema + annotations for every verb. The kernel is a
      **layered `msgraph` package** — a thin `client.py` entrypoint (argparse dispatch + `describe`)
      over `runtime.py` (the `_http` seam, token cache, markers + catch-set, Graph primitives),
      `catalog.py` (the `TOOLS` catalog), `render.py`, `graph.py`, and `verbs.py` — still importable
      AND runnable, via both `python3 -m msgraph.client …` and the file-path form.

## Quality / hygiene

- [ ] **Offline-testable.** Classification/verification/output-shaping logic is unit-tested without
      network (Graph HTTP boundary mockable). Tests pass with stdlib only. **Includes real-URL
      construction coverage** (`tests/test_url_construction.py`): each verb's URL is built through the
      real path and asserted free of raw spaces/control characters — the `_http`-mock tests alone
      missed a malformed `$orderby` that crashed the first live run (feature 002).
- [ ] **Two-tier layout.** Shippable payload lives under `plugin/` (`plugin/.claude-plugin/plugin.json`,
      `plugin/skills/`, `plugin/src/msgraph/`); the root carries `.claude-plugin/marketplace.json`
      whose plugin `source` resolves to `./plugin`.
- [ ] **Template residue gone.** `plugin/src/example/` and `plugin/skills/example-subject-verb/`
      replaced by the real `plugin/src/msgraph/` and real skills; placeholders
      (`{{NAME}}`/`{{DESCRIPTION}}`) all filled.
- [ ] **Docs honest.** `README.md` reflects the shipped verbs; `auth-login` documents the one-time
      Azure app-registration prerequisite and the `MSGRAPH_CLIENT_ID`/`MSGRAPH_TENANT_ID` env vars.
- [ ] **SDD trail stays local.** `.specify/`, `specs/`, `.tredl/` remain gitignored; the public
      surface stays minimal.

## Acceptance demo (the working slice)

**One-time Azure app reg prerequisites** (verified on the first live run — see auth-login SKILL.md
for the full walkthrough): a personal Microsoft account has **no tenant** by default, so you must
create one via the Azure free trial (card-verified; tenant + app reg are free forever after the trial
lapses); register the app at **entra.microsoft.com** (not portal.azure.com) as **Personal Microsoft
accounts only**, blank redirect URI, **Allow public client flows = Yes** (Authentication → Settings
sub-tab), delegated `Mail.Read` + `MailboxSettings.Read` (+ `MailboxSettings.ReadWrite` for rule/
category authoring, + `Mail.ReadWrite` for search folders and message move); export
`MSGRAPH_CLIENT_ID` and `MSGRAPH_TENANT_ID="consumers"`.

A reviewer can, from a clean checkout + the one-time Azure app reg above:

1. `auth-login` (read-only) → succeeds.
2. `mail-list` → sees real inbox messages.
3. `rule-verify headerContains=["List-Unsubscribe"]` → sees the exact set of newsletters that rule
   would catch, with nothing written.
4. `auth-login` (rule-authoring) → consents to the write scope.
5. `rule-create` → the verified rule appears in Outlook's own Rules UI and files matching mail to a
   folder.
6. `rule-remove` → the rule is gone; organisation undone.
7. `auth-login --mode messages` → consents to the separate `Mail.ReadWrite` message-write tier.
8. `message-move --dry_run true` → previews the exact set that would move (nothing written); then
   `message-move` files those messages to a folder, and moving them back restores them — proving the
   action is move-only and reversible, with no delete path anywhere.

When all of the above hold, msgraph-stdlib v0.1 is done and ready for kypr to consume.
