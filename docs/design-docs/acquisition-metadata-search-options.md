# Acquisition Metadata Search Options

Exploratory design document for making acquisition metadata searchable from inside OMERO.web.

## Problem Statement

Assumption for this design: acquisition metadata shown in the OMERO.web right-side "Acquisition" tab is not currently a usable indexed search substrate in this deployment. Users need to search by acquisition metadata directly inside OMERO.web without relying on ad-hoc scripts or external manual exports.

## Local Starting Point

This repository already contains two useful building blocks:

- [`omeroweb_omp_plugin/services/omero/metadata_service.py`](../../omeroweb_omp_plugin/services/omero/metadata_service.py) can extract typed acquisition metadata plus Bio-Formats original metadata from an image.
- [`omeroweb_omp_plugin/views/job_view.py`](../../omeroweb_omp_plugin/views/job_view.py) already has an acquisition-mode job that writes extracted values as `MapAnnotation` key-value pairs.
- [`env/omeroweb.env`](../../env/omeroweb.env) already enables `omero_mapr` and exposes a `Mapr` top link in OMERO.web.

That means the platform does not need a greenfield search system. The key design question is where to normalize acquisition metadata, how much to normalize, and which OMERO.web search surface should expose it.

## External Prior Art

The main patterns found online cluster into three families:

1. Normalize metadata into `MapAnnotation`s and expose it through OMERO.mapr.
2. Mirror metadata into text attachments or custom indexed fields and use OMERO full-text search.
3. Build a dedicated OMERO.web search plugin backed by a separate metadata index.

Key source findings:

- OMERO search uses Lucene and indexes string/timestamp fields plus parseable file contents. It also creates dynamic fields for `MapAnnotation` named values and a `has_key` field for keys.
  Source: <https://omero.readthedocs.io/en/stable/developers/Modules/Search.html>
- OMERO indexing runs automatically in the background and can lag or require re-index operations after schema/index changes.
  Source: <https://omero.readthedocs.io/en/stable/sysadmins/search.html>
- OMERO.mapr is specifically designed to browse data through attributes linked as `MapAnnotation`s and is heavily used by IDR.
  Sources: <https://github.com/ome/omero-mapr>, <https://idr.openmicroscopy.org/about/curation-workflow.html>
- IDR operationally populates mapr categories through `omero metadata populate --context bulkmap`, which is strong evidence that "normalize first, search second" is the dominant OMERO pattern for rich metadata search.
  Source: <https://idr.openmicroscopy.org/about/curation-workflow.html>
- OMERO.web supports both right-panel tabs and other plugin surfaces, so a dedicated acquisition-search UI can be added without patching core OMERO.web navigation patterns.
  Source: <https://omero.readthedocs.io/en/v5.6.10/developers/Web/WebclientPlugin.html>
- There is community precedent for converting original metadata into indexed surrogates, including attaching original metadata as text specifically to make it searchable.
  Source: <https://gist.github.com/will-moore/d49252600b4a3dce26468012f6fcfe3b>

## Design Constraints

- Vendor/original metadata keys are inconsistent across file formats and Bio-Formats readers.
- Search must respect OMERO permissions and group visibility.
- A practical design must keep index freshness manageable for large backfills and new imports.
- The solution should not flood images with low-value noisy metadata unless there is an explicit normalization policy.
- Search UX should live inside OMERO.web, not in a separate operator-only tool.

## Feasibility Summary

| Option | Summary | Feasibility | Main Advantage | Main Risk |
| --- | --- | --- | --- | --- |
| A | Normalize acquisition metadata into namespaced `MapAnnotation`s and search via MAPR | High | Reuses existing repo code and shipped plugin | Requires schema curation and category design |
| B | Build a dedicated search index in `database_plugin` plus custom OMERO.web search UI | Medium-High | Best control over schema, faceting, ranking, saved queries | More code and sync logic |
| C | Mirror metadata into OMERO full-text search via text/file or custom search bridge | Medium | Smallest conceptual delta from OMERO core search | Weakest faceting and hardest UX to make pleasant |

## Recommendation

Recommended path: **Option A first**, with Option B reserved for a second phase if MAPR-based faceting proves too rigid.

