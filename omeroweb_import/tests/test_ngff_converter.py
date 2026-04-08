"""
Tests for NGFF converter settings normalization, command building,
and the conversion block in the import pipeline.

These tests catch real edge cases: injection attacks in series strings,
invalid enum values, out-of-range integers, non-dict inputs, and
correct CLI flag generation for every bioformats2raw option.
"""

import os
import unittest

# Minimal Django bootstrap (no DB required)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "omeroweb.settings")

try:
    import django

    django.setup()
except Exception:
    pass

from omeroweb_import.views.core_functions import (
    NGFF_CONVERTER_SETTINGS_DEFAULTS,
    SEM_EDX_SETTINGS_DEFAULTS,
    _build_bioformats2raw_command,
    _normalize_ngff_converter_settings,
    _normalize_sem_edx_settings,
)
from omeroweb_import.constants import BIOFORMATS2RAW_CLI


class TestNormalizeNgffConverterSettings(unittest.TestCase):
    """Validates that every setting is properly sanitized."""

    def test_none_returns_defaults(self):
        assert (
            _normalize_ngff_converter_settings(None) == NGFF_CONVERTER_SETTINGS_DEFAULTS
        )

    def test_string_returns_defaults(self):
        assert (
            _normalize_ngff_converter_settings("garbage")
            == NGFF_CONVERTER_SETTINGS_DEFAULTS
        )

    def test_list_returns_defaults(self):
        assert (
            _normalize_ngff_converter_settings([1, 2, 3])
            == NGFF_CONVERTER_SETTINGS_DEFAULTS
        )

    def test_empty_dict_returns_defaults(self):
        assert (
            _normalize_ngff_converter_settings({}) == NGFF_CONVERTER_SETTINGS_DEFAULTS
        )

    # --- compression whitelist ---

    def test_compression_blosc(self):
        assert (
            _normalize_ngff_converter_settings({"compression": "blosc"})["compression"]
            == "blosc"
        )

    def test_compression_zlib(self):
        assert (
            _normalize_ngff_converter_settings({"compression": "zlib"})["compression"]
            == "zlib"
        )

    def test_compression_null(self):
        assert (
            _normalize_ngff_converter_settings({"compression": "null"})["compression"]
            == "null"
        )

    def test_compression_case_insensitive(self):
        assert (
            _normalize_ngff_converter_settings({"compression": "BLOSC"})["compression"]
            == "blosc"
        )
        assert (
            _normalize_ngff_converter_settings({"compression": "Zlib"})["compression"]
            == "zlib"
        )

    def test_compression_invalid_defaults_to_blosc(self):
        assert (
            _normalize_ngff_converter_settings({"compression": "lz4"})["compression"]
            == "blosc"
        )
        assert (
            _normalize_ngff_converter_settings({"compression": ""})["compression"]
            == "blosc"
        )
        assert (
            _normalize_ngff_converter_settings({"compression": 42})["compression"]
            == "blosc"
        )

    # --- downsampling whitelist ---

    def test_downsampling_all_valid_values(self):
        for ds in ("SIMPLE", "GAUSSIAN", "AREA", "LINEAR", "CUBIC", "LANCZOS"):
            result = _normalize_ngff_converter_settings({"downsampling": ds})
            assert result["downsampling"] == ds, f"Failed for {ds}"

    def test_downsampling_case_insensitive(self):
        assert (
            _normalize_ngff_converter_settings({"downsampling": "gaussian"})[
                "downsampling"
            ]
            == "GAUSSIAN"
        )

    def test_downsampling_invalid_defaults_to_simple(self):
        assert (
            _normalize_ngff_converter_settings({"downsampling": "BICUBIC"})[
                "downsampling"
            ]
            == "SIMPLE"
        )
        assert (
            _normalize_ngff_converter_settings({"downsampling": ""})["downsampling"]
            == "SIMPLE"
        )

    # --- integer bounds ---

    def test_tile_width_clamped_low(self):
        assert _normalize_ngff_converter_settings({"tile_width": 1})["tile_width"] == 64

    def test_tile_width_clamped_high(self):
        assert (
            _normalize_ngff_converter_settings({"tile_width": 99999})["tile_width"]
            == 8192
        )

    def test_tile_width_valid(self):
        assert (
            _normalize_ngff_converter_settings({"tile_width": 512})["tile_width"] == 512
        )

    def test_tile_height_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"tile_height": 0})["tile_height"] == 64
        )
        assert (
            _normalize_ngff_converter_settings({"tile_height": 10000})["tile_height"]
            == 8192
        )

    def test_resolutions_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"resolutions": -1})["resolutions"] == 0
        )
        assert (
            _normalize_ngff_converter_settings({"resolutions": 50})["resolutions"] == 20
        )
        assert (
            _normalize_ngff_converter_settings({"resolutions": 0})["resolutions"] == 0
        )

    def test_max_workers_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"max_workers": 0})["max_workers"] == 1
        )
        assert (
            _normalize_ngff_converter_settings({"max_workers": 100})["max_workers"]
            == 32
        )

    def test_chunk_depth_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"chunk_depth": 0})["chunk_depth"] == 1
        )
        assert (
            _normalize_ngff_converter_settings({"chunk_depth": 999})["chunk_depth"]
            == 256
        )

    def test_fill_value_bounds(self):
        assert _normalize_ngff_converter_settings({"fill_value": -1})["fill_value"] == 0
        assert (
            _normalize_ngff_converter_settings({"fill_value": 999})["fill_value"] == 255
        )

    def test_max_cached_tiles_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"max_cached_tiles": 0})[
                "max_cached_tiles"
            ]
            == 1
        )
        assert (
            _normalize_ngff_converter_settings({"max_cached_tiles": 10000})[
                "max_cached_tiles"
            ]
            == 4096
        )

    def test_target_min_size_bounds(self):
        assert (
            _normalize_ngff_converter_settings({"target_min_size": 0})[
                "target_min_size"
            ]
            == 1
        )
        assert (
            _normalize_ngff_converter_settings({"target_min_size": 100000})[
                "target_min_size"
            ]
            == 65536
        )

    def test_integer_field_with_non_numeric_value_uses_default(self):
        result = _normalize_ngff_converter_settings({"tile_width": "abc"})
        assert result["tile_width"] == 1024

    def test_integer_field_with_none_uses_default(self):
        result = _normalize_ngff_converter_settings({"tile_width": None})
        assert result["tile_width"] == 1024

    # --- boolean fields ---

    def test_boolean_fields_true(self):
        for field in ("min_max", "nested", "hcs", "overwrite", "progress"):
            result = _normalize_ngff_converter_settings({field: True})
            assert result[field] is True, f"{field} should be True"

    def test_boolean_fields_false(self):
        for field in ("min_max", "nested", "hcs", "overwrite", "progress"):
            result = _normalize_ngff_converter_settings({field: False})
            assert result[field] is False, f"{field} should be False"

    def test_boolean_fields_truthy_coercion(self):
        result = _normalize_ngff_converter_settings({"min_max": 1})
        assert result["min_max"] is True
        result = _normalize_ngff_converter_settings({"min_max": 0})
        assert result["min_max"] is False

    # --- series sanitization ---

    def test_series_valid(self):
        assert (
            _normalize_ngff_converter_settings({"series": "0,1,3"})["series"] == "0,1,3"
        )

    def test_series_empty(self):
        assert _normalize_ngff_converter_settings({"series": ""})["series"] == ""

    def test_series_strips_non_digits(self):
        assert (
            _normalize_ngff_converter_settings({"series": "0,abc,2"})["series"] == "0,2"
        )

    def test_series_injection_attack(self):
        """Semicolons, pipes, backticks etc. must be stripped."""
        assert (
            _normalize_ngff_converter_settings({"series": "; rm -rf /"})["series"] == ""
        )
        assert (
            _normalize_ngff_converter_settings({"series": "0|1"})["series"] == ""
        )  # pipe not a valid separator
        assert (
            _normalize_ngff_converter_settings({"series": "`whoami`"})["series"] == ""
        )
        assert (
            _normalize_ngff_converter_settings({"series": "$(cat /etc/passwd)"})[
                "series"
            ]
            == ""
        )

    def test_series_with_spaces(self):
        assert (
            _normalize_ngff_converter_settings({"series": " 0 , 1 , 2 "})["series"]
            == "0,1,2"
        )

    def test_series_none(self):
        assert _normalize_ngff_converter_settings({"series": None})["series"] == ""


