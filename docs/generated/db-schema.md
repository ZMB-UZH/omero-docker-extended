# Generated Artifacts: Database Schema

This directory is reserved for generated reference artifacts.

## OMERO plugin database (`database_plugin`)

The OMERO plugin database (`omero-plugin` on port 5433) stores per-user data for OMERO.web plugins, including OMP, Import, and Tools enhanced search. Tables are created on first use via psycopg2 in the plugin data-store modules.

### Known table patterns

**OMP Plugin (`omeroweb_omp_plugin/services/data_store.py`):**

- Variable sets: per-user named sets of variable configurations (name, regex, separator, variable names).
- AI credentials: per-user, per-provider API key storage.
- User settings: per-user plugin preferences.

**Import Plugin (`omeroweb_import/services/data_store.py`):**

- User settings: per-user upload preferences.
- Special method settings: per-user SEM-EDX method configurations.

**Tools Plugin (`omeroweb_tools/services/enhanced_search_store.py`):**

- Enhanced-search sync state: per-user opt-in state, refresh timestamps, and sync cursors.
- Metadata index: user-scoped image, scope-membership, key-value, and acquisition metadata rows used for search.
- Saved queries and user settings: per-user search preferences and reusable query payloads.

### OMERO core database (`database`)

The OMERO core database schema is managed by OMERO.server and is not modified by this repository. See the [OMERO documentation](https://omero.readthedocs.io/) for schema details.

No generated schema snapshot is committed at this time. To generate one, connect to the running database and export the schema.
