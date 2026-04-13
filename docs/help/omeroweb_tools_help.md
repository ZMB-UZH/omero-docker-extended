# OMERO.web Help — Tools (`omeroweb_tools`)

## Overview

Tools is the user-facing utility area in OMERO.web. The first available tool is
`Enhanced search`, which lets regular users search a selective metadata index
stored in the plugin database.

## Access model

- Intended for **regular OMERO users**.
- Root is intentionally blocked from running searches, saving queries, or
  refreshing the index.
- Search results are always rechecked through OMERO before they are shown.

## What Enhanced search does

- Searches a selective PostgreSQL index built from configured groups, projects,
  or datasets.
- Supports free-text search plus fielded filters for instrument, detector,
  objective, acquisition date, channel metadata, and pixel sizes.
- Lets each user save and reopen their own searches.
- Shows per-scope index status and refresh progress.

## Data handling

- Indexed rows, sync state, and saved queries are written only to the plugin
  database.
- The core OMERO PostgreSQL database is not used as a write target for this
  feature.
- OMERO itself is queried only to read metadata during indexing and to
  revalidate result visibility during search.

## Typical workflow

1. Open `Tools` from the OMERO.web top navigation.
2. Open `Enhanced search`.
3. Choose a configured indexed scope, or search across all enabled scopes.
4. Add free-text or fielded filters.
5. Run the search and open matching Project, Dataset, or Image links in
   OMERO.web.
6. Save useful queries for repeat use.

## Troubleshooting

- **No scopes are available**: ask an operator to configure
  `TOOLS_ENHANCED_SEARCH_SCOPES` and restart the `omeroweb` service.
- **Refresh index fails**: check the `tools-celery-worker` logs and confirm the
  OMERO API and plugin database are reachable from the `omeroweb` container.
- **Search returns fewer rows than expected**: OMERO permission revalidation may
  remove indexed matches that are no longer visible to your account.
- **Root is blocked**: this is intentional; use a normal OMERO user account for
  this plugin.

## Best practices

- Keep indexed scopes selective instead of indexing every accessible object.
- Refresh a scope after major import or metadata-ingestion changes.
- Use saved queries for common microscope, detector, or acquisition filters.
