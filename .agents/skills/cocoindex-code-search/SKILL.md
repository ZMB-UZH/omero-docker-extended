---
name: cocoindex-code-search
description: Mandatory MCP-first workflow for the repo's pinned host-side CocoIndex Code semantic routing and token reduction without writing index artifacts into the live checkout.
origin: repo-local skill based on verified cocoindex-code 0.2.32 behavior
---

# CocoIndex Code Search

Use this skill for broad repo navigation when semantic routing can reduce
context before exact `rg`, file reads, and tests.

## Required workflow

1. For broad repo navigation, this skill is mandatory. Check for an already
   configured MCP server or tool named `cocoindex-code` before reading
   installation instructions. If it exists, use it for broad semantic routing
   and skip install/setup.
2. Keep `rg` as the exact search and validation tool.
3. Use `python3 tools/cocoindex_agent_search.py mcp-install` for Codex, or
   `python3 tools/cocoindex_agent_search.py mcp-config` for other MCP clients,
   only when the MCP server is absent.
4. After installing, changing, or debugging the MCP path, run
   `python3 tools/cocoindex_agent_search.py mcp-smoke`; registration alone is
   not proof until stdio `initialize`, raw JSON-RPC protocol probes,
   and `list_tools` succeed. `mcp-smoke --include-search` may only use an
   already-recorded active index and must refuse to build or refresh one.
5. Use `python3 tools/cocoindex_agent_search.py install` directly only when MCP
   is unavailable or a CLI-only workflow is intentionally being prepared.
6. Use `python3 tools/cocoindex_agent_search.py search --limit 5 "<query>"` only
   after an explicit `index` has recorded an active index for this repo. Use
   `--index-if-missing` only when cold indexing is intentional and safe, then
   confirm the returned files with `rg` in the real repo.
   `prepare`, `index`, `search --index-if-missing`, `search --refresh`, and
   `benchmark` reject dirty or untracked worktrees unless the caller uses the
   explicit dirty flag for that disk-heavy operation.
7. If the wrapper reports a cold semantic index, tell the user once in one
   short sentence that the first search can take several minutes and later
   searches reuse the external cache.
8. Use `--path '<glob>'` only after the first pass identifies a likely subtree.
9. Run
   `python3 tools/cocoindex_agent_search.py benchmark --cases <cases.json>`
   when changing this workflow or after a major CocoIndex Code release.
10. Skip CocoIndex when an exact string, symbol, or small `rg` result is already
   likely; the hybrid path is for broad routing where candidate output would be
   large.

## Artifact rules

- Never run `ccc init` directly in the live checkout.
- Keep pinned `cocoindex-code[full]==0.2.32`; do not use a floating version.
- The wrapper indexes an external mirror of Git-visible non-ignored files.
  Settings, runtime files, model caches, and SQLite databases stay under XDG
  paths or `AGENT_COCOINDEX_HOME`, never under the live repository.
- Use exactly one host install per user account: the shared pinned venv lives
  under `AGENT_COCOINDEX_HOME` or the XDG data default. Each repository content
  digest gets a separate mirror, database directory, and daemon runtime
  directory under that one install so parallel agents on different repositories
  do not share project locks or databases.
- The wrapper reuses a daemon that already exists for the same repository
  runtime, starts one only when needed, and stops only daemons it started itself.
  Do not leave wrapper-owned `ccc run-daemon` processes running after CLI or MCP
  verification.
- Launch commands from the target Git repository root, or set
  `AGENT_COCOINDEX_REPO` to that root for clients that cannot control their
  working directory. Do not put installation-specific paths in committed files.
- Do not add, commit, or normalize `.cocoindex_code/` in the repository.
- Do not index real `.env` files; only example env contracts are allowed.
- The mirror asks CocoIndex Code 0.2.32 to include every Git-visible mirrored
  file pattern. CocoIndex indexes text-decodable content and safely skips
  undecodable binary files; do not claim semantic search inside arbitrary binary
  formats.
- Do not add repo-specific language rewrites or file-type exclusions without a
  tested, documented configuration contract.
- Avoid `--lang` for mixed-language or container formats such as templates,
  notebooks, Markdown with code blocks, or generated manifests unless the exact
  language filter is known to be safe for that file type.
- Treat semantic output as routing only; read and edit real repo files after
  exact confirmation.

## MCP

- Upstream CocoIndex Code documents the native contract as
  `pipx install 'cocoindex-code[full]'` plus
  `codex mcp add cocoindex-code -- ccc mcp`. This repo intentionally registers
  `tools/cocoindex_agent_search.py mcp` instead so agents get the same
  CocoIndex server while keeping `.cocoindex_code/`, runtime files, model
  caches, and per-repo databases outside the live checkout.
- Do not copy the upstream `ccc` skill into this repository. Keep this file as
  the single repository-local CocoIndex skill surface and generate MCP
  configuration from `tools/cocoindex_agent_search.py mcp-config` when another
  MCP-capable agent needs explicit stdio settings.
- Generic MCP: first check whether a server or tool named `cocoindex-code` is
  already configured. If it is absent, run
  `python3 tools/cocoindex_agent_search.py mcp-config` and map the printed
  stdio `command`, `args`, `env`, `startup_timeout_sec`, and `tool_timeout_sec`
  into the MCP-capable client's native config. The client must launch it from
  the target Git repository root, or use `mcp-config --pin-repo` only for a
  workspace-scoped static config. Do not claim compatibility with an agent that
  cannot run local stdio MCP servers, set environment variables, and allow long
  tool timeouts.
- Codex: run `python3 tools/cocoindex_agent_search.py mcp-install`. It registers
  one MCP server named `cocoindex-code` with a host-local workspace-pinned
  wrapper path and `AGENT_COCOINDEX_REPO`, repairs a stale same-name entry
  instead of adding duplicates, and writes explicit per-server startup/tool
  timeouts. The MCP server must answer
  initialize and tool-list requests without installing, mirroring, launching the
  daemon, or indexing; MCP search may only query an existing active index.
  Then run `python3 tools/cocoindex_agent_search.py mcp-smoke` from the target
  repo root to prove the configured server completes the MCP handshake. Use
  `mcp-smoke --include-search` only for an explicit end-to-end search smoke
  against an existing active index; it must refuse to build or refresh one.

## Stop signs

- Do not use this for precise string, symbol, or scanner-count checks; use `rg`
  or the repo scanner tools.
- Do not run CocoIndex plus `rg` by default for narrow queries; benchmark it
  first if the token budget benefit is unclear.
- Do not expand context just because semantic search returned results. Open the
  smallest confirmed file set and follow `context-budget`.
