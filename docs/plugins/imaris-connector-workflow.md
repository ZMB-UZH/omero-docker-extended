# Imaris Connector Plugin Workflow

This document describes the complete control flow for the OMERO-to-Imaris
connector. It covers the Imaris XT client (`omero_imaris_connector/XTOmeroConnector.py`), the custom
`omero_imaris_connector` server endpoint, converter detection, selected-image
download behavior, local Imaris conversion, same-session Imaris handoff, and the
main failure boundaries.

The connector exposes two user-facing converter choices when the relevant
capabilities are present:

- `OMERO`: a custom server-side IMS export provided by this repository.
- `Imaris`: a host-side conversion path that uses standard OMERO.web selected
  Image ID export, then converts that export with the locally installed Imaris
  converter.

`OMERO` is intentionally hidden unless the connected OMERO.web instance returns
the repository-specific custom capability flag. `Imaris` is intentionally
independent of that custom server capability.

## Top-level workflow

```mermaid
flowchart TD
    A[Start Imaris XT extension] --> B[Load connector settings.env]
    B --> C[Discover local Imaris handoff support]
    C --> D[User connects to OMERO.web]
    D --> E[Authenticate with OMERO.web session cookies]
    E --> F[Load projects, datasets, and images through OMERO.web API]
    F --> G[Detect converter capabilities]
    G --> H{Available converters}
    H -->|OMERO only| I[Show OMERO option]
    H -->|Imaris only| J[Show Imaris option]
    H -->|Both| K[Show OMERO and Imaris options]
    H -->|None| L[Hide converter dropdown and disable load]
    I --> M[User selects image or images]
    J --> M
    K --> M
    M --> N[Validate local output folder]
    N --> O[Validate selected converter is still available]
    O --> P[Confirm load]
    P --> Q{Selected converter}
    Q -->|OMERO| R[Run custom server-side IMS export]
    Q -->|Imaris| S[Run standard selected-image export plus local ImarisConvert]
    R --> T[Validate IMS file signature]
    S --> T
    T --> U[Open IMS in current Imaris session]
```

## Capability detection

Capability detection is performed after a successful OMERO.web login and before
the converter dropdown is populated.

```mermaid
flowchart TD
    A[Authenticated OMERO.web client] --> B[Probe custom IMS capability endpoint]
    B --> C{HTTP JSON response?}
    C -->|No| D[OMERO option unavailable]
    C -->|Yes| E{custom capability flag matches?}
    E -->|No| D
    E -->|Yes| F{converters.OMERO true and omero_ims_export true?}
    F -->|No| D
    F -->|Yes| G[OMERO option available]

    A --> H[Probe local Imaris handoff target]
    H --> I{Live Imaris handle or numeric XT app id?}
    I -->|No| J[Imaris option unavailable]
    I -->|Yes| K[Find local ImarisConvert executable]
    K --> L{Executable found?}
    L -->|No| J
    L -->|Yes| M[Imaris option available]

    G --> N[Build dropdown from verified options]
    D --> N
    M --> N
    J --> N
```

The custom server capability contract is strict:

- The endpoint must return `omero_ims_export_capability`.
- The value must match the repository-defined capability flag.
- `converters.OMERO` must be `true`.
- `omero_ims_export` must be `true`.

Legacy responses such as `HTTP 400 Missing image id` do not enable the `OMERO`
converter. This prevents a non-custom OMERO.web installation from being treated
as if it supports the repository's custom IMS export.

The `Imaris` converter is not enabled merely because Imaris is installed. The XT
client also requires an Imaris handoff target and a local Imaris conversion
executable. Discovery is installation-agnostic: environment overrides, Imaris
install roots, registry/vendor locations, and `PATH` are checked without
hard-coding a single host path.

## Saved converter settings

The connector stores the last selected converter in the connector-owned
`settings.env`. That value is treated as a preference only, never as authority.

```mermaid
flowchart TD
    A[Detected converter options] --> B{Any option available?}
    B -->|No| C[Clear converter value and hide dropdown]
    B -->|Yes| D[Read in-memory preferred converter]
    D --> E{Preferred converter still available?}
    E -->|Yes| F[Select preferred converter]
    E -->|No| G[Read saved converter from settings.env]
    G --> H{Saved converter still available?}
    H -->|Yes| I[Select saved converter]
    H -->|No| J[Select first currently available converter]
    F --> K[Store verified option list]
    I --> K
    J --> K
```