Why:

- The repository already extracts acquisition metadata and already ships MAPR.
- The OMERO ecosystem already treats map-annotation normalization as the standard route for rich metadata browsing.
- This keeps the first implementation inside OMERO/OMERO.web without adding a separate query backend.

## Option A: Normalized MapAnnotations + OMERO.mapr

### Short Summary

Normalize a curated subset of acquisition metadata into a dedicated `MapAnnotation` namespace, then expose it through MAPR and a small acquisition-oriented entry point in OMERO.web.

### Architecture

1. Extend the existing acquisition extraction logic to produce a curated normalized schema, not a raw dump.
2. Write those normalized values as one or more dedicated namespaced `MapAnnotation`s per image.
3. Configure MAPR categories and namespace mappings for the chosen acquisition fields.
4. Add a focused OMERO.web entry point for acquisition search, either as:
   - a top link into MAPR with a default acquisition query, or
   - a small OMERO.web plugin page that redirects into curated MAPR categories.

### Data Model

Use two layers:

- `normalized acquisition fields`
  Examples: `instrument_manufacturer`, `instrument_model`, `objective_magnification`, `objective_na`, `detector_model`, `channel_0_name`, `channel_0_excitation_nm`, `acquisition_date`, `pixel_size_x_um`, `pixel_size_y_um`, `z_step_um`
- `raw passthrough fields`
  Only for selected high-value vendor keys that users explicitly want searchable

Namespace strategy:

- Use one dedicated namespace for the normalized search schema, e.g. `openmicroscopy.org/mapr/acquisition`
- Keep raw or debugging-only payloads out of the search namespace

### Detailed Plan

1. Define the search schema.
   Output: a controlled field list, canonical names, units, allowed value shapes, and rules for missing/multi-valued fields.
2. Audit current extraction coverage.
   Compare what [`metadata_service.py`](../../omeroweb_omp_plugin/services/omero/metadata_service.py) can already emit against the target schema by format family.
3. Split extraction into two outputs.
   One output becomes "normalized searchable acquisition metadata"; the other remains "raw/unbounded diagnostic metadata".
4. Add idempotent write/update behavior.
   Existing acquisition-search annotations should be updated or replaced deterministically, not appended forever.
5. Configure MAPR categories.
   Add category definitions for the chosen namespace and decide which fields are searchable, displayed, hidden, or linked.
6. Backfill existing data.
   Add a dataset/project/group scoped backfill job so operators can populate searchable acquisition metadata for legacy images.
7. Hook new imports.
   Run normalization after import confirmation or as a background follow-up step so new images become searchable automatically.
8. Add OMERO.web entry points.
   Keep the default MAPR top link, but add acquisition-oriented saved searches or a small "Acquisition Search" launcher page.
9. Validate performance and re-index behavior.
   Measure index lag, MAPR page load times, and category-cardinality impact on representative projects.

### Acceptance Criteria

- A user can search inside OMERO.web for at least 10 agreed acquisition fields.
- Search returns only objects the user is allowed to see.
- Backfill and re-run are idempotent.
- No image accumulates duplicate acquisition-search annotations from repeated runs.

### Strengths

- Fastest route to useful in-web search.
- Reuses existing repository code and shipped OMERO.web plugins.
- Aligns with IDR/OMERO community practice.

### Weaknesses

- Requires careful schema curation up front.
- MAPR works best with stable categories, less well with very free-form metadata.
- Cross-format normalization work is the main engineering cost.

### Feasibility Judgment

High. This is the strongest near-term option.

## Option B: Dedicated Plugin Index in `database_plugin` + Custom Acquisition Search UI

### Short Summary

Build a dedicated OMERO.web acquisition-search page backed by denormalized search tables in `database_plugin`, optimized for structured filtering, ranking, and saved queries.

### Architecture

1. Extract acquisition metadata from OMERO images into a dedicated denormalized search table in `database_plugin`.
2. Store one row per image plus auxiliary tables for repeated values, channels, and search facets.
3. Expose search through a purpose-built OMERO.web plugin page with structured filters and result links back into OMERO.web objects.

### Data Model

Possible table split:

- `acquisition_search_image`
  Core image id, group id, owner id, indexed-at timestamp, common scalar fields
- `acquisition_search_channel`
  Per-image repeated channel attributes
- `acquisition_search_kv`
  Sparse fallback store for lower-frequency normalized keys
- `acquisition_search_sync_state`
  Sync cursor, error state, retry state, schema version

### Detailed Plan

1. Define the query model first.
   Decide which searches matter: exact match, range filters, multi-select facets, free text, channel-aware filters.
2. Design the storage schema for those queries.
   Keep common fields columnar for speed; use sparse auxiliary rows for rarer fields.
3. Build a sync pipeline.
   Support initial backfill, incremental refresh, deletion handling, and retry/error reporting.
4. Build permission-aware result filtering.
   Either pre-store group ownership and re-check OMERO permissions at query time, or materialize only enough metadata to rehydrate and validate through OMERO.
5. Implement the OMERO.web UI.
   Use a dedicated acquisition search page with saved filters, pagination, and deep links to datasets/images.
6. Add operator controls.
   Backfill status, last-sync metrics, schema version, rebuild control.
7. Add import hooks.
   Ensure new uploads/imports schedule indexing work automatically.

### Acceptance Criteria

- Users can combine filters such as microscope model, objective, channel fluor, acquisition date range, and pixel size.
- Search latency stays predictable even for high-cardinality fields.
- A full rebuild is operationally documented and bounded.

### Strengths

- Best UX and query flexibility.
- Cleaner separation between searchable schema and OMERO annotation surface.
- Easier to support numeric/range filters well.

### Weaknesses

- Most engineering effort.
- Requires lifecycle management for sync drift, rebuilds, and schema migrations.
- Duplicates metadata outside OMERO core storage.

### Feasibility Judgment

Medium-High. Strong if the project wants a productized search experience rather than adapting MAPR.

## Option C: OMERO Full-Text Search Mirror

### Short Summary

Mirror normalized acquisition metadata into OMERO’s existing search substrate, then wrap that indexed content with a small OMERO.web query helper or advanced search surface.

### Architecture

Two variants:

- `text mirror`: attach normalized or raw acquisition metadata as searchable text/file content
- `search bridge`: extend OMERO indexing to emit more custom fields directly into Lucene

The OMERO.web front-end can then use either the existing search surface or a small custom page that translates form fields into Lucene-style queries.

### Detailed Plan

1. Choose the minimum viable mirror.
   Start with attached text payloads if the goal is proving searchability quickly.
2. Normalize query-critical fields into deterministic text tokens.
   Example: `instrument_model=LSM980`, `objective_na=1.4`, `channel_name=DAPI`.
3. Attach or update the searchable payload on each image.
4. Validate OMERO indexer throughput and lag under backfill.
5. Add an OMERO.web query helper UI.
   Users should not be asked to type raw Lucene field syntax unless explicitly in an advanced mode.
6. If text payloads prove insufficient, prototype a custom search bridge for more direct field-level indexing.

### Acceptance Criteria

- Search works inside OMERO.web without MAPR.
- Re-indexing behavior is documented and testable.
- Queries for high-value fields are stable and reproducible.

### Strengths

- Leans on OMERO core indexing.
- Can be piloted quickly for a proof of concept.
- Useful as a bridge or spike before a richer UI.

### Weaknesses

- Faceting, category browsing, and structured filtering are weak compared with MAPR or a dedicated UI.
- Search syntax becomes harder for end users unless heavily wrapped.
- Search-bridge customization is more invasive and harder to maintain.

### Feasibility Judgment

Medium. Good as a spike, weaker as the final user-facing solution.

## Suggested Delivery Sequence

### Phase 0: Discovery

- Lock the normalized acquisition schema.
- Pick 10 to 20 fields that actually matter to users.
- Measure current extraction quality by file format.

### Phase 1: Recommended MVP

- Implement Option A for a constrained field set.
- Backfill one representative project and one representative screen.
- Validate MAPR usability with real users.

### Phase 2: Expansion

- Add more normalized fields only after usage data confirms value.
- Decide whether MAPR remains sufficient or whether Option B is justified.
