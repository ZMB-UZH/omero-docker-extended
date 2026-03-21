# Branding Logo Fallback

## Behavior contract

`startup/10-web-bootstrap.sh` manages the login logo only when
`CONFIG_omero_web_login__logo` is explicitly set to `/static/branding/logo.png`.
If that env var is unset, empty, or points somewhere else, bootstrap does not
generate a fallback and does not fail startup on account of a missing logo.

When the env does point at `/static/branding/logo.png`, bootstrap follows this
order:

1. Preserve a real existing `branding/logo.png` across static sync.
2. Restore the repository-managed `logo/logo.png` if the image contains one.
3. Generate a deterministic fallback icon only if no real logo is available.

## Runtime details

- The active runtime path is the bind-mounted
  `OMERO.web/var/static/branding/logo.png`.
- The generated fallback is a deterministic PNG built by
  `tools/write_branding_logo_fallback.py`.
- Bootstrap writes `branding/.generated-logo-fallback` when it creates that
  fallback itself.
- Bootstrap also recognizes known historical generated fallback hashes, so a
  stale old placeholder is refreshed automatically on restart even if the marker
  file was lost.
- Real operator-provided logos remain authoritative and are not overwritten by
  the fallback refresh path.

## Repository logo recovery

On March 22, 2026, the historical repository logo was recovered from local git
history and restored to `logo/logo.png` from commit
`b01dbe8c7e055483e88afd903adb83fded1a574c`.

The restored file is now the canonical repository-managed logo asset:

- Path: `logo/logo.png`
- Mode: `0644`

## Objective benchmark

Measured on March 21-22, 2026 during live repair of `omeroweb`.

### Broken baseline before the final fix

| Check | Result |
| --- | --- |
| Container health | `unhealthy` |
| Login endpoint | `000`, connection refused |
| Supervisor churn | `66` `exit status 1` events in the sampled tail |
| Django startup error | `ModuleNotFoundError: No module named 'omeroweb_upload'` |
| Placeholder refresh | stale generated fallback could survive rebuilds |

### Verified state after the final fix

| Check | Placeholder-only validation | Final real-logo validation |
| --- | --- | --- |
| Health | `healthy` | `healthy` |
| `GET /webclient/login/` | `200` in `0.405189s` | `200` in `0.018040s` |
| `GET /static/branding/logo.png` | `200`, `370` bytes | `200`, `16777` bytes |
| Runtime logo hash | `4962acc5fbf52f8ef72721990487fdc9a1e76c862e8e0676acd4aa0dad867286` | `e001ba68d28b072463454fbd988f901f89895dd12b8d9e238265aa67f0ca11ae` |
| Disabled-logo path | isolated startup check returned `logo-absent` when the logo env was unset and no real logo was present | not applicable |

Benchmark scope:

- These checks measure correctness and runtime health, not rendering aesthetics
  or browser paint speed.
- The login endpoint timing includes normal OMERO.web startup state after the
  service had already become healthy.

## Operational note

The placeholder or real logo is resolved before OMERO.web starts, so the login
page never points at a missing static asset once bootstrap completes
successfully.
