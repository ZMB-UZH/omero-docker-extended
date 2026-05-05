# CocoIndex Code Agent Benchmark 2026-04-27

One-off developer note. Update this document only on explicit maintainer
request or after a major CocoIndex Code release.

## Scope

This benchmark validates the repository's hybrid AI Agent search workflow:

1. For broad repo navigation, treat the `cocoindex-code` MCP check as
   mandatory.
2. Use CocoIndex Code only for broad semantic routing.
3. Confirm exact symbols, strings, and edits with `rg` in the real checkout.
4. Use `rg` only when the query is already exact or expected to return a small
   result set.

The goal is lower context volume for broad navigation without replacing exact
search.

## Package Evidence

- Package: `cocoindex-code[full]==0.2.32`
- PyPI latest observed on 2026-05-05: `0.2.32`
- Wheel: `cocoindex_code-0.2.32-py3-none-any.whl`
- Wheel upload: `2026-04-27T07:19:43.737589Z`
- Wheel SHA256:
  `2749689bff4f1ac5bfa555c6ddaa1fe9055165c0e61184c819e6339eabf6a6f2`
- Source upload: `2026-04-27T07:19:45.269188Z`
- Source SHA256:
  `7844441f074bc5c304cb598d721dc0c6cd36fde904ab42a51e9be96488809108`
- Installed dependency freeze: `109` packages, SHA256
  `d88b2991f04845e3b9e43ae5b26b16077342e959eb3db99c59323a809c224002`
- Upstream `v0.2.31...v0.2.32` changes observed on 2026-05-05: Svelte
  and Vue support, plus Claude documentation cleanup.
- Open upstream MCP-related issues observed on 2026-05-05 include non-JSON stdio
  output and sqlite-vec extension-loading failures; this repo's raw `mcp-smoke`
  checks fail on non-JSON stdout, JSON-RPC error payloads, stale registration,
  and missing search tools so those classes surface before agents rely on MCP.
- Live 2026-05-05 verification found that wrapper-started `ccc run-daemon`
  processes can otherwise remain after index/search commands. The wrapper now
  reuses pre-existing daemons, records ownership of daemons it starts, and stops
  only those owned daemons after CLI and MCP operations.
- Sources: [PyPI 0.2.32](https://pypi.org/project/cocoindex-code/0.2.32/),
  [GitHub compare](https://github.com/cocoindex-io/cocoindex-code/compare/v0.2.31...v0.2.32),
  [GitHub issues](https://github.com/cocoindex-io/cocoindex-code/issues)

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
  `agent-cocoindex-code/venv/cocoindex-code-0.2.32`
- Per-repository mirror:
  `agent-cocoindex-code/mirrors/<content-digest>/repo`
- Per-repository database:
  `agent-cocoindex-code/db/<content-digest>`
- Per-repository daemon runtime:
  `agent-cocoindex-code/runtime/<content-digest>`
- Live checkout artifact rule: no `.cocoindex_code/` is written into the repo.

Codex MCP recognition was verified: `codex mcp get cocoindex-code` returned an
enabled stdio server using `python3`, an absolute workspace-pinned wrapper path,
and `AGENT_COCOINDEX_REPO` for the target checkout. A second `mcp-install`
reported the server already configured, and `codex mcp list` showed exactly one
`cocoindex-code` entry.

## Final Benchmark Result

- Benchmarked implementation base head:
  `b38099078a721ef97009d037aa3fca4a62f0006e`
- Mirror digest: `53755ced03293b2951a3a67e08026f5b`
- SQLite DB size: `57,577,472` bytes
- Cold index time: `862.90` seconds
- Cases: `10`
- Broad `rg` output: `315,974` characters across `287` unique file mentions
- CocoIndex routing output: `44,181` characters across `35` unique file mentions
- Focused `rg` on CocoIndex candidates: `47,200` characters
- Hybrid total output: `91,381` characters
- Hybrid reduction vs broad `rg`: `71.1%`
- CocoIndex-only routing reduction vs broad `rg`: `86.0%`
- Candidate-file reduction: `87.8%`
- Top-5 expected-file hits: CocoIndex `8/10`, broad `rg` `7/10`
- Average command time after indexing: CocoIndex `1,349.0 ms`, broad `rg`
  `17.6 ms`, focused candidate `rg` `6.1 ms`

For the seven broad cases where broad `rg` produced at least `10,000`
characters, hybrid output was `73,293` characters versus `301,163` characters
for broad `rg`, a `75.7%` reduction. The hybrid workflow is therefore justified
for broad routing. It is not justified for already-narrow exact searches; in
those cases agents must use `rg` directly.

## Per-Case Summary

| Case | Coco rank | broad `rg` rank | Hybrid chars | broad `rg` chars |
| --- | ---: | ---: | ---: | ---: |
| `logging_loki_timeout` | 1 | 2 | 8,731 | 13,817 |
| `redis_cache_defaults` | 1 | 1 | 5,063 | 2,212 |
| `dropbox_bootstrap_readiness` | 2 | 2 | 7,487 | 6,920 |
| `managed_repo_shared_prefix` | 1 | 4 | 9,118 | 31,462 |
| `env_safety_guard` | miss | 1 | 5,893 | 31,726 |
| `upload_tmp_managedrepo` | 1 | 5 | 6,325 | 70,659 |
| `enhanced_search_indexing` | miss | 20 | 9,304 | 44,511 |
| `scanner_inventory_deepsource` | 1 | 12 | 9,063 | 21,026 |
| `agent_context_caps` | 1 | 1 | 5,538 | 5,679 |
| `crowdsec_bridge_bouncer` | 1 | 9 | 24,859 | 87,962 |

## Decision

Keep CocoIndex Code as the mandatory broad-routing gate, not as an exact-search
replacement. Agents must check for the MCP server first, use CocoIndex only when
the query is broad enough to avoid large `rg` output, and always validate with
exact `rg` and file reads before editing.
