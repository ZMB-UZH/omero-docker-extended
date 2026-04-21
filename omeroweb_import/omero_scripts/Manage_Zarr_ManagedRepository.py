#!/usr/bin/env python
import os
import re
import shutil
import stat
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
_PREFIX_DIR_MODE = stat.S_IRWXU | stat.S_IXGRP | stat.S_IXOTH
_STAGED_DIR_MODE = (
    stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
)
_STAGED_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
_VOLATILE_TEMPLATE_PATTERNS = {
    "%year%": r"\d{4}",
    "%month%": r"\d{2}",
    "%day%": r"\d{2}",
    "%time%": r"\d{2}-\d{2}-\d{2}",
}


def _set_prefix_directory_mode(path: Path | str) -> None:
    # Allow a separate OMERO.web service account to traverse the known
    # managed-repository prefix without exposing sibling directory listings.
    os.chmod(path, _PREFIX_DIR_MODE)


def _set_staged_directory_mode(path: Path | str) -> None:
    # Native ``omero zarr import`` runs from OMERO.web, so the staged tree
    # must be readable across service-user boundaries on shared host mounts.
    os.chmod(path, _STAGED_DIR_MODE)


def _set_staged_file_mode(path: Path | str) -> None:
    os.chmod(path, _STAGED_FILE_MODE)


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
        raise RuntimeError(
            "OMERODIR is not set in the OMERO script processor environment."
        )
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
            f"Missing required import runtime value: {key}. Check {state_path}."
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


def _repo_model_attr(model_obj, attr_name: str):
    value = getattr(model_obj, attr_name, None)
    if value is None:
        value = getattr(model_obj, f"_{attr_name}", None)
    return value


def _repo_text(value) -> str:
    if value is None:
        return ""
    inner = getattr(value, "val", None)
    if inner is None:
        inner = getattr(value, "_val", None)
    if inner is None:
        inner = value
    return str(inner or "").strip()


def _repo_description_root(description) -> str:
    description_path = _repo_text(_repo_model_attr(description, "path")).rstrip("/")
    description_name = _repo_text(_repo_model_attr(description, "name")).strip("/")
    if description_path and description_name:
        return f"{description_path}/{description_name}"
    if description_name:
        return f"/{description_name}"
    return description_path


def _repo_template_parts(config: dict[str, str]) -> list[str]:
    template = _require_config_value(config, _CONFIG_REPO_PATH)
    raw_parts = [part for part in template.split("/") if part]
    if not raw_parts:
        raise RuntimeError(f"{_CONFIG_REPO_PATH} must not be empty.")
    return raw_parts


def _assert_supported_template_tokens(raw_part: str) -> None:
    tokens = set(_TOKEN_PATTERN.findall(raw_part))
    unknown_tokens = tokens - _KNOWN_TEMPLATE_TOKENS
    if unknown_tokens:
        raise RuntimeError(
            f"{_CONFIG_REPO_PATH} contains unsupported tokens: "
            + ", ".join(sorted(unknown_tokens))
        )

    preview = raw_part
    for token in _KNOWN_TEMPLATE_TOKENS:
        preview = preview.replace(token, "TOKEN")
    if "%" in preview:
        raise RuntimeError(f"{_CONFIG_REPO_PATH} contains unresolved token syntax.")


def _render_repo_template(
    config: dict[str, str], group_name: str, username: str, when: datetime
) -> list[str]:
    raw_parts = _repo_template_parts(config)

    values = {
        "%group%": _validate_path_component(group_name, "group name"),
        "%user%": _validate_path_component(username, "username"),
        "%year%": when.strftime("%Y"),
        "%month%": when.strftime("%m"),
        "%day%": when.strftime("%d"),
        "%time%": when.strftime("%H-%M-%S"),
    }

    rendered_parts = []

    for raw_part in raw_parts:
        _assert_supported_template_tokens(raw_part)
        part = raw_part
        for token, token_value in values.items():
            part = part.replace(token, token_value)

        rendered = _validate_path_component(part, "managed-repository template segment")
        rendered_parts.append(rendered)

    return rendered_parts


def _match_repo_template(
    config: dict[str, str],
    group_name: str,
    username: str,
    actual_parts: tuple[str, ...],
) -> tuple[list[str], tuple[str, ...]]:
    raw_parts = _repo_template_parts(config)
    if len(actual_parts) < len(raw_parts):
        raise RuntimeError(
            "Managed Zarr path does not match the configured managed-repository "
            "staging template."
        )

    group_component = _validate_path_component(group_name, "group name")
    user_component = _validate_path_component(username, "username")
    matched_parts: list[str] = []

    for index, raw_part in enumerate(raw_parts):
        _assert_supported_template_tokens(raw_part)

        matcher_parts = ["^"]
        cursor = 0
        for token_match in _TOKEN_PATTERN.finditer(raw_part):
            matcher_parts.append(re.escape(raw_part[cursor : token_match.start()]))
            template_marker = token_match.group(0)
            if template_marker == "%group%":
                matcher_parts.append(re.escape(group_component))
            elif template_marker == "%user%":
                matcher_parts.append(re.escape(user_component))
            else:
                matcher_parts.append(_VOLATILE_TEMPLATE_PATTERNS[template_marker])
            cursor = token_match.end()
        matcher_parts.append(re.escape(raw_part[cursor:]))
        matcher_parts.append("$")

        actual_part = _validate_path_component(
            actual_parts[index], "managed-repository cleanup path segment"
        )
        if not re.fullmatch("".join(matcher_parts), actual_part):
            raise RuntimeError(
                "Managed Zarr path does not match the configured "
                "managed-repository staging template."
            )

        matched_parts.append(actual_part)
    return matched_parts, actual_parts[len(raw_parts) :]


