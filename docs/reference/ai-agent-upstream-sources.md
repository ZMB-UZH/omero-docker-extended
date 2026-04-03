# AI Agent Upstream Sources

This document records the pinned upstream AI-agent material vendored into this repository.

## ECC snapshot

- Upstream repository: `affaan-m/everything-claude-code`
- Release tag: `v1.9.0`
- Release commit: `29277ac273f294fd4804c35e43af9c8a5fc5ba9d`
- Local vendor path: `third_party/ecc-v1.9.0/`
- License: MIT (`third_party/ecc-v1.9.0/LICENSE`)

## Selected upstream skills

The vendor snapshot includes only the ECC skills that map cleanly onto this repo's Python, Django, Docker, deployment, verification, security, and research workflows.

| Local skill or surface | Pinned upstream source |
| --- | --- |
| `search-first` | `third_party/ecc-v1.9.0/skills/search-first/SKILL.md` |
| `documentation-lookup` | `third_party/ecc-v1.9.0/skills/documentation-lookup/SKILL.md` |
| `verification-loop` | `third_party/ecc-v1.9.0/skills/verification-loop/SKILL.md` |
| `security-review` | `third_party/ecc-v1.9.0/skills/security-review/SKILL.md` |
| `python-patterns` | `third_party/ecc-v1.9.0/skills/python-patterns/SKILL.md` |
| `python-testing` | `third_party/ecc-v1.9.0/skills/python-testing/SKILL.md` |
| `django-patterns` | `third_party/ecc-v1.9.0/skills/django-patterns/SKILL.md` |
| `django-security` | `third_party/ecc-v1.9.0/skills/django-security/SKILL.md` |
| `django-verification` | `third_party/ecc-v1.9.0/skills/django-verification/SKILL.md` |
| `docker-patterns` | `third_party/ecc-v1.9.0/skills/docker-patterns/SKILL.md` |
| `deployment-patterns` | `third_party/ecc-v1.9.0/skills/deployment-patterns/SKILL.md` |
| `postgres-patterns` | `third_party/ecc-v1.9.0/skills/postgres-patterns/SKILL.md` |
| `tdd-workflow` | `third_party/ecc-v1.9.0/skills/tdd-workflow/SKILL.md` |
| `ai-regression-testing` | `third_party/ecc-v1.9.0/skills/ai-regression-testing/SKILL.md` |
| `context-budget` | `third_party/ecc-v1.9.0/skills/context-budget/SKILL.md` |

## Local overlay rule

The files under `.agents/skills/` are the active repo-specific overlays. They are intentionally shorter than the upstream ECC files and route agents into this repo's actual docs, tests, env contracts, and security rules.

Do not replace the local overlays with the upstream files verbatim unless the repo's own workflow contracts have been reviewed and preserved.
