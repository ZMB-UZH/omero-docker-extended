---
name: cocoindex-code-search
description: Mandatory semantic routing for broad repository navigation; use exact rg for known symbols and keep all index state external.
origin: repo-local skill based on verified cocoindex-code 0.2.41 behavior
---

# CocoIndex Code Search

Use semantic output as routing only. Confirm paths, symbols, and behavior in
current source before editing. Exact strings, symbols, scanner counts, and
already-small scopes use `rg` directly without semantic-search overhead.

## Required workflow

1. Broad navigation is mandatory MCP-first: check for an MCP server or tool named
   `cocoindex-code`. Verify its repository binding; never trust another checkout's
   results or overwrite another repository's registration.
2. Query a current active index with a specific natural-language question and
   `limit=3` initially. Refine once using the discovered vocabulary and subtree;
   avoid loading duplicate chunks or all matching files. Escalate when evidence
   is insufficient, not just because more results exist.
3. MCP search itself never refreshes and can return stale active-index text.
   After relevant edits, explicitly run
   `python3 tools/cocoindex_agent_search.py index --allow-dirty-index`, or
   `python3 tools/cocoindex_agent_search.py search --refresh "<query>"` on a
   clean tree. Never infer current-source truth from an old index.
4. If MCP is absent, inspect `codex mcp get cocoindex-code` and its
   `AGENT_COCOINDEX_REPO` binding once. Use repo-scoped CLI search when the
   registration belongs to another repo or the client cannot expose the tool:
   `python3 tools/cocoindex_agent_search.py search --limit 3 "<query>"`.
5. If no active index exists, check disk headroom/system load, then explicitly
   run `python3 tools/cocoindex_agent_search.py index`. The first cold semantic
   index can take several minutes; tell the user once. Later searches reuse
   the external cache. Dirty/untracked trees require the explicit dirty flag.
   Never retry an unchanged missing-index, binding, or install failure.
6. Open only the smallest confirmed source/test set. Use `--path '<glob>'`
   after identifying a subtree; avoid `--lang` on mixed-language files unless
   proven safe. Follow `context-budget`; save complete evidence outside source.

If indexing is genuinely unavailable (access, resources, or tool failure), state
the limitation once and use bounded `rg` temporarily. Do not claim CocoIndex
ran successfully, discard relevant files, or block exact-file work on an index.

## State and quality boundaries

- Keep pinned `cocoindex-code[full]==0.2.41`; never run `ccc init` directly
  in the live checkout. Use one host install under XDG/`AGENT_COCOINDEX_HOME`.
- The wrapper indexes an external mirror of Git-visible non-ignored files.
  Per-repo content digests isolate mirrors, databases, runtime files, and locks.
  Settings, model caches, and `.cocoindex_code/` stay outside the live checkout.
  Never index real deployment env files; only example env contracts are allowed.
- Include every mirrored file pattern. CocoIndex indexes text-decodable content;
  binary formats are not semantically searchable. Do not add file-type
  exclusions or language rewrites without a tested configuration contract.
- Leave embedding-device selection automatic. Supported accelerators may be
  used; explicit unavailable GPUs must fail closed and CPU fallback must work.
- The wrapper uses the cached runtime's own isolated Python interpreter, never
  another interpreter's `site-packages`. It reuses existing daemons and stops
  only daemons it started itself. Do not leave wrapper-owned daemons running.

## Maintenance only

Read the CocoIndex section of `docs/reference/ai-agent-integrations.md` when
installing, changing the launcher/runtime, debugging MCP, or upgrading the tool.
Do not load installer procedures during ordinary successful searches.

- `mcp-install` registers one MCP server named `cocoindex-code` using a
  host-stable launcher and repository binding; it refuses other/unproven bindings.
  Use `mcp-config` for compatible stdio clients, `--pin-repo` only for a
  workspace-scoped static config. Never register a temporary clone's tool path.
- After MCP/launcher changes, run
  `python3 tools/cocoindex_agent_search.py mcp-smoke`: verify `initialize`,
  `list_tools`, and protocol probes. Add `--include-search` only with an
  existing active index. Handshake/search must never install, mirror, or index.
- Test CLI and MCP integration with matching and different supported host Python
  versions after runtime changes. Do not copy the upstream `ccc` skill here.
- Benchmark changed search workflows with
  `python3 tools/cocoindex_agent_search.py benchmark --cases <cases.json>`.
  Record expected-file recall, output bytes, and timing for both broad and exact
  cases. Do not call character counts model tokens or promise universal savings.
