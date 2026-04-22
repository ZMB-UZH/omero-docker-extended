# Python Style and Linting

This repository uses [Ruff](https://github.com/astral-sh/ruff) as the canonical Python formatter and lightweight correctness lint gate, [Mypy](https://github.com/python/mypy) as the static type-check gate for tracked production Python files, and [Vulture](https://github.com/jendrikseipp/vulture) as the dead-code gate for tracked production Python files.

## CI workflow

- `.github/workflows/ruff.yml` listens for `pull_request` to `main`, `push` to `main`, and `workflow_dispatch`, but the job only executes when the ref resolves to the repository's current default branch.
- `.github/workflows/mypy.yml` listens for `pull_request` to `main`, `push` to `main`, and `workflow_dispatch`, but the job only executes when the ref resolves to the repository's current default branch.
- `.github/workflows/vulture.yml` listens for `pull_request` to `main`, `push` to `main`, and `workflow_dispatch`, but the job only executes when the ref resolves to the repository's current default branch.
- The workflow uses pinned GitHub Actions and a pinned Ruff release (`0.15.10`).
- The Mypy workflow restores and stores the `pip` download cache using the hash-pinned `.github/requirements/tests-ci.txt` and `.github/requirements/mypy-ci.txt` lockfiles as its cache key, installs both dependency sets, then runs `python3 tools/mypy_check.py`.
- The Vulture workflow restores and stores the `pip` download cache using the hash-pinned `.github/requirements/vulture-ci.txt` lockfile as its cache key, then runs `python3 tools/vulture_check.py`.
- CI runs:
  - `ruff check .`
  - `ruff format --check .`
  - `python3 tools/mypy_check.py`
  - `python3 tools/vulture_check.py`

## Local workflow

Install Ruff and the local hooks once:

```bash
python3 -m pip install ruff pre-commit
pre-commit install
```

Run the same checks locally before proposing Python changes:

```bash
python3 tools/run_local_workflow_gates.py --setup --profile ci
ruff check .
ruff format --check .
python3 tools/mypy_check.py
python3 tools/vulture_check.py
pre-commit run --all-files
```

To apply the canonical formatting baseline locally:

```bash
ruff format .
```

## Lint scope

- Ruff formatting applies repo-wide to tracked Python files.
- The lint gate is intentionally narrow: `F`, `E7`, and `E9`.
- The current repository baseline does not use `per-file-ignores` in `.ruff.toml`.
- Do not reintroduce file-level Ruff exceptions casually. Prefer fixing the underlying code and covering it with targeted tests.
- The Mypy gate scans tracked production Python files only. Tests, docs, vendored third-party content, hidden harness folders, `conftest.py`, and test-named modules stay out of scope by design.
- Mypy is configured to use the active CI Python interpreter, check untyped function bodies, report redundant casts, report unused ignores, reject implicit optionals, and apply strict equality checks.
- Runtime-only APIs that do not publish usable type information are stubbed under `typings/` and loaded through `mypy_path`; do not add global missing-import ignores for those dependencies.
- The Vulture dead-code gate scans tracked production Python files only. Tests, docs, vendored third-party content, hidden harness folders, `conftest.py`, and test-named modules stay out of scope by design.

## Agent guidance

- For Python edits, run `ruff check` and `ruff format` on the affected files before finishing.
- For typing-sensitive Python edits or shared helper changes, run `python3 tools/mypy_check.py` before finishing.
- For dead-code cleanup or larger Python refactors, run `python3 tools/vulture_check.py` before finishing.
- For CI, workflow, or repo-wide formatting changes, rerun the repo-wide commands.
- Use Ruff formatting as the source of truth for Python style in this repository.
