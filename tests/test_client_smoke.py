"""The bundled stdlib kernel must stay importable and runnable.

`describe` is the discovery entry point (the zero-backend MCP tools/list equivalent); if it stops
emitting a valid catalog, agents can no longer enumerate the plugin's verbs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLIENT = Path(__file__).resolve().parent.parent / "plugin" / "src" / "msgraph" / "client.py"


def test_describe_emits_a_valid_tool_catalog():
    proc = subprocess.run(
        [sys.executable, str(CLIENT), "describe"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"describe failed: {proc.stderr}"
    catalog = json.loads(proc.stdout)
    assert isinstance(catalog.get("tools"), list) and catalog["tools"], "describe must list tools"
    for tool in catalog["tools"]:
        assert tool.get("name") and tool.get("description") and tool.get("inputSchema")
