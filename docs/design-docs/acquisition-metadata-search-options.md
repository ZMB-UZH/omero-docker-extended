# Acquisition Metadata Search Options

Exploratory design document for making acquisition metadata searchable from inside OMERO.web without falling back to `MapAnnotation`/key-value-pair mirroring as the primary product design.

## Problem Statement

Acquisition metadata shown in the OMERO.web right-side "Acquisition" tab is not currently a usable indexed search substrate in this deployment. Users want to find images by acquisition metadata such as microscope system, detector, excitation wavelength, laser settings, objective, pixel size, or acquisition date without relying on manual exports or operator-only scripts.

For this repository, the acceptable end-state is narrowed further:

- `MapAnnotation`/key-value-pair conversion is **not** an acceptable primary solution.
- "Attach metadata as text so Lucene can find words" is also **not** an acceptable primary solution.
- The target should be either:
  - a `new OMERO.web plugin` with a selective acquisition-metadata index, or
  - a `modification of an existing search engine` so that acquisition metadata becomes selectively indexed and searchable.

## Local Starting Point

This repository already contains useful extraction and UI building blocks:

- [`omeroweb_omp_plugin/services/omero/metadata_service.py`](../../omeroweb_omp_plugin/services/omero/metadata_service.py) can extract typed acquisition metadata plus Bio-Formats original metadata from an image.
- [`omeroweb_omp_plugin/views/job_view.py`](../../omeroweb_omp_plugin/views/job_view.py) already has an acquisition-mode job that writes extracted values as `MapAnnotation` key-value pairs.
- The repository already ships OMERO.web plugin infrastructure, Celery-backed job patterns, and a `database_plugin` PostgreSQL database that can support plugin-specific state.

That means the missing piece is not metadata extraction. The missing piece is a private-instance-safe search architecture that:

- selectively indexes acquisition metadata,
- stays usable at scale,
- respects OMERO permissions,
- and does not flood the server with low-value metadata.

## Hard Constraints

- `Search must respect OMERO permissions and group visibility.`
- `Search must be selective, not a dump of all original metadata by default.`
- `Indexing must be opt-in at an admin-controlled scope.` Reasonable scope units are group, project, dataset, import route, or a future user-owned saved profile.
- `Search UX must live inside OMERO.web.` A sidecar API is acceptable only if OMERO.web owns the user-facing workflow.
- `The design must stay host-agnostic and location-agnostic.` No installation-specific paths or host assumptions.
- `Backfill must be bounded.` A design that requires indexing every image and every vendor key on day one is operationally unsafe.

## Why "Index Everything" Is Dangerous

Acquisition/original metadata is unusually risky to index wholesale:

- Vendor metadata is inconsistent across formats and Bio-Formats readers.
- The same conceptual field often appears under many keys with slightly different units or encodings.
- Many original-metadata keys are high-cardinality or effectively unique per acquisition, which degrades facet usefulness and index size.
- Re-indexing in OMERO is background work that can take time and is operationally sensitive.
- The OMERO search documentation explicitly treats indexing as a Lucene-backed subsystem with re-index procedures and operational cost.
  Source: <https://omero.readthedocs.io/en/stable/sysadmins/search.html>

Conclusion: any viable design must enforce a schema budget, indexing budget, and rollout budget.

## Current Upstream Signal

The current upstream/community picture is consistent:

- `2021` Josh Moore: original metadata is not directly searchable because it is not extracted into the OMERO database/index, and a custom search extension could add it but may create substantial overhead.
  Source: <https://forum.image.sc/t/are-omero-original-metadata-searchable/58056>
- `2025` Will Moore: little has changed; OMERO advanced search still cannot search acquisition metadata because it is not currently indexed, and a custom search bridge would require Java work.
  Source: <https://forum.image.sc/t/best-practices-for-metadata-based-image-search-in-omero/112222>
