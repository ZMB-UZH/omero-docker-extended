# OMP Plugin Guide (`omeroweb_omp_plugin`)

## Purpose
The OMP plugin provides a workflow for parsing filenames into metadata variables, previewing parsed values, and writing OMERO key-value annotations with controlled job execution.

## Main Capabilities

- project and dataset selection for target images,
- filename parsing (regex and helper logic),
- variable set save/load/delete actions,
- AI-assisted parsing support (provider/model/credentials-aware),
- progress-tracked background jobs,
- plugin user data management (credentials, variable sets).

## Key Routes

- `/omeroweb_omp_plugin/`
- `/omeroweb_omp_plugin/projects/`
- `/omeroweb_omp_plugin/start_job/`
- `/omeroweb_omp_plugin/progress/<job_id>/`
- `/omeroweb_omp_plugin/varsets/*`
- `/omeroweb_omp_plugin/ai-credentials/*`
- `/omeroweb_omp_plugin/user-data/*`
- `/omeroweb_omp_plugin/help/`

## Typical User Workflow

1. Open plugin page.
2. Select project and datasets.
3. Configure parser variables/regex.
4. Run preview parsing to verify extraction quality.
5. Start metadata write job.
6. Monitor job progress endpoint until completion.
7. Optionally persist variable sets and user settings.

## Access and Safety Considerations

- Plugin checks project/image access constraints via OMERO permissions.
- Use regular non-root OMERO users for normal operation.
- Rate limiting logic applies to major actions to reduce misuse risk.
- AI credential handling is isolated in plugin user data storage.

## Operator Checklist

- Verify plugin is listed in `CONFIG_omero_web_apps`.
- Verify route loads with authenticated user.
- Validate write operations on test datasets before broad rollout.
- Review logs for parser and job execution anomalies.
