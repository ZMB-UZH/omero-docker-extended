---
name: cocoindex-code-search
description: Install and use the repo's pinned host-side CocoIndex Code workflow for semantic routing, token reduction, and optional MCP registration without writing index artifacts into the live checkout.
origin: repo-local skill based on verified cocoindex-code 0.2.31 behavior
---

# CocoIndex Code Search

Use this skill when repo navigation is broad enough that semantic routing can
reduce context before exact `rg`, file reads, and tests.

## Required workflow

1. Check for an already configured MCP server or tool named `cocoindex-code`
   before reading installation instructions. If it exists, use it for broad
   semantic routing and skip install/setup.
2. Keep `rg` as the exact search and validation tool.
3. Use `python3 tools/cocoindex_agent_search.py mcp-install` for Codex, or
   `python3 tools/cocoindex_agent_search.py mcp-config` for other MCP clients,
   only when the MCP server is absent.
4. Use `python3 tools/cocoindex_agent_search.py install` directly only when MCP
   is unavailable or a CLI-only workflow is intentionally being prepared.
5. Use `python3 tools/cocoindex_agent_search.py search --limit 5 "<query>"` for
   subsystem routing, then confirm the returned files with `rg` in the real repo.
6. Use `--path '<glob>'` only after the first pass identifies a likely subtree.
7. Run
   `python3 tools/cocoindex_agent_search.py benchmark --cases <cases.json>`
   when changing this workflow or after a major CocoIndex Code release.
8. Skip CocoIndex when an exact string, symbol, or small `rg` result is already
   likely; the hybrid path is for broad routing where candidate output would be
   large.

## Artifact rules

- Never run `ccc init` directly in the live checkout.
- Keep pinned `cocoindex-code[full]==0.2.31`; do not use a floating version.
- The wrapper indexes an external mirror of Git-visible non-ignored files.
  Settings, runtime files, model caches, and SQLite databases stay under XDG
  paths or `AGENT_COCOINDEX_HOME`, never under the live repository.
- Use exactly one host install per user account: the shared pinned venv lives
  under `AGENT_COCOINDEX_HOME` or the XDG data default. Each repository content
  digest gets a separate mirror, database directory, and daemon runtime
  directory under that one install so parallel agents on different repositories
  do not share project locks or databases.
- Launch commands from the target Git repository root, or set
  `AGENT_COCOINDEX_REPO` to that root for clients that cannot control their
  working directory. Do not put installation-specific paths in committed files.
- Do not add, commit, or normalize `.cocoindex_code/` in the repository.
- Do not index real `.env` files; only example env contracts are allowed.
- Treat semantic output as routing only; read and edit real repo files after
  exact confirmation.

## MCP

- Generic MCP: first check whether a server or tool named `cocoindex-code` is
  already configured. If it is absent, run
  `python3 tools/cocoindex_agent_search.py mcp-config` and use the printed
  stdio command, args, and env in any MCP-capable agent. The client must launch
  it from the target Git repository root, or use `mcp-config --pin-repo` only
  for a workspace-scoped static config.
- Codex: run `python3 tools/cocoindex_agent_search.py mcp-install`. It registers
  one workspace-agnostic MCP server named `cocoindex-code` and does not add a
  duplicate if that name already exists.

## Stop signs

- Do not use this for precise string, symbol, or scanner-count checks; use `rg`
  or the repo scanner tools.
- Do not run CocoIndex plus `rg` by default for narrow queries; benchmark it
  first if the token budget benefit is unclear.
- Do not expand context just because semantic search returned results. Open the
  smallest confirmed file set and follow `context-budget`.
