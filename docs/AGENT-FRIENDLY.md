# Agent-friendly design guidelines

**Required reading before adding a skill.**

This plugin does not run an MCP server — but a skill's `description` and the CLI's inputs/outputs
**are** the agent-facing tool contract. So the principles MCP and Anthropic codified for tool design
apply directly. Design for the agent that will *call* the tool, not for a human reading an API doc.

Sources:
- Anthropic — [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- MCP — [Tool annotations](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)

---

## 1. Design for the agent, not the API
Prefer workflow-shaped, high-leverage commands over thin 1:1 API wrappers. A `schedule_event` beats
`list_users` + `list_events` + `create_event` if scheduling is the real task.

> **Judgement call:** a plugin may *start* thin (faithfully expose the API) to ship value, then
> consolidate into workflow tools as real usage reveals them. Start thin deliberately, not by default.

## 2. Naming & namespacing
- Skill (and dir) names: `<subject>-<verb>` under the plugin prefix → `<plugin>-<subject>-<verb>`.
- verb-noun, under 64 chars, no abbreviations or ambiguous terms.
- Parameter names are specific: `rule_id`, not `id`; `folder_name`, not `name`.

## 3. Descriptions are the instruction manual
The `description` is prompt context the agent uses to choose the tool. Write it like onboarding a new
hire: **what it does, when to use it (and when not), required vs optional params, niche terms, and a
worked example.** Iterating on descriptions yields outsized gains in agent accuracy.

## 4. Inputs as flat JSON Schema
Typed, `required`-marked, each with a `description`. **Do not use `oneOf`/`allOf`/`anyOf` at the top
level** — it breaks MCP clients and confuses model usage. Keep schemas flat and predictable.

## 5. Return agent-legible output
- Resolve cryptic IDs to human-readable names (folder names, sender display names).
- Drop low-signal metadata (mime types, thumbnail URLs, internal flags).
- Offer **`concise` vs `detailed`** modes so the agent controls context cost — concise by default,
  detailed when it needs IDs for follow-up calls.

## 6. Token efficiency by default
Pagination, filtering, and truncation defaults so no command can dump an entire mailbox/dataset into
the agent's context. A sensible `--limit` default and a clear "more available" signal.

## 7. Errors that steer
Actionable messages that tell the agent what to do next:
`error: not signed in — run /<plugin>-auth-login first, then retry.`
Never raw tracebacks or opaque error codes.

## 8. Behavioural annotations (adopt MCP's vocabulary)
Declare these in each skill's frontmatter `annotations:` block:

| Annotation | Meaning | Default |
|---|---|---|
| `readOnlyHint` | tool makes no state changes | false |
| `destructiveHint` | (only if not read-only) changes are irreversible | true |
| `idempotentHint` | same args → same result, safe to retry | false |
| `openWorldHint` | reaches arbitrary/external content | true |

Examples:
- a **list/read** tool → `readOnly: true, destructive: false, idempotent: true, openWorld: false`
- a **create** tool → `readOnly: false, destructive: false` (additive/reversible), `idempotent: false`
- a **delete** tool → `readOnly: false, destructive: true, idempotent: false`

> **Critical caveat:** annotations are *advisory UX hints, not security*. A bug or a bad caller can
> ignore them. Real safety comes from **least-privilege OAuth scope** (read-only tools request only
> read scopes), **explicit confirmation before destructive actions**, and **verify-then-reversible**
> designs (preview the effect; prefer reversible actions like move-to-folder over delete). Never let a
> hint be the thing standing between a bug and data loss.

## 9. Discoverability — make the tool self-describing (MCP `tools/list`)
An agent should be able to enumerate what the plugin can do, and fetch each verb's description and
expected input schema, **at runtime** — not rely on hardcoded knowledge. MCP does this via
`tools/list` (name + description + `inputSchema` + annotations per tool). The zero-backend equivalent:

- Keep a single **`TOOLS` catalog** in the kernel (name, description, flat `inputSchema`, annotations)
  that *both* discovery and execution read from — so they can never drift.
- Expose a **`describe`** command that emits that catalog as JSON (`describe` for all, `describe --name X`
  for one). This is the introspection surface an agent calls to learn the verbs and their schemas.

```bash
python3 -m example.client describe          # → {"tools": [{name, description, inputSchema, annotations}, …]}
python3 -m example.client describe --name list
```

A skill's `SKILL.md` should point at `describe` as the source of truth for arguments rather than
duplicating the schema (which would drift).

## 10. Evaluate & iterate
Build realistic multi-step eval tasks (not toy sandboxes). Measure tokens, call-count, and error rate
— not just success. Feed transcripts back in to find contradictory descriptions and consolidation
opportunities.
