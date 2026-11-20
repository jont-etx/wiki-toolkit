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
            f'tools = {json.dumps(tools or ["wiki_read", "wiki_write", "coordinator_call"])}\n'
            '\n[adapter.env]\nFIXTURE_WIKI_ROOT = "{project}"\n',
            encoding="utf-8",
        )
        return path

    @asynccontextmanager
    async def connect(self, project):
        config = tomllib.loads((project / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(config["mcp_servers"]), {"wiki"})
        async with stdio_client(StdioServerParameters(**config["mcp_servers"]["wiki"])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
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

    def test_profiles_preserve_contracts_and_bind_to_each_worktree(self):
        def git(*args):
            subprocess.run(
                ["git", "-C", str(self.project), *args], check=True, capture_output=True, timeout=20,
            )

        wiki = self.project / ".wiki"
        wiki.mkdir()
        (wiki / "index.md").write_text("# Synthetic wiki\n", encoding="utf-8")
        git("init", "--quiet")
        git("add", ".wiki/index.md")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        worktree = self.root / "second worktree"
        git("worktree", "add", "--quiet", "--detach", str(worktree), "HEAD")

        for project in (self.project, worktree):
            self.profile(project)
            result = self.run_tool(project, "--profile", "revisioned", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)

        async def probe():
            async with self.connect(self.project) as first, self.connect(worktree) as second:
                tools = {tool.name: tool for tool in (await first.list_tools()).tools}
                self.assertEqual(set(tools), {"wiki_list", "wiki_read",
                                              "wiki_write", "coordinator_call"})
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
                claim = await first.call_tool("coordinator_call", {"operation": "claim", "session_id": "fixture"})
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