- `2025` Jean-Marie Burel: OME is running a new Elasticsearch-based search engine in production for IDR, but permissions handling is still a blocker for private/authenticated OMERO use.
  Source: <https://forum.image.sc/t/best-practices-for-metadata-based-image-search-in-omero/112222>
- `2025` Will Moore: `ome/omero_search_engine` runs independently of OMERO, is currently focused on indexed metadata records, and is not linked to the OMERO permissions system.
  Sources: <https://forum.image.sc/t/best-practices-for-metadata-based-image-search-in-omero/112222>, <https://github.com/ome/omero_search_engine>
- `2025` Jens Wendt: the updated TagSearch plugin is still the practical recommendation for many users today, with richer metadata search still constrained by available development effort.
  Source: <https://forum.image.sc/t/best-practices-for-metadata-based-image-search-in-omero/112222>
- `2025` Tiago Lubiana: a longer-term RDF/SPARQL route is being explored, but it is not a finished product.
  Sources: <https://forum.image.sc/t/best-practices-for-metadata-based-image-search-in-omero/112222>, <https://github.com/German-BioImaging/omero-rdf>

## External Prior Art

### OMERO Server Search

- OMERO.server uses `Lucene` to index string and timestamp data plus parseable attached files.
- OMERO search has extension points, including search bridges that can parse more metadata entering the system.
- The documented route for extending indexing is therefore real, but it lives on the OMERO.server side and is a Java/search-internals problem, not a simple OMERO.web customization.
  Source: <https://omero.readthedocs.io/en/stable/developers/Modules/Search.html#extension-points>

### OMERO Search Operations

- Re-indexing is an explicit operational workflow with preparation, wipe, reset, and finish steps.
- That is a warning sign against any design that forces frequent wide rebuilds.
  Source: <https://omero.readthedocs.io/en/stable/sysadmins/search.html>

### OMERO.parade and parade-crossfilter

- `ome/omero-parade` is an OMERO.web app for filtering data in the center panel and supports custom filters plus custom data providers.
- `will-moore/parade-crossfilter` is a prototype modernized front-end that explores richer client-side filtering and plots over OMERO-sourced data.
- Parade-style UI is relevant not because it solves acquisition search already, but because it proves the feasibility of a dedicated OMERO.web exploration app backed by a custom metadata provider.
  Sources: <https://github.com/ome/omero-parade>, <https://github.com/will-moore/parade-crossfilter>

### IDR Search Engine

- `ome/omero_search_engine` is a separate Elasticsearch service developed for IDR.
- It supports large-scale search, cross-resource query patterns, asynchronous search, and selective resource queries.
- The main blocker for direct reuse on private OMERO is explicit in the README: it bypasses OMERO authentication and currently assumes indexed data is public.
  Sources: <https://github.com/ome/omero_search_engine>, <https://omero-search-engine.readthedocs.io/en/latest/>

### RDF / SPARQL

- `German-BioImaging/omero-rdf` demonstrates active work toward RDF export from OMERO.
- This is relevant as a longer-term metadata-integration direction, not as an immediate product-ready OMERO.web search answer.
  Source: <https://github.com/German-BioImaging/omero-rdf>

## Shared Design Rules For Any Acceptable Plan

All acceptable plans should use the same selective-index contract.

### 1. Schema Manifest

Maintain an explicit acquisition-search schema manifest that classifies fields as:

- `facet`
- `range`
- `exact`
- `full_text`
- `display_only`
- `drop`

Examples of likely keepers:

- microscope/instrument model
- objective model
- objective magnification
- objective NA
- detector model
- excitation wavelength
- emission wavelength
- laser line
- pixel size
- z-step
- acquisition date/time
- channel label

Examples of likely drops:

- volatile vendor diagnostics
- per-plane counters
- low-level importer internals
- keys that are effectively unique per file and therefore useless as search facets

### 2. Scope Control

Indexing should be opt-in at one or more of these scopes:

- OMERO group
- project
- dataset
- import workflow/profile
- future saved admin policy

Do not default to "all images on the server".

### 3. Cardinality Guardrails

