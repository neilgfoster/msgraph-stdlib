# Contributing

`msgraph-stdlib` is a standalone, public, MIT plugin. The few rules that earn their keep:

## Standards

- **Python 3.11+, stdlib only at runtime.** `urllib` for HTTP, `json` for parsing. `ruff` and
  `pytest` are dev tooling — they never ship in `plugin/`. No third-party runtime dependencies, no
  backend/server process. The constraint is the product: portable, auditable, no supply-chain surface.
- **Two-tier layout.** `plugin/` is the shippable payload (its own `.claude-plugin/plugin.json` +
  `skills/`, `src/`, `hooks/`); the repo root is the build/distribution repo
  (`.claude-plugin/marketplace.json`, `pyproject.toml`, `tests/`, `.github/`, docs). Inside the
  plugin, reference bundled files via `${CLAUDE_PLUGIN_ROOT}/...` — it resolves to `plugin/`.
- **Command naming: `<subject>-<verb>`.** Skills are named subject-then-verb (e.g. `mail-list`,
  `rule-verify`). Keep the convention.
- **Secrets live OUTSIDE the repo** — a user-level XDG path
  (`${XDG_STATE_HOME:-~/.local/state}/msgraph-stdlib/`) with `0600` perms. Never committed, not even
  encrypted. Do not add an in-repo secrets path or a git-crypt dependency.
- **Safety model is structural.** Read path requests only `Mail.Read`; rule authoring uses the
  separate `MailboxSettings.ReadWrite` scope; a rule is verified against a read-only catch-set before
  install; rule actions file to a folder and never delete. Do not weaken these for convenience.
- **Agent-friendly by design.** Every skill follows `docs/AGENT-FRIENDLY.md` — read it before adding
  or changing a skill. The skill `description` and the CLI's inputs/outputs **are** the tool contract
  an agent reads.
- **Conventional Commit messages and PR titles.**

## Verify before claiming done

```sh
ruff check . && ruff format --check .
python3 -m pytest -q
```

CI (`.github/workflows/ci.yml`) runs exactly these; green CI is part of the Definition of Done.

## Cutting a release

SemVer, tag-driven. The version in `plugin/.claude-plugin/plugin.json` is the single source of truth.

1. Bump `version` in `plugin/.claude-plugin/plugin.json`.
2. In `CHANGELOG.md`, move `## [Unreleased]` notes under a new `## [X.Y.Z] - YYYY-MM-DD` heading.
3. `ruff check . && ruff format --check . && python3 -m pytest -q`.
4. Merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow publishes it.
