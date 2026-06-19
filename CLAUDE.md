# CLAUDE.md

Grounding for any Claude Code session working in this repository.

## What this repo is

A **minimal skeleton/template for building Claude Code plugins** that are **stdlib-only,
zero-dependency, and zero-backend**. It is not a working plugin itself — it is the copyable starting
point. The `example` package and `example-subject-verb` skill are deliberately inert demonstrations
of the conventions, meant to be renamed and replaced.

Two situations you might be in:
1. **Maintaining the template** — keep it minimal. Layout + exemplary patterns only; **no shared
   framework or abstractions**. Real abstractions are harvested later from working plugins, never
   invented here speculatively.
2. **A plugin instantiated from the template** — the `example`/placeholder names have been replaced
   with a real plugin. Follow the same conventions below.

## Non-negotiable conventions

- **stdlib only, zero third-party dependencies, no backend/server process.** `urllib` for HTTP,
  `json` for parsing. If you reach for a dependency, stop — the constraint is the point (portable,
  auditable, no install friction).
- **Secrets/tokens NEVER live in the repo.** They belong outside it, in a user-level XDG path
  (`${XDG_STATE_HOME:-~/.local/state}/<plugin>/`) with `0600` perms. Never committed, not even
  encrypted. Do not add an in-repo secrets path or a git-crypt dependency.
- **Agent-friendly by design.** Every skill follows `docs/AGENT-FRIENDLY.md` — read it before adding
  or changing a skill. The skill `description` and the CLI's inputs/outputs **are** the tool contract
  an agent reads, so they get first-class care.

## Where things are

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest (`{{NAME}}`/`{{DESCRIPTION}}` placeholders) |
| `skills/<subject>-<verb>/SKILL.md` | Agent-facing commands; one exemplary skill ships in the template |
| `src/<plugin>/client.py` | Stdlib kernel — importable AND runnable (`python3 -m <plugin>.client …`) |
| `docs/AGENT-FRIENDLY.md` | **Required reading** — the MCP/agent-tool design principles |
| `README.md` | Human-facing overview + instantiation steps |

## How to instantiate a real plugin

1. Copy this repo; rename `src/example` → `src/<plugin>` (update `APP` in `client.py`).
2. Rename `skills/example-subject-verb` → real `<subject>-<verb>` skills.
3. Fill `{{NAME}}` / `{{DESCRIPTION}}` in `.claude-plugin/plugin.json`.
4. Build each skill against `docs/AGENT-FRIENDLY.md`.