def _managed_repository_root(config: dict[str, str]) -> Path:
    data_dir = Path(_require_config_value(config, _CONFIG_DATA_DIR)).resolve(
        strict=False
    )
    managed_dir_raw = _require_config_value(config, _CONFIG_MANAGED_DIR)
    managed_dir = Path(managed_dir_raw)
    if not managed_dir.is_absolute():
        raise RuntimeError(
            f"{_CONFIG_MANAGED_DIR} must be an absolute path inside {data_dir}, "
            f"got: {managed_dir_raw}"
        )
    root = managed_dir.resolve(strict=False)
    try:
        root.relative_to(data_dir)
    except ValueError as exc:
        raise RuntimeError(
            f"{_CONFIG_MANAGED_DIR} must stay within {data_dir}: {root}"
        ) from exc
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Managed repository root does not exist: {root}")
    return root


def _shared_tmp_root(config: dict[str, str]) -> Path:
    root = Path(_require_config_value(config, _CONFIG_SHARED_TMP_PATH)).resolve(
        strict=False
    )
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
                raise RuntimeError(
                    f"Symlinks are not allowed in staged Zarrs: {current_path}"
                )


def _template_container_dir(
    config: dict[str, str],
    group_name: str,
    username: str,
    when: datetime,
) -> Path:
    managed_root = _managed_repository_root(config)
    rendered_parts = _render_repo_template(config, group_name, username, when)
    container_dir = managed_root
    for part in rendered_parts:
        container_dir = (container_dir / part).resolve(strict=False)
        try:
            container_dir.relative_to(managed_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Managed-repository template escaped its root: {container_dir}"
            ) from exc
    return container_dir


def _managed_repository_proxy(conn: BlitzGateway, config: dict[str, str]):
    if conn is None:
        raise RuntimeError("Missing OMERO connection for managed-repository access.")

    try:
        repo_map = conn.c.sf.sharedResources().repositories()
    except Exception as exc:
        raise RuntimeError(
            "Failed to resolve the managed-repository proxy from OMERO shared resources."
        ) from exc

    proxies = getattr(repo_map, "proxies", None) or {}
    descriptions = list(getattr(repo_map, "descriptions", None) or [])
    managed_root = str(_managed_repository_root(config)).rstrip("/")

    for index, description in enumerate(descriptions):
        if _repo_description_root(description).rstrip("/") != managed_root:
            continue
        if isinstance(proxies, dict):
            for key in (
                _repo_text(_repo_model_attr(description, "hash")),
                _repo_text(_repo_model_attr(description, "name")),
            ):
                if key and key in proxies and proxies[key] is not None:
                    return proxies[key]
            continue
        if index < len(proxies) and proxies[index] is not None:
            return proxies[index]

    if not descriptions and "ManagedRepository" in proxies:
        return proxies["ManagedRepository"]

    if not descriptions:
        if isinstance(proxies, dict) and len(proxies) == 1:
            return next(iter(proxies.values()))
        if len(proxies) == 1 and proxies[0] is not None:
            return proxies[0]

    raise RuntimeError(
        f"Failed to resolve the managed-repository proxy for {managed_root}."
    )


def _repo_relative_path(
    managed_root: Path, path: Path, *, directory: bool, leading_slash: bool = False
) -> str:
    target = path.resolve(strict=False)
    try:
        relative_path = target.relative_to(managed_root)
    except ValueError as exc:
        raise RuntimeError(
            f"Managed-repository path escaped its root: {target}"
        ) from exc

    path_text = relative_path.as_posix().strip("/")
    if path_text in {"", "."}:
        raise RuntimeError("Managed-repository relative path must not be empty.")
    if directory:
        path_text = f"{path_text.rstrip('/')}/"
    if leading_slash:
        path_text = f"/{path_text.lstrip('/')}"
    return path_text


def _register_managed_directory(
    repo_proxy, managed_root: Path, target_dir: Path
) -> None:
    repo_relative_dir = _repo_relative_path(managed_root, target_dir, directory=True)
    try:
        repo_proxy.makeDir(repo_relative_dir, True)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create registered managed-repository directory: {target_dir}"
        ) from exc


