# CocoIndex Code Agent Benchmark 2026-04-27

One-off developer note. Update this document only on explicit maintainer
request or after a major CocoIndex Code release.

## 2026-08-22 Validation Refresh

- Validated `cocoindex-code[full]==0.2.41` with stdio MCP initialization,
  tool-listing, four protocol-version probes, and the 10-case routing benchmark.
- The refreshed semantic pass placed an expected file in the top five for 8 of
  10 cases versus 5 of 10 for broad `rg`, while reducing semantic candidate
  output to 43,755 characters versus 331,108 broad-search characters.
- The default embedding-device setting remains automatic. The wrapper now also
  validates intentional `cuda`, `mps`, `cpu`, and `auto` overrides before use.
- The detailed package hashes and benchmark tables below remain the historical
  baseline for the original 2026-04-27 measurement.

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

- Package: `cocoindex-code[full]==0.2.37`
- PyPI latest observed on 2026-06-27: `0.2.37`
- Wheel: `cocoindex_code-0.2.37-py3-none-any.whl`
- Wheel upload: `2026-06-23T05:19:05.661342Z`
- Wheel SHA256:
  `9510e2810fcec5cfe9c9fb42e42acb9910155d5b5de0d7514bfa42daeb21b9ba`
- Source upload: `2026-06-23T05:19:07.247704Z`
- Source SHA256:
  `089888f455f71bfcdef6426150ce7bbbb3ff067b4448a6aef943152e38b4b214`
- Installed dependency freeze: `110` packages, SHA256
  `460ab6b92d3f0ab2c8920eb03268bcb78e282598e4562bd9b5be3f554e85d9bf`
- Upstream `v0.2.36...v0.2.37` changes observed on 2026-06-27: added
  `ccc grep` structural code search. Local wrapper behavior remains pinned and
  routing-only; exact edits still require `rg`/file-read validation in the live
  checkout.
- Open upstream MCP-related issues observed on 2026-05-05 include non-JSON stdio
  output and sqlite-vec extension-loading failures; this repo's raw `mcp-smoke`
  checks fail on non-JSON stdout, JSON-RPC error payloads, stale registration,
  and missing search tools so those classes surface before agents rely on MCP.
- Live 2026-05-05 verification found that wrapper-started `ccc run-daemon`
  processes can otherwise remain after index/search commands. The wrapper now
  reuses pre-existing daemons, records ownership of daemons it starts, and stops
  only those owned daemons after CLI and MCP operations.
- Sources: [PyPI 0.2.37](https://pypi.org/project/cocoindex-code/0.2.37/),
  [GitHub release 0.2.37](https://github.com/cocoindex-io/cocoindex-code/releases/tag/v0.2.37),
  [GitHub compare](https://github.com/cocoindex-io/cocoindex-code/compare/v0.2.36...v0.2.37),
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
  `agent-cocoindex-code/venv/cocoindex-code-0.2.37`
- Codex launcher:
  `agent-cocoindex-code/bin/cocoindex-code-mcp`
- Per-repository mirror:
  `agent-cocoindex-code/mirrors/<content-digest>/repo`
- Per-repository database:
  `agent-cocoindex-code/db/<content-digest>`
- Per-repository daemon runtime:
  `agent-cocoindex-code/runtime/<content-digest>`
- Live checkout artifact rule: no `.cocoindex_code/` is written into the repo.

Codex MCP recognition was verified: `codex mcp get cocoindex-code` returned an
enabled stdio server using the host-stable
`agent-cocoindex-code/bin/cocoindex-code-mcp` launcher and
`AGENT_COCOINDEX_REPO` for the target checkout. `mcp-install` repaired a stale
temporary-clone registration, and `codex mcp list` showed exactly one
`cocoindex-code` entry. Direct stdio probing through that launcher negotiated
protocol `2025-06-18` and listed the `search` tool without building or
refreshing an index.

## Final Benchmark Result

- Benchmark result below predates the `0.2.37` wrapper refresh and remains a
  historical routing benchmark, not a fresh benchmark of `0.2.37`.
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
