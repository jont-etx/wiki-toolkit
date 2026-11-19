# Wiki Toolkit

Wiki Toolkit is a work in progress for setting up and maintaining a project wiki in Codex. The toolkit will ship reusable templates, skills, setup and upgrade tools, and a local Model Context Protocol (MCP) server. Each project will use its own wiki checkout to store its knowledge.

## Status

This repository is in initial setup. Install commands will be published after the first release is tested in a separate project.

## What lives where

| Location | Contents |
| --- | --- |
| Wiki Toolkit | Generic templates and skills, setup and upgrade tools, MCP server, and tests with fictional data |
| Project wiki | Project rules, notes, decisions, evidence, and version history |
| Local runtime state | Work claims and reservations shared by worktrees of the same project |

Each installation will select a project and wiki explicitly. A toolkit upgrade should preserve project content and settings. Project credentials belong in the project's secret store.

## First release plan

1. Set up a new wiki or connect an existing one. Preview changes before applying them and verify rollback.
2. Provide local wiki search and read tools through MCP. Add write support behind project-level configuration and the project's existing review process.
3. Test setup and upgrade in a separate project. Verify that content survives the upgrade, worktrees share their project's claims when coordination is enabled, and an unrelated wiki stays out of reach.

Projects that already use a Coordinator will keep one authority for each shared resource. Wiki Toolkit will integrate with the existing authority where needed. Projects that share a resource must use the same authority for that resource.

## License

Wiki Toolkit is licensed under the [Apache License, Version 2.0](LICENSE). Project wikis keep their own licensing and access rules.
