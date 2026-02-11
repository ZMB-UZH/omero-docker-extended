# omero-zmb-omp-plugin

## Project instructions
- Script naming policy (do not alter): keep the repository script filename as `github_pull_project_bash_example`.
- `env/installation_paths.env` must reference `github_pull_project_bash` in its descriptive header text for release/custom workflow compatibility.
- Do not rename either identifier without explicit maintainer direction.

## Docker image package inventory automation

Use `helper_scripts/docker_image_inventory.sh` to automatically inspect a Docker image and produce a user-readable package/version inventory report.

It detects OS package managers (`dpkg`, `rpm`, `apk`, `pacman`, `opkg`) and Python package inventories, including discovered virtual environments (`pyvenv.cfg` scan).

Examples:

```bash
# Interactive prompt for image reference
./helper_scripts/docker_image_inventory.sh

# Non-interactive usage
./helper_scripts/docker_image_inventory.sh --image postgres:16.11

# Skip pull and inspect only local image cache
./helper_scripts/docker_image_inventory.sh --image postgres:16.11 --skip-pull

# Run internal self-tests
./helper_scripts/docker_image_inventory.sh --self-test
```

Reports are written to `image-inventory-reports/` by default.
