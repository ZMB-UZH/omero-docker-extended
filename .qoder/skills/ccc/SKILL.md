---
name: ccc
description: "This skill should be used when code search is needed (whether explicitly requested or as part of completing a task), when indexing the codebase after changes, or when the user asks about ccc, cocoindex-code, or the codebase index. Trigger phrases include 'search the codebase', 'find code related to', 'update the index', 'ccc', 'cocoindex-code'."
origin: repo-local installed upstream CocoIndex Code skill with OMERO override
---

# ccc - Semantic Code Search & Indexing

`ccc` is the CLI for CocoIndex Code, providing semantic search over the current codebase and index management.

## OMERO Docker Extended override

When working in this repository, follow the repo-local `cocoindex-code-search`
skill first. Check for an already available MCP tool named `cocoindex-code`.
If it is absent, use `python3 tools/cocoindex_agent_search.py mcp-install`
for Codex or `python3 tools/cocoindex_agent_search.py mcp-config` for other
MCP-capable agents. Do not run `ccc init`, `ccc index`, `ccc search`, or
`ccc mcp` directly in the live checkout unless the user explicitly asks to use
upstream native project-local settings. The repo wrapper keeps
`.cocoindex_code/`, daemon state, caches, and per-repo databases outside the
live checkout while still exposing the upstream `ccc mcp` server behavior.

## Ownership

The agent owns the search lifecycle. Do not ask the user to initialize, index,
or search manually.

- **OMERO Docker Extended**: use `python3 tools/cocoindex_agent_search.py
  search`, `status`, `mcp-config`, `mcp-install`, and `mcp-smoke`. The wrapper
  handles install, external settings, indexing, daemon startup, and freshness.
- **Other projects or explicit native opt-in**: use the upstream native
  lifecycle. If `ccc search` or `ccc index` reports that the project is not
  initialized, run `ccc init`, then `ccc index`, then retry the original
  command. Refresh with `ccc index` or `ccc search --refresh` after significant
  code changes.
- **Installation**: If the OMERO wrapper or native `ccc` command is unavailable,
  use [management.md](references/management.md) for the matching installation
  path.

## Searching the Codebase

Inside this repository:

```bash
python3 tools/cocoindex_agent_search.py search --limit 5 "<query terms>"
```

For upstream native use outside this repository:

```bash
ccc search <query terms>
```

The query should describe the concept, functionality, or behavior to find, not exact code syntax. For example:

```bash
ccc search database connection pooling
ccc search user authentication flow
ccc search error handling retry logic
```

### Filtering Results

- **By language** (`--lang`, repeatable): restrict results to specific languages.

  ```bash
  python3 tools/cocoindex_agent_search.py search --lang python --lang markdown schema
  ccc search --lang python --lang markdown database schema
  ```

- **By path** (`--path`): restrict results to a glob pattern relative to project root. If omitted, defaults to the current working directory (only results under that subdirectory are returned).

  ```bash
  python3 tools/cocoindex_agent_search.py search --path 'src/api/*' validation
  ccc search --path 'src/api/*' request validation
  ```

### Pagination

Results default to the first page. To retrieve additional results:

```bash
python3 tools/cocoindex_agent_search.py search --offset 5 --limit 5 database schema
ccc search --offset 5 --limit 5 database schema
```

If all returned results look relevant, use `--offset` to fetch the next page — there are likely more useful matches beyond the first page.

### Working with Search Results

Search results include file paths and line ranges. To explore a result in more detail:

- Use the editor's built-in file reading capabilities (e.g., the `Read` tool) to load the matched file and read lines around the returned range for full context.
- When working in a terminal without a file-reading tool, use `sed -n '<start>,<end>p' <file>` to extract a specific line range.

## Settings

To view or edit embedding model configuration, include/exclude patterns, or language overrides, see [settings.md](references/settings.md).

## Management & Troubleshooting

For installation, initialization, daemon management, troubleshooting, and cleanup commands, see [management.md](references/management.md).
