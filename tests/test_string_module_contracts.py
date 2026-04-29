from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STRING_PACKAGES = {
    "omeroweb_omp_plugin": {
        "errors": importlib.import_module("omeroweb_omp_plugin.strings.errors"),
        "messages": importlib.import_module("omeroweb_omp_plugin.strings.messages"),
    },
    "omeroweb_import": {
        "errors": importlib.import_module("omeroweb_import.strings.errors"),
        "messages": importlib.import_module("omeroweb_import.strings.messages"),
    },
}
COMMON_CONTAINER_METHODS = {"append", "extend", "get", "items", "keys", "values"}

SAMPLE_ARGUMENTS = {
    "code": 503,
    "count": 3,
    "detail": "detail",
    "expected": 2,
    "file_name": "sample.txt",
    "filename": "sample.txt",
    "group_id": 17,
    "group_name": "research",
    "image_id": 19,
    "job_id": "job-1",
    "max_sets": 8,
    "max_bytes": 255,
    "maxVarsUncapped": 12,
    "message": "message",
    "minutes": 15,
    "name": "name",
    "parent_id": 42,
    "path": "dataset/file.tif",
    "port": 4064,
    "provider": "groq",
    "received": 1,
    "retry_after": 30,
    "status": 500,
    "username": "alice",
    "value": "value",
}


def _public_functions(module):
    """Handle public functions."""
    for name, value in vars(module).items():
        if name.startswith("_") or not callable(value):
            continue
        yield name, value


def _build_call_args(func):
    """Handle build call args."""
    args = []
    for parameter in inspect.signature(func).parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        if parameter.default is not inspect._empty:
            args.append(SAMPLE_ARGUMENTS.get(parameter.name, parameter.default))
            continue
        if parameter.name in SAMPLE_ARGUMENTS:
            args.append(SAMPLE_ARGUMENTS[parameter.name])
            continue
        args.append("value")
    return args


def _referenced_helper_names(package_name: str, module_alias: str) -> set[str]:
    """Handle referenced helper names."""
    names: set[str] = set()
    for source_path in (REPO_ROOT / package_name).rglob("*.py"):
        if "strings" in source_path.parts:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id == module_alias:
                names.add(node.func.attr)
    return names


def test_referenced_string_helpers_exist_across_import_and_omp_packages():
    """Verify test referenced string helpers exist across i behavior."""
    for package_name, modules in STRING_PACKAGES.items():
        for module_alias, module in modules.items():
            for helper_name in _referenced_helper_names(package_name, module_alias):
                if not hasattr(module, helper_name):
                    assert helper_name in COMMON_CONTAINER_METHODS, (
                        f"{package_name}.{module_alias}.{helper_name} is referenced "
                        f"but not defined"
                    )
                    continue
                assert callable(getattr(module, helper_name))


def test_public_string_helpers_return_non_empty_text():
    """Verify test public string helpers return non empty text."""
    for package_name, modules in STRING_PACKAGES.items():
        for module_alias, module in modules.items():
            for helper_name, func in _public_functions(module):
                if helper_name.startswith("build_"):
                    continue
                result = func(*_build_call_args(func))
                if isinstance(result, dict):
                    assert result, (
                        f"{package_name}.{module_alias}.{helper_name} returned empty payload"
                    )
                    assert all(
                        isinstance(value, str) and value.strip()
                        for value in result.values()
                    )
                    continue
                assert isinstance(result, str), (
                    f"{package_name}.{module_alias}.{helper_name} did not return str"
                )
                assert result.strip(), (
                    f"{package_name}.{module_alias}.{helper_name} returned empty text"
                )
