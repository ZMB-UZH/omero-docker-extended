# CocoIndex Code Agent Benchmark 2026-04-27

One-off developer note. Update this document only on explicit maintainer
request or after a major CocoIndex Code release.

## Scope

This benchmark validates the repository's hybrid AI-agent search workflow:

1. Check for an MCP server or tool named `cocoindex-code`.
2. Use CocoIndex Code only for broad semantic routing.
3. Confirm exact symbols, strings, and edits with `rg` in the real checkout.
4. Use `rg` only when the query is already exact or expected to return a small
   result set.

The goal is lower context volume for broad navigation without replacing exact
search.

## Package Evidence

- Package: `cocoindex-code[full]==0.2.31`
- PyPI latest observed on 2026-04-27: `0.2.31`
- Wheel: `cocoindex_code-0.2.31-py3-none-any.whl`
- Wheel upload: `2026-04-27T01:39:06.530423Z`
- Wheel SHA256:
  `bcaf341035901bf8d66491ce1a72d97d60e1ce6147d1187f1a2ee9377b189cf7`
- Source upload: `2026-04-27T01:39:08.081088Z`
- Source SHA256:
  `19bf4cbb7c94801b1108ae742fccefc73b103b99ba4668868dbba10e3fb68b02`
- Installed dependency freeze: `110` packages, SHA256
  `eb5c056e5e01cd0bb35e32571cfe425c665512e4ff2db67f05717779e8db26f1`
- Sources: [PyPI](https://pypi.org/project/cocoindex-code/0.2.31/),
  [GitHub](https://github.com/cocoindex-io/cocoindex-code)

## Commands

```bash
python3 tools/cocoindex_agent_search.py install
python3 tools/cocoindex_agent_search.py mcp-config
python3 tools/cocoindex_agent_search.py mcp-install
codex mcp get cocoindex-code
python3 tools/cocoindex_agent_search.py benchmark \
  --cases docs/reference/cocoindex-code-agent-benchmark-2026-04-27-cases.json \
  --output /tmp/omero-cocoindex-benchmark-2026-04-27-final.json
```

The benchmark runner excluded its own cases file from both the CocoIndex mirror
and the `rg` baseline:
`docs/reference/cocoindex-code-agent-benchmark-2026-04-27-cases.json`.

## Host Layout Verified

- Shared host root: `${XDG_DATA_HOME:-~/.local/share}/agent-cocoindex-code`
- Shared venv:
  `agent-cocoindex-code/venv/cocoindex-code-0.2.31`
- Per-repository mirror:
  `agent-cocoindex-code/mirrors/<content-digest>/repo`
- Per-repository database:
  `agent-cocoindex-code/db/<content-digest>`
- Per-repository daemon runtime:
  `agent-cocoindex-code/runtime/<content-digest>`
- Live checkout artifact rule: no `.cocoindex_code/` is written into the repo.

Codex MCP recognition was verified: `codex mcp get cocoindex-code` returned an
enabled stdio server using `/usr/bin/python3` and
`/opt/omero/tools/cocoindex_agent_search.py mcp`. A second `mcp-install`
reported the server already configured, and `codex mcp list` showed exactly one
`cocoindex-code` entry.

## Final Benchmark Result

- Repo head: `9cd71a748e12eccd2cbbb0879b6cc769edddfc3b`
- Mirror digest: `f8c06a1040beceb3c665af8e7d1652ae`
- SQLite DB size: `35,749,888` bytes
- Cold index time: `217.67` seconds
- Cases: `10`
- Broad `rg` output: `282,693` characters across `279` unique file mentions
- CocoIndex routing output: `43,683` characters across `34` unique file mentions
- Focused `rg` on CocoIndex candidates: `47,959` characters
- Hybrid total output: `91,642` characters
- Hybrid reduction vs broad `rg`: `67.6%`
- CocoIndex-only routing reduction vs broad `rg`: `84.5%`
- Candidate-file reduction: `87.8%`
- Top-5 expected-file hits: CocoIndex `8/10`, broad `rg` `5/10`
- Average command time after indexing: CocoIndex `366.2 ms`, broad `rg`
  `8.1 ms`, focused candidate `rg` `5.2 ms`

For the seven broad cases where broad `rg` produced at least `10,000`
characters, hybrid output was `72,887` characters versus `269,569` characters
for broad `rg`, a `73.0%` reduction. The hybrid workflow is therefore justified
for broad routing. It is not justified for already-narrow exact searches; in
those cases agents must use `rg` directly.

## Per-Case Summary

| Case | Coco rank | broad `rg` rank | Hybrid chars | broad `rg` chars |
| --- | ---: | ---: | ---: | ---: |
| `logging_loki_timeout` | 1 | 3 | 6,381 | 12,106 |
| `redis_cache_defaults` | 1 | 1 | 5,279 | 1,818 |
| `dropbox_bootstrap_readiness` | 3 | 2 | 7,091 | 5,628 |
| `managed_repo_shared_prefix` | 1 | 14 | 8,578 | 30,837 |
| `env_safety_guard` | miss | 2 | 11,559 | 28,581 |
| `upload_tmp_managedrepo` | 1 | 8 | 6,325 | 63,948 |
| `enhanced_search_indexing` | miss | 10 | 9,304 | 40,108 |
| `scanner_inventory_deepsource` | 1 | 5 | 7,293 | 19,287 |
| `agent_context_caps` | 1 | 9 | 6,385 | 5,678 |
| `crowdsec_bridge_bouncer` | 1 | 2 | 23,447 | 74,702 |

## Decision

Keep CocoIndex Code as a broad-routing accelerator, not as an exact-search
replacement. Agents must check for the MCP server first, use CocoIndex only
when the query is broad enough to avoid large `rg` output, and always validate
with exact `rg` and file reads before editing.
