import asyncio
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RUNNER = Path(__file__).resolve().parents[1] / "plugins/wiki-toolkit/bin/wiki_toolkit.py"


class WikiToolkitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "field guide"
        self.project.mkdir()

    def run_tool(self, command, *options):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(RUNNER), command,
             "--project", str(self.project), *options],
            capture_output=True, text=True, timeout=15
        )

    def test_setup_preview_and_repeat_preserve_existing_content(self):
        guide = self.project / "AGENTS.md"
        guide.write_text("Existing instructions", encoding="utf-8")
        self.assertEqual(self.run_tool("setup").returncode, 0)
        self.assertFalse((self.project / ".wiki").exists())
        self.assertFalse((self.project / ".codex").exists())
        result = self.run_tool("setup", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        wiki = self.project / ".wiki/index.md"
        wiki.write_text("# My notes", encoding="utf-8")
        config = self.project / ".codex/config.toml"
        original = config.read_bytes()
        result = self.run_tool("setup", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(wiki.read_text(encoding="utf-8"), "# My notes")
        self.assertEqual(guide.read_text(encoding="utf-8"), "Existing instructions")

    def test_setup_leaves_existing_config_for_review(self):
        config = self.project / ".codex/config.toml"
        config.parent.mkdir()
        config.write_bytes(b'model = "local-example"\n')
        result = self.run_tool("setup", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.read_bytes(), b'model = "local-example"\n')
        self.assertIn("[mcp_servers.wiki_toolkit]", result.stdout)

    def link_directory(self, link, target):
        if os.name == "nt":
            subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                check=True, capture_output=True, timeout=10,
            )
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_setup_refuses_linked_config_directory(self):
        outside = Path(self.temp.name) / "other config"
        outside.mkdir()
        config = outside / "config.toml"
        config.write_text("keep me", encoding="utf-8")
        self.link_directory(self.project / ".codex", outside)
        self.assertNotEqual(self.run_tool("setup", "--apply").returncode, 0)
        self.assertFalse((self.project / ".wiki").exists())
        self.assertEqual(config.read_text(encoding="utf-8"), "keep me")

    def test_setup_refuses_conflicting_registration(self):
        config = self.project / ".codex/config.toml"
        config.parent.mkdir()
        original = b'mcp_servers.wiki_toolkit = false\n'
        config.write_bytes(original)
        result = self.run_tool("setup", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("registration differs", result.stderr)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((self.project / ".wiki").exists())

    def test_mcp_lists_searches_and_reads_only_approved_markdown(self):
        result = self.run_tool("setup", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        wiki = self.project / ".wiki"
        note = wiki / "trail.md"
        note.write_text("# Trails\nThe heron nests at dawn.\n", encoding="utf-8")
        (wiki / ".private.md").write_text("heron hidden", encoding="utf-8")
        (wiki / "raw.txt").write_text("heron raw", encoding="utf-8")
        (wiki / "oversize.md").write_bytes(b"heron " + b"x" * 1_048_577)
        outside = self.project.parent / "outside.md"
        outside.write_text("heron outside", encoding="utf-8")
        os.link(outside, wiki / "hardlink.md")
        self.link_directory(wiki / "other-project", self.project.parent)
        before = note.read_bytes()

        async def probe():
            config = self.project / ".codex/config.toml"
            registration = tomllib.loads(config.read_text(encoding="utf-8"))
            params = StdioServerParameters(**registration["mcp_servers"]["wiki_toolkit"])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.assertEqual({tool.name for tool in tools},
                                     {"wiki_list", "wiki_read", "wiki_search"})
                    self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                    listed = await session.call_tool("wiki_list")
                    self.assertFalse(listed.isError, str(listed))
                    self.assertEqual(listed.structuredContent["paths"], ["index.md", "trail.md"])
                    hit = await session.call_tool("wiki_search", {"query": "HERON"})
                    self.assertEqual([x["path"] for x in hit.structuredContent["matches"]], ["trail.md"])
                    found = await session.call_tool("wiki_read", {"path": "trail.md", "start_line": 2})
                    self.assertIn("nests at dawn", found.structuredContent["text"])
                    for path in ("../outside.md", str(outside), ".private.md",
                                 "raw.txt", "hardlink.md", "trail.md:stream", "oversize.md",
                                 "other-project/outside.md"):
                        with self.subTest(path=path):
                            denied = await session.call_tool("wiki_read", {"path": path})
                            self.assertTrue(denied.isError, str(denied))
        asyncio.run(asyncio.wait_for(probe(), timeout=20))
        self.assertEqual(note.read_bytes(), before)

    def test_server_refuses_linked_wiki_root(self):
        target = Path(self.temp.name) / "other wiki"
        target.mkdir()
        self.link_directory(self.project / ".wiki", target)
        result = self.run_tool("serve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("links", result.stderr)


if __name__ == "__main__":
    unittest.main()
