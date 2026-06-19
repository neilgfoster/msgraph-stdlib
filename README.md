# claude-plugin-template

A minimal skeleton for a Claude Code plugin. Stdlib-only, zero-dependency,
zero-backend by convention. Copy it to start a new plugin with a consistent layout and the
agent-friendly conventions already in place.

This is **layout only — no framework, no shared abstractions.** Real reusable abstractions get
harvested later, from working plugins, not invented up front.

## Layout

```
.claude-plugin/plugin.json     # manifest ({{NAME}}/{{DESCRIPTION}} placeholders)
skills/<subject>-<verb>/SKILL.md  # one exemplary skill demonstrating the conventions
src/<plugin>/                  # stdlib Python kernel (importable + runnable by skills)
  client.py                    # urllib+json idiom + output-shaping patterns (stub)
hooks/hooks.json               # optional PreToolUse example (delete if unused)
docs/AGENT-FRIENDLY.md         # REQUIRED READING before adding a skill
```

## How to instantiate

1. Copy this repo to `~/source/neilgfoster/<plugin>` and `git init`.
2. Rename `src/example` → `src/<plugin>`; update `APP` in `client.py`.
3. Rename `skills/example-subject-verb` → real `<subject>-<verb>` skills.
4. Fill the `{{NAME}}` / `{{DESCRIPTION}}` placeholders in `.claude-plugin/plugin.json`.
5. Build features spec-first (Spec-Driven Development):
   `/speckit-specify` → `clarify` → `plan` → `tasks` → `implement`.

## Non-negotiable conventions

- **stdlib only, zero dependencies, no backend.** `urllib` for HTTP, `json` for parsing.
- **Secrets/tokens live OUTSIDE the repo** — a user-level XDG path
  (`${XDG_STATE_HOME:-~/.local/state}/<plugin>/`) with `0600` perms. Never committed, not even
  encrypted. This repo must not depend on git-crypt.
- **Agent-friendly by design** — every skill follows `docs/AGENT-FRIENDLY.md` (MCP/agent-tool
  principles: onboarding descriptions, behavioural annotations, flat JSON-schema inputs, agent-legible
  output, steering errors).
