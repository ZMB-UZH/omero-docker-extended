"""Contract tests for tracked example env templates only.

When intentionally adding, removing, or renaming an active assignment in any
tracked `*_example.env` file or in `installation_paths_example.env`, update the
expected contract below in the same change.

These tests must stay repo-local: they inspect only tracked example templates
under the repository root and must never read deployment-local runtime env
files such as `.env`, `env/*.env`, or any host/VM-specific path.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

EXPECTED_EXAMPLE_ENV_KEYS: dict[str, frozenset[str]] = {
    "env/grafana_example.env": frozenset(
        {
            "GF_SECURITY_ADMIN_USER",
            "GF_AUTH_ANONYMOUS_ENABLED",
            "GF_ANALYTICS_REPORTING_ENABLED",
            "GF_ANALYTICS_CHECK_FOR_UPDATES",
            "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES",
            "GF_PLUGINS_PREINSTALL_AUTO_UPDATE",
            "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH",
        }
    ),
    "env/omero-celery_example.env": frozenset(
        {
            "OMERO_JOB_SERVICE_USERNAME",
            "OMERO_JOB_SERVICE_GROUP",
            "OMERO_JOB_SERVICE_SECURE",
            "OMERO_WEB_JOB_SERVICE_USERNAME",
            "OMERO_IMS_USE_CELERY",
            "OMERO_IMS_CELERY_BROKER_URL",
            "OMERO_IMS_CELERY_BACKEND_URL",
            "OMERO_IMS_CELERY_QUEUE",
            "OMERO_IMS_CELERY_RESULT_EXPIRES",
            "OMERO_IMS_CELERY_TIME_LIMIT",
            "OMERO_IMS_CELERY_LOGLEVEL",
            "OMERO_IMS_CELERY_WORKER_CONCURRENCY",
            "OMERO_IMS_CELERY_MAX_RETRIES",
            "OMERO_IMS_CELERY_PREFETCH",
            "TOOLS_ENHANCED_SEARCH_USE_CELERY",
            "TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL",
            "TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL",
            "TOOLS_ENHANCED_SEARCH_CELERY_QUEUE",
            "TOOLS_ENHANCED_SEARCH_CELERY_RESULT_EXPIRES",
            "TOOLS_ENHANCED_SEARCH_CELERY_TIME_LIMIT",
            "TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL",
            "TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY",
            "TOOLS_ENHANCED_SEARCH_CELERY_MAX_RETRIES",
            "TOOLS_ENHANCED_SEARCH_CELERY_PREFETCH",
            "OMERO_IMS_SCRIPT_NAME",
            "OMERO_IMS_EXPORT_DIR",
            "OMERO_IMS_EXPORT_TIMEOUT",
            "OMERO_IMS_EXPORT_POLL_INTERVAL",
            "OMERO_IMS_SCRIPT_START_TIMEOUT",
            "OMERO_IMS_SCRIPT_START_RETRY_INTERVAL",
            "OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL",
            "OMERO_IMS_USE_JOB_SERVICE_SESSION",
        }
    ),
    "env/omero_secrets_example.env": frozenset(
        {
            "OMERO_DB_PASS",
            "OMP_PLUGIN_DB_PASS",
            "OMP_DATA_PASS",
            "ROOTPASS",
            "OMERO_JOB_SERVICE_PASS",
            "OMERO_WEB_JOB_SERVICE_PASS",
            "OMP_HASH_SECRET",
            "FMP_HASH_SECRET",
            "GF_SECURITY_ADMIN_PASSWORD",
            "CROWDSEC_ENROLL_KEY",
            "CROWDSEC_ENGINE_NAME",
        }
    ),
    "env/omeroserver_example.env": frozenset(
        {
            "CONFIG_omero_host",
            "CONFIG_omero_db_host",
            "CONFIG_omero_db_user",
            "CONFIG_omero_db_name",
            "TZ",
            "OMERO_CLI_USER",
            "OMERO_CLI_HOST",
            "OMERO_CLI_PORT",
            "OMERO_SERVER_HOST_PORT",
            "OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS",
            "OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS",
            "OMERO_SERVER_HEALTHCHECK_RETRIES",
            "OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS",
            "OMERO_JOB_SERVICE_USERNAME",
            "OMERO_JOB_SERVICE_JOIN_ALL_GROUPS",
            "OMERO_JOB_SERVICE_HOST",
            "OMERO_JOB_SERVICE_PORT",
            "OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS",
            "OMERO_JOB_SERVICE_READINESS_POLL_SECONDS",
            "OMERO_JOB_SERVICE_USER_ENSURE_RETRIES",
            "OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS",
            "OMERO_JOB_SERVICE_SYNC_MAX_RETRIES",
            "OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS",
            "OMERO_JOB_SERVICE_SECURE",
            "OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS",
            "OMERO_REPO_ROOT_SYNC_JITTER_SECONDS",
            "OMERO_BINARY_REPO_CLEANSE_ON_START",
            "OMERO_BINARY_REPO_CLEANSE_DATA_DIR",
            "OMERO_BINARY_REPO_CLEANSE_STARTUP_WAIT_SECONDS",
            "OMERO_BINARY_REPO_CLEANSE_READINESS_POLL_SECONDS",
            "OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS",
            "OMERO_REPOSITORY_LOCK_CLEANUP_ON_START",
            "OMERO_RENDERING_CACHE_CLEANUP_ON_START",
            "CONFIG_omero_security_login__failure__throttle__count",
            "CONFIG_omero_security_login__failure__throttle__time",
            "OMERO_INSTALL_GROUP_LIST",
            "CONFIG_omero_db_poolsize",
            "JAVA_OPTS",
            "CONFIG_omero_scripts_processors",
            "CONFIG_omero_pixeldata_threads",
            "CONFIG_omero_managed_dir",
            "CONFIG_omero_fs_repo_path",
            "OMERO_DROPBOX_ENABLED",
            "OMERO_DROPBOX_VERSION",
            "OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS",
            "OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS",
            "OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS",
            "CONFIG_omero_fs_host",
            "CONFIG_omero_fs_port",
            "CONFIG_omero_fs_maxRetries",
            "CONFIG_omero_fs_retryInterval",
            "CONFIG_omero_fs_defaultDropBoxDir",
            "CONFIG_omero_fs_platformCheck",
            "CONFIG_omero_fs_importUsers",
            "CONFIG_omero_fs_watchDir",
            "CONFIG_omero_fs_eventTypes",
            "CONFIG_omero_fs_pathMode",
            "CONFIG_omero_fs_whitelist",
            "CONFIG_omero_fs_blacklist",
            "CONFIG_omero_fs_timeout",
            "CONFIG_omero_fs_timeToLive",
            "CONFIG_omero_fs_timeToIdle",
            "CONFIG_omero_fs_blockSize",
            "CONFIG_omero_fs_ignoreSysFiles",
            "CONFIG_omero_fs_ignoreDirEvents",
            "CONFIG_omero_fs_dirImportWait",
            "CONFIG_omero_fs_fileBatch",
            "CONFIG_omero_fs_throttleImport",
            "CONFIG_omero_fs_readers",
            "CONFIG_omero_fs_importArgs",
            "CONFIG_omero_fs_serverIdString",
            "CONFIG_omero_fs_clientIdString",
            "CONFIG_omero_fs_clientAdapterName",
            "OMERO_DROPBOX_USER_DIR_SYNC_ENABLED",
            "OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS",
            "OMERO_DROPBOX_USER_DIR_SYNC_JITTER_SECONDS",
            "OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS",
            "OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS",
            "OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES",
            "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_HOST",
            "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT",
            "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_SECURE",
            "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_USERNAME",
            "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV",
            "OMERO_DROPBOX_USER_DIR_CREATE_ROOT",
            "OMERO_DROPBOX_USER_DIR_OWNER",
            "OMERO_DROPBOX_USER_DIR_GROUP",
            "OMERO_DROPBOX_USER_DIR_MODE",
            "OMERO_DROPBOX_USER_DIR_ALLOW_WORLD_WRITABLE",
            "REGISTER_OFFICIAL_SCRIPTS",
            "OMERO_FIGURE_VERSION",
            "OMERO_DOWNLOADER_VERSION",
            "OMEZARR_READER_VERSION",
            "JZARR_VERSION",
            "OMERO_ZARR_PIXEL_BUFFER_VERSION",
            "OMERO_ZARR_PIXEL_BUFFER_ENABLED",
            "OMERO_CLI_ZARR_VERSION",
            "OME_ZARR_PY_VERSION",
            "BIOFORMATS2RAW_VERSION",
            "BIOFORMATS_VERSION",
            "OMERO_IMS_EXPORT_DIR",
        }
    ),
    "env/omeroweb_example.env": frozenset(
        {
            "OMEROHOST",
            "OMERO_PORT",
            "OMERO_WEB_ROOT",
            "OMERO_WEB_HOST_PORT",
            "CONFIG_omero_security_transport",
            "CONFIG_omero_security_ssl",
            "OMP_DATA_USER",
            "OMP_DATA_HOST",
            "OMP_DATA_DB",
            "OMP_DATA_PORT",
            "CONFIG_omero_web_application__server_port",
            "CONFIG_omero_web_session__cookie__secure",
            "CONFIG_omero_web_time__zone",
            "TZ",
            "CONFIG_omero_web_logdir",
            "OMERO_WEB_WSGI_ARGS",
            "CONFIG_omero_web_session__engine",
            "CONFIG_omero_web_session__cookie__age",
            "CONFIG_omero_web_session__expire__at__browser__close",
            "CONFIG_omero_web_caches",
            "CONFIG_omero_web_apps",
            "CONFIG_omero_web_ui_right__plugins",
            "CONFIG_omero_web_ui_center__plugins",
            "CONFIG_omero_web_open__with",
            "CONFIG_omero_web_ui_top__links",
            "CONFIG_omero_web_login__logo",
            "ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS",
            "ADMIN_TOOLS_MIN_QUOTA_GB",
            "ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB",
            "ADMIN_TOOLS_AUTO_SET_DEFAULT_GROUP_QUOTA",
            "ADMIN_TOOLS_QUOTA_PROJECTS_FILE",
            "ADMIN_TOOLS_QUOTA_PROJID_FILE",
            "ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN",
            "ADMIN_TOOLS_LOKI_URL",
            "ADMIN_TOOLS_LOG_LOOKBACK_SECONDS",
            "ADMIN_TOOLS_LOG_MAX_ENTRIES",
            "ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS",
            "ADMIN_TOOLS_LOG_CACHE_MAX_MB",
            "ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE",
            "ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES",
            "ADMIN_TOOLS_OMERO_SERVER_HOST",
            "ADMIN_TOOLS_OMERO_BLITZ_PORT",
            "ADMIN_TOOLS_OMERO_SECURE_PORT",
            "ADMIN_TOOLS_OMERO_WEB_HOST",
            "ADMIN_TOOLS_OMERO_WEB_PATH",
            "ADMIN_TOOLS_GRAFANA_URL",
            "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID",
            "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG",
            "ADMIN_TOOLS_PROMETHEUS_URL",
            "TOOLS_ENHANCED_SEARCH_INDEX_BATCH_SIZE",
            "TOOLS_ENHANCED_SEARCH_MAX_RESULTS",
            "TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS",
            "TOOLS_ENHANCED_SEARCH_SCHEMA_VERSION",
            "OMERO_WEB_UPLOAD_CONCURRENCY",
            "OMERO_WEB_UPLOAD_BATCH_FILES",
            "OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS",
            "OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS",
            "OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS",
            "OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS",
            "OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS",
            "OMERO_WEB_UPLOAD_NATIVE_ZARR_GZIP_LEVEL",
            "OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS",
            "OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT",
            "OMERO_WEB_UPLOAD_DISABLE_SPECIAL_METHODS",
            "OMERO_WEB_ZARR_ALTERNATIVE_RENDERING",
            "CONFIG_omero_web_debug",
            "OMERO_WEB_VENV",
        }
    ),
    "installation_paths_example.env": frozenset(
        {
            "OMERO_INSTALLATION_PATH",
            "OMERO_DATABASE_PATH",
            "OMERO_PLUGIN_DATABASE_PATH",
            "OMERO_DATA_PATH",
            "OMERO_TMP_PATH",
            "OMERO_DATA_DIR",
            "OMERO_USER_DATA_PATH",
            "OMERO_IMPORT_PATH",
            "OMERO_SERVER_VAR_PATH",
            "OMERO_SERVER_LOGS_PATH",
            "OMERO_WEB_VAR_PATH",
            "OMERO_WEB_LOGS_PATH",
            "OMERO_WEB_SUPERVISOR_LOGS_PATH",
            "PORTAINER_DATA_PATH",
            "PROMETHEUS_DATA_PATH",
            "GRAFANA_DATA_PATH",
            "LOKI_DATA_PATH",
            "ALLOY_DATA_PATH",
            "PG_MAINTENANCE_DATA_PATH",
            "BUILDX_DATA_PATH",
            "NODE_EXPORTER_TEXTFILE_PATH",
            "CROWDSEC_DB_PATH",
            "CROWDSEC_CONFIG_PATH",
        }
    ),
}


class ExampleEnvContractTests(unittest.TestCase):
    """Lock the tracked example env inventory and active assignment names."""

    @classmethod
    def setUpClass(cls) -> None:
        """Store set up class."""
        cls.repo_root = Path(__file__).resolve().parents[1]

    def parse_assignment_keys(
        self, relative_path: str
    ) -> tuple[list[str], list[tuple[int, str]]]:
        """Return active assignment keys plus malformed non-comment lines."""
        keys: list[str] = []
        malformed: list[tuple[int, str]] = []
        env_path = self.repo_root / relative_path
        for lineno, raw_line in enumerate(
            env_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = ASSIGNMENT_RE.match(line)
            if match is None:
                malformed.append((lineno, raw_line))
                continue
            keys.append(match.group(1))
        return keys, malformed

    def parse_active_assignments(self, relative_path: str) -> dict[str, str]:
        """Validate parse active assignments."""
        env_path = self.repo_root / relative_path
        assignments: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            assignments[key] = value
        return assignments

    def test_tracked_example_env_inventory_is_locked(self) -> None:
        """Verify test tracked example env inventory is locked."""
        discovered = {
            path.relative_to(self.repo_root).as_posix()
            for path in (self.repo_root / "env").glob("*_example.env")
        }
        discovered.add("installation_paths_example.env")
        self.assertEqual(set(EXPECTED_EXAMPLE_ENV_KEYS), discovered)

    def test_example_env_files_have_only_assignment_or_comment_lines(self) -> None:
        """Verify test example env files have only assignment o behavior."""
        for relative_path in EXPECTED_EXAMPLE_ENV_KEYS:
            with self.subTest(relative_path=relative_path):
                _, malformed = self.parse_assignment_keys(relative_path)
                self.assertEqual(
                    [],
                    malformed,
                    f"{relative_path} contains malformed active lines: {malformed}",
                )

    def test_example_env_files_do_not_repeat_active_keys(self) -> None:
        """Verify test example env files do not repeat active keys."""
        for relative_path in EXPECTED_EXAMPLE_ENV_KEYS:
            with self.subTest(relative_path=relative_path):
                keys, _ = self.parse_assignment_keys(relative_path)
                duplicates = sorted({key for key in keys if keys.count(key) > 1})
                self.assertEqual(
                    [],
                    duplicates,
                    f"{relative_path} contains duplicate active keys: {duplicates}",
                )

    def test_example_env_assignment_keys_match_locked_contract(self) -> None:
        """Verify test example env assignment keys match locked behavior."""
        for relative_path, expected_keys in EXPECTED_EXAMPLE_ENV_KEYS.items():
            with self.subTest(relative_path=relative_path):
                actual_keys, _ = self.parse_assignment_keys(relative_path)
                actual_key_set = frozenset(actual_keys)
                missing = sorted(expected_keys - actual_key_set)
                extra = sorted(actual_key_set - expected_keys)
                self.assertEqual(
                    expected_keys,
                    actual_key_set,
                    "\n".join(
                        [
                            f"{relative_path} drifted from the locked example-env contract.",
                            f"Missing keys: {missing or 'none'}",
                            f"Unexpected keys: {extra or 'none'}",
                            "Update this test only when the key change is intentional.",
                        ]
                    ),
                )

    def test_secrets_example_has_no_placeholder_secret_values(self) -> None:
        """Verify test secrets example has no placeholder secre behavior."""
        assignments = self.parse_active_assignments("env/omero_secrets_example.env")
        self.assertFalse(
            any(value for value in assignments.values()),
            "Tracked secrets examples must keep values empty so scanners do not "
            "treat placeholders as checked-in credentials.",
        )
        example_text = (self.repo_root / "env/omero_secrets_example.env").read_text(
            encoding="utf-8"
        )
        legacy_placeholder_prefix = "CHANGE"
        self.assertNotIn(f"{legacy_placeholder_prefix}PASSWORD", example_text)
        self.assertNotIn(f"{legacy_placeholder_prefix}VALUE", example_text)


if __name__ == "__main__":
    unittest.main()
