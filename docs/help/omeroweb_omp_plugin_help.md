# OMERO.web Help — Filename & Metadata Manager (`omeroweb_omp_plugin`)

## Overview

The Filename & Metadata Manager parses image filenames into structured variables and writes those values as OMERO MapAnnotations. It is designed for repeatable metadata ingestion workflows at dataset scale.

## Who should use this plugin

- Scientists or data stewards who need to convert naming conventions into searchable metadata.
- Users who process many images and want consistent key/value annotations.
- Teams that need reusable parsing templates (variable sets) and controlled deletion behavior.

## Access and permissions

- This plugin is intended for **regular (non-root) users**.
- You can only process projects/datasets/images that your OMERO account can access.
- The plugin applies user-scoped rate limiting on major actions.

## Main workflow

1. Open the plugin and select a project.
2. Choose one or more datasets.
3. Configure filename parsing:
   - separator strategy,
   - variable names,
   - optional regex assistance.
4. Run a preview and verify extracted values.
5. Start an annotation job.
6. Monitor progress until completion.
7. Save variable sets for reuse.

## Core UI areas

### Dataset and filename scope

- Project selection loads accessible datasets.
- Dataset selection defines the processing scope.
- Preview parses representative filenames before any write operation.

### Variable definitions

- Define ordered variable names that map to parsed filename parts.
- Use deterministic separators/regex where possible.
- Keep variable names stable over time to simplify downstream queries.

### AI-assisted parsing (optional)

- You may configure provider-specific API keys in **Settings → AI API credentials**.
- AI output should always be validated in preview mode before writing metadata.
- API keys are stored per user in the plugin database.

### Jobs and progress

- Write/delete operations run as background jobs.
- Progress polling surfaces status and completion/failure messages.
- Retry only after reviewing the reported failure cause.

## Safe deletion options

- **Delete plugin annotations**: removes only annotations created by this plugin (hash-verified ownership).
- **Delete all annotations**: destructive operation that removes all target MapAnnotations from selected images.

Use delete-all only when the impact is fully understood.

## Collaboration mode

- Collaboration mode is intended for coordinated team usage.
- Ensure naming conventions and variable definitions are agreed before large batch writes.

## User settings and stored data

You can manage and delete plugin-scoped user data from Settings:

- API keys,
- saved variable sets,
- complete plugin user data.

## Troubleshooting

- **No datasets/images shown**: confirm OMERO permissions and project selection.
- **Preview extraction is wrong**: adjust separators/regex and re-run preview.
- **Job fails**: inspect job error details, then retry with smaller scope.
- **AI model listing/test fails**: verify provider key validity and outbound connectivity.

## Operational recommendations

- Start with one dataset and a small sample.
- Lock variable naming conventions early.
- Save validated variable sets for repeat use.
- Prefer plugin-owned deletion over global deletion.
