# OMERO Docker Extended

A complete OMERO deployment for microscopy facilities, with custom research
workflows and the tools needed to operate them together.

## Beyond stock OMERO

Built on OMERO.server and OMERO.web, this project adds:

- **Browser-based imports:** file and folder uploads, chunked large-file
  transfers, background jobs, and specialized SEM-EDX handling.
- **Metadata workflows:** filename-to-annotation parsing, reusable variable
  sets, and optional AI assistance through local or external providers.
- **Enhanced search:** a per-user acquisition-metadata index combined with
  OMERO's built-in search, with permission checks on displayed results.
- **Analysis and viewing integrations:** Imaris 11 export and XT connector
  workflows, plus authenticated access and viewing for supported OME-Zarr data.
- **Operations in one deployment:** Admin Tools, Grafana dashboards, Prometheus
  metrics, Loki logs, PostgreSQL maintenance and configurable storage quotas.

## What each tag contains

Each versioned tag is a **release carrier containing the stack's prebuilt
runtime images**. It is not a standalone OMERO service: deploy it with the
installation tooling from the matching GitHub release. Source, release notes,
checksums and the runtime manifest accompany each release.

Deploy on Linux with persistent storage and operator-managed configuration.
Review the upgrade instructions and validate your formats, permissions and
integrations before production use. Quotas and alternative Zarr workflows
require their documented prerequisites; OMP and Imaris integrations remain
under active development.

[Source and README](https://github.com/ZMB-UZH/omero-docker-extended) |
[Releases and installation bundles](https://github.com/ZMB-UZH/omero-docker-extended/releases) |
[Documentation](https://github.com/ZMB-UZH/omero-docker-extended/blob/main/docs/index.md)