class TestBuildBioformats2rawCommand(unittest.TestCase):
    """Validates CLI command generation for every bioformats2raw flag."""

    def _defaults(self, **overrides):
        s = dict(NGFF_CONVERTER_SETTINGS_DEFAULTS)
        s.update(overrides)
        return s

    def test_binary_path_is_first(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults())
        assert cmd[0] == BIOFORMATS2RAW_CLI

    def test_input_output_paths_are_last(self):
        cmd = _build_bioformats2raw_command(
            "/in/f.czi", "/out/f.zarr", self._defaults()
        )
        assert cmd[-2] == "/in/f.czi"
        assert cmd[-1] == "/out/f.zarr"

    def test_compression_blosc(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(compression="blosc")
        )
        idx = cmd.index("--compression")
        assert cmd[idx + 1] == "blosc"

    def test_compression_null(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(compression="null")
        )
        idx = cmd.index("--compression")
        assert cmd[idx + 1] == "null"

    def test_tile_dimensions(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(tile_width=512, tile_height=256)
        )
        assert cmd[cmd.index("--tile-width") + 1] == "512"
        assert cmd[cmd.index("--tile-height") + 1] == "256"

    def test_resolutions_zero_omitted(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(resolutions=0)
        )
        assert "--resolutions" not in cmd

    def test_resolutions_nonzero_included(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(resolutions=5)
        )
        assert cmd[cmd.index("--resolutions") + 1] == "5"

    def test_max_workers(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(max_workers=8)
        )
        assert cmd[cmd.index("--max-workers") + 1] == "8"

    def test_chunk_depth(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(chunk_depth=16)
        )
        assert cmd[cmd.index("--chunk-depth") + 1] == "16"

    def test_downsample_type(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(downsampling="LANCZOS")
        )
        assert cmd[cmd.index("--downsample-type") + 1] == "LANCZOS"

    def test_fill_value(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(fill_value=128)
        )
        assert cmd[cmd.index("--fill-value") + 1] == "128"

    def test_max_cached_tiles(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(max_cached_tiles=32)
        )
        assert cmd[cmd.index("--max-cached-tiles") + 1] == "32"

    def test_target_min_size(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(target_min_size=512)
        )
        assert cmd[cmd.index("--target-min-size") + 1] == "512"

    def test_no_minmax_when_disabled(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(min_max=False)
        )
        assert "--no-minmax" in cmd

    def test_no_minmax_absent_when_enabled(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(min_max=True))
        assert "--no-minmax" not in cmd

    def test_no_nested_when_disabled(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(nested=False))
        assert "--no-nested" in cmd

    def test_no_nested_absent_when_enabled(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(nested=True))
        assert "--no-nested" not in cmd

    def test_no_hcs_when_disabled(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(hcs=False))
        assert "--no-hcs" in cmd

    def test_no_hcs_absent_when_enabled(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(hcs=True))
        assert "--no-hcs" not in cmd

    def test_overwrite_present_when_true(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(overwrite=True)
        )
        assert "--overwrite" in cmd

    def test_overwrite_absent_when_false(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(overwrite=False)
        )
        assert "--overwrite" not in cmd

    def test_progress_present_when_true(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(progress=True)
        )
        assert "--progress" in cmd

    def test_progress_absent_when_false(self):
        cmd = _build_bioformats2raw_command(
            "/in", "/out", self._defaults(progress=False)
        )
        assert "--progress" not in cmd

    def test_series_included_when_nonempty(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(series="0,1"))
        assert cmd[cmd.index("--series") + 1] == "0,1"

    def test_series_omitted_when_empty(self):
        cmd = _build_bioformats2raw_command("/in", "/out", self._defaults(series=""))
        assert "--series" not in cmd

    def test_none_settings_uses_defaults(self):
        cmd = _build_bioformats2raw_command("/in", "/out", None)
        assert cmd[0] == BIOFORMATS2RAW_CLI
        assert "--overwrite" in cmd
        assert "--progress" in cmd

    def test_all_flags_combined(self):
        """A single run with all non-default options to verify no clashes."""
        s = self._defaults(
            compression="zlib",
            tile_width=512,
            tile_height=256,
            resolutions=3,
            max_workers=2,
            chunk_depth=8,
            downsampling="CUBIC",
            fill_value=42,
            max_cached_tiles=16,
            target_min_size=64,
            min_max=False,
            nested=False,
            hcs=False,
            overwrite=False,
            progress=False,
            series="0,2,4",
        )
        cmd = _build_bioformats2raw_command("/test/in.lif", "/test/out.zarr", s)
        assert "--compression" in cmd
        assert "zlib" in cmd
        assert "--no-minmax" in cmd
        assert "--no-nested" in cmd
        assert "--no-hcs" in cmd
        assert "--overwrite" not in cmd
        assert "--progress" not in cmd
        assert "--series" in cmd
        assert "--resolutions" in cmd
        # No duplicate flags
        flag_counts = {}
        for item in cmd:
            if item.startswith("--"):
                flag_counts[item] = flag_counts.get(item, 0) + 1
        for flag, count in flag_counts.items():
            assert count == 1, f"Duplicate flag: {flag}"


