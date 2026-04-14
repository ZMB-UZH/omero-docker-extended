# Python Style and Linting

This repository uses [Ruff](https://github.com/astral-sh/ruff) as the canonical Python formatter and lightweight correctness lint gate, plus [Vulture](https://github.com/jendrikseipp/vulture) as the dead-code gate for tracked production Python files.

## CI workflow

- `.github/workflows/ruff.yml` runs on `pull_request` to `main`, `push` to `main`, and `workflow_dispatch`.
- `.github/workflows/vulture.yml` runs on `pull_request` to `main`, `push` to `main`, and `workflow_dispatch`.
- The workflow uses pinned GitHub Actions and a pinned Ruff release (`0.15.10`).
- The Vulture workflow restores and stores the `pip` download cache using the hash-pinned `.github/requirements/vulture-ci.txt` lockfile as its cache key, then runs `python3 tools/vulture_check.py`.
- CI runs:
  - `ruff check .`
  - `ruff format --check .`
  - `python3 tools/vulture_check.py`

## Local workflow

Install Ruff and the local hooks once:

```bash
python3 -m pip install ruff pre-commit
pre-commit install
```

Run the same checks locally before proposing Python changes:

```bash
ruff check .
ruff format --check .
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
- The Vulture dead-code gate scans tracked production Python files only. Tests, docs, vendored third-party content, hidden harness folders, `conftest.py`, and test-named modules stay out of scope by design.

## Agent guidance

- For Python edits, run `ruff check` and `ruff format` on the affected files before finishing.
- For dead-code cleanup or larger Python refactors, run `python3 tools/vulture_check.py` before finishing.
- For CI, workflow, or repo-wide formatting changes, rerun the repo-wide commands.
- Use Ruff formatting as the source of truth for Python style in this repository.
