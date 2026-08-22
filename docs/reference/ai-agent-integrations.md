# AI Agent Integrations

This document defines the repository's complete cross-agent instruction surface.

The goal is to support the major documented instruction systems without changing runtime code, Docker behavior, or CI logic.

## Precedence

Apply guidance in this order:

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-runtime-playbook.md`
4. `docs/reference/ai-agent-security-prevention-playbook.md`
5. `docs/reference/code-scanning-resolved-findings.md`
6. `docs/operations/code-scanning.md`
7. `docs/reference/ai-agent-skills.md` and `.agents/skills/`
8. harness-specific adapter files

Harness-specific files are additive. They must not override the repo's security
read order, single-session rule, current-remote-default-branch development rule,
environment-driven configuration model, or split-pytest policy. The
single-session rule prohibits background agents, subagents, spawned agents,
delegated agents, and any separate agent session except for on-demand Codex
Security vulnerability scanning that the user explicitly authorizes and the
loaded security skill requires.

## Karpathy baseline

`AGENTS.md` carries a compact, pinned Karpathy agent baseline sourced from
`forrestchang/andrej-karpathy-skills@2c606141936f1eeef17fa3043a72095b4765b9c2`.
It is centralized in the universal entrypoint so Claude, Gemini, Copilot, and
Cursor inherit the same four-principle behavior without duplicating full prompt
text in each adapter.

## AI commit identity

Every AI-facing adapter inherits the commit-identity rule from `AGENTS.md`. Any AI tool that creates or rewrites a commit object must set both author and committer to `AI Agent <>`, using an empty email field. Any AI co-author trailer must be `Co-authored-by: AI Agent` with no email.

AI tools must not infer identity from global Git config, prior commits, GitHub accounts, host users, or human operators. If the active tool cannot create that exact empty-email identity or trailer, or would use a profile-mapped AI/tool address, it must stop before committing.

Identity cleanup must check fresh branch-head authors, committers, `Co-authored-by` trailers, and GitHub anonymous contributors (`contributors?anon=1`); a normal contributors check without anonymous entries is incomplete. GitHub PR-head refs are managed snapshots and must be reported separately from current branch heads.

Non-AI commit identities must be real human GitHub identities or actual human author names with real email addresses. Host usernames, computer names, local account names, placeholder domains, generated fake names, and fake emails are invalid commit identities.

## Default-branch development

Every AI-facing adapter inherits the default-branch rule from `AGENTS.md`. AI Agents must develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch, must resolve that branch from the remote instead of hard-coding `main`, and must not create feature branches, PR branches, temporary remote branches, or draft PRs for routine work.

## Supported instruction surfaces

| Harness or surface | Files in this repo | Purpose |
| --- | --- | --- |
| Universal | `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, `docs/reference/ai-agent-runtime-playbook.md`, `.agents/skills/`, `docs/reference/ai-agent-skills.md` | shared repo contract, narrow routing, deep runtime procedure, and reusable workflows |
| Claude Code | `CLAUDE.md` | Claude-specific session guidance |
| GitHub Copilot | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.agents/skills/` | repo-wide and path-specific Copilot guidance |
| Cursor | `.cursor/rules/*.mdc`, `AGENTS.md`, `.agents/skills/` | rule-based Cursor context plus shared skills |
| Gemini CLI | `GEMINI.md` | project-level Gemini context file |

## ECC integration model

This repository does not run ECC's installer directly against the working tree.

Instead it uses:

- a pinned upstream snapshot under `third_party/ecc-v2.0.0/`
- repo-specific overlays in `.agents/skills/`
- native adapter files for each harness

This avoids importing ECC hooks, commands, multi-agent orchestration, or platform configs that would disturb the repo's existing workflows.

## caveman integration model

This repository also carries an opt-in `caveman` communication overlay:

- vendored upstream prompt reference material under `third_party/caveman-v2.2.0/`
- a repo-local overlay at `.agents/skills/caveman/`
- shared-skill catalog routing in `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, and `.cursor/rules/00-omero-core.mdc`

Compression stays opt-in and quality-first:

- use `context-budget` to reduce input/context cost first
- use `caveman` only when the user explicitly asks for lower-token replies
- expose `caveman` through the same shared `.agents/skills/` catalog as every other skill; do not make it Codex-only
- start at lite compression in this repo and return to normal detail whenever safety, sequencing, or ambiguity matters
- keep `caveman` limited to internal AI communication and prompting; repository docs, comments, docstrings, function descriptions, commit messages, and user-facing text stay in normal prose
- keep routing, tool use, verification scope, and uncertainty handling identical to normal mode

Upstream `caveman` `v2.2.0` preserves the measured 65% average output-token
reduction baseline, adds negation, number, unit, grammar, persisted-prose, and
destructive-command clarity guards, rejects invented abbreviations and causal
arrows that do not save tokens, and forbids self-referential mode narration.
It also includes hooks, stats, installers,
`caveman-shrink`, `caveman-init`, and cavecrew orchestration. This repo imports
only the prompt-reference clarity lessons; activation, hook, installer, MCP,
subagent, statusline, stats, configuration, and context-rewrite surfaces remain
disabled.

The upstream `caveman` hooks, plugin auto-loading, `.codex` hook config, natural-language auto-activation, smart installer, cavecrew subagents, `caveman-shrink`, stats/statusline scripts, and compression-tool context rewriting are not activated in this repo.

## What is intentionally imported

- engineering skills relevant to this repo: Python, Django, testing, verification, Docker, deployment, PostgreSQL, security, research, and context-budget control
- the opt-in `caveman` overlay for lower-token replies when the user explicitly requests terseness
- the compact, pinned Karpathy baseline in `AGENTS.md`
- ECC provenance and license material for the selected upstream skills
- harness-specific adapters that route agents into the repo's existing docs and tests

## What is intentionally not imported

- ECC hook runtime
- ECC command shims
- ECC multi-agent orchestration, delegated loops, and separate agent sessions
- ECC MCP server configs
- `caveman` hook runtime, plugin auto-loading, `.codex` hook config, natural-language auto-activation, per-turn reinforcement, default-mode config resolution, `off`, `caveman-help`, smart installer, cavecrew subagents, `caveman-shrink`, stats/statusline scripts, `caveman-init`, and `/compress` context-rewrite automation
- unrelated domain skills such as business-content, media-generation, or social-distribution

## Token and speed guidance

The adapter set is designed to improve accuracy first, then reduce wasted context:

- route agents into `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, and the nearest domain doc before broad repo reads
- keep the routing doc's numeric caps CI-validated so first-pass reads, refine loops, and escalation stay bounded
- keep the Karpathy baseline centralized in `AGENTS.md` instead of duplicating it across adapters
- expose reusable workflows through `.agents/skills/`
- prefer `context-budget` for input reduction and the opt-in `caveman` overlay for output reduction
- add path-specific Copilot and Cursor guidance so agents do not rediscover the same rules every time
- keep skills in `.agents/skills/` as the all-agent source of truth; adapter files may point to the catalog but should not duplicate full skill bodies
- keep all workflows single-session; skills and adapters must not introduce
  delegated or spawned agent work except for explicitly authorized, on-demand
  Codex Security scanning when the loaded security skill requires it
- keep `AGENTS.md`, Claude, Gemini, Copilot, and Cursor core rules concise so they do not bloat always-on context

## CocoIndex Code routing

`.agents/skills/cocoindex-code-search/` defines the mandatory semantic routing
gate for broad repo navigation in every agent harness. Agents must first
check whether an MCP server or tool named `cocoindex-code` is already available,
and only read setup or installation instructions when it is absent. Direct `rg`
comes first only for precise string, symbol, scanner-count, or already-small
searches. The wrapper installs the pinned `cocoindex-code[full]` package once per
host account under
`AGENT_COCOINDEX_HOME` or the XDG data default, then keeps each repository
content digest in its own external mirror, database directory, and daemon
runtime directory outside the live checkout. The wrapper reuses a matching
daemon when one is already running, starts one only when needed, and stops only
daemons it started itself so CLI and MCP checks do not leave stale
`ccc run-daemon` processes behind.

Agents must treat CocoIndex output as routing only. Use it to find a small
candidate file set, then confirm exact strings, symbols, scanner findings, and
edits with `rg`, file reads, and tests in the real checkout.

When CocoIndex reports a cold semantic index, agents should tell the user once
in one short sentence that the first search can take several minutes and later
searches reuse the external cache. The wrapper configures CocoIndex Code 0.2.41
to include every Git-visible mirrored file pattern instead of upstream's
extension list. CocoIndex indexes text-decodable content and skips undecodable
binary files, so agents must not claim semantic search inside arbitrary binary
formats or add repo-specific language rewrites or file-type exclusions without a
tested, documented configuration contract.

Embedding-device selection remains automatic, so Sentence Transformers uses a
Linux-visible accelerator when supported and otherwise uses CPU. Operators can
request `cuda`, `mps`, `cpu`, or `auto` with the wrapper's `--device` option or
`AGENT_COCOINDEX_DEVICE`; explicit unavailable accelerators fail before an
index or query starts.

Upstream CocoIndex Code documents native MCP setup as installing the full
package and registering `ccc mcp` with the agent. This repo keeps that MCP
server contract but launches it through `tools/cocoindex_agent_search.py mcp`
so every MCP-capable agent can share one host install while keeping
`.cocoindex_code/`, model caches, runtime files, and SQLite databases out of
the live checkout. Do not copy the upstream `ccc` skill into per-agent
directories in this repository; adapter files should point to the single
`.agents/skills/cocoindex-code-search/` workflow instead.

MCP-capable clients can run
`python3 tools/cocoindex_agent_search.py mcp-config` for a generic stdio
configuration, then map the printed `command`, `args`, `env`,
`startup_timeout_sec`, and `tool_timeout_sec` into the client's native config.
The MCP client must launch the command from the target Git repository root or
set `AGENT_COCOINDEX_REPO` for a workspace-scoped static configuration. Do not
claim compatibility with clients that cannot run local stdio MCP servers, set
environment variables, and allow long tool timeouts. Codex can use
`python3 tools/cocoindex_agent_search.py mcp-install`, which registers or
repairs the same server name without duplicating it, writes a host-stable
launcher under `AGENT_COCOINDEX_HOME`, pins the target checkout with
`AGENT_COCOINDEX_REPO`, and writes explicit per-server startup/tool timeouts.
The MCP
server itself stays lightweight through initialize and tool-list requests. MCP
search may only query an existing active index; cold install, mirror, daemon,
and index work requires an explicit CLI command outside the MCP request path.
Mirror, index, refresh, and benchmark commands reject dirty or untracked
worktrees by default and require an explicit dirty flag for intentional
disk-heavy runs.
Before relying on MCP search for current local edits, refresh the external
index with `python3 tools/cocoindex_agent_search.py index --allow-dirty-index`
for an intentional dirty-worktree index or
`python3 tools/cocoindex_agent_search.py search --refresh "<query>"` on a clean
tree. MCP search itself never refreshes and can otherwise return
stale active-index text.
After any MCP install, config change, or launcher change, run
`python3 tools/cocoindex_agent_search.py mcp-smoke` from the target repo root;
the MCP path is not verified until stdio `initialize`, raw JSON-RPC protocol
probes, and `list_tools` succeed. Use `mcp-smoke --include-search` only for an
explicit end-to-end search smoke against an existing active index; it must
refuse to build or refresh one.

## Claude Code hooks

`.claude/settings.json` defines PostToolUse and PreToolUse hooks that automate rules from `AGENTS.md`:

| Event | Matcher | Action | Rule enforced |
| --- | --- | --- | --- |
| PostToolUse | Write\|Edit | Run `ruff check --fix` and `ruff format` on edited `.py` files | Ruff is the canonical Python formatter and lint gate |
| PostToolUse | Write\|Edit | Run `npx --yes markdownlint-cli2@0.23.1` on edited `.md` files | Validate Markdown with a pinned package instead of tracking the unpinned latest package |
| PreToolUse | Bash | Run `python3 tools/env_safety_guard.py check` before `docker compose` commands | Verify deployment env files are intact before compose operations |

These hooks are Claude Code-specific (other harnesses do not support hooks). The underlying rules are documented in `AGENTS.md` so all agents follow them regardless of automation.

## Maintenance rules

- Add new skills once in `.agents/skills/` and once in `docs/reference/ai-agent-skills.md`. Supported harnesses inherit new skills through the shared catalog; do not duplicate per-skill instructions into every harness adapter.
- Update `docs/index.md` when this surface changes.
- Update `docs/reference/ai-agent-upstream-sources.md` when the ECC snapshot, vendored `caveman` prompt references, or selected upstream skills change.
- For ECC-derived local skills, keep the repo overlay concise and point to the pinned upstream snapshot.
- Run `python3 tools/lint_docs_structure.py` and the AI-surface regression tests after changing any adapter or skill file.