Each indexed field should declare:

- expected value type,
- maximum allowed cardinality for faceting,
- whether it is safe for aggregation,
- and whether it should be searchable only as exact/range, not as a facet.

### 4. Permission Model

The search layer should never trust stale visibility alone. It should use one of these patterns:

- `index ACL facts + re-check OMERO permissions at result hydration time`
- `filter through OMERO session-aware APIs before showing results`

### 5. Backfill and Freshness

All plans need:

- bounded backfill jobs,
- resumable indexing,
- per-image sync status,
- schema-version tagging,
- and rate limits so normal OMERO use is not starved by metadata indexing.

## Feasibility Summary

| Plan | Summary | Feasibility | Main Advantage | Main Risk |
| --- | --- | --- | --- | --- |
| A | New OMERO.web plugin backed by a selective PostgreSQL acquisition index | High | Best fit for private/authenticated deployments and strongest control over permissions | More application code to build and own |
| B | New OMERO.web plugin backed by a selective OpenSearch/Elasticsearch sidecar | Medium-High | Best scalability and future faceting/query power | Additional operational surface and sync complexity |
| C | Modify `ome/omero_search_engine` for authenticated/private selective acquisition search | Medium | Reuses an actively developed upstream search service | Requires substantial permission and ingestion redesign |
| D | Extend OMERO.server search bridge / Lucene indexing for acquisition metadata | Medium-Low | Reuses OMERO core search infrastructure | Java-side maintenance burden and weaker UX/faceting |
| E | RDF/SPARQL exploration track | Low for near-term productization | Powerful long-term semantic search possibilities | Not product-ready for this repository today |

## Recommendation

Recommended near-term path: **Plan A**.

Recommended scale-out path if Plan A proves too limited: **Plan B**.

Why:

- Both plans can be made private-instance-safe from the start.
- Both plans support selective indexing instead of server-wide metadata dumps.
- Both plans allow a purpose-built OMERO.web acquisition-search experience instead of forcing users to learn Lucene syntax.
- Plan A minimizes moving parts and is the easiest route to "rock-solid on a private OMERO deployment".
- Plan B is the best step if cross-resource search, richer faceting, or search-volume growth justify a dedicated search service.

Plans C and D are real but should be treated as `investigation-heavy engineering tracks`, not as the first implementation.

## Plan A: New OMERO.web Plugin + Selective PostgreSQL Acquisition Index

### Short Summary

Build a new OMERO.web plugin such as `omeroweb_acquisition_search` and back it with a selective acquisition-search schema in the plugin PostgreSQL database. Use OMERO APIs for metadata extraction and OMERO session-aware result validation.

### Architecture

1. Add a new plugin with a dedicated search page and saved-query model.
2. Persist selectively indexed acquisition fields into dedicated PostgreSQL tables.
3. Keep one row per image for common scalar fields and auxiliary tables for repeated channel or detector fields.
4. Run extraction and indexing asynchronously through the existing repo job/Celery patterns.
5. On query, filter candidate rows by stored scope and ownership facts, then rehydrate through OMERO for final permission-safe results.

### Data Model

Suggested tables:

- `acquisition_search_image`
  Image id, group id, owner id, schema version, indexed-at timestamp, core scalar fields
- `acquisition_search_channel`
  Per-image channel rows
- `acquisition_search_attribute`
  Sparse exact/range fields that do not justify dedicated columns
- `acquisition_search_sync_state`
  Last extraction time, last successful index time, error state, retry count
- `acquisition_search_saved_query`
  User-owned saved filters for repeat searches

### Selective Indexing Strategy

Keep two separate concepts:

- `extractable metadata`
  What `metadata_service.py` can read
- `searchable metadata`
  What the schema manifest allows into the index

That separation is critical. Most extracted metadata should remain display-only unless it proves useful as a filter.

### UX Model

The plugin should present:

- fielded filters,
- numeric ranges,
- date ranges,
- channel-aware filters,
- saved searches,
- and a concise result view linking back to OMERO.web images, datasets, and projects.

