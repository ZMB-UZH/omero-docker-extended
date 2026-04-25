# Closed-Alert Archive — 2026-04-25 snapshot

> **Reference only.** The canonical anti-regression gate is `tools/regression_guard.py`. Run `python3 tools/regression_guard.py scan` and `python3 tools/regression_guard.py catalog` before editing security-sensitive code. This document captures the closed-alert history that informed the catalog rules; it is not the source of truth.

## GitHub code-scanning closed history (2373 alerts)

| Scanner | Count | Share |
| --- | ---: | ---: |
| `bandit` | 880 | 37.1% |
| `codeql` | 728 | 30.7% |
| `semgrep oss` | 312 | 13.1% |
| `devskim` | 248 | 10.5% |
| `scorecard` | 112 | 4.7% |
| `trivy` | 60 | 2.5% |
| `hadolint` | 33 | 1.4% |
| **Total** | **2373** | **100%** |

### Closed alerts by severity

| Severity | Count |
| --- | ---: |
| note | 1076 |
| warning | 494 |
| high | 347 |
| error | 246 |
| medium | 174 |
| low | 27 |
| critical | 9 |

### Highest-recurrence rule families

| Tool | Rule | Closed alerts | Severity | Top hotspot file |
| --- | --- | ---: | --- | --- |
| `bandit` | `B101` | 499 | note | `omeroweb_admin_tools/tests/test_resource_monitoring.py` |
| `devskim` | `DS137138` | 165 | warning | `omeroweb_admin_tools/tests/test_resource_monitoring.py` |
| `semgrep oss` | `python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query` | 165 | error | `omeroweb_omp_plugin/services/data_store.py` |
| `codeql` | `py/log-injection` | 123 | high | `omeroweb_upload/views/index_view.py` |
| `codeql` | `py/empty-except` | 117 | note | `omeroweb_import/views/core_functions.py` |
| `scorecard` | `PinnedDependenciesID` | 107 | medium | `.github/workflows/security-code-scanning.yml` |
| `codeql` | `py/path-injection` | 103 | high | `omeroweb_import/views/core_functions.py` |
| `bandit` | `B108` | 95 | warning | `tests/test_import_plugin_regressions.py` |
| `bandit` | `B105` | 74 | note | `tests/test_omp_plugin_view_regressions.py` |
| `codeql` | `py/stack-trace-exposure` | 62 | medium | `omeroweb_omp_plugin/views/job_view.py` |
| `codeql` | `py/clear-text-logging-sensitive-data` | 55 | high | `omeroweb_upload/services/omero/import_service.py` |
| `devskim` | `DS162092` | 46 | note | `docker-compose.yml` |
| `bandit` | `B110` | 40 | note | `omeroweb_import/views/core_functions.py` |
| `bandit` | `B311` | 37 | note | `omeroweb_import/services/omero/sem_edx_parser.py` |
| `devskim` | `DS173237` | 35 | error | `tests/test_omeroweb_logo_bootstrap_regressions.py` |
| `semgrep oss` | `python.django.security.audit.csrf-exempt.no-csrf-exempt` | 34 | warning | `omeroweb_admin_tools/views/index_view.py` |
| `codeql` | `py/unused-import` | 34 | note | `omeroweb_upload/services/omero/import_service.py` |
| `codeql` | `py/unnecessary-lambda` | 29 | note | `omeroweb_import/tests/test_sem_edx_parser.py` |
| `bandit` | `B607` | 28 | note | `tests/test_tmp_cleanup_regressions.py` |
| `codeql` | `py/overly-permissive-file` | 25 | high | `omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py` |
| `semgrep oss` | `python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure` | 24 | warning | `omeroweb_omp_plugin/views/ai_credentials_view.py` |
| `bandit` | `B603` | 24 | note | `omeroweb_upload/views/core_functions.py` |
| `bandit` | `B112` | 23 | note | `omeroweb_omp_plugin/views/index_view.py` |
| `codeql` | `py/uninitialized-local-variable` | 22 | error | `omeroweb_import/views/core_functions.py` |
| `codeql` | `py/unused-global-variable` | 21 | note | `omeroweb_upload/services/upload_management/workflow_service.py` |
| `semgrep oss` | `python.django.security.audit.xss.direct-use-of-httpresponse.direct-use-of-httpresponse` | 19 | warning | `omero_web_zarr/views.py` |
| `semgrep oss` | `python.lang.security.audit.insecure-file-permissions.insecure-file-permissions` | 18 | warning | `omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py` |
| `bandit` | `B404` | 18 | note | `omeroweb_upload/views/core_functions.py` |
| `codeql` | `py/multiple-definition` | 17 | warning | `omero_plugin_common/tests/test_logging_utils_additional.py` |
| `bandit` | `B608` | 17 | warning | `omeroweb_import/views/core_functions.py` |
| `semgrep oss` | `python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected` | 16 | warning | `omeroweb_admin_tools/views/index_view.py` |
| `trivy` | `DS026` | 15 | low | `docker/path-usage-exporter.Dockerfile` |
| `trivy` | `DS002` | 15 | high | `docker/path-usage-exporter.Dockerfile` |
| `codeql` | `py/unused-local-variable` | 14 | note | `omeroweb_import/views/core_functions.py` |
| `trivy` | `DS-0002` | 12 | high | `docker/redis-sysctl-init.Dockerfile` |
| `codeql` | `py/unexpected-raise-in-special-method` | 11 | note | `omeroweb_imaris_connector/tests/test_imaris_service_additional.py` |
| `codeql` | `js/syntax-error` | 11 | note | `omero_web_zarr/templates/webclient/annotations/includes/toolbar.html` |
| `trivy` | `DS-0026` | 11 | low | `docker/redis-sysctl-init.Dockerfile` |
| `bandit` | `B310` | 10 | warning | `omeroweb_admin_tools/views/index_view.py` |
| `bandit` | `B103` | 9 | warning | `omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py` |

