# Generated Artifacts: Database Schema

This directory is reserved for generated reference artifacts.

## OMERO plugin database (`database_plugin`)

The OMERO plugin database (`omero-plugin` on port 5433) stores per-user data for OMERO.web plugins, including OMP and Upload. Tables are created on first use via psycopg2 in the plugin `data_store.py` modules.

### Known table patterns

**OMP Plugin (`omeroweb_omp_plugin/services/data_store.py`):**
- Variable sets: per-user named sets of variable configurations (name, regex, separator, variable names).
- AI credentials: per-user, per-provider API key storage.
- User settings: per-user plugin preferences.

**Upload Plugin (`omeroweb_upload/services/data_store.py`):**
- User settings: per-user upload preferences.
- Special method settings: per-user SEM-EDX method configurations.

### OMERO core database (`database`)

The OMERO core database schema is managed by OMERO.server and is not modified by this repository. See the [OMERO documentation](https://omero.readthedocs.io/) for schema details.

No generated schema snapshot is committed at this time. To generate one, connect to the running database and export the schema.
