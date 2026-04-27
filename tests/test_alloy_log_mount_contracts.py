from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_alloy_file_log_paths_use_collector_mounts_not_install_paths() -> None:
    alloy_text = (REPO_ROOT / "monitoring" / "alloy" / "alloy-config.alloy").read_text(
        encoding="utf-8"
    )

    assert "/logs/omeroserver/*.log" in alloy_text
    assert "/logs/omeroweb/*.log" in alloy_text
    assert "/logs/omeroweb-supervisor/*.log" in alloy_text
    assert "/opt/omero/server/OMERO.server/var/log" not in alloy_text
    assert "/opt/omero/web/OMERO.web/var/log" not in alloy_text
    assert "/opt/omero/web/logs" not in alloy_text
