---
name: plugin-regression-triager
description: Map changed files to the correct split pytest suites and fast regression checks for this repository.
origin: repo-local skill informed by ECC v1.10.0 workflow patterns
---

# Plugin Regression Triager

Use this skill to choose the narrowest correct verification set after a change.

## Path-to-suite mapping

- `omeroweb_import/` -> `omeroweb_import/tests/`
- `omeroweb_omp_plugin/` -> `omeroweb_omp_plugin/tests/`
- `omeroweb_admin_tools/` -> `omeroweb_admin_tools/tests/`
- `omeroweb_imaris_connector/` -> `omeroweb_imaris_connector/tests/`
- `omero_web_zarr/` -> `omero_web_zarr/tests/`
- `omero_plugin_common/` -> `omero_plugin_common/tests/`
- `tests/`, root `README.md`, `AGENTS.md`, `.github/workflows/`, `tools/`, `startup/`, `docker/`, or `installation/` changes -> `tests/`

## Combination rules

- Shared-library plus plugin change: run both suites
- Shared helper plus root shell/bootstrap change: run `omero_plugin_common/tests/`, `tests/`, and each directly affected package suite
- Root docs plus plugin change: run `tests/` plus the affected plugin suite
- `docker/`, `startup/`, or `installation/` change: run `tests/`, syntax checks, and any affected package suites
- Multi-plugin refactor: run every touched package suite separately

## Fast checks

If the runtime-complete environment is blocked:

- `python3 -m py_compile` for touched Python files
- `bash -n` for touched shell scripts
- `ruff check` and `ruff format --check`

Fallback checks do not replace the required split-suite tests when those suites are runnable.

## Anti-patterns

- Running one giant `pytest` command across all suites
