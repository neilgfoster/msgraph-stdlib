# msgraph-stdlib

A Claude Code plugin for Microsoft Graph (Outlook) that is **stdlib-only, zero-dependency, and
zero-backend** by design — just `urllib` + `json`, no SDK, no server process, no install friction.

It gives an agent two capabilities, with safety built into the *structure*, not the behaviour:

1. **Read Outlook mail** — list/get messages and their headers, read-only.
2. **Author native Outlook message rules** — create / list / verify / remove server-side
   `messageRule`s, so deterministic mail organisation lives *in Outlook* (runs even when nothing
   else is, visible and editable in Outlook's own UI, reversible by deleting one rule).

## Verbs (skills)

Each skill is a thin wrapper over the stdlib kernel; the runtime catalog is the source of truth
(`python3 -m msgraph.client describe`). Names are prefixed `msgraph-` when invoked as slash commands.

| Skill | Scope it needs | What it does |
|---|---|---|
| `auth-login` | `Mail.Read + MailboxSettings.Read` (read, default) or `+ MailboxSettings.ReadWrite` (`--mode rules`) | Device-code sign-in; caches the token at the XDG path and refreshes it silently. **Run first.** |
| `mail-list` | `Mail.Read` | List recent inbox messages (concise/detailed, pagination default 25). |
| `mail-get` | `Mail.Read` | Fetch one message incl. its internet headers (e.g. `List-Unsubscribe`). |
| `rule-list` | `MailboxSettings.Read` | Enumerate existing inbox rules agent-legibly. |
| `rule-verify` | `Mail.Read` | Compute a candidate rule's **read-only catch-set** and record the verification gate. |
| `rule-create` | `MailboxSettings.ReadWrite` | Install a verified move-to-folder rule; refuses unverified criteria. |
| `rule-remove` | `MailboxSettings.ReadWrite` | Delete a rule by id (the reversibility primitive). |

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

Two-tier: `plugin/` is the shippable payload; the repo root is the build/distribution repo.

```
.claude-plugin/marketplace.json          # marketplace entry — points at ./plugin
plugin/.claude-plugin/plugin.json        # plugin manifest
plugin/skills/<subject>-<verb>/SKILL.md  # agent-facing commands (auth, mail-read, rule-*)
plugin/src/msgraph/client.py             # stdlib kernel — importable + runnable, exposes a `describe` catalog
docs/AGENT-FRIENDLY.md                   # REQUIRED READING before adding/changing a skill
pyproject.toml  tests/  .github/         # dev tooling, tests, CI/release (never shipped)
DEFINITION_OF_DONE.md                    # what "working" means — the build target
CLAUDE.md                                # grounding + build plan for a Claude Code session in this repo
```

## Prerequisite (one-time, free)

An **Azure AD app registration** (public client, device-code / public-client flow **enabled**). Add
the delegated permissions `Mail.Read` + `MailboxSettings.Read` (read mail and list rules), plus
`MailboxSettings.ReadWrite` only if you want rule authoring. No cost, no admin consent for personal
accounts. Then export the resulting identifiers before first sign-in (read from the environment,
never hardcoded):

```bash
export MSGRAPH_CLIENT_ID="<application (client) id>"
export MSGRAPH_TENANT_ID="consumers"   # or "common" for work/school + personal accounts
```

See `plugin/skills/auth-login/SKILL.md` for the full walkthrough.

## Quick start

```bash
python3 -m msgraph.client describe                              # discover every verb + schema
python3 -m msgraph.client auth-login                           # read-only sign-in (device code)
python3 -m msgraph.client mail-list --limit 10                 # triage the inbox
python3 -m msgraph.client rule-verify --header_contains "List-Unsubscribe"   # preview, read-only
python3 -m msgraph.client auth-login --mode rules             # escalate (separate consent)
python3 -m msgraph.client rule-create --name "Newsletters" \
    --header_contains "List-Unsubscribe" --move_to_folder "Newsletters"
```

(Run from `plugin/src/`, or set `PYTHONPATH=plugin/src`. Inside an installed plugin the skills use
`${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py`.)

## Verify before done

`ruff` and `pytest` are dev tooling only — they never ship inside `plugin/`. If `python3 -m pip`
is unavailable, install them isolated with [`uv`](https://docs.astral.sh/uv/)
(`uv tool install ruff pytest`, then `export PATH="$HOME/.local/bin:$PATH"`).

```sh
ruff check . && ruff format --check .   # apply with `ruff format .` if it wants changes
python3 -m pytest -q

# Stdlib-only guard — the same denylist CI enforces in tests/test_stdlib_only.py. The shipped
# payload under plugin/src must import only the standard library (plus its own `msgraph` package).
grep -rnE '^\s*(import|from)\s+(msal|azure|requests|urllib3|httpx|aiohttp|pydantic|yaml|dotenv)\b' plugin/src && echo 'FORBIDDEN IMPORT' || echo 'stdlib-only OK'
```

## Status

v0.1 implemented spec-first (`/speckit-specify` → `clarify` → `plan` → `tasks` → `implement`): the
seven verbs above, the runtime `describe` catalog, and offline unit tests (Graph HTTP boundary
mocked). Live auth/Graph behaviour requires the one-time Azure app registration above. See
`DEFINITION_OF_DONE.md` for the target and `CLAUDE.md` for the build plan.

## License

MIT.
