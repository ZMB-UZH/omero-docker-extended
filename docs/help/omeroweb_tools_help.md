# OMERO.web Help — Tools (`omeroweb_tools`)

## Overview

Tools is the user-facing utility area in OMERO.web. The first available tool is
`Enhanced search`, which lets regular users search OMERO's built-in search
results together with a selective acquisition-metadata index stored in the
plugin database.

## Access model

- Intended for **regular OMERO users**.
- Root is intentionally blocked from running searches, saving queries, or
  refreshing the index.
- Search results are always rechecked through OMERO before they are shown.

## What Enhanced search does

- Supports the `OMERO index`, `Acquisition metadata`, and `All indexed
  scopes` search modes.
- Supports a compact search form with a search box, typed `Start date` /
  `End date` filters, a popup calendar with month/year selectors, and async
  image previews in the results table.
- Lets each user opt in to acquisition metadata indexing for all images they
  own; the checkbox saves immediately when it is toggled.
- Lets each user save and reopen their own searches.
- Shows acquisition-index status and refresh progress for the current user.

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
3. Enable acquisition metadata indexing if you want acquisition metadata for
   your images to be indexed in the background.
4. Choose an indexed scope, then add a search term or acquisition-date filter.
5. Run the search and open matching Project, Dataset, or Image links in
   OMERO.web.
6. Save useful queries for repeat use.

## Troubleshooting

- **Refresh index fails**: check the `tools-celery-worker` logs and confirm the
  OMERO API and plugin database are reachable from the `omeroweb` container.
- **Acquisition results do not appear yet**: enable acquisition metadata
  indexing for your user account and wait for the background indexer to finish.
- **The indexing checkbox is disabled with a database warning**: the plugin
  database is not currently reachable, so the page cannot safely read or save
  your per-user indexing setting.
- **Search returns fewer rows than expected**: OMERO permission revalidation may
  remove indexed matches that are no longer visible to your account.
- **Root is blocked**: this is intentional; use a normal OMERO user account for
  this plugin.

## Best practices

- Enable acquisition metadata indexing only for accounts that actually need it.
- Use saved queries for common acquisition searches.
- Use `All indexed scopes` when you want OMERO-index and acquisition-index
  results together.