This is a better product fit than bolting acquisition search onto the existing generic advanced-search UI.

### Operational Guardrails

- Admin can enable indexing only for named groups/projects/datasets.
- Backfill runs in batches and can pause/resume.
- Field-level metrics record cardinality and query hit rates.
- High-cardinality fields can be demoted from `facet` to `exact` without reworking the UI contract.

### Acceptance Criteria

- Users can search at least 10 to 20 agreed acquisition fields inside OMERO.web.
- Queries return only objects the user is allowed to see.
- Indexing can be turned on for one pilot group/project without touching the rest of the server.
- Re-running extraction/indexing is idempotent.
- No host-specific paths or installation-local assumptions appear in code or docs.

### Strengths

- Strongest control over permission handling.
- Best match to this repository's existing Django/plugin architecture.
- Fastest path to an opt-in private-instance-safe MVP.

### Weaknesses

- More custom application code than reusing core OMERO search.
- PostgreSQL can support this well for a selective schema, but it is not the best fit for very broad free-text search across arbitrarily shaped metadata.

### Feasibility Judgment

High. This is the recommended first implementation.

## Plan B: New OMERO.web Plugin + Selective OpenSearch/Elasticsearch Sidecar

### Short Summary

Build the same OMERO.web acquisition-search plugin, but back it with a dedicated selective search index in OpenSearch or Elasticsearch instead of PostgreSQL.

### Architecture

1. Add a sidecar search service with one acquisition document per image.
2. Index only the curated acquisition schema, not all original metadata.
3. Keep ACL-relevant fields in the search document, but still validate access through OMERO-aware logic before final display.
4. Query the sidecar from the plugin backend, not directly from the browser.

### Document Shape

Suggested indexed fields:

- `image_id`
- `group_id`
- `owner_id`
- `indexed_schema_version`
- `instrument.*`
- `objective.*`
- `detector.*`
- `channels[]`
- `physical_pixel_size.*`
- `acquisition_time`
- `index_policy_id`

### When This Is Worth It

Choose this plan if the intended product needs:

- large-scale faceting,
- search across many groups/projects,
- advanced multi-field filtering,
- future synonym handling,
- or long-term ranking/query sophistication beyond what PostgreSQL should comfortably own.

### Key Engineering Requirement

Do **not** copy the IDR deployment model blindly. The search service must be private-instance-safe:

- no direct public search endpoint,
- no assumption that indexed data is public,
- OMERO session-aware authentication at the plugin/backend boundary,
- and result-level permission checks.

### Strengths

- Best long-term search ergonomics and scalability.
- Clean separation between OMERO extraction and search serving.
- Easy to extend later with autocomplete, aggregations, and richer drill-downs.

### Weaknesses

- More infrastructure and operational burden.
- Higher sync complexity than PostgreSQL.
- ACL drift becomes a real risk if permission checks are not designed carefully.

### Feasibility Judgment

Medium-High. Best second step if Plan A hits scale or UX limits.

## Plan C: Modify `ome/omero_search_engine` For Authenticated Private Acquisition Search

### Short Summary

Fork or contribute to `ome/omero_search_engine` so it can selectively ingest acquisition metadata and operate safely for private OMERO deployments.

### Why This Is Attractive

The engine already has:

- a real query model,
- asynchronous search,
- cross-resource design,
- and production use at IDR scale.

It also already stores fields such as `owner_id`, `group_id`, and `permissions` in its Elasticsearch mappings, which shows the data model is not the blocker.

### Why This Is Not Ready As-Is

Per the upstream README and forum guidance:

- it is not linked to OMERO permissions,
- it assumes indexed data is public,
- and its current focus is on already-available indexed metadata records rather than private-instance acquisition-search workflows.

### Required Work

