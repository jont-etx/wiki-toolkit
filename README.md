# Wiki Toolkit

Wiki Toolkit sets up a project Markdown wiki for Codex. Version 0.1.0 includes a setup skill and a local, read-only Model Context Protocol (MCP) server. Each project keeps its wiki files in its own `.wiki/` directory.

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
| `wiki_read` | Read a range of lines from a UTF-8 Markdown page |
| `wiki_search` | Find literal text in page names and contents, ignoring case |

The server runs over local stdio. It excludes hidden paths, symlinks, Windows junctions, hard-linked files, and files larger than 1 MiB. Search scans at most 250 pages per call. The server has no wiki write, Git publication, or coordinator tools. Wiki content is project-owned data and stays out of this distribution.

## Run tests

From the toolkit checkout, with its Python environment set up, run:

```powershell
& $python -B -m unittest discover -s tests -v
```

The tests create disposable projects and use an MCP client to call the server over stdio.

## License

Wiki Toolkit is licensed under the [Apache License, Version 2.0](LICENSE). Project wikis keep their own licensing and access rules.
