"""Tests for the OMERO Processor environment allowlist patch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = REPO_ROOT / "docker" / "patch_omero_processor_env.py"


def _load_patch_module():
    """Return the patch module loaded from the Docker helper path.

    Inputs: none. Output: imported patch helper module.
    """
    spec = importlib.util.spec_from_file_location(
        "patch_omero_processor_env", PATCH_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_patch_processor_env_adds_export_path_env_idempotently(
    tmp_path: Path,
) -> None:
    """Verify the Processor patch preserves env-driven IMS export paths.

    Inputs: pytest `tmp_path` fixture. Output: fails on allowlist regressions.
    """
    module = _load_patch_module()
    processor_path = tmp_path / "processor.py"
    processor_path.write_text(
        "\n".join(
            [
                "class ProcessI:",
                "    def make_env(self):",
                "        self.env = omero.util.Environment(",
                '            "OMERO_TEMPDIR",',
                '            "OMERO_TMPDIR",',
                '            "PATH",',
                "        )",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert module.patch_processor_env(processor_path) is True
    patched = processor_path.read_text(encoding="utf-8")
    assert (
        '            "OMERO_TMPDIR",\n'
        '            "OMERO_IMS_EXPORT_DIR",\n'
        '            "CONFIG_omero_managed_dir",'
    ) in patched

    assert module.patch_processor_env(processor_path) is False
    assert processor_path.read_text(encoding="utf-8") == patched


def test_patch_processor_env_adds_only_missing_export_path_env(
    tmp_path: Path,
) -> None:
    """Verify partial earlier patches are upgraded without duplicate entries.

    Inputs: pytest `tmp_path` fixture. Output: fails on duplicate env entries.
    """
    module = _load_patch_module()
    processor_path = tmp_path / "processor.py"
    processor_path.write_text(
        "\n".join(
            [
                "class ProcessI:",
                "    def make_env(self):",
                "        self.env = omero.util.Environment(",
                '            "OMERO_TEMPDIR",',
                '            "OMERO_TMPDIR",',
                '            "OMERO_IMS_EXPORT_DIR",',
                '            "PATH",',
                "        )",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert module.patch_processor_env(processor_path) is True
    patched = processor_path.read_text(encoding="utf-8")
    assert patched.count('            "OMERO_IMS_EXPORT_DIR",') == 1
    assert '            "CONFIG_omero_managed_dir",' in patched


def test_patch_processor_env_fails_when_allowlist_shape_changes(tmp_path: Path) -> None:
    """Verify the Docker build fails closed if upstream Processor shape changes.

    Inputs: pytest `tmp_path` fixture. Output: raises assertion on ignored upstream drift.
    """
    module = _load_patch_module()
    processor_path = tmp_path / "processor.py"
    processor_path.write_text("class ProcessI:\n    pass\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="environment allowlist"):
        module.patch_processor_env(processor_path)
