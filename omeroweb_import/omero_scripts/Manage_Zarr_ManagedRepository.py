#!/usr/bin/env python
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from omero import scripts
from omero.gateway import BlitzGateway
from omero.rtypes import rstring


_ACTION_STAGE = "stage"
_ACTION_CLEANUP = "cleanup"
_SUPPORTED_ACTIONS = {_ACTION_STAGE, _ACTION_CLEANUP}
_TOKEN_PATTERN = re.compile(r"%[A-Za-z0-9_]+%")
_KNOWN_TEMPLATE_TOKENS = {
    "%group%",
    "%user%",
    "%year%",
    "%month%",
    "%day%",
    "%time%",
}
_CONFIG_DATA_DIR = "omero.data.dir"
_CONFIG_MANAGED_DIR = "omero.managed.dir"
_CONFIG_REPO_PATH = "omero.fs.repo.path"
_CONFIG_SHARED_TMP_PATH = "omero.web.import.shared_tmp_path"
_RUNTIME_STATE_FILENAME = "managed-zarr-runtime.env"


def _require_config_value(config: dict[str, str], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required OMERO config value: {key}. "
            "Ensure startup/10-server-bootstrap.sh persisted the env-driven value."
        )
    return value


def _load_server_config(conn: BlitzGateway) -> dict[str, str]:
    if conn is None:
        raise RuntimeError("Missing OMERO connection for managed-repository staging.")

    try:
        config_service = conn.c.sf.getConfigService()
    except Exception as exc:
        raise RuntimeError(
            "Failed to access the OMERO config service for managed-repository staging."
        ) from exc

    if config_service is None:
        raise RuntimeError("OMERO config service is unavailable.")

    values = {}
    for key in (
        _CONFIG_DATA_DIR,
        _CONFIG_MANAGED_DIR,
        _CONFIG_REPO_PATH,
    ):
        try:
            value = config_service.getConfigValue(key)
        except Exception as exc:
            raise RuntimeError(f"Failed to read OMERO config value: {key}") from exc
        values[key] = str(value or "").strip()
    values[_CONFIG_SHARED_TMP_PATH] = _load_runtime_state_value(_CONFIG_SHARED_TMP_PATH)
    return values


def _runtime_state_path() -> Path:
    omerodir = str(os.environ.get("OMERODIR") or "").strip()
    if not omerodir:
        raise RuntimeError("OMERODIR is not set in the OMERO script processor environment.")
    return Path(omerodir).resolve(strict=False) / "var" / _RUNTIME_STATE_FILENAME


def _load_runtime_state_value(key: str) -> str:
    state_path = _runtime_state_path()
    if not state_path.is_file():
        raise RuntimeError(
            f"Missing import runtime state file: {state_path}. "
            "Ensure startup/10-server-bootstrap.sh completed successfully."
        )

    values = {}
    with state_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            current_key, current_value = line.split("=", 1)
            values[current_key.strip()] = current_value.strip()

    value = values.get(key, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required import runtime value: {key}. "
            f"Check {state_path}."
        )
    return value


def _validate_path_component(value: str, label: str) -> str:
    component = str(value or "").strip()
    if (
        not component
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
        or "\x00" in component
    ):
        raise ValueError(f"Invalid {label}: {value!r}")
    return component


def _render_repo_template(config: dict[str, str], group_name: str, username: str, when: datetime):
    template = _require_config_value(config, _CONFIG_REPO_PATH)
    raw_parts = [part for part in template.split("/") if part]
    if not raw_parts:
        raise RuntimeError(f"{_CONFIG_REPO_PATH} must not be empty.")

    values = {
        "%group%": _validate_path_component(group_name, "group name"),
        "%user%": _validate_path_component(username, "username"),
        "%year%": when.strftime("%Y"),
        "%month%": when.strftime("%m"),
        "%day%": when.strftime("%d"),
        "%time%": when.strftime("%H-%M-%S"),
    }

    rendered_parts = []
    prefix_parts = []
    seen_user = False

    for raw_part in raw_parts:
        part = raw_part
        for token, token_value in values.items():
            part = part.replace(token, token_value)

        unknown_tokens = set(_TOKEN_PATTERN.findall(part)) - _KNOWN_TEMPLATE_TOKENS
        if unknown_tokens:
            raise RuntimeError(
                f"{_CONFIG_REPO_PATH} contains unsupported tokens: "
                + ", ".join(sorted(unknown_tokens))
            )
        if "%" in part:
            raise RuntimeError(f"{_CONFIG_REPO_PATH} contains unresolved token syntax.")

        rendered = _validate_path_component(part, "managed-repository template segment")
        rendered_parts.append(rendered)
        if not seen_user:
            prefix_parts.append(rendered)
        if "%user%" in raw_part:
            seen_user = True

    if not seen_user:
        raise RuntimeError(f"{_CONFIG_REPO_PATH} must include a %user% token for Zarr staging.")

    suffix_parts = rendered_parts[len(prefix_parts):]
    return prefix_parts, suffix_parts


