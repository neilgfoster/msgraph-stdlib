# Definition of Done — msgraph-stdlib

The build target. A Claude Code session (and the local SDD/tredl observer) builds *toward this*. The
plugin is "done" for its first release when **every** box below is true. Read `CLAUDE.md` for the why.

## Capability

- [ ] **Auth** — device-code login works end-to-end; token cached at
      `${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/token.json` (`0600`, outside the repo) and
      transparently refreshed. Two distinct modes: read-only (`Mail.Read`) and
      rule-authoring (`+ MailboxSettings.ReadWrite`).
- [ ] **Mail read** — `mail-list` and `mail-get` return messages and their internet headers,
      read-only, with concise/detailed output and a sane pagination default.
- [ ] **Rule read** — `rule-list` enumerates existing Outlook `messageRule`s, agent-legibly.
- [ ] **Rule verify** — `rule-verify` takes candidate predicates and returns the **read-only
      catch-set** (the messages the rule would match) without writing anything.
- [ ] **Rule create** — `rule-create` installs a predicate→move-to-folder rule, and **refuses**
      unless a catch-set has been verified for it.
- [ ] **Rule remove** — `rule-remove` deletes a rule by id (the reversibility primitive).

## Constraints (any failure = not done)

- [ ] **Zero third-party dependencies.** `pipdeptree`/imports show only the standard library.
      No `msal`, `azure-*`, `requests`, etc. No backend or long-running process.
- [ ] **No secrets in the repo.** No token/credential file under version control; `git log -p` and
      the working tree are clean of secrets; storage is the external XDG path only. No git-crypt
      dependency.
- [ ] **Read cannot mutate.** Read-only mode holds `Mail.Read` only; no write endpoint is reachable
      from any read skill. Write capability exists *only* after explicit `MailboxSettings.ReadWrite`
      opt-in.
- [ ] **No imperative per-message mutation.** The plugin never archives/moves/deletes an individual
      message itself; organisation happens only via installed rules, which file (never delete).
- [ ] **Agent-friendly.** Every skill meets `docs/AGENT-FRIENDLY.md`: onboarding-quality
      `description` (incl. when-to-use), flat JSON-schema inputs, agent-legible output (IDs resolved
      to names; concise/detailed), steering error messages, accurate `annotations`.
- [ ] **Discoverable.** `python3 -m msgraph.client describe` (and `--name <verb>`) emits the `TOOLS`
      catalog — name + description + input schema + annotations for every verb.

## Quality / hygiene

- [ ] **Offline-testable.** Classification/verification/output-shaping logic is unit-tested without
      network (Graph HTTP boundary mockable). Tests pass with stdlib only.
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

A reviewer can, from a clean checkout + a one-time Azure app reg:

1. `auth-login` (read-only) → succeeds.
2. `mail-list` → sees real inbox messages.
3. `rule-verify headerContains=["List-Unsubscribe"]` → sees the exact set of newsletters that rule
   would catch, with nothing written.
4. `auth-login` (rule-authoring) → consents to the write scope.
5. `rule-create` → the verified rule appears in Outlook's own Rules UI and files matching mail to a
   folder.
6. `rule-remove` → the rule is gone; organisation undone.

When all of the above hold, msgraph-stdlib v0.1 is done and ready for kypr to consume.
