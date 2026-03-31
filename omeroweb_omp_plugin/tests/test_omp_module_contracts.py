from __future__ import annotations

from omeroweb_omp_plugin import apps, urls
from omeroweb_omp_plugin.services import ai_providers
from omeroweb_omp_plugin.services.jobs import job_storage


def test_ai_provider_options_return_copy():
    options = ai_providers.list_ai_provider_options()
    options.append({"value": "new", "label": "New"})

    assert all(option["value"] != "new" for option in ai_providers.AI_PROVIDER_OPTIONS)


def test_job_storage_validates_and_roundtrips_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))
    job_id = "d" * 32
    uppercase_job_id = job_id.upper()
    job = {"job_id": uppercase_job_id, "status": "queued"}

    assert job_storage.get_job_path(uppercase_job_id).endswith(f"{job_id}.json")
    assert job_storage.get_job_lock_path(uppercase_job_id).endswith(f"{job_id}.lock")
    job_storage.save_job(job)
    assert job_storage.load_job(uppercase_job_id) == job
    assert job_storage.load_job(job_id) == job
    assert job_storage.load_job("invalid") is None


def test_omp_module_contracts_cover_ready_hook_and_named_routes(monkeypatch):
    configured = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: configured.append(True)
    )

    config = apps.OMPPluginConfig(apps.OMPPluginConfig.name, apps)
    config.ready()

    assert configured == [True]
    route_names = [pattern.name for pattern in urls.urlpatterns]
    assert "omeroweb_omp_plugin_index" in route_names
    assert "omeroweb_omp_plugin_start_job" in route_names
    assert "omeroweb_omp_plugin_save_ai_credentials" in route_names
    assert "omeroweb_omp_plugin_help" in route_names
