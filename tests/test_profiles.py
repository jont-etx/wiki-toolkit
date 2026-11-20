import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RUNNER = Path(__file__).resolve().parents[1] / "plugins/wiki-toolkit/bin/wiki_toolkit.py"
ADAPTER = Path(__file__).with_name("fixture_revisioned_wiki.py").resolve()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.project = self.root / "first project"
        self.project.mkdir()

    def command(self, project, verb, *options):
        return [sys.executable, "-I", "-B", str(RUNNER), verb, "--project", str(project), *options]

    def run_tool(self, project, *options):
        return subprocess.run(
            self.command(project, "setup", *options), capture_output=True, text=True, timeout=15,
        )

    def profile(self, project, tools=None):
        directory = project / ".codex/wiki-toolkit"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "revisioned.toml"
        path.write_text(
            'version = 1\nserver_name = "wiki"\nbase_tools = ["wiki_list"]\n\n[adapter]\n'
            f'command = {json.dumps(sys.executable)}\n'
            f'args = {json.dumps(["-I", "-B", str(ADAPTER)])}\n'
            f'tools = {json.dumps(tools or ["wiki_read", "wiki_write", "fixture_claim"])}\n'
            '\n[adapter.env]\nFIXTURE_WIKI_ROOT = "{project}"\n',
            encoding="utf-8",
        )
        return path

    @asynccontextmanager
    async def connect(self, project, expected_instructions=None):
        config = tomllib.loads((project / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(config["mcp_servers"]), {"wiki"})
        async with stdio_client(StdioServerParameters(**config["mcp_servers"]["wiki"])) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                if expected_instructions is not None:
                    self.assertEqual(initialized.instructions, expected_instructions)
                yield session

    def test_profile_preview_and_invalid_profile_fail_before_writes(self):
        profile = self.profile(self.project)
        preview = self.run_tool(self.project, "--profile", "revisioned")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("[mcp_servers.wiki]", preview.stdout)
        self.assertFalse((self.project / ".wiki").exists())
        self.assertFalse((self.project / ".codex/config.toml").exists())

        for name in ("../revisioned", "missing"):
            with self.subTest(profile=name):
                result = self.run_tool(self.project, "--profile", name, "--apply")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.project / ".wiki").exists())
        with profile.open("a", encoding="utf-8") as stream:
            stream.write("invalid = 123\n")
        result = self.run_tool(self.project, "--profile", "revisioned", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / ".wiki").exists())

    def test_setup_refuses_hard_linked_profile(self):
        profile = self.profile(self.project)
        os.link(profile, self.root / "other profile.toml")
        result = self.run_tool(self.project, "--profile", "revisioned", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard links", result.stderr)
        self.assertFalse((self.project / ".wiki").exists())

    def test_profile_setup_preserves_a_conflicting_registration(self):
        self.profile(self.project)
        path = self.project / ".codex/config.toml"
        existing = b'[mcp_servers.wiki]\ncommand = "existing-server"\n'
        path.write_bytes(existing)
        result = self.run_tool(self.project, "--profile", "revisioned", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing wiki registration differs", result.stderr)
        self.assertEqual(path.read_bytes(), existing)
        self.assertFalse((self.project / ".wiki").exists())

    def test_profile_serve_refuses_unavailable_tools(self):
        self.profile(self.project, tools=["not_provided"])
        setup = self.run_tool(self.project, "--profile", "revisioned", "--apply")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        result = subprocess.run(
            self.command(self.project, "serve", "--profile", "revisioned"),
            input="", capture_output=True, text=True, timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Adapter did not provide: not_provided", result.stderr)

    def test_unselected_profile_does_not_change_default_registration(self):
        self.profile(self.project)
        result = self.run_tool(self.project, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = tomllib.loads((self.project / ".codex/config.toml").read_text(encoding="utf-8"))
        servers = config["mcp_servers"]
        self.assertEqual(set(servers), {"wiki_toolkit"})
        self.assertNotIn("--profile", servers["wiki_toolkit"]["args"])

    def setup_writer(self):
        config = self.project / ".codex/wiki-toolkit"
        config.mkdir(parents=True)
        (config / "writer.toml").write_text(
            'version = 1\nserver_name = "wiki"\n[write]\npaths = ["notes/", "index.md"]\n',
            encoding="utf-8",
        )
        result = self.run_tool(self.project, "--profile", "writer", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        wiki = self.project / ".wiki"
        (wiki / "notes").mkdir()
        (wiki / "other.md").write_text("# Private scope", encoding="utf-8")
        os.link(wiki / "other.md", wiki / "notes/linked.md")
        return wiki

    def test_builtin_write_preview_scope_and_revision(self):
        wiki = self.setup_writer()
        index = wiki / "index.md"
        original = index.read_bytes()

        async def probe():
            async with self.connect(self.project) as session:
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                self.assertTrue(tools["wiki_write_preview"].annotations.readOnlyHint)
                self.assertFalse(tools["wiki_write"].annotations.readOnlyHint)
                page = await session.call_tool("wiki_read", {"path": "index.md"})
                revision = page.structuredContent["revision"]
                args = {"path": "index.md", "content": "# Updated\n", "expected_revision": revision}
                preview = await session.call_tool("wiki_write_preview", args)
                self.assertIn("+# Updated", preview.structuredContent["diff"])
                self.assertEqual(index.read_bytes(), original)
                self.assertFalse((self.project / ".codex/wiki-toolkit/.write.lock").exists())
                changed = await session.call_tool("wiki_write", args)
                self.assertFalse(changed.isError, str(changed))
                self.assertEqual(changed.structuredContent["revision"], preview.structuredContent["new_revision"])
                self.assertEqual(index.read_bytes(), b"# Updated\n")
                stale = await session.call_tool("wiki_write", args)
                self.assertTrue(stale.isError)
                self.assertIn("revision", stale.content[0].text)
                newline = await session.call_tool("wiki_write_preview", {
                    **args, "content": "# Updated", "expected_revision": changed.structuredContent["revision"],
                })
                self.assertTrue(newline.structuredContent["changed"])
                self.assertIn("line endings", newline.structuredContent["diff"])

                create = {"path": "notes/new.md", "content": "# New", "expected_revision": "missing"}
                written = await session.call_tool("wiki_write", create)
                self.assertFalse(written.isError, str(written))
                self.assertEqual((wiki / "notes/new.md").read_bytes(), b"# New")
                self.assertTrue((await session.call_tool("wiki_write", create)).isError)
                for path in ("other.md", "notes-sibling/refused.md", "../outside.md", "notes/linked.md"):
                    with self.subTest(path=path):
                        blocked = await session.call_tool("wiki_write", {**create, "path": path})
                        self.assertTrue(blocked.isError)
                self.assertEqual((wiki / "other.md").read_text(encoding="utf-8"), "# Private scope")
        asyncio.run(asyncio.wait_for(probe(), 25))

    def test_two_servers_cannot_write_the_same_revision(self):
        wiki = self.setup_writer()
        sibling_page = self.linked_worktree() / ".wiki/index.md"
        sibling_original = sibling_page.read_bytes()

        async def probe():
            async with self.connect(self.project) as first, self.connect(self.project) as second:
                page = await first.call_tool("wiki_read", {"path": "index.md"})
                args = {"path": "index.md", "expected_revision": page.structuredContent["revision"]}
                results = await asyncio.gather(
                    first.call_tool("wiki_write", {**args, "content": "# First"}),
                    second.call_tool("wiki_write", {**args, "content": "# Second"}),
                )
                self.assertEqual(sum(not result.isError for result in results), 1)
                winner = "# Second" if results[0].isError else "# First"
                self.assertEqual((wiki / "index.md").read_text(encoding="utf-8"), winner)
                self.assertEqual(sibling_page.read_bytes(), sibling_original)
        asyncio.run(asyncio.wait_for(probe(), 25))

    def linked_worktree(self):
        def git(*args):
            subprocess.run(
                ["git", "-C", str(self.project), *args], check=True, capture_output=True, timeout=20,
            )

        wiki = self.project / ".wiki"
        wiki.mkdir(exist_ok=True)
        if not (wiki / "index.md").exists():
            (wiki / "index.md").write_text("# Synthetic wiki\n", encoding="utf-8")
        git("init", "--quiet")
        git("add", ".wiki/index.md")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        worktree = self.root / "second worktree"
        git("worktree", "add", "--quiet", "--detach", str(worktree), "HEAD")
        return worktree

    def test_profiles_preserve_contracts_and_bind_to_each_worktree(self):
        worktree = self.linked_worktree()
        for project in (self.project, worktree):
            self.profile(project)
            result = self.run_tool(project, "--profile", "revisioned", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)

        async def probe():
            instructions = "Verify the fixture claim before writing."
            async with (
                self.connect(self.project, instructions) as first,
                self.connect(worktree, instructions) as second,
            ):
                tools = {tool.name: tool for tool in (await first.list_tools()).tools}
                self.assertEqual(set(tools), {"wiki_list", "wiki_read",
                                              "wiki_write", "fixture_claim"})
                self.assertIn("offset", tools["wiki_read"].inputSchema["properties"])
                self.assertTrue(tools["wiki_read"].annotations.readOnlyHint)
                self.assertFalse(tools["wiki_write"].annotations.readOnlyHint)
                original = await first.call_tool("wiki_read", {"path": "index.md", "offset": 2})
                self.assertFalse(original.isError)
                self.assertEqual(original.structuredContent["text"].strip(), "Synthetic wiki")
                revision = original.structuredContent["revision"]
                pages = await first.call_tool("wiki_list", {})
                self.assertEqual(pages.structuredContent["paths"], ["index.md"])
                for name in ("hidden_tool", "wiki_search"):
                    blocked = await first.call_tool(name, {})
                    self.assertTrue(blocked.isError)
                args = {"path": "index.md", "content": "# Changed", "expected_revision": revision,
                        "session_id": "fixture"}
                denied = await first.call_tool("wiki_write", args)
                self.assertTrue(denied.isError)
                self.assertIn("CLAIM_REQUIRED", denied.content[0].text)
                claim = await first.call_tool("fixture_claim", {"operation": "claim", "session_id": "fixture"})
                self.assertEqual(claim.structuredContent, {"claimed": True})
                stale = await first.call_tool("wiki_write", {**args, "expected_revision": "stale"})
                self.assertTrue(stale.isError)
                self.assertIn("STALE_REVISION", stale.content[0].text)
                changed = await first.call_tool("wiki_write", args)
                self.assertEqual(changed.structuredContent["text"], "# Changed")
                self.assertTrue((await second.call_tool("wiki_write", args)).isError)
                untouched = await second.call_tool("wiki_read", {"path": "index.md"})
                self.assertEqual(untouched.structuredContent["revision"], revision)
        asyncio.run(asyncio.wait_for(probe(), 35))


if __name__ == "__main__":
    unittest.main()