### Hotspot files across the closed history

| File | Closed alerts |
| --- | ---: |
| `omeroweb_admin_tools/tests/test_resource_monitoring.py` | 200 |
| `omeroweb_import/views/core_functions.py` | 184 |
| `omeroweb_omp_plugin/services/data_store.py` | 116 |
| `omeroweb_upload/views/core_functions.py` | 82 |
| `.github/workflows/security-code-scanning.yml` | 70 |
| `omeroweb_admin_tools/views/index_view.py` | 67 |
| `omeroweb_admin_tools/tests/test_storage_quotas.py` | 59 |
| `omeroweb_upload/tests/test_chunked_upload.py` | 54 |
| `omeroweb_upload/tests/test_auto_skip.py` | 53 |
| `omeroweb_import/services/data_store.py` | 51 |
| `omeroweb_upload/views/index_view.py` | 50 |
| `omeroweb_upload/services/omero/import_service.py` | 39 |
| `omeroweb_omp_plugin/views/index_view.py` | 36 |
| `omeroweb_admin_tools/tests/test_storage_quotas_root_resolution.py` | 32 |
| `omeroweb_admin_tools/tests/test_log_query.py` | 31 |

## DeepSource resolved-occurrence history

- Analysis runs surveyed: 52
- Total occurrences resolved across runs: 310
- Total occurrences introduced across runs: 1347

### Resolved occurrences by analyzer

| Analyzer | Resolved occurrences |
| --- | ---: |
| `python` | 240 |
| `shell` | 58 |
| `javascript` | 12 |
| `docker` | 0 |
| `secrets` | 0 |

### DeepSource currently-open issues at the snapshot

| Shortcode | Title | Severity | Occurrences |
| --- | --- | --- | ---: |
| `secrets/SCT-1000` | Secrets detected in source code | CRITICAL | 4 |
| `secrets/SCT-A000` | Possible hardcoded secrets detected in source code | MINOR | 21 |
| `python/PY-R1000` | Function with cyclomatic complexity higher than threshold | MINOR | 91 |

## Cross-references

- **Anti-regression gate (canonical):** `tools/regression_guard.py` (`scan`, `catalog`, `selfcheck`).
- **Live open alerts:** query via `tools/scanner_inventory.py`; do not trust prose snapshots.
- **Normative coding patterns (reference):** `docs/reference/ai-agent-security-prevention-playbook.md`.
- **Per-rule lessons (reference):** `docs/reference/code-scanning-resolved-findings.md`.
- **Live alert workflow (reference):** `docs/operations/code-scanning.md`.

