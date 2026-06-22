#!/usr/bin/env python3
"""msgraph-stdlib CLI entrypoint — argparse dispatch over the single TOOLS catalog.

The kernel is a layered package (feature 004): `runtime` owns the HTTP seam, mutable state, token
cache, markers + catch-set, and the Graph primitives; `catalog` owns TOOLS; `render` shapes output;
`graph` resolves folders/categories; `verbs` holds the cmd_* implementations. This module is the thin
top of the dependency DAG: it builds the parser from the catalog, dispatches to a verb handler, and
stays runnable both as a module (`python3 -m msgraph.client ...`) and as a script
(`python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" ...`).

It re-exports the established public surface so existing `client.<name>` references keep resolving.
The mockable seam and mutable state paths live in `msgraph.runtime` (patch them there).
"""

import argparse
import sys
from pathlib import Path

# Script form: `python3 .../msgraph/client.py <verb>` runs as __main__ with sys.path[0] = the
# msgraph/ dir, so `from msgraph...` would fail. Insert src/ and adopt the package identity first.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "msgraph"

from msgraph import graph, render, runtime, verbs  # noqa: E402,F401
from msgraph.catalog import TOOLS  # noqa: E402
from msgraph.graph import _filter_query_for_category  # noqa: E402,F401  (re-export; tested directly)
from msgraph.runtime import (  # noqa: E402,F401  (re-export the established public surface)
    APP,
    GRAPH,
    WRITE_SCOPE,
    SteerError,
    _graph_url,
    _require_scopes,
    compute_catch_set,
    load_token,
    read_verification,
    record_verification,
    save_token,
)
from msgraph.verbs import (  # noqa: E402
    cmd_auth_login,
    cmd_category_ensure,
    cmd_category_list,
    cmd_describe,
    cmd_folder_list,
    cmd_mail_get,
    cmd_mail_list,
    cmd_message_move,
    cmd_rule_create,
    cmd_rule_list,
    cmd_rule_remove,
    cmd_rule_verify,
    cmd_searchfolder_create,
    cmd_searchfolder_list,
    cmd_searchfolder_remove,
)

# Public surface other code/tests reference as client.<name>. The mockable seam (`_http`) and mutable
# state paths (`STATE_DIR`/`TOKEN_PATH`/`MARKER_PATH`) are deliberately NOT re-exported — patch and
# read them at their owner, `msgraph.runtime` (feature 004 contract §B/§C).
__all__ = [
    "APP",
    "GRAPH",
    "WRITE_SCOPE",
    "SteerError",
    "TOOLS",
    "compute_catch_set",
    "load_token",
    "read_verification",
    "record_verification",
    "save_token",
    "_graph_url",
    "_require_scopes",
    "_filter_query_for_category",
    "cmd_describe",
    "cmd_auth_login",
    "cmd_mail_list",
    "cmd_mail_get",
    "cmd_message_move",
    "cmd_rule_verify",
    "cmd_rule_list",
    "cmd_rule_create",
    "cmd_rule_remove",
    "cmd_category_list",
    "cmd_category_ensure",
    "cmd_folder_list",
    "cmd_searchfolder_list",
    "cmd_searchfolder_create",
    "cmd_searchfolder_remove",
    "main",
]


# ================================================================================================
# Dispatch — built from the TOOLS catalog so discovery and execution read from one source.
# ================================================================================================
_HANDLERS = {
    "describe": cmd_describe,
    "auth-login": cmd_auth_login,
    "mail-list": cmd_mail_list,
    "mail-get": cmd_mail_get,
    "message-move": cmd_message_move,
    "rule-list": cmd_rule_list,
    "rule-verify": cmd_rule_verify,
    "rule-create": cmd_rule_create,
    "rule-remove": cmd_rule_remove,
    "category-list": cmd_category_list,
    "category-ensure": cmd_category_ensure,
    "folder-list": cmd_folder_list,
    "searchfolder-list": cmd_searchfolder_list,
    "searchfolder-create": cmd_searchfolder_create,
    "searchfolder-remove": cmd_searchfolder_remove,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP, description="msgraph-stdlib kernel (stdlib only).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for tool in TOOLS:
        p = sub.add_parser(tool["name"], help=tool["description"].split(".")[0])
        p.set_defaults(func=_HANDLERS[tool["name"]])

    sub.choices["describe"].add_argument("--name", help="describe a single verb instead of the catalog")
    sub.choices["auth-login"].add_argument(
        "--mode",
        choices=["read", "rules", "folders", "messages"],
        default="read",
        help="read (default), rules (rule-authoring), folders (search-folder), or messages (message-move)",
    )
    for verb in ("mail-list",):
        sub.choices[verb].add_argument("--limit", type=int, default=25, help="max items (pagination)")
        sub.choices[verb].add_argument(
            "--folder",
            default="inbox",
            help="folder to list: well-known name or display name (default: inbox)",
        )
    for verb in (
        "mail-list",
        "mail-get",
        "message-move",
        "rule-list",
        "rule-verify",
        "category-list",
        "folder-list",
        "searchfolder-list",
    ):
        sub.choices[verb].add_argument("--format", choices=["concise", "detailed"], default="concise")
    sub.choices["folder-list"].add_argument(
        "--include_hidden",
        type=lambda v: str(v).lower() not in ("false", "0", "no"),
        default=False,
        help="also list hidden folders (default false)",
    )
    sub.choices["mail-get"].add_argument("--message_id", required=True, help="Graph message id")

    mvm = sub.choices["message-move"]
    mvm.add_argument("--message_ids", nargs="+", required=True, metavar="ID", help="message id(s) to move")
    mvm.add_argument("--destination_folder", required=True, help="target folder name, well-known name, or id")
    mvm.add_argument(
        "--dry_run",
        type=lambda v: str(v).lower() not in ("false", "0", "no"),
        default=False,
        help="preview what would move without writing (default false)",
    )
    sub.choices["rule-verify"].add_argument(
        "--header_contains", nargs="+", required=True, metavar="SUBSTR", help="header substrings to match"
    )
    sub.choices["rule-create"].add_argument("--name", required=True, help="rule display name")
    sub.choices["rule-create"].add_argument(
        "--header_contains",
        nargs="+",
        required=True,
        metavar="SUBSTR",
        help="predicate substrings (must match a prior verify)",
    )
    sub.choices["rule-create"].add_argument(
        "--move_to_folder", help="optional target folder name (files matching mail there)"
    )
    sub.choices["rule-create"].add_argument(
        "--assign_category", nargs="+", metavar="NAME", help="optional category name(s) to assign"
    )
    sub.choices["rule-remove"].add_argument("--rule_id", required=True, help="Graph rule id")

    sub.choices["category-ensure"].add_argument("--name", required=True, help="category display name")
    sub.choices["category-ensure"].add_argument("--color", default="preset9", help="categoryColor preset")

    sfc = sub.choices["searchfolder-create"]
    sfc.add_argument("--name", required=True, help="search folder display name")
    sfc.add_argument("--category", help="build a category filter for this name")
    sfc.add_argument("--filter_query", help="explicit OData filter (overrides --category)")
    sfc.add_argument("--source_folders", nargs="+", metavar="FOLDER", help="folders to mine (default: inbox)")
    sfc.add_argument(
        "--include_nested",
        type=lambda v: str(v).lower() not in ("false", "0", "no"),
        default=True,
        help="deep-search source subtrees (default true)",
    )
    sub.choices["searchfolder-remove"].add_argument("--folder_id", required=True, help="search folder id")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SteerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