def _managed_repository_root(config: dict[str, str]) -> Path:
    data_dir = _require_config_value(config, _CONFIG_DATA_DIR)
    managed_dir = _require_config_value(config, _CONFIG_MANAGED_DIR)
    root = (Path(data_dir) / managed_dir).resolve(strict=False)
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Managed repository root does not exist: {root}")
    return root


def _shared_tmp_root(config: dict[str, str]) -> Path:
    root = Path(_require_config_value(config, _CONFIG_SHARED_TMP_PATH)).resolve(strict=False)
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Shared temp root does not exist: {root}")
    return root


def _validate_source_path(config: dict[str, str], source_path: str) -> Path:
    shared_tmp_root = _shared_tmp_root(config)
    source = Path(str(source_path or "")).resolve(strict=True)
    try:
        source.relative_to(shared_tmp_root)
    except ValueError as exc:
        raise RuntimeError(
            f"Source path must stay within {shared_tmp_root}: {source}"
        ) from exc
    if not source.is_dir():
        raise RuntimeError(f"Source path is not a directory: {source}")
    if not source.name.endswith(".zarr"):
        raise RuntimeError(f"Source path is not a .zarr directory: {source}")
    return source


def _reject_symlinks(path: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        current_dir = Path(dirpath)
        if current_dir.is_symlink():
            raise RuntimeError(f"Symlinked directories are not allowed: {current_dir}")
        for name in list(dirnames) + list(filenames):
            current_path = current_dir / name
            if current_path.is_symlink():
                raise RuntimeError(f"Symlinks are not allowed in staged Zarrs: {current_path}")


def _user_prefix_dir(
    config: dict[str, str],
    group_name: str,
    username: str,
    when: datetime,
    *,
    create_missing: bool,
) -> tuple[Path, list[str]]:
    managed_root = _managed_repository_root(config)
    prefix_parts, suffix_parts = _render_repo_template(config, group_name, username, when)
    prefix_dir = managed_root
    for part in prefix_parts:
        prefix_dir = (prefix_dir / part).resolve(strict=False)
        try:
            prefix_dir.relative_to(managed_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Managed-repository prefix escaped its root: {prefix_dir}"
            ) from exc
        if create_missing:
            prefix_dir.mkdir(parents=False, exist_ok=True)
        elif not prefix_dir.exists() or not prefix_dir.is_dir():
            raise RuntimeError(
                "Managed-repository user prefix does not exist yet and must be created "
                f"by OMERO.server first: {prefix_dir}"
            )
        if not prefix_dir.is_dir():
            raise RuntimeError(f"Managed-repository prefix path is not a directory: {prefix_dir}")
        os.chmod(prefix_dir, 0o755)
    return prefix_dir, suffix_parts


def _ensure_suffix_dir(managed_root: Path, prefix_dir: Path, suffix_parts: list[str]) -> Path:
    target_dir = prefix_dir
    for part in suffix_parts:
        target_dir = target_dir / part
    target_dir = target_dir.resolve(strict=False)
    try:
        target_dir.relative_to(managed_root)
    except ValueError as exc:
        raise RuntimeError(
            f"Managed-repository target escaped its root: {target_dir}"
        ) from exc
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, 0o755)
    return target_dir


def _allocate_destination_dir(target_dir: Path, source_name: str) -> Path:
    candidate = target_dir / source_name
    if not candidate.exists():
        return candidate

    if source_name.endswith(".ome.zarr"):
        stem = source_name[:-9]
        suffix = ".ome.zarr"
    elif source_name.endswith(".zarr"):
        stem = source_name[:-5]
        suffix = ".zarr"
    else:
        stem = source_name
        suffix = ""

    while True:
        alt_name = f"{stem}__{uuid.uuid4().hex[:8]}{suffix}"
        candidate = target_dir / alt_name
        if not candidate.exists():
            return candidate