At load time, the selected value is checked against the stored verified option
list again. If `settings.env` contains `OMERO` but the connected server no
longer exposes the custom capability flag, the connector refuses the stale value,
refreshes the dropdown from the verified options, and does not start a download.

## OMERO converter path

The `OMERO` converter is the custom server-side path in this repository. It
requires the custom OMERO.web app, Celery, and the IMS export script.

```mermaid
flowchart TD
    A[XT client requests /imaris-export/?capabilities=1] --> B[Server checks Celery]
    B --> C[Server checks IMS_Export.py script availability]
    C --> D[Server returns custom capability flag and converter map]
    D --> E{XT user selects OMERO}
    E --> F[XT requests /imaris-export/?image=ID&async=1]
    F --> G[Server creates Celery job]
    G --> H[XT polls /imaris-export/?job=JOB]
    H --> I{Job state}
    I -->|RUNNING| H
    I -->|FAILED| J[XT reports export failure]
    I -->|FINISHED| K[XT downloads exported IMS]
    K --> L[XT validates IMS HDF5 signature]
    L --> M[XT opens IMS in current Imaris session]
```

Server-side job execution:

```mermaid
flowchart TD
    A[Celery task starts] --> B{Use job-service session?}
    B -->|Yes| C[Open OMERO connection with job-service credentials]
    B -->|No| D[Join user's OMERO session key]
    C --> E[Locate IMS_Export.py through OMERO script service]
    D --> E
    E --> F[Resolve OMERO CLI from env-driven runtime contract]
    F --> G[Run omero script launch]
    G --> H[Parse Export_Path, Export_Name, File_Annotation_Id, Message]
    H --> I{Export path available?}
    I -->|Yes| J[Return FINISHED outputs]
    I -->|No| K[Return task failure metadata]
```

This path is custom by design. It must not appear for arbitrary OMERO
installations that do not explicitly expose this repository's capability flag.
For a standard non-custom OMERO.web host, a missing custom capability endpoint is
treated as an ordinary absence of the `OMERO` converter, not as an Imaris
converter warning or failure.

## Imaris converter path

The `Imaris` converter is the generic path intended to work with standard
OMERO.web installations and a local Imaris 11 or newer installation. It does not
require the custom IMS export endpoint or the server-side Imaris conversion
script.

On the client workstation, the XT connector startup gate requires Windows 10 or
later. Windows 11 is included by that version rule; the connector must not
special-case a single Windows release.

The path is source-format agnostic. It never downloads archived originals,
filesets, source containers, nested folder payloads, or repository-managed
source paths. The original data may come from any OMERO-supported source,
including high-content screening layouts and OME-Zarr-backed images, because the
client requests only the selected OMERO Image ID through standard OMERO.web.
Diagnostics for this path are scoped as `Imaris converter` messages; normal
absence of the custom server-side OMERO converter must not leak into this path.

```mermaid
flowchart TD
    A[User selects Imaris converter] --> B[Verify same-session Imaris handoff target]
    B --> C[Export selected OMERO Image ID as OME-TIFF through OMERO.web]
    C --> D[Validate downloaded file is TIFF or BigTIFF]
    D --> E[Collect explicit selected-image voxel metadata]
    E --> F[Run local ImarisConvert]
    F --> G[Validate output is IMS/HDF5]
    G --> H[Open IMS in the current Imaris session]
```

The selected-image export uses the OMERO.web image export endpoint for the
selected Image ID. The OME-TIFF file is only the standard OMERO.web transport
envelope for the selected Image pixels that ImarisConvert can read locally; it
is not a source-filetype decision and it is not a download of the archived
original container. The client does not use
`webgateway/archived_files/download/`. If the selected-image OME-TIFF export is
unavailable, the connector fails explicitly instead of falling back to
original-file download.

Voxel-size metadata is handled without guessing. The connector may pass
`-vsx`, `-vsy`, and `-vsz` to ImarisConvert only when the corresponding value is
explicitly present in selected Image metadata returned by OMERO.web or in the
selected-image OME-TIFF metadata. Missing axes remain missing; the connector does
not infer Z from X/Y, single-plane status, source filename, source format, or any
installation-specific rule.

Local conversion:

```mermaid
flowchart TD
    A[Selected-image OME-TIFF exists] --> B{TIFF signature valid?}
    B -->|No| C[Stop: invalid selected-image export]
    B -->|Yes| D[Merge explicit selected-image metadata]
    D --> E[Find ImarisConvert]
    E --> F{Converter found?}
    F -->|No| G[Stop: local Imaris converter unavailable]
    F -->|Yes| H[Try compatible ImarisConvert argument forms]
    H --> I{Any attempt exits 0 and writes IMS?}
    I -->|No| J[Report exit code and missing explicit voxel axes]
    I -->|Yes| K{Output IMS/HDF5 signature valid?}
    K -->|No| L[Stop: conversion did not produce IMS]
    K -->|Yes| M[Return IMS path to handoff flow]
```

