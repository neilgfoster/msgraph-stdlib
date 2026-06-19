---
name: "example-subject-verb"
description: "EXAMPLE skill — copy this directory to start a real one. Demonstrates the agent-friendly conventions in docs/AGENT-FRIENDLY.md. Replace this line with an onboarding-quality description: what the tool does, WHEN to use it (and when not), required vs optional params, and a worked example. This text is prompt context the agent reads to choose the tool — invest in it."
argument-hint: "[--limit N] [--format concise|detailed] — example args; mirror your real params here"
user-invocable: true
disable-model-invocation: false
# --- Behavioural annotations (MCP vocabulary; advisory, NOT security — see docs/AGENT-FRIENDLY.md §8)
annotations:
  readOnlyHint: true        # this example only reads; set false for tools that mutate
  destructiveHint: false    # only meaningful when readOnlyHint is false; true = irreversible
  idempotentHint: true      # same args → same result, safe to retry
  openWorldHint: false      # closed domain (one API); true if it reaches arbitrary external content
---

## What this does

> This is the **template's example skill**. It does nothing real — it exists to show the shape and
> the conventions. To make a real plugin: copy this directory, rename it `<subject>-<verb>`, and
> replace the placeholder content. Read `docs/AGENT-FRIENDLY.md` first.

A real "what this does" section explains the operation in plain terms and, crucially, **when the
agent should reach for it** versus a neighbouring tool. Make implicit context explicit (niche terms,
prerequisites like "run `/{{NAME}}-auth-login` first", relationships to other tools).

## Discoverability

Verbs, descriptions, and input schemas are discoverable at runtime — don't rely on this doc being
in sync. Ask the kernel (the `TOOLS` catalog is the single source of truth, like MCP `tools/list`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/example/client.py" describe            # all verbs
python3 "${CLAUDE_PLUGIN_ROOT}/src/example/client.py" describe --name list # one verb's schema
```

## Inputs (JSON Schema — typed, described, flat)

Keep schemas flat: **no `oneOf`/`allOf`/`anyOf` at the top level** (MCP-incompatible). Name params
unambiguously (`rule_id`, not `id`). This schema is mirrored in the kernel's `TOOLS` catalog (above).

```json
{
  "type": "object",
  "properties": {
    "limit":  { "type": "integer", "default": 25, "description": "Max items to return (pagination)." },
    "format": { "type": "string", "enum": ["concise", "detailed"], "default": "concise",
                "description": "concise = agent-legible summary; detailed = adds IDs for follow-up calls." }
  },
  "required": []
}
```

## How it runs

Skills invoke the stdlib kernel directly (no backend, no dependency):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/example/client.py" list --limit 25 --format concise
# or, as a module:  python3 -m example.client list ...
```

## Output (agent-legible)

`concise` returns human-readable fields only — resolve IDs to names, drop low-signal metadata:

```
- "Weekly Newsletter" from news@example.com  (folder: Inbox)
- "Receipt #4471" from billing@example.com   (folder: Inbox)
2 items. Pass --format detailed for IDs needed by follow-up commands.
```

## Errors steer the agent

Return actionable guidance, never a raw traceback:

```
error: not signed in — run /{{NAME}}-auth-login first, then retry.
```

## Checklist before shipping a real skill (see docs/AGENT-FRIENDLY.md)

- [ ] Onboarding-quality `description` with when-to-use + a worked example
- [ ] Accurate `annotations` block (read-only vs destructive)
- [ ] Flat JSON-schema inputs, unambiguous names
- [ ] Agent-legible output with concise/detailed modes + pagination default
- [ ] Actionable error messages
