# AI Agent Upstream Sources

This document records the pinned upstream AI Agent material vendored into this repository.

## ECC snapshot

- Upstream repository: `affaan-m/everything-claude-code`
- Release tag: `v2.0.0`
- Release commit: `8ad4151095e453301ce0e50374103bcd8f50ded2`
- Local vendor path: `third_party/ecc-v2.0.0/`
- License: MIT (`third_party/ecc-v2.0.0/LICENSE`)
- Vendored files: `LICENSE`, the selected skill files listed below, and the
  security review's referenced cloud checklist only. Upstream README,
  installers, hooks, and cross-platform runtime documentation remain upstream
  so the repository's Linux-only operating contract stays unambiguous.
- DeepSource-only `skipcq` annotation lines may appear in selected vendored
  skill files to suppress false-positive secret findings in instructional
  examples. `tools/verify_agent_skill_provenance.py` strips only those
  standalone scanner annotations before comparing the vendored text with the
  pinned upstream release.
- Latest upstream observed and reviewed on 2026-10-07: `v2.2.3`. Complete
  recursive trees and exact source diffs show six selected files changed since
  `v2.2.1`: discovery descriptions, an optional persisted-byte diagnostic, a
  parameterized-SQL example, and a generic TDD artifact path. Existing overlays
  already preserve SQL parameterization and distinguish bytes from billed tokens;
  they retain this repo's verification and private-evidence paths. No upstream
  installer or harness runtime is imported. The earlier `v2.0.0` to `v2.2.0` comparison found metadata changes across the selected
  skills and body changes in five of them. The repo overlays adopt applicable
  installer isolation, plan-input validation, and failure-preserving command
  guidance. Keep the reproducible `v2.0.0` reference snapshot: generic MIME
  allowlists would exclude supported scientific formats, and Zod examples
  do not apply to this Python stack. Do not infer unchanged files from a
  truncated GitHub comparison response. The repo imports no ECC control pane, hooks,
  commands, connectors, session adapters, MCP configuration, worktree service,
  or multi-agent orchestration; the repo's single-session, host-agnostic, and
  Linux-only workflow contracts remain authoritative.

## Selected upstream skills

The vendor snapshot includes only the ECC skills that map cleanly onto this repo's Python, Django, Docker, deployment, verification, security, and research workflows.

| Local skill or surface | Pinned upstream source |
| --- | --- |
| `search-first` | `third_party/ecc-v2.0.0/skills/search-first/SKILL.md` |
| `documentation-lookup` | `third_party/ecc-v2.0.0/skills/documentation-lookup/SKILL.md` |
| `verification-loop` | `third_party/ecc-v2.0.0/skills/verification-loop/SKILL.md` |
| `security-review` | `third_party/ecc-v2.0.0/skills/security-review/SKILL.md` |
| `python-patterns` | `third_party/ecc-v2.0.0/skills/python-patterns/SKILL.md` |
| `python-testing` | `third_party/ecc-v2.0.0/skills/python-testing/SKILL.md` |
| `django-patterns` | `third_party/ecc-v2.0.0/skills/django-patterns/SKILL.md` |
| `django-security` | `third_party/ecc-v2.0.0/skills/django-security/SKILL.md` |
| `django-verification` | `third_party/ecc-v2.0.0/skills/django-verification/SKILL.md` |
| `docker-patterns` | `third_party/ecc-v2.0.0/skills/docker-patterns/SKILL.md` |
| `deployment-patterns` | `third_party/ecc-v2.0.0/skills/deployment-patterns/SKILL.md` |
| `postgres-patterns` | `third_party/ecc-v2.0.0/skills/postgres-patterns/SKILL.md` |
| `tdd-workflow` | `third_party/ecc-v2.0.0/skills/tdd-workflow/SKILL.md` |
| `ai-regression-testing` | `third_party/ecc-v2.0.0/skills/ai-regression-testing/SKILL.md` |
| `context-budget` | `third_party/ecc-v2.0.0/skills/context-budget/SKILL.md` |

## CocoIndex Code skill

- Repository: `cocoindex-io/cocoindex-code`
- Upstream native installation command:
  `pipx install 'cocoindex-code[full]'`
- Verified upstream release tag:
  `v0.2.42` at `6bb17d001649fc0948a7300c2ce847b6218d174c`
