# AI Agent Context Routing

Minimal routing map for AI Agents. Use this to load only the smallest correct part of the repository.

## Core rule

Start with:

1. one task class from the matrix below
2. one nearest code root
3. one nearest test module or suite
4. one matching skill from `.agents/skills/`

Do not broad-read `docs/`, all plugin trees, or all tests unless the first narrow pass proves insufficient.

## Iterative retrieval loop

Use the ECC-inspired progressive retrieval pattern:

1. Dispatch: search broadly with `rg` for the task terms and touched paths.
2. Evaluate: keep only files that directly affect the requested change.
3. Refine: search again using the repo terminology you just discovered.
4. Stop: once you have the edit target, one confirming test module, and one verification lane.

Three strong files beat thirty mediocre ones.

## Numeric caps

These numeric caps are CI-validated by `python3 tools/lint_docs_structure.py`.

- Open at most 4 task-specific files in the first pass: one domain doc, one implementation file, one nearest test module or suite, and one matching skill.
- Run at most 2 refine loops before you either name the edit target or escalate.
- Add at most 3 more files per escalation round: one additional domain doc, one adjacent implementation file, and one more confirming test module.
- If you have opened 8 task-specific files without naming the edit target and verification lane, stop and summarize before reading more.

## Task matrix

| Task class | Load first docs | Code roots | Default skills | First verification lane |
| --- | --- | --- | --- | --- |
| Docker, Compose, startup, install, env wiring | `docs/deployment/configuration.md`, `docs/reference/ai-agent-runtime-playbook.md`, `docs/operations/installation-permissions.md` | `docker-compose.yml`, `docker/`, `startup/`, `installation/`, `env/` | `docker-patterns`, `deployment-patterns`, `env-contract-reviewer` | `tests/`, then the matching shell or workflow contracts |
| Shared Python helpers and env loaders | `ARCHITECTURE.md`, `docs/reference/python-style-and-linting.md` | `omero_plugin_common/` | `python-patterns`, `python-testing`, `env-contract-reviewer` | `omero_plugin_common/tests/` |
| OMP Django views, annotation, AI parsing, user data | `docs/plugins/omp-plugin.md`, `docs/plugins/omp-plugin-workflow.md` | `omeroweb_omp_plugin/` | `django-patterns`, `django-security`, `django-verification` | `omeroweb_omp_plugin/tests/` |
| Import plugin uploads, dataset routing, OMERO CLI import, SEM-EDX | `docs/plugins/import-plugin.md`, `docs/plugins/import-plugin-workflow.md`, `docs/reference/ai-agent-runtime-playbook.md` | `omeroweb_import/` | `django-patterns`, `omero-runtime-verifier`, `plugin-regression-triager`, `verification-loop` | `omeroweb_import/tests/` |
| Admin Tools logs, Grafana/Prometheus proxy, quotas, diagnostics | `docs/plugins/admin-tools-plugin.md`, `docs/plugins/admin-tools-workflow.md`, `docs/operations/monitoring.md` | `omeroweb_admin_tools/` | `django-patterns`, `django-security`, `omero-runtime-verifier` | `omeroweb_admin_tools/tests/` |
| Tools and Enhanced search plugin | `docs/plugins/tools-plugin.md`, `docs/reference/plugin-help-page-style-guide.md` | `omeroweb_tools/` | `django-patterns`, `django-security`, `frontend-preview`, `plugin-regression-triager` | `omeroweb_tools/tests/` |
| Plugin user help pages, screenshots, and help-page collapse behavior | `docs/reference/plugin-help-page-style-guide.md`, nearest `docs/plugins/*.md` | plugin `templates/`, plugin `static/`, `docs/help/` | `frontend-preview`, `docs-knowledge-maintainer`, `django-verification` | focused plugin contract tests plus browser preview tests |
| Imaris export task flow and scripts | `docs/plugins/imaris-connector-plugin.md`, `docs/plugins/imaris-connector-workflow.md` | `omeroweb_imaris_connector/` | `python-patterns`, `omero-runtime-verifier`, `plugin-regression-triager` | `omeroweb_imaris_connector/tests/` |
| OMERO.web Zarr rendering and store-backed integration | `docs/plugins/omero-web-zarr-plugin.md`, `docs/plugins/omero-web-zarr-workflow.md` | `omero_web_zarr/` | `django-patterns`, `django-verification`, `python-testing` | `omero_web_zarr/tests/` |
| Docs and agent surfaces | `docs/index.md`, `docs/reference/ai-agent-integrations.md` | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/`, `.cursor/` | `context-budget`, `docs-knowledge-maintainer`, `search-first` | `tests/test_lint_docs_structure.py`, AI-surface tests |
| Agent skills and reusable workflows | `docs/reference/ai-agent-skills.md`, `docs/reference/ai-agent-integrations.md` | `.agents/skills/`, `tools/lint_docs_structure.py` | `cocoindex-code-search`, `docs-knowledge-maintainer`, `verification-loop` | skill catalog and contract tests |
| Security findings or scanner regressions | `docs/reference/ai-agent-security-prevention-playbook.md`, `docs/reference/code-scanning-resolved-findings.md`, `docs/operations/code-scanning.md` | touched code only | `security-finding-triager`, `security-review`, `documentation-lookup` | touched suite plus security contract tests |
| Workflow and CI changes | `docs/operations/code-scanning.md`, `docs/reference/ai-agent-security-prevention-playbook.md` | `.github/workflows/` | `documentation-lookup`, `verification-loop`, `security-review` | workflow contract tests in `tests/` |

## Split pytest map

- `tests/`: repo-wide contracts, workflows, docs, scanners, shared integration checks
- `omero_plugin_common/tests/`: shared helper modules and env utilities
- `omeroweb_imaris_connector/tests/`: Celery task flow, IMS export script contracts
- `omeroweb_admin_tools/tests/`: quotas, monitoring, logs, Grafana/Prometheus proxy
- `omeroweb_omp_plugin/tests/`: OMP views, annotation services, AI credential handling
- `omeroweb_import/tests/`: upload pipeline, import planning, dataset routing, SEM-EDX, native Zarr import
- `omeroweb_tools/tests/`: Tools landing page, Enhanced search, acquisition metadata index, help UI
- `omero_web_zarr/tests/`: store-backed image rendering and webgateway overrides

Run only the touched lanes while iterating. Run the full split matrix before final push when the change spans multiple domains or shared infrastructure.

## Always-loaded surface policy

- Keep `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and `.github/copilot-instructions.md` short and index-first.
- Detailed procedures belong in deep docs such as `docs/reference/ai-agent-runtime-playbook.md`.
- Reusable workflows belong in `.agents/skills/`, not in every adapter file.
- If an instruction file becomes long enough that agents keep rereading it, split it and link to the deeper file.

## What not to load by default

- Entire plugin trees when only one service file is touched
- Entire `docs/` when one plugin or operations document answers the question
- All split test suites during debug cycles
- Vendored ECC sources under `third_party/` unless verifying provenance or adapting a specific skill

## Escalation

If the first narrow pass still leaves uncertainty:

1. load one additional domain doc
2. load one adjacent implementation file
3. load one more confirming test module

Do not jump straight from one file to the whole repository.
