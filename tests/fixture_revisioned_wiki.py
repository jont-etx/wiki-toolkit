"""Synthetic revisioned wiki and claim tools for profile integration tests."""

from hashlib import sha256
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

root = Path(os.environ["FIXTURE_WIKI_ROOT"])
if root != Path.cwd():
    raise RuntimeError("Fixture adapter cwd does not match the selected project")
page = root / ".wiki/index.md"
claims = set()
server = FastMCP("Synthetic revisioned wiki", instructions="Verify the fixture claim before writing.")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def wiki_read(path: str, offset: int = 0, revision: str = "") -> dict[str, Any]:
    if path != "index.md":
        raise ValueError("INVALID_PATH")
    content = page.read_bytes()
    digest = sha256(content).hexdigest()
    if revision and revision != digest:
        raise ValueError("STALE_REVISION")
    return {"text": content[offset:].decode("utf-8"), "revision": digest}


@server.tool(annotations=ToolAnnotations(readOnlyHint=False))
def fixture_claim(operation: str, session_id: str) -> dict[str, Any]:
    if operation != "claim":
        raise ValueError("UNKNOWN_OPERATION")
    claims.add(session_id)
    return {"claimed": True}


@server.tool(annotations=ToolAnnotations(readOnlyHint=False))
def wiki_write(path: str, content: str, expected_revision: str, session_id: str) -> dict[str, Any]:
    if session_id not in claims:
        raise ValueError("CLAIM_REQUIRED")
    found = wiki_read(path, revision=expected_revision)
    if found["revision"] != expected_revision:
        raise ValueError("STALE_REVISION")
    page.write_text(content, encoding="utf-8")
    return wiki_read(path)


@server.tool()
def hidden_tool() -> str:
    return "This adapter tool was excluded by the project profile."


if __name__ == "__main__":
    server.run()