def _normalize_tree_permissions(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for dirname in dirnames:
            os.chmod(os.path.join(dirpath, dirname), 0o755)
        for filename in filenames:
            os.chmod(os.path.join(dirpath, filename), 0o644)


def _stage_zarr(config: dict[str, str], source_path: str, group_name: str, username: str) -> Path:
    when = datetime.now()
    source = _validate_source_path(config, source_path)
    _reject_symlinks(source)
    managed_root = _managed_repository_root(config)
    prefix_dir, suffix_parts = _user_prefix_dir(
        config,
        group_name,
        username,
        when,
        create_missing=True,
    )
    target_dir = _ensure_suffix_dir(managed_root, prefix_dir, suffix_parts)
    destination = _allocate_destination_dir(target_dir, source.name)
    shutil.copytree(source, destination)
    _normalize_tree_permissions(destination)
    return destination


def _cleanup_zarr(config: dict[str, str], managed_path: str, group_name: str, username: str) -> Path:
    when = datetime.now()
    managed_root = _managed_repository_root(config)
    prefix_dir, _ = _user_prefix_dir(
        config,
        group_name,
        username,
        when,
        create_missing=False,
    )
    target = Path(str(managed_path or "")).resolve(strict=False)
    try:
        target.relative_to(managed_root)
        target.relative_to(prefix_dir)
    except ValueError as exc:
        raise RuntimeError(
            f"Managed Zarr path is outside the allowed user prefix: {target}"
        ) from exc

    if target == prefix_dir:
        raise RuntimeError("Refusing to delete the user managed-repository prefix.")

    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    return target


def run_script():
    client = scripts.client(
        "Manage_Zarr_ManagedRepository.py",
        "Stage or clean up OME-Zarr directories in the OMERO managed repository.",
        scripts.String(
            "Action",
            optional=False,
            grouping="1",
            description="One of: stage, cleanup",
        ),
        scripts.String(
            "Group_Name",
            optional=False,
            grouping="2",
            description="OMERO group name for the managed-repository template.",
        ),
        scripts.String(
            "Username",
            optional=False,
            grouping="3",
            description="OMERO username for the managed-repository template.",
        ),
        scripts.String(
            "Source_Path",
            optional=True,
            grouping="4",
            description="Shared temp source path for stage operations.",
        ),
        scripts.String(
            "Managed_Path",
            optional=True,
            grouping="5",
            description="Managed-repository path for cleanup operations.",
        ),
        namespaces=["omero.import"],
        version="1.0.0",
        authors=["OpenAI"],
        institutions=["OMERO"],
        contact="n/a",
    )
    conn = None
    try:
        conn = BlitzGateway(client_obj=client)
        server_config = _load_server_config(conn)
        params = client.getInputs(unwrap=True)
        action = str(params.get("Action") or "").strip().lower()
        group_name = str(params.get("Group_Name") or "").strip()
        username = str(params.get("Username") or "").strip()

        if action not in _SUPPORTED_ACTIONS:
            raise RuntimeError(
                "Action must be one of: " + ", ".join(sorted(_SUPPORTED_ACTIONS))
            )

        if action == _ACTION_STAGE:
            managed_path = _stage_zarr(
                server_config,
                source_path=str(params.get("Source_Path") or ""),
                group_name=group_name,
                username=username,
            )
            message = f"Staged Zarr into managed repository: {managed_path}"
        else:
            managed_path = _cleanup_zarr(
                server_config,
                managed_path=str(params.get("Managed_Path") or ""),
                group_name=group_name,
                username=username,
            )
            message = f"Cleaned managed-repository Zarr path: {managed_path}"

        client.setOutput("Managed_Path", rstring(str(managed_path)))
        client.setOutput("Message", rstring(message))
        print(f"Managed_Path={managed_path}")
        print(f"Message={message}")
    except Exception as exc:
        client.setOutput("Message", rstring(f"Script error: {exc}"))
        raise
    finally:
        # ``client.closeSession()`` is sufficient here. Closing the BlitzGateway
        # wrapper as well can invalidate result collection for callers waiting on
        # the ScriptProcess handle.
        client.closeSession()


if __name__ == "__main__":
    run_script()
