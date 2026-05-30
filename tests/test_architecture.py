"""Guard the extractable-core invariant: ibkr_mcp/core/ never imports mcp or fastmcp."""

import pathlib

CORE_DIR = pathlib.Path(__file__).resolve().parent.parent / "ibkr_mcp" / "core"
MCP_DIR = pathlib.Path(__file__).resolve().parent.parent / "ibkr_mcp" / "mcp"


def test_core_never_imports_mcp_or_fastmcp():
    offenders = []
    for py in CORE_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            # Allow our own package; forbid the MCP SDK / FastMCP.
            if (
                "fastmcp" in stripped
                or stripped.startswith("import mcp")
                or stripped.startswith("from mcp")
            ):
                offenders.append(f"{py.name}:{lineno}: {stripped}")
    assert not offenders, "core/ must not depend on MCP layer:\n" + "\n".join(offenders)


def test_mcp_layer_never_imports_ib_async_directly():
    offenders = []
    for py in MCP_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if stripped.startswith("import ib_async") or stripped.startswith("from ib_async"):
                offenders.append(f"{py.name}:{lineno}: {stripped}")
    assert not offenders, (
        "mcp/ must not import ib_async directly (go through core/):\n" + "\n".join(offenders)
    )
