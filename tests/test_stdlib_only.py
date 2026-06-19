"""Enforce — not just assert — the stdlib-only guarantee for the shipped payload.

The plugin under plugin/src/ must import only the Python standard library (plus its own package)
at runtime: that is the whole portability/auditability promise (no install friction, no third-party
attack surface). ruff/pytest are dev tooling and live OUTSIDE plugin/, so they never count here.

Two layers of defence:
  - test_no_forbidden_imports — a fast denylist grep, mirrored verbatim in README's verify steps,
    so a human and CI fail on the same obvious offenders (msal, azure, requests, ...).
  - test_every_import_is_stdlib_or_first_party — the real guarantee: AST-walk every import and assert
    each top-level module is in the stdlib or is the plugin's own package. Catches anything the
    denylist forgot.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "plugin" / "src"

# First-party package(s) shipped in the plugin. This plugin's own kernel package is `msgraph`.
FIRST_PARTY = {"msgraph"}

# Mirrored in README "Verify before done". Keep the two in sync. NB: `msgraph` is this plugin's own
# first-party package (see FIRST_PARTY), so it is NOT denylisted here — unlike the template, whose
# own package is `example` and which therefore forbids the real PyPI `msgraph` SDK.
FORBIDDEN = (
    "msal",
    "azure",
    "requests",
    "urllib3",
    "httpx",
    "aiohttp",
    "pydantic",
    "yaml",
    "dotenv",
)


def _py_files() -> list[Path]:
    return sorted(PLUGIN_SRC.rglob("*.py"))


def test_plugin_src_has_python_files():
    # Guard against the test silently passing because the path moved.
    assert _py_files(), f"no .py files under {PLUGIN_SRC} — did the layout change?"


def test_no_forbidden_imports():
    """The denylist grep, applied as code. Same intent as the README one-liner."""
    pattern = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(FORBIDDEN) + r")\b", re.MULTILINE)
    offenders = []
    for path in _py_files():
        for m in pattern.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(PLUGIN_SRC.parent.parent)}: {m.group(1)}")
    assert not offenders, "forbidden third-party imports in shipped plugin:\n  " + "\n  ".join(offenders)


def test_every_import_is_stdlib_or_first_party():
    """The real guarantee: every imported top-level module is stdlib or the plugin's own package."""
    stdlib = sys.stdlib_module_names  # Python 3.10+
    bad: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            else:
                continue
            for mod in mods:
                if mod not in stdlib and mod not in FIRST_PARTY:
                    bad.append(f"{path.relative_to(PLUGIN_SRC.parent.parent)}: {mod}")
    assert not bad, (
        "non-stdlib / non-first-party imports in shipped plugin (stdlib-only is non-negotiable):\n  "
        + "\n  ".join(bad)
    )