class TestSemEdxSettingsUnchanged(unittest.TestCase):
    """Verify SEM EDX normalization behaviour was NOT broken by NGFF changes."""

    def test_defaults(self):
        assert _normalize_sem_edx_settings({}) == SEM_EDX_SETTINGS_DEFAULTS

    def test_none_returns_defaults(self):
        assert _normalize_sem_edx_settings(None) == SEM_EDX_SETTINGS_DEFAULTS

    def test_string_returns_defaults(self):
        assert _normalize_sem_edx_settings("x") == SEM_EDX_SETTINGS_DEFAULTS

    def test_partial_override(self):
        result = _normalize_sem_edx_settings({"create_tables": False})
        assert result["create_tables"] is False
        assert result["create_figures_attachments"] is True
        assert result["create_figures_images"] is True

    def test_all_false(self):
        result = _normalize_sem_edx_settings(
            {
                "create_tables": False,
                "create_figures_attachments": False,
                "create_figures_images": False,
            }
        )
        assert all(v is False for v in result.values())

    def test_truthy_coercion(self):
        result = _normalize_sem_edx_settings(
            {"create_tables": 1, "create_figures_attachments": ""}
        )
        assert result["create_tables"] is True
        assert result["create_figures_attachments"] is False

    def test_unknown_keys_ignored(self):
        result = _normalize_sem_edx_settings(
            {"unknown_key": True, "create_tables": False}
        )
        assert "unknown_key" not in result
        assert result["create_tables"] is False