- Local path: `.agents/skills/cocoindex-code-search/`
- Integration rule: keep one repository-local CocoIndex workflow and generate
  MCP configuration with `tools/cocoindex_agent_search.py mcp-config` when a
  client needs explicit stdio settings. Do not copy the upstream `ccc` skill
  into root dot-directories or per-agent skill directories.

## Crawl4AI research

- Source: [unclecode/crawl4ai 0.9.4](https://github.com/unclecode/crawl4ai/tree/v0.9.4).
- Independent local implementation: `tools/crawl4ai_research.py`; mandatory
  cross-agent routing: `.agents/skills/crawl4ai-research/`.
- Packages are hash-pinned in `.github/requirements/crawl4ai.txt` and installed
  only into an external Linux developer environment. No code or host-specific
  configuration is copied from other repositories.
- [Research operations](ai-agent-web-research-stack.md) documents attribution,
  qualified behavior, dependencies and known limitations. The upstream license
  has an additional attribution requirement; do not call it unmodified Apache 2.0.

## Karpathy baseline

- Repository: `forrestchang/andrej-karpathy-skills`
- Pinned latest commit: `2c606141936f1eeef17fa3043a72095b4765b9c2`
- Local surface: compact agent-neutral baseline in `AGENTS.md`; Claude,
  Gemini, Copilot, and Cursor adapters point back to that section.
- Integration rule: keep the four principles centralized to reduce duplicated
  always-on context while preserving the repo-specific single-session,
  security, environment, and verification rules.
- `EXAMPLES.md` rule: keep upstream examples as optional rationale for
  maintaining the baseline only. Do not load them by default or let generic
  examples override OMERO-specific rules.

## Local overlay rule

The files under `.agents/skills/` are the active repo-specific overlays. They are intentionally shorter than the upstream ECC files and route agents into this repo's actual docs, tests, env contracts, and security rules.

Do not replace the local overlays with the upstream files verbatim unless the repo's own workflow contracts have been reviewed and preserved.

## caveman reference snapshot

- Repository: `JuliusBrussee/caveman`
- Reviewed release notes: `v1.5.1` through `v1.9.1`, `v2.0.0`, `v2.1.0`, and
  `v2.2.0`; subsequent reviews cover `v2.7.0` and `v3.1.0`.
- caveman release tag: `v2.2.0`
- caveman release commit: `9aa63945a349bef17206540650db48c30fafbdf2`
- Latest upstream observed and reviewed on 2026-10-07: `v3.1.0`. Its skill split
  and model-specific length evaluations do not justify automatic stronger
  compression or a repo-wide token-savings claim. The existing overlay already
  preserves exact evidence, normal persisted prose, and host-required updates;
  the new upstream mode migration and session hooks remain disabled. The overlay
  adopts explicit reply-language precedence and removes unmeasured savings
  claims. The `v2.2.0` vendor snapshot remains a reproducible historical
  reference, not a claim of the latest installed runtime. Installer, hook,
  natural-language activation, compression-tool, MCP, proxy, credential-routing,
  stats, and cavecrew surfaces remain disabled.
- caveman vendor path: `third_party/caveman-v2.2.0/`
- License: MIT (`third_party/caveman-v2.2.0/LICENSE`); the upstream license
  scope note keeps engine-linked components under BSL-1.1, and none are vendored.
- Vendored files: `LICENSE` and `skills/caveman/SKILL.md` only. Upstream README/install docs stay upstream-only so repo docs remain standard prose.
- Selected upstream reference: `third_party/caveman-v2.2.0/skills/caveman/SKILL.md`
- Integration rule: the active repo surface is `.agents/skills/caveman/`; it
  is an all-agent, mandatory lite overlay for lower-token internal AI
  prompting only. Upstream hooks, plugin auto-loading, `.codex` hook config,
  natural-language auto-activation, `CAVEMAN_DEFAULT_MODE`/config resolution,
  `off`, `caveman-help`, compression-tool context rewriting, stats/statusline
  scripts, `caveman-shrink`, `caveman-init`, cavecrew subagents, and smart
  installer side effects stay disabled. The local overlay starts at lite
  compression, preserves the upstream v2.2.0 language, negation, numeric,
  code-symbol, persisted-prose, no-invented-abbreviation, no-self-reference,
  destructive-command, and ambiguity guards,
  and never changes routing, tool choice, verification scope, or uncertainty
  handling.
