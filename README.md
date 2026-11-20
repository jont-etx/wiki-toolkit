# Wiki Toolkit

Wiki Toolkit sets up a project Markdown wiki for Codex. The toolkit includes a setup skill and a local Model Context Protocol (MCP) server that starts read-only by default. Each project keeps its wiki files in its own `.wiki/` directory.

## Install on Windows

Use a recent Codex CLI with `codex plugin` support and Python 3.11 or newer. Extract the release or check out the toolkit in a directory you can keep in place. Run these PowerShell commands from that directory, substituting your project path.

```powershell
$toolkit = (Get-Location).Path
$project = (Resolve-Path 'C:\path\to\your-project').Path
codex plugin marketplace add "$toolkit"
codex plugin add wiki-toolkit@wiki-toolkit-local
python -m venv "$toolkit/.venv"
$python = Join-Path $toolkit '.venv/Scripts/python.exe'
$plugin = Join-Path $toolkit 'plugins/wiki-toolkit'
& $python -m pip install -r "$plugin/requirements.txt"
$runner = Join-Path $plugin 'bin/wiki_toolkit.py'
& $python -I -B $runner setup --project "$project"
```

Review the preview, then apply it.

```powershell
& $python -I -B $runner setup --project "$project" --apply
```

Setup creates `.wiki/index.md` if there is no `.wiki/` and preserves any existing wiki and project instructions. If `.codex/config.toml` already exists, review and add the printed MCP registration by hand. If the registration conflicts with an existing one, review and reconcile the existing entry before applying setup again.

Open a new Codex session from the project and trust the project if you want Codex to load its configuration. From the project root, `codex mcp get wiki_toolkit` shows the registration. Ask Codex to list your wiki pages to verify the server responds.

The registration points to the toolkit runner and Python environment by absolute path. Keep both in place. If you move or replace that installation, update the registration in the project config. To disconnect the server, remove only the `[mcp_servers.wiki_toolkit]` table from the project config. Wiki files can be kept and used independently of the plugin.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `wiki_list` | List visible Markdown pages in the selected project wiki |
| `wiki_read` | Read a range of lines and return the revision of a UTF-8 Markdown page |
| `wiki_search` | Find literal text in page names and contents, ignoring case |

The server runs over local stdio. It excludes hidden paths, symlinks, Windows junctions, hard-linked files, and files larger than 1 MiB. Search scans at most 250 pages per call. The default server exposes no wiki write, Git publication, or coordinator tools. Wiki content is project-owned data and stays out of this distribution.

## Project profiles

A project can opt into a named profile by adding `.codex/wiki-toolkit/<name>.toml` to that project and selecting it with `--profile <name>` during setup. Each launcher binds the selected profile to its explicit project checkout. Without `--profile`, the launcher ignores profile files and keeps the original three read-only tools.

This example exposes only list and read and registers the server as `project_wiki`:

```toml
version = 1
server_name = "project_wiki"
base_tools = ["wiki_list", "wiki_read"]
```

Save the example as `.codex/wiki-toolkit/reader.toml` in the selected project, then run:

```powershell
& $python -I -B $runner setup --project "$project" --profile reader
& $python -I -B $runner setup --project "$project" --profile reader --apply
```

Review the preview before applying. For an existing Codex config, merge the emitted registration yourself. If a server with the same name is already registered, review and update that entry explicitly. To revert, restore the previous registration table and reopen Codex in the project.

### Enable scoped writes

Add this table to a project profile to expose the built-in `wiki_write_preview` and `wiki_write` tools:

```toml
[write]
paths = ["index.md", "notes/"]
```

Paths are relative to `.wiki/`. Use an exact Markdown filename or a directory prefix ending in `/`. Parent directories must already exist. Keep the base `wiki_read` tool available so clients can get the current revision.

For an edit, read the page and pass the returned `revision` as `expected_revision`. For a new page, pass `"missing"`. Call `wiki_write_preview` with the path, proposed complete content, and expected revision to get a bounded diff without writing. Use those same inputs for `wiki_write`. A stale revision or a page that already exists when creation was requested is refused.

Wiki Toolkit processes serialize writes within each checkout. The writer uses atomic replacement for existing pages and creation that refuses to overwrite an existing file. The writer manages `.codex/wiki-toolkit/.write.lock` as local runtime state. Keep it out of version control and leave it in place while a server is running. External editors do not participate in the lock. On Windows, replaced pages inherit directory permissions. Use an adapter when writes must preserve custom permissions on individual files.

The profile opts into write access and sets its path scope. The preview is for review. Apply the project's approval process before calling the write tool. Projects requiring server-enforced claims or approvals can delegate writes to their own adapter.

### Project-owned MCP adapters

An optional `[adapter]` table delegates explicit tools to a trusted local MCP server. Set `command` to the absolute executable path, `args` to a string array, and `tools` to the exact tool names the profile may expose. Set `[adapter.env]` only when the adapter needs environment variables. The value `"{project}"` expands to this launcher's selected project root. The adapter starts from that root over stdio.

Use `base_tools = []` to expose only the delegated tools. When an allowed adapter tool shares a name with a base tool, the adapter supplies that tool's input and output schemas, annotations, results, and errors. All allowlisted adapter tools must be present at startup. The server keeps that tool inventory until restart.

The adapter runs with the launcher account's permissions. Only use profiles and executables you trust. The adapter enforces its own access, claims, write approvals, and revision checks. Choose one writer per profile. Built-in writes and adapter-provided write tools cannot be combined. Keep project policies, coordinator state, and any sensitive profile values in the owning project or its local environment.

The tests include a synthetic revisioned wiki adapter. Its guarded writes run only against disposable fixtures. The base `wiki_read` retains line ranges, and an adapter may supply a different read contract, such as byte offsets plus revision tokens.

## Run tests

From the toolkit checkout, with its Python environment set up, run:

```powershell
& $python -B -m unittest discover -s tests -v
```

The tests create disposable projects and use an MCP client to call the server over stdio.

## License

Wiki Toolkit is licensed under the [Apache License, Version 2.0](LICENSE). Project wikis keep their own licensing and access rules.