def _repository_directory_registered(
    repo_proxy,
    managed_root: Path,
    directory: Path,
) -> bool:
    repo_relative_dir = _repo_relative_path(managed_root, directory, directory=True)
    try:
        return bool(repo_proxy.fileExists(repo_relative_dir))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to query managed-repository registration state for: {directory}"
        ) from exc


def _assert_no_unregistered_existing_dirs(
    repo_proxy,
    managed_root: Path,
    target_dir: Path,
) -> None:
    current = managed_root.resolve(strict=False)
    for part in target_dir.relative_to(managed_root).parts:
        current = (current / part).resolve(strict=False)
        if not current.exists():
            continue
        if not current.is_dir():
            raise RuntimeError(f"Managed-repository path is not a directory: {current}")
        if _repository_directory_registered(repo_proxy, managed_root, current):
            continue
        raise RuntimeError(
            "Managed-repository path exists on disk but is not registered "
            f"in OMERO: {current}. This usually means a stale native-Zarr staging "
            "directory was left behind by an older helper that created "
            "managed-repository directories with raw filesystem operations."
        )


def _registered_delete_path(managed_root: Path, target: Path) -> str:
    return _repo_relative_path(
        managed_root,
        target,
        directory=target.is_dir(),
        leading_slash=True,
    )


def _delete_registered_managed_path(
    conn: BlitzGateway, repo_proxy, managed_root: Path, target: Path
) -> None:
    delete_path = _registered_delete_path(managed_root, target)
    try:
        handle = repo_proxy.deletePaths([delete_path], True, False)
        conn.c.waitOnCmd(handle, closehandle=True)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to delete managed-repository path: {target}"
        ) from exc


def _prefix_directories(managed_root: Path, leaf_parent: Path) -> list[Path]:
    prefix_dirs: list[Path] = []
    current = managed_root
    for part in leaf_parent.relative_to(managed_root).parts:
        current = (current / part).resolve(strict=False)
        prefix_dirs.append(current)
    return prefix_dirs


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
        _set_staged_directory_mode(dirpath)
        for dirname in dirnames:
            _set_staged_directory_mode(os.path.join(dirpath, dirname))
        for filename in filenames:
            _set_staged_file_mode(os.path.join(dirpath, filename))


def _stage_zarr(
    conn: BlitzGateway,
    config: dict[str, str],
    source_path: str,
    group_name: str,
    username: str,
) -> Path:
    when = datetime.now()
    source = _validate_source_path(config, source_path)
    _reject_symlinks(source)
    managed_root = _managed_repository_root(config)
    container_dir = _template_container_dir(config, group_name, username, when)
    repo_proxy = _managed_repository_proxy(conn, config)
    _assert_no_unregistered_existing_dirs(repo_proxy, managed_root, container_dir)
    if not container_dir.exists():
        _register_managed_directory(repo_proxy, managed_root, container_dir)
    destination = _allocate_destination_dir(container_dir, source.name)
    _register_managed_directory(repo_proxy, managed_root, destination)
    for directory in _prefix_directories(managed_root, destination.parent):
        if not directory.is_dir():
            raise RuntimeError(
                f"Managed-repository prefix path is not a directory: {directory}"
            )
        _set_prefix_directory_mode(directory)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    _normalize_tree_permissions(destination)
    return destination


def _cleanup_zarr(
    conn: BlitzGateway,
    config: dict[str, str],
    managed_path: str,
    group_name: str,
    username: str,
) -> Path:
    managed_root = _managed_repository_root(config)
    target = Path(str(managed_path or "")).resolve(strict=False)
    try:
        relative_parts = target.relative_to(managed_root).parts
    except ValueError as exc:
        raise RuntimeError(
            f"Managed Zarr path is outside the managed repository: {target}"
        ) from exc
    try:
        _container_parts, remainder = _match_repo_template(
            config, group_name, username, relative_parts
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"Managed Zarr path is outside the configured staging template: {target}"
        ) from exc
    if len(remainder) != 1:
        raise RuntimeError(
            "Managed Zarr cleanup only supports staged .zarr directories directly "
            "under the configured managed-repository template."
        )
    staged_name = _validate_path_component(remainder[0], "managed Zarr directory name")
    if not staged_name.endswith((".zarr", ".ome.zarr")):
        raise RuntimeError(
            "Managed Zarr cleanup only supports staged .zarr directories."
        )
    if target.exists():
        repo_proxy = _managed_repository_proxy(conn, config)
        if not target.is_dir():
            raise RuntimeError(f"Managed-repository path is not a directory: {target}")
        if not _repository_directory_registered(repo_proxy, managed_root, target):
            raise RuntimeError(
                "Managed-repository path exists on disk but is not registered "
                f"in OMERO: {target}"
            )
        _delete_registered_managed_path(conn, repo_proxy, managed_root, target)
        return target

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
                conn,
                server_config,
                source_path=str(params.get("Source_Path") or ""),
                group_name=group_name,
                username=username,
            )
            message = f"Staged Zarr into managed repository: {managed_path}"
        else:
            managed_path = _cleanup_zarr(
                conn,
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