The connector reports Windows breakpoint-style converter failures with both
decimal and unsigned hexadecimal process exit codes, so failures such as
`0x80000003` remain visible in diagnostics.

## Imaris same-session handoff

After either converter produces a valid IMS, the XT client opens the file in the
current Imaris session.

```mermaid
flowchart TD
    A[IMS path ready] --> B{Direct XT Imaris handle available?}
    B -->|Yes| C[Call Imaris FileOpen/OpenFile/LoadFile]
    B -->|No| D{Numeric XT application id available?}
    D -->|No| E[Stop: no same-session handoff target]
    D -->|Yes| F[Resolve compatible native bridge Python]
    F --> G{Bridge available?}
    G -->|Yes| H[Submit open request through native bridge]
    G -->|No| E
    C --> K[Verify current file when possible]
    H --> K
```

The load workers validate that the file is IMS before any Imaris open request is
made. Non-IMS files are rejected at the connector boundary.

## Multi-image loading

Multi-image loading uses the same converter-specific preparation as single-image
loading, but it waits until every selected image has produced a valid IMS before
submitting any file to Imaris.

```mermaid
flowchart TD
    A[Selected image list] --> B[Prepare first selected image]
    B --> C{IMS valid?}
    C -->|No| D[Stop before Imaris handoff]
    C -->|Yes| E{More images?}
    E -->|Yes| F[Prepare next selected image]
    F --> C
    E -->|No| G[Submit all IMS files to Imaris]
```

This prevents partial handoff where the first files open in Imaris and a later
download or conversion fails.

## Failure boundaries

- No authenticated OMERO.web session: the connector refuses browsing and export.
- Custom capability flag missing: the `OMERO` converter is hidden.
- Custom capability flag present but `converters.OMERO` false: the `OMERO`
  converter is hidden.
- No local ImarisConvert executable: the `Imaris` converter is hidden.
- Stale saved converter value: the stale option is ignored and cannot start a
  load.
- No same-session Imaris handoff target: no download or conversion is started.
- Selected-image OME-TIFF endpoint unavailable: the `Imaris` path fails without
  downloading archived originals.
- Selected-image voxel metadata missing for an axis required by ImarisConvert:
  the `Imaris` path reports the missing explicit axis and does not invent a
  voxel size.
- Local Imaris converter nonzero exit: the connector reports the exit code and
  bounded stdout/stderr.
- Server-side IMS download is not IMS/HDF5: the `OMERO` path rejects the file
  before any Imaris handoff.
- Local conversion output is not IMS/HDF5: the connector refuses to open it.
- Multi-image preparation failure: no batch handoff is attempted.

## Verification points

The regression suite covers the critical contracts:

- `OMERO` converter requires the custom capability flag.
- Legacy custom-endpoint responses do not enable `OMERO`.
- `Imaris` converter requires local Imaris conversion support.
- Stale `settings.env` converter values are ignored.
- The `Imaris` path uses selected Image ID OME-TIFF export.
- The `Imaris` path does not call archived original download.
- The `Imaris` path passes only explicit selected-image voxel sizes to
  ImarisConvert.
- The `Imaris` path fails missing-Z metadata without guessing a replacement.
- Local Imaris conversion command construction is checked, including the
  documented `-vsx`, `-vsy`, and `-vsz` flags.
- The `OMERO` path rejects non-HDF5 IMS download responses.
- Breakpoint-style local conversion exit codes include hexadecimal diagnostics.
- Single-image and multi-image load workers require valid IMS outputs before
  Imaris handoff.
- Optional live OMERO coverage is available through `OMERO_LIVE_HOST`,
  `OMERO_LIVE_PORT`, `OMERO_LIVE_SCHEME`, `OMERO_LIVE_USER`,
  `OMERO_LIVE_PASSWORD`, and `OMERO_LIVE_IMAGE_ID`. The live test authenticates,
  downloads the selected-image OME-TIFF, checks server-side IMS export when the
  custom capability exists, and can run local Imaris conversion only when
  `IMARIS_OMERO_RUN_LIVE_IMARIS_CONVERSION` is explicitly enabled.

## Related docs

- `imaris-connector-plugin.md`
- `../troubleshooting/imaris-export.md`
