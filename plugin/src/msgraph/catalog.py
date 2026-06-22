"""msgraph-stdlib tool catalog — the single source of truth for discovery and dispatch.

`TOOLS` drives both `describe` (the zero-backend equivalent of MCP tools/list) and the argparse
dispatch in `client.py`, so the two can never drift (feature 004 data-model: INV-2). Pure data.
"""

# ================================================================================================
# The TOOLS catalog — single source of truth for `describe` and dispatch (contracts/tools.md).
# Flat JSON Schemas (no oneOf/allOf/anyOf); descriptions are onboarding-quality with when-to-use;
# annotations are advisory MCP hints (NOT security). Keep in sync with contracts/tools.md.
# ================================================================================================
TOOLS = [
    {
        "name": "describe",
        "description": (
            "Emit the tool catalog as JSON (all verbs, or one via --name). The zero-backend "
            "equivalent of MCP tools/list; use to discover verbs, descriptions, and input "
            "schemas at runtime."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Describe a single verb instead of the whole catalog.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "auth-login",
        "description": (
            "Sign in via OAuth device-code. Default mode requests Mail.Read MailboxSettings.Read "
            "(read-only: read mail and read existing rules, no write capability). Pass --mode rules "
            "to consent to MailboxSettings.ReadWrite for rule authoring (incl. categories), "
            "--mode folders to consent to Mail.ReadWrite for creating search folders, or "
            "--mode messages to consent to Mail.ReadWrite for moving messages between folders "
            "(MOVE only — never delete) — each a separate, deliberate escalation. Run this first; "
            "the operator authorises in a browser."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["read", "rules", "folders", "messages"],
                    "default": "read",
                    "description": "read = Mail.Read + MailboxSettings.Read; "
                    "rules = + MailboxSettings.ReadWrite (rule authoring + categories); "
                    "folders = Mail.ReadWrite + MailboxSettings.Read (create search folders); "
                    "messages = Mail.ReadWrite + MailboxSettings.Read (move messages between folders).",
                },
            },
            "required": [],
        },
        "scope": (
            "Mail.Read MailboxSettings.Read (read) | "
            "Mail.Read MailboxSettings.ReadWrite (rules) | "
            "Mail.ReadWrite MailboxSettings.Read (folders) | "
            "Mail.ReadWrite MailboxSettings.Read (messages)"
        ),
    },
    {
        "name": "mail-list",
        "description": (
            "List recent messages from a single folder, agent-legibly. Defaults to the Inbox — what "
            "actually needs triage, not already-filed mail across every folder. Use for "
            "triage/overview; pass folder to inspect another folder. concise (default) returns "
            "readable summaries; detailed adds IDs for follow-up calls. Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 25,
                    "description": "Max messages to return (pagination).",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = agent-legible summary; detailed = adds IDs.",
                },
                "folder": {
                    "type": "string",
                    "default": "inbox",
                    "description": (
                        "Folder to list: well-known name (e.g. inbox, archive) or display name. "
                        "Defaults to inbox."
                    ),
                },
            },
            "required": [],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "mail-get",
        "description": (
            "Fetch one message including its internet headers. Use when you need a message's full "
            "content or headers (e.g. to inspect List-Unsubscribe before proposing a rule). "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Graph message id (from mail-list --format detailed).",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = summary + headers; detailed = full JSON.",
                },
            },
            "required": ["message_id"],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "message-move",
        "description": (
            "Move one or more messages to a destination mail folder (POST /me/messages/{id}/move). "
            "MOVE only — never deletes; the operation is reversible (move the message back). Use to "
            "re-file backlog mail that incoming-only rules cannot touch. ALWAYS preview first with "
            "--dry_run true: it resolves the destination and lists the exact messages that would move "
            "WITHOUT writing anything. Batch-safe: each message reports its own outcome, so one bad id "
            "never aborts the rest. Requires the SEPARATE message-write sign-in "
            "(auth-login --mode messages; Mail.ReadWrite) — a distinct write tier from read, rule "
            "authoring, and search folders."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Graph message id(s) to move (from mail-list --format detailed).",
                },
                "destination_folder": {
                    "type": "string",
                    "description": "Target folder: a display name, a well-known name (inbox, archive, "
                    "deleteditems, …), or a folder id. Messages are filed here; never deleted.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "true = preview only: resolve the destination and list what WOULD "
                    "move, writing nothing. Run this first to gate the move on the shown set.",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = per-message summary; detailed = full JSON incl. new ids.",
                },
            },
            "required": ["message_ids", "destination_folder"],
        },
        "scope": "Mail.ReadWrite",
    },
    {
        "name": "rule-list",
        "description": (
            "Enumerate existing inbox message rules with name, criteria, and target folder in "
            "readable terms. Use to understand current organisation before proposing changes. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = readable summary; detailed = full JSON incl. ids.",
                },
            },
            "required": [],
        },
        "scope": "MailboxSettings.Read",
    },
    {
        "name": "rule-verify",
        "description": (
            "Compute the read-only catch-set — the existing messages candidate criteria would "
            "match — WITHOUT writing anything. ALWAYS run before rule-create; it both previews "
            "intent and records the verification that rule-create requires. Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "header_contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Substrings matched (case-insensitively) against raw internet headers.",
                },
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = matches + count; detailed = full JSON.",
                },
            },
            "required": ["header_contains"],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "rule-create",
        "description": (
            "Install a rule that files matching mail to a folder and/or assigns a category. REFUSES "
            "unless the same predicate was verified first (run rule-verify). Actions are "
            "move-to-folder and/or assign-category only — never delete. Any assigned category is "
            "ensured to exist (coloured) first. Requires rule-authoring sign-in (auth-login --mode rules)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the rule."},
                "header_contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Predicate substrings — MUST match a prior rule-verify.",
                },
                "move_to_folder": {
                    "type": "string",
                    "description": "Optional target folder name for matching mail (filed, never deleted).",
                },
                "assign_category": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional category name(s) to assign to matching mail. Ensured to "
                    "exist (coloured) before install. At least one of move_to_folder/assign_category "
                    "required.",
                },
            },
            "required": ["name", "header_contains"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "rule-remove",
        "description": (
            "Delete a rule by id (the reversibility primitive). Removes only the rule; never deletes "
            "any messages. Requires rule-authoring sign-in."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_id": {
                    "type": "string",
                    "description": "Graph rule id (from rule-list --format detailed).",
                },
            },
            "required": ["rule_id"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "category-list",
        "description": (
            "List the mailbox's master categories (name + colour), read-only. Use to see which "
            "labels exist before authoring an assign-category rule or a category search folder. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = name + colour; detailed = full JSON.",
                },
            },
            "required": [],
        },
        "scope": "MailboxSettings.Read",
    },
    {
        "name": "category-ensure",
        "description": (
            "Ensure a named master category exists: create it with a colour if absent, no-op if "
            "present. Use before assigning a category so the label renders with a colour. "
            "Requires rule-authoring sign-in (auth-login --mode rules)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Category display name (unique, immutable once created).",
                },
                "color": {
                    "type": "string",
                    "default": "preset9",
                    "description": "categoryColor preset, e.g. preset0..preset24 or none.",
                },
            },
            "required": ["name"],
        },
        "scope": "MailboxSettings.ReadWrite",
    },
    {
        "name": "folder-list",
        "description": (
            "List the mailbox's real mail folders as a nested tree (each folder's name, message "
            "totals, unread count, and child count), read-only, via GET /me/mailFolders recursed "
            "through childFolders. Use to audit/understand the folder layout before proposing "
            "move-to-folder rules that target it. These are real mail folders, not virtual search "
            "folders (use searchfolder-list for those). concise (default) prints an indented tree "
            "with total/unread counts; detailed returns full JSON with ids + parentFolderId. "
            "Requires read sign-in (Mail.Read)."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = indented tree + counts; detailed = full JSON with ids.",
                },
                "include_hidden": {
                    "type": "boolean",
                    "default": False,
                    "description": "true = also list hidden folders (includeHiddenFolders=true).",
                },
            },
            "required": [],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "searchfolder-list",
        "description": (
            "List virtual search folders (name, filter, source-folder scope, id), read-only. Search "
            "folders never move or delete mail. Use to find a folder's id before removing it. "
            "Requires read sign-in."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                    "description": "concise = name + filter + scope; detailed = full JSON.",
                },
            },
            "required": [],
        },
        "scope": "Mail.Read",
    },
    {
        "name": "searchfolder-create",
        "description": (
            "Create a virtual search folder: a saved filtered view (e.g. all mail tagged a category) "
            "over chosen source folders. Non-destructive — it never moves or deletes mail. Requires "
            "the SEPARATE search-folder sign-in (auth-login --mode folders), a distinct write tier "
            "from rule authoring."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the search folder."},
                "category": {
                    "type": "string",
                    "description": "Convenience: builds filter categories/any(c:c eq '<name>').",
                },
                "filter_query": {
                    "type": "string",
                    "description": "Explicit OData filter; overrides category if both given.",
                },
                "source_folders": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Folder names/well-known names to mine. Default ['inbox'].",
                },
                "include_nested": {
                    "type": "boolean",
                    "default": True,
                    "description": "true = deep-search source subtrees; false = shallow.",
                },
            },
            "required": ["name"],
        },
        "scope": "Mail.ReadWrite",
    },
    {
        "name": "searchfolder-remove",
        "description": (
            "Delete a search folder by id (the reversibility primitive for search folders). Removes "
            "only the virtual folder; never deletes any messages. Requires search-folder sign-in "
            "(auth-login --mode folders)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "Search folder id (from searchfolder-list --format detailed).",
                },
            },
            "required": ["folder_id"],
        },
        "scope": "Mail.ReadWrite",
    },
]
