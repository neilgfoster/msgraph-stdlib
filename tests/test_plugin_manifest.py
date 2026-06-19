"""The marketplace manifest must resolve to a real, well-formed plugin.

Guards the install path: `/plugin marketplace add neilgfoster/msgraph-stdlib` then
`/plugin install msgraph-stdlib@neilgfoster/msgraph-stdlib` only works if the root
.claude-plugin/marketplace.json lists a plugin whose `source` directory carries a valid
.claude-plugin/plugin.json.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def test_marketplace_manifest_exists_and_is_valid_json():
    assert MARKETPLACE.is_file(), "root .claude-plugin/marketplace.json is required to install the plugin"
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert data.get("name"), "marketplace needs a name"
    assert isinstance(data.get("plugins"), list) and data["plugins"], "marketplace needs at least one plugin"


def test_each_plugin_source_resolves_to_a_plugin_manifest():
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    for entry in data["plugins"]:
        source = entry.get("source")
        assert source, f"plugin entry missing source: {entry}"
        plugin_json = (REPO_ROOT / source / ".claude-plugin" / "plugin.json").resolve()
        assert plugin_json.is_file(), f"source {source} has no .claude-plugin/plugin.json"
        manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
        # The marketplace entry name must match the plugin's own name so `install <name>@<repo>` works.
        assert manifest.get("name") == entry.get("name"), (
            f"marketplace name {entry.get('name')!r} != plugin.json name {manifest.get('name')!r}"
        )
