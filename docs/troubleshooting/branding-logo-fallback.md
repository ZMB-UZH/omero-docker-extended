# Branding Logo Fallback

`startup/10-web-bootstrap.sh` only manages the login-logo fallback when
`CONFIG_omero_web_login__logo` is explicitly set to `/static/branding/logo.png`.
If that env var is unset, empty, or points somewhere else, bootstrap leaves the
branding logo path alone and does not generate a placeholder.

When the env does point at `/static/branding/logo.png` but no site logo is
available, bootstrap generates a small deterministic placeholder PNG at that
path instead of leaving the login page to request a missing asset.

Runtime details:

- The generated file is written to the bind-mounted OMERO.web static directory as
  `branding/logo.png`.
- Bootstrap also writes `branding/.generated-logo-fallback` as a marker so later
  restarts can distinguish the generated placeholder from a real site logo.
- If an operator later provides a real `branding/logo.png`, bootstrap compares
  the current file with the generated fallback, removes a stale marker if needed,
  and preserves the real logo across the static sync.
- If a real repository-managed `logo/logo.png` becomes available in a future
  image build, the generated fallback will not block that real logo from taking
  over on restart.

Operational note:

- The placeholder generation happens before OMERO.web starts, so the login page
  sees a valid PNG path even when the deployment has never had a custom logo.
