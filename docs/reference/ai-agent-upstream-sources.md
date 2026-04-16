# AI Agent Upstream Sources

This document records the pinned upstream AI-agent material vendored into this repository.

## ECC snapshot

- Upstream repository: `affaan-m/everything-claude-code`
- Release tag: `v1.10.0`
- Release commit: `846ffb75da9a5f4e677d927af1ad4a1951652267`
- Local vendor path: `third_party/ecc-v1.10.0/`
- License: MIT (`third_party/ecc-v1.10.0/LICENSE`)

## Selected upstream skills

The vendor snapshot includes only the ECC skills that map cleanly onto this repo's Python, Django, Docker, deployment, verification, security, and research workflows.

| Local skill or surface | Pinned upstream source |
| --- | --- |
| `search-first` | `third_party/ecc-v1.10.0/skills/search-first/SKILL.md` |
| `documentation-lookup` | `third_party/ecc-v1.10.0/skills/documentation-lookup/SKILL.md` |
| `verification-loop` | `third_party/ecc-v1.10.0/skills/verification-loop/SKILL.md` |
| `security-review` | `third_party/ecc-v1.10.0/skills/security-review/SKILL.md` |
| `python-patterns` | `third_party/ecc-v1.10.0/skills/python-patterns/SKILL.md` |
| `python-testing` | `third_party/ecc-v1.10.0/skills/python-testing/SKILL.md` |
| `django-patterns` | `third_party/ecc-v1.10.0/skills/django-patterns/SKILL.md` |
| `django-security` | `third_party/ecc-v1.10.0/skills/django-security/SKILL.md` |
| `django-verification` | `third_party/ecc-v1.10.0/skills/django-verification/SKILL.md` |
| `docker-patterns` | `third_party/ecc-v1.10.0/skills/docker-patterns/SKILL.md` |
| `deployment-patterns` | `third_party/ecc-v1.10.0/skills/deployment-patterns/SKILL.md` |
| `postgres-patterns` | `third_party/ecc-v1.10.0/skills/postgres-patterns/SKILL.md` |
| `tdd-workflow` | `third_party/ecc-v1.10.0/skills/tdd-workflow/SKILL.md` |
| `ai-regression-testing` | `third_party/ecc-v1.10.0/skills/ai-regression-testing/SKILL.md` |
| `context-budget` | `third_party/ecc-v1.10.0/skills/context-budget/SKILL.md` |

## Local overlay rule

The files under `.agents/skills/` are the active repo-specific overlays. They are intentionally shorter than the upstream ECC files and route agents into this repo's actual docs, tests, env contracts, and security rules.

Do not replace the local overlays with the upstream files verbatim unless the repo's own workflow contracts have been reviewed and preserved.

## caveman reference snapshot

- Repository: `JuliusBrussee/caveman`
- Reviewed release notes: `v1.5.1` and `v1.6.0` for the upgrade path from the prior `v1.5.0` pin
- caveman release tag: `v1.6.0`
- caveman release commit: `c2ed24b3e5d412cd0c25197b2bc9af587621fd99`
- caveman vendor path: `third_party/caveman-v1.6.0/`
- License: MIT (`third_party/caveman-v1.6.0/LICENSE`)
- Vendored files: `LICENSE` and `skills/caveman/SKILL.md` only. Upstream README/install docs stay upstream-only so repo docs remain standard prose.
- Selected upstream reference: `third_party/caveman-v1.6.0/skills/caveman/SKILL.md`
- Integration rule: the active repo surface is `.agents/skills/caveman/`; it
  is an all-agent, opt-in overlay for lower-token replies and internal AI
  prompting only. Upstream hooks, plugin auto-loading, `.codex` hook config,
  natural-language auto-activation, `CAVEMAN_DEFAULT_MODE`/config resolution,
  `off`, `caveman-help`, and compression-tool context rewriting stay disabled,
  and the local overlay starts at lite compression without changing routing,
  tool choice, verification scope, or uncertainty handling.
