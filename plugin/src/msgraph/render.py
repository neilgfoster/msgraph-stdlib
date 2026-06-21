"""msgraph-stdlib output shaping — agent-legible (concise) vs detailed (IDs/JSON) rendering.

Pure functions over Graph payloads; no I/O, no package imports (a leaf of the dependency DAG).
"""

import json


# ================================================================================================
# Output shaping — agent-legible (concise) vs detailed (IDs/JSON for follow-up).
# ================================================================================================
def _sender_of(msg: dict) -> str:
    frm = (msg.get("from") or {}).get("emailAddress") or {}
    return frm.get("address") or frm.get("name") or "(unknown)"


def _render_messages(items: list, fmt: str) -> str:
    if fmt == "detailed":
        return json.dumps(items, indent=2)
    if not items:
        return "No messages."
    lines = [
        f'- "{m.get("subject", "(no subject)")}" from {_sender_of(m)}'
        f"  (received: {m.get('receivedDateTime', '?')})"
        for m in items
    ]
    lines.append(f"{len(items)} message(s). Pass --format detailed for IDs needed by follow-up commands.")
    return "\n".join(lines)


# Action keys whose value is an opaque folder id we can resolve to a display name (read-only).
_FOLDER_ACTION_KEYS = ("moveToFolder", "copyToFolder")


def _humanize_key(key: str) -> str:
    """Turn a camelCase predicate/action name into spaced lower-case words (agent-legible)."""
    return "".join(f" {c.lower()}" if c.isupper() else c for c in key).strip()


def _humanize_value(value) -> str:
    """Render a Graph predicate/action value (list, recipient list, bool, enum, range) legibly."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):  # recipient: {"emailAddress": {"name", "address"}}
                addr = item.get("emailAddress") or {}
                parts.append(addr.get("address") or addr.get("name") or json.dumps(item))
            else:
                parts.append(str(item))
        return ", ".join(parts)
    if isinstance(value, dict):  # e.g. withinSizeRange {minimumSize, maximumSize}
        return ", ".join(f"{_humanize_key(k)} {v}" for k, v in value.items())
    return str(value)


def _summarize_clauses(clauses: dict, folders: dict | None = None) -> list:
    """Summarize whichever conditions/actions are present, skipping empty/false ones.

    ``folders`` (id→displayName) resolves move/copy-to-folder action ids to legible names; an
    unresolved id falls back to the raw id so the output never misrepresents the target.
    """
    folders = folders or {}
    lines = []
    for key, value in (clauses or {}).items():
        if value in (None, [], {}, "", False):
            continue  # absent predicate/action — don't pretend it's set
        if key in _FOLDER_ACTION_KEYS and isinstance(value, str) and value in folders:
            rendered = f'"{folders[value]}"'
        else:
            rendered = _humanize_value(value)
        lines.append(f"{_humanize_key(key)}: {rendered}")
    return lines


def _render_rules(rules: list, fmt: str, folders: dict | None = None) -> str:
    if fmt == "detailed":
        return json.dumps(rules, indent=2)
    if not rules:
        return "No inbox message rules."
    out = []
    for r in rules:
        conds = _summarize_clauses(r.get("conditions") or {}, folders)
        actions = _summarize_clauses(r.get("actions") or {}, folders)
        line = (
            f'- "{r.get("displayName", "(unnamed)")}"'
            f"{'  enabled' if r.get('isEnabled', True) else '  disabled'}"
            f"\n    if   {'; '.join(conds) or '(no conditions)'}"
            f"\n    then {'; '.join(actions) or '(no actions)'}"
        )
        out.append(line)
    out.append(f"{len(rules)} rule(s). Pass --format detailed for ids needed by rule-remove.")
    return "\n".join(out)
