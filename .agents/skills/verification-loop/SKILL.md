---
name: verification-loop
description: Repository-specific verification flow for OMERO Docker Extended. Runs docs validation, Ruff, split pytest suites, and targeted fallback checks without overstating coverage.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/verification-loop/SKILL.md
---

# Verification Loop

Use this skill after any non-trivial change and before proposing a PR.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/verification-loop/SKILL.md` for the generic verify-before-finish workflow.

## Verification order

### 1. Documentation structure

```bash
python3 tools/lint_docs_structure.py
python3 -m unittest -v tests/test_lint_docs_structure.py
```

### 2. Python lint and formatting

Run Ruff on touched files first. If you change Ruff policy or broad formatting, rerun repo-wide.

```bash
ruff check <touched-python-files>
ruff format --check <touched-python-files>
```

### 3. Fast syntax and shell checks

Use these when shell/bootstrap logic changed or when runtime-complete verification is blocked.

```bash
python3 -m py_compile <touched-python-files>
bash -n <touched-shell-scripts>
```

### 4. Split pytest execution

Never run all suites in a single pytest process. Run only the relevant suites, each separately:

```bash
python3 -m pytest tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_imaris_connector/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_web_zarr/tests/ -v -p no:cacheprovider -W error
```

Boundary helper change: rerun the helper's own suite plus every directly affected package suite.

### 5. Diff review

Check for:

- unintended workflow or docs drift
- stale service counts or plugin names
- hard-coded paths, credentials, or ports
- weakened validation or security boundaries

## Required reporting

Every verification summary must state which of these levels was achieved:

1. runtime-complete split pytest
2. targeted tests plus syntax/contract checks
3. syntax-only fallback

Never imply that full pytest passed when only `py_compile`, `bash -n`, or narrow tests ran.

## Common blockers

- Host Python missing Django: switch to the dependency-complete runtime or use the fallback verification order documented in `AGENTS.md`
- Docker socket unavailable: do not keep retrying the same runtime probe
- Root-owned repo or cache warnings: keep `-p no:cacheprovider`
