# OMP Plugin Guide (`omeroweb_omp_plugin`)

## Purpose

The OMP plugin provides a workflow for parsing scientific image filenames into structured metadata variables, previewing parsed values, and writing OMERO MapAnnotation key-value pairs with controlled background job execution.

## Main capabilities

- Project and dataset selection for target images.
- Filename parsing via configurable regex patterns with separator detection.
- AI-assisted parsing support (OpenAI, Anthropic, Google, Mistral) for regex suggestions and value extraction.
- Variable set save/load/delete with per-user PostgreSQL persistence in `database_plugin`.
- Progress-tracked background jobs for metadata writing and deletion.
- Hash-based annotation ownership for safe plugin-only deletion (`omp_hash` / `omphash_v1:` prefix).
- Per-user rate limiting on major actions (6 actions / 60 seconds).
- REMBI-aligned default variable names with scientific nomenclature-aware hyphen protection.
- User data management: AI credentials, variable sets, user settings.

## Key routes

| Route | Method | Purpose |
|---|---|---|
| `/omeroweb_omp_plugin/` | GET | Main plugin page |
| `/omeroweb_omp_plugin/projects/` | GET | List accessible projects and datasets |
| `/omeroweb_omp_plugin/root-status/` | GET | Check if current user is OMERO root |
| `/omeroweb_omp_plugin/start_job/` | POST | Start metadata write job |
| `/omeroweb_omp_plugin/start_acq_job/` | POST | Start acquisition metadata job |
| `/omeroweb_omp_plugin/start_delete_all_job/` | POST | Start delete-all annotations job |
| `/omeroweb_omp_plugin/start_delete_plugin_job/` | POST | Start delete plugin-owned annotations job |
| `/omeroweb_omp_plugin/progress/<job_id>/` | GET | Poll job progress |
| `/omeroweb_omp_plugin/varsets/` | GET | List saved variable sets |
| `/omeroweb_omp_plugin/varsets/save/` | POST | Save a variable set |
| `/omeroweb_omp_plugin/varsets/load/` | POST | Load a variable set |
| `/omeroweb_omp_plugin/varsets/delete/` | POST | Delete a variable set |
| `/omeroweb_omp_plugin/ai-credentials/` | GET | List AI provider credentials |
| `/omeroweb_omp_plugin/ai-credentials/save/` | POST | Save AI credentials |
| `/omeroweb_omp_plugin/ai-credentials/test/` | POST | Test AI provider connectivity |
| `/omeroweb_omp_plugin/ai-credentials/models/` | GET | List available AI models |
| `/omeroweb_omp_plugin/user-settings/save/` | POST | Save user preferences |
| `/omeroweb_omp_plugin/user-data/delete-api-keys/` | POST | Delete stored API keys |
| `/omeroweb_omp_plugin/user-data/delete-variable-sets/` | POST | Delete all variable sets |
| `/omeroweb_omp_plugin/user-data/delete-all/` | POST | Delete all user data |
| `/omeroweb_omp_plugin/help/` | GET | Serve plugin help documentation (Markdown) |

## Typical user workflow

1. Open plugin page at `/omeroweb_omp_plugin/`.
2. Select a project; datasets and image filenames load automatically.
3. Configure parser: choose separator, define variable names, optionally use AI to suggest regex.
4. Run preview parsing to verify extraction matches expected values.
5. Start metadata write job. Monitor progress via the progress endpoint.
6. Optionally save the variable set configuration for reuse.
7. Optionally persist user settings (default separator, preferred AI provider).

## Code structure

```
omeroweb_omp_plugin/
├── views/
│   ├── index_view.py          # Main page, project listing, root status
│   ├── job_view.py            # Job start (write, acq, delete-all, delete-plugin), progress
│   ├── save_keyvaluepairs_view.py  # MapAnnotation write logic
│   ├── delete_all_view.py     # Delete all annotations from images
│   ├── delete_plugin_view.py  # Delete only plugin-owned annotations (hash-verified)
│   ├── variable_set_view.py   # Variable set CRUD
│   ├── ai_credentials_view.py # AI credential management and provider testing
│   ├── user_data_view.py      # Bulk user data deletion
│   ├── user_settings_view.py  # User preference persistence
│   └── help_view.py           # Help Markdown download
├── services/
│   ├── core.py                # Backward compatibility layer
│   ├── data_store.py          # PostgreSQL persistence (variable sets, credentials, settings)
│   ├── ai_assist.py           # AI-powered parsing orchestration
│   ├── ai_providers.py        # Provider-specific API clients (OpenAI, Anthropic, Google, Mistral)
│   ├── filename_utils.py      # Separator detection and regex generation
│   ├── http_utils.py          # HTTP client helpers
│   ├── rate_limit.py          # Per-user rate limiting
│   ├── job_cleanup.py         # Stale job file cleanup
│   ├── jobs/job_storage.py    # Job file I/O with portalocker
│   ├── omero/annotation_service.py  # MapAnnotation creation/deletion
│   ├── omero/image_service.py       # Image and filename retrieval
│   ├── omero/metadata_service.py    # Metadata query and manipulation
│   └── parsing/filename_parser.py   # Regex-based filename parsing engine
├── constants.py               # Configuration constants, default variables, hash parameters
├── strings/errors.py          # All error message functions
└── strings/messages.py        # All user-facing message functions
```

## Access and safety

- Plugin checks project/image access constraints via OMERO permissions.
- Rate limiting applies to major actions (job starts, bulk deletes) to reduce misuse risk.
- AI credential handling is isolated in per-user plugin database storage.
- Annotation deletion uses hash verification: only annotations created by this plugin (matching `omp_hash` key) can be deleted via the "delete plugin" action.
- The "delete all" action requires explicit confirmation and removes all MapAnnotations regardless of origin.

## Environment variables

Key variables in `env/omeroweb.env`:

- `OMERO_WEB_ROOT`, `OMERO_WEB_VENV` -- OMERO.web installation paths
- `OMP_DATA_USER`, `OMP_DATA_PASS`, `OMP_DATA_HOST`, `OMP_DATA_PORT`, `OMP_DATA_DB` -- Plugin database connection
- `FMP_HASH_SECRET` -- Optional HMAC secret for annotation ownership hashing

## Operator checklist

- Verify plugin is listed in `CONFIG_omero_web_apps` in `env/omeroweb.env`.
- Verify route loads with authenticated user at `/omeroweb_omp_plugin/`.
- Verify plugin database connectivity (`database_plugin` on port 5433).
- Validate write operations on test datasets before broad rollout.
- Review logs for parser and job execution anomalies.
- If using AI features, verify at least one AI provider credential is saved and tests successfully.