1. Add a private-instance-safe authentication boundary tied to OMERO sessions.
2. Add a selective acquisition-metadata ingestion layer using OMERO APIs or controlled SQL extraction plus schema manifest rules.
3. Add OMERO.web plugin pages in this repository so the UI lives inside OMERO.web.
4. Add ACL invalidation/rebuild semantics whenever group membership or visibility changes.

### Strengths

- Reuses the strongest existing OME search backend.
- Gives a path toward cross-resource search if that becomes important later.

### Weaknesses

- Heavy engineering lift before it is acceptable for a private deployment.
- The permission model is the hardest part, not the indexing itself.
- This repository would either own a fork or depend on upstream features that do not exist yet.

### Feasibility Judgment

Medium. Viable only if the project explicitly wants to invest in hardening a separate search service.

## Plan D: Extend OMERO.server Search Bridge / Lucene Indexing

### Short Summary

Modify OMERO’s search-bridge layer so selective acquisition metadata becomes part of OMERO’s Lucene index, then add a lightweight OMERO.web UI wrapper for acquisition-specific queries.

### Why This Exists

The OMERO search documentation explicitly documents search bridges as an extension point for parsing more metadata entering the system.
Source: <https://omero.readthedocs.io/en/stable/developers/Modules/Search.html#extension-points>

### Why This Is Hard

- This is Java-side OMERO.server work, not a normal plugin-only change.
- It couples the design to OMERO search internals and version behavior.
- Even if indexing succeeds, the user-facing OMERO.web search experience remains less structured than a purpose-built acquisition-search plugin.
- Large selective re-indexing still remains an operational concern.

### Best Use Of This Plan

Treat it as a narrowly scoped spike if the project wants to prove:

- that selective acquisition fields can be indexed directly in OMERO core,
- and that the resulting query behavior is good enough to justify the maintenance burden.

### Feasibility Judgment

Medium-Low. Real, but not the recommended first implementation.

## Plan E: RDF / SPARQL Exploration Track

### Short Summary

Export OMERO metadata into RDF and support metadata exploration through SPARQL or SPARQL-backed guided search UIs.

### Why Mention It

This is an interesting future direction for:

- ontology-aware metadata integration,
- federation across repositories,
- and richer semantics than fixed field/filter search.

### Why It Is Not The Product Plan

- It is not a drop-in OMERO.web search answer today.
- It introduces a much larger conceptual and operational surface.
- It is better treated as a research track than a repository roadmap deliverable.

### Feasibility Judgment

Low for near-term delivery.

## Suggested Delivery Sequence

### Phase 0: Discovery And Guardrails

1. Lock the acquisition-search schema manifest.
2. Classify fields into `facet`, `range`, `exact`, `full_text`, `display_only`, and `drop`.
3. Pick one pilot group/project with real user demand.
4. Measure extraction coverage and metadata shape on that pilot scope only.

### Phase 1: Recommended MVP

1. Implement `Plan A`.
2. Support only 10 to 20 high-value fields.
3. Add opt-in scope controls and resumable indexing.
4. Pilot with one user group and collect actual query patterns.

### Phase 2: Product Hardening

1. Add saved searches and admin metrics.
2. Tune cardinality and field classes using real usage.
3. Add incremental refresh hooks for new imports.
4. Decide whether PostgreSQL remains sufficient.

### Phase 3: Scale Decision

If the plugin-backed PostgreSQL index starts to limit UX or performance:

- move to `Plan B`, or
- explicitly invest in `Plan C` if alignment with upstream OME search-engine work becomes strategic.

## Concrete Recommendation For This Repository

If the goal is "professional, private-instance-safe acquisition metadata search inside OMERO.web", the repository should pursue:

1. `Plan A` as the implementation roadmap.
2. `Plan B` as the scale-out contingency.
3. `Plan C` only if there is appetite to help harden the upstream IDR search engine for authenticated OMERO deployments.
4. `Plan D` only as a controlled spike, not as the default roadmap.

That sequencing minimizes operational risk, avoids the unacceptable key-value-pair end-state, and keeps the solution selective, opt-in, and maintainable.
