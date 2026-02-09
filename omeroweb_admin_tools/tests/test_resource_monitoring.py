from __future__ import annotations

from omeroweb_admin_tools.views.index_view import (
    _build_target_service_status,
    _load_compose_service_names,
)


def test_load_compose_service_names_reads_service_block(tmp_path, monkeypatch) -> None:
    compose_text = """
services:
  app:
    image: test
  db:
    image: postgres
networks:
  default:
""".strip()
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(compose_text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    names = _load_compose_service_names()

    assert names == ["app", "db"]


def test_build_target_service_status_prefers_up() -> None:
    active_targets = [
        {"labels": {"job": "app"}, "health": "down"},
        {
            "labels": {"container_label_com_docker_compose_service": "app"},
            "health": "up",
        },
        {
            "discoveredLabels": {
                "__meta_docker_container_label_com_docker_compose_service": "db"
            },
            "health": "unknown",
        },
    ]

    statuses = _build_target_service_status(active_targets, ["app", "db", "redis"])

    assert statuses == [
        {"service": "app", "health": "up"},
        {"service": "db", "health": "unknown"},
        {"service": "redis", "health": "unknown"},
    ]
