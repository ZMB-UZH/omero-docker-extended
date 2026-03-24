from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path


def _load_omp_service_module(module_name: str, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    package_name = "omeroweb_omp_plugin"
    services_name = f"{package_name}.services"

    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(repo_root / package_name)]
    services_module = types.ModuleType(services_name)
    services_module.__path__ = [str(repo_root / package_name / "services")]
    constants_module = types.ModuleType(f"{package_name}.constants")
    constants_module.PROTECTED_HYPHEN_PATTERNS = [
        r"(?<=x)(?:objective|oil|water)",
        r"(?<=[ZTC])(?:stack|series|plane|projection)",
        r"[A-Za-z]+\d+",
    ]

    monkeypatch.setitem(sys.modules, package_name, package_module)
    monkeypatch.setitem(sys.modules, services_name, services_module)
    monkeypatch.setitem(sys.modules, f"{package_name}.constants", constants_module)

    full_name = f"{services_name}.{module_name}"
    spec = importlib.util.spec_from_file_location(
        full_name,
        repo_root / package_name / "services" / f"{module_name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_error_details_handles_json_plain_text_and_empty_payloads(monkeypatch):
    http_utils = _load_omp_service_module("http_utils", monkeypatch)

    class _ErrorWithPayload:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload

    class _BrokenRead:
        def read(self):
            raise RuntimeError("boom")

    assert http_utils.extract_error_details(None) is None
    assert http_utils.extract_error_details(_BrokenRead()) is None
    assert http_utils.extract_error_details(_ErrorWithPayload(b"")) is None
    assert (
        http_utils.extract_error_details(
            _ErrorWithPayload(b'{"error": {"message": "nested failure"}}')
        )
        == "nested failure"
    )
    assert http_utils.extract_error_details(_ErrorWithPayload(b'{"message": "flat failure"}')) == "flat failure"
    assert http_utils.extract_error_details(_ErrorWithPayload(b" plain text failure \n")) == "plain text failure"


def test_extract_base_name_and_pair_detection_cover_brackets_whitespace_and_threshold(monkeypatch):
    filename_utils = _load_omp_service_module("filename_utils", monkeypatch)

    assert filename_utils.extract_base_name("prefix [A-01] suffix.tif") == "A-01"
    assert filename_utils.extract_base_name("prefix\tcell-ab-12.ome.tif") == "cell-ab-12.ome"

    has_pairs, labels = filename_utils.detect_label_value_pairs(
        [
            "run ab-12-cd-34.tif",
            "run ab-13-cd-35.tif",
            "run ab-14-cd-36.tif",
        ]
    )
    assert has_pairs is True
    assert labels == {"ab", "cd"}

    has_pairs, labels = filename_utils.detect_label_value_pairs(
        [
            "run AB-12-random.tif",
            "run q-9-other.tif",
            "run sample-only.tif",
        ]
    )
    assert has_pairs is False
    assert labels == set()


def test_filename_regex_helpers_keep_digit_fallback_and_detected_labels(monkeypatch):
    filename_utils = _load_omp_service_module("filename_utils", monkeypatch)

    assert (
        filename_utils.regex_for_separators([], filenames=["image001"])
        == r"(?<=\D)(?=\d)|(?<=\d)(?=\D)"
    )

    pattern = filename_utils.build_hyphen_protection_pattern({"ab", "cd"})
    assert "(?:^|-)(?:ab|cd)-" in pattern
    assert r"(?<=x)(?:objective|oil|water)" in pattern

    combined_pattern = filename_utils.regex_for_separators(
        ["-"],
        filenames=[
            "sample-ab-12-cd-34.tif",
            "sample-ab-13-cd-35.tif",
        ],
    )
    assert "(?:^|-)(?:ab|cd)-" in combined_pattern
    assert re.search(r"A-Za-z", combined_pattern)


def test_suggest_separator_regex_prefers_frequent_non_alphanumeric_candidates(monkeypatch):
    filename_utils = _load_omp_service_module("filename_utils", monkeypatch)
    captured = {}

    def _fake_regex_for_separators(separators, filenames=None):
        captured["separators"] = list(separators)
        captured["filenames"] = list(filenames or [])
        return "captured-pattern"

    monkeypatch.setattr(filename_utils, "regex_for_separators", _fake_regex_for_separators)

    result = filename_utils.suggest_separator_regex(
        [
            "alpha_beta-gamma.tif",
            "delta_beta-gamma.tif",
            "omega_beta-gamma.tif",
        ],
        allowed_separators={"_", "-"},
    )

    assert result == "captured-pattern"
    assert set(captured["separators"]) == {"_", "-"}
    assert len(captured["filenames"]) == 3