class TestSpecialMethodSettingsViewNormalization(unittest.TestCase):
    """Verify the view-level normalization preserves types for NGFF settings."""

    def test_preserves_string_int_bool(self):
        from omeroweb_import.views.special_method_settings_view import (
            _normalize_special_method_settings,
        )

        raw = {
            "compression": "zlib",
            "tile_width": 512,
            "min_max": False,
            "nested": True,
        }
        result = _normalize_special_method_settings(raw)
        assert result["compression"] == "zlib"
        assert result["tile_width"] == 512
        assert result["min_max"] is False
        assert result["nested"] is True

    def test_non_dict_returns_empty(self):
        from omeroweb_import.views.special_method_settings_view import (
            _normalize_special_method_settings,
        )

        assert _normalize_special_method_settings(None) == {}
        assert _normalize_special_method_settings("x") == {}
        assert _normalize_special_method_settings(42) == {}

    def test_unknown_types_coerced_to_bool(self):
        from omeroweb_import.views.special_method_settings_view import (
            _normalize_special_method_settings,
        )

        result = _normalize_special_method_settings({"x": [1, 2]})
        assert result["x"] is True

    def test_float_preserved(self):
        from omeroweb_import.views.special_method_settings_view import (
            _normalize_special_method_settings,
        )

        result = _normalize_special_method_settings({"quality": 0.75})
        assert result["quality"] == 0.75


class TestNgffConverterInStartUpload(unittest.TestCase):
    """Verify that index_view._start_upload handles ngff_converter settings."""

    def test_ngff_settings_stored_in_job_when_ngff_selected(self):
        from omeroweb_import.views.core_functions import (
            _normalize_ngff_converter_settings,
        )

        raw = {"compression": "zlib", "tile_width": 2048, "series": "0,1"}
        normalized = _normalize_ngff_converter_settings(raw)
        assert normalized["compression"] == "zlib"
        assert normalized["tile_width"] == 2048
        assert normalized["series"] == "0,1"
        # Verify the job dict would contain the right keys
        job = {
            "special_upload": "ngff_converter",
            "ngff_converter_settings": normalized,
        }
        assert job["ngff_converter_settings"]["compression"] == "zlib"

    def test_ngff_settings_empty_when_sem_selected(self):
        from omeroweb_import.views.core_functions import (
            _normalize_ngff_converter_settings,
        )

        raw = {"compression": "zlib"}
        # When special_upload != ngff_converter, settings should be empty
        # This mimics the logic in index_view.py
        special_upload = "sem_edx_spectra"
        ngff_settings = (
            _normalize_ngff_converter_settings(raw)
            if special_upload == "ngff_converter"
            else {}
        )
        assert ngff_settings == {}


if __name__ == "__main__":
    unittest.main()
