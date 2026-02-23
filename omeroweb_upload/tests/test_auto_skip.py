"""Tests for _should_auto_skip_import and related constants."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_upload.views.core_functions import (
    _ALWAYS_SKIP_DIRS,
    _ALWAYS_SKIP_FILENAMES,
    _should_auto_skip_import,
)


# ── helpers ──────────────────────────────────────────────────────────

class TestConstantsAreLowercase:
    """All entries in the skip sets must be lowercase (matching is case-folded)."""

    def test_filenames_all_lowercase(self):
        for name in _ALWAYS_SKIP_FILENAMES:
            assert name == name.lower(), f"{name!r} is not lowercase"

    def test_dirs_all_lowercase(self):
        for name in _ALWAYS_SKIP_DIRS:
            assert name == name.lower(), f"{name!r} is not lowercase"


# ── Windows OS files ─────────────────────────────────────────────────

class TestWindowsJunkFiles:
    @pytest.mark.parametrize("filename", [
        "Thumbs.db",
        "thumbs.db",
        "THUMBS.DB",
        "desktop.ini",
        "Desktop.ini",
        "ehthumbs.db",
        "ehthumbs_vista.db",
        "IconCache.db",
        "ntuser.dat",
        "ntuser.dat.log",
        "ntuser.ini",
    ])
    def test_windows_files_skipped(self, filename):
        assert _should_auto_skip_import(filename) is True

    @pytest.mark.parametrize("filename", [
        "Thumbs.db",
        "desktop.ini",
    ])
    def test_windows_files_in_subdirectory_skipped(self, filename):
        assert _should_auto_skip_import(f"experiment/{filename}") is True


# ── macOS OS files ───────────────────────────────────────────────────

class TestMacOSJunkFiles:
    @pytest.mark.parametrize("filename", [
        ".DS_Store",
        ".ds_store",
        ".DS_STORE",
        ".apdisk",
        ".VolumeIcon.icns",
        ".fseventsd",
        ".Spotlight-V100",
        ".TemporaryItems",
        ".Trashes",
    ])
    def test_macos_files_skipped(self, filename):
        assert _should_auto_skip_import(filename) is True

    def test_macos_resource_fork_files(self):
        assert _should_auto_skip_import("._image.tif") is True
        assert _should_auto_skip_import("folder/._data.xml") is True
        assert _should_auto_skip_import("a/b/._anything") is True


# ── Linux OS files ───────────────────────────────────────────────────

class TestLinuxJunkFiles:
    def test_directory_file_skipped(self):
        assert _should_auto_skip_import(".directory") is True

    def test_trash_sentinel_skipped(self):
        assert _should_auto_skip_import(".Trash-1000") is True


# ── Application metadata files ───────────────────────────────────────

class TestApplicationJunkFiles:
    @pytest.mark.parametrize("filename", [
        ".picasa.ini",
        ".BridgeCache",
        ".bridgecache",
        ".BridgeCacheT",
        ".bridgecachet",
        ".BridgeSort",
        ".bridgesort",
        ".PicasaOriginals",
        ".picasaoriginals",
        ".adobe",
    ])
    def test_app_metadata_skipped(self, filename):
        assert _should_auto_skip_import(filename) is True


# ── OS junk directories ──────────────────────────────────────────────

class TestJunkDirectories:
    def test_lost_and_found_contents_skipped(self):
        assert _should_auto_skip_import("lost+found/file.tif") is True
        assert _should_auto_skip_import("lost+found/subdir/image.png") is True

    def test_lost_and_found_case_insensitive(self):
        assert _should_auto_skip_import("Lost+Found/file.tif") is True
        assert _should_auto_skip_import("LOST+FOUND/file.tif") is True

    def test_recycle_bin_contents_skipped(self):
        assert _should_auto_skip_import("$RECYCLE.BIN/file.tif") is True
        assert _should_auto_skip_import("$Recycle.Bin/S-1-5/image.jpg") is True

    def test_system_volume_information_skipped(self):
        assert _should_auto_skip_import("System Volume Information/file.tif") is True

    def test_spotlight_dir_contents_skipped(self):
        assert _should_auto_skip_import(".Spotlight-V100/store.db") is True

    def test_fseventsd_dir_contents_skipped(self):
        assert _should_auto_skip_import(".fseventsd/000001") is True

    def test_trashes_dir_contents_skipped(self):
        assert _should_auto_skip_import(".Trashes/501/image.tif") is True

    def test_temporaryitems_dir_contents_skipped(self):
        assert _should_auto_skip_import(".TemporaryItems/temp.tif") is True

    def test_junk_dir_nested_deep(self):
        assert _should_auto_skip_import("volume/lost+found/deep/file.tif") is True


# ── XML files: MUST NOT be skipped ───────────────────────────────────

class TestXMLFilesNeverSkipped:
    """XML files must always be forwarded to OMERO regardless of location."""

    def test_plain_xml_not_skipped(self):
        assert _should_auto_skip_import("data.xml") is False

    def test_ome_xml_not_skipped(self):
        assert _should_auto_skip_import("image.ome.xml") is False

    def test_companion_ome_not_skipped(self):
        assert _should_auto_skip_import("image.companion.ome") is False

    def test_xml_in_root_not_skipped(self):
        assert _should_auto_skip_import("settings.xml") is False

    def test_xml_in_metadata_dir_not_skipped(self):
        """XML files inside metadata/ directories must NOT be auto-skipped.
        OMERO should decide whether it can import them."""
        assert _should_auto_skip_import("metadata/data.xml") is False
        assert _should_auto_skip_import("_metadata/info.xml") is False
        assert _should_auto_skip_import(".metadata/config.xml") is False

    def test_xml_in_arbitrary_dir_not_skipped(self):
        assert _should_auto_skip_import("experiment/data.xml") is False
        assert _should_auto_skip_import("project/subfolder/config.xml") is False

    def test_xml_in_deeply_nested_dir_not_skipped(self):
        assert _should_auto_skip_import("a/b/c/d/image.xml") is False

    def test_ome_xml_in_metadata_dir_not_skipped(self):
        assert _should_auto_skip_import("metadata/image.ome.xml") is False

    def test_xml_with_various_cases_not_skipped(self):
        assert _should_auto_skip_import("DATA.XML") is False
        assert _should_auto_skip_import("Image.Xml") is False
        assert _should_auto_skip_import("folder/FILE.XML") is False


# ── Legitimate image / data files: MUST NOT be skipped ───────────────

class TestLegitimateFilesNotSkipped:
    """Regular files must pass through to OMERO."""

    @pytest.mark.parametrize("path", [
        "image.tif",
        "image.tiff",
        "image.ome.tif",
        "image.ome.tiff",
        "image.png",
        "image.jpg",
        "image.jpeg",
        "image.bmp",
        "image.gif",
        "image.nd2",
        "image.czi",
        "image.lif",
        "image.lsm",
        "image.dv",
        "image.svs",
        "image.vsi",
        "image.ims",
        "data.h5",
        "data.hdf5",
        "data.csv",
        "data.txt",
        "notes.pdf",
        "readme.md",
    ])
    def test_image_and_data_files_not_skipped(self, path):
        assert _should_auto_skip_import(path) is False

    def test_files_in_subdirectories_not_skipped(self):
        assert _should_auto_skip_import("experiment/image.tif") is False
        assert _should_auto_skip_import("project/data/image.czi") is False
        assert _should_auto_skip_import("a/b/c/scan.nd2") is False

    def test_files_in_metadata_named_dir_not_skipped(self):
        """Files in directories called 'metadata' must NOT be auto-skipped
        (only OS junk dirs trigger skipping)."""
        assert _should_auto_skip_import("metadata/image.tif") is False
        assert _should_auto_skip_import("_metadata/scan.nd2") is False


# ── Edge cases ───────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string_not_skipped(self):
        assert _should_auto_skip_import("") is False

    def test_none_like_empty_not_skipped(self):
        # The function checks `if not relative_path`
        assert _should_auto_skip_import("") is False

    def test_filename_only_no_directory(self):
        assert _should_auto_skip_import("Thumbs.db") is True
        assert _should_auto_skip_import("image.tif") is False

    def test_hidden_regular_file_not_skipped(self):
        """Hidden files that aren't in the skip list pass through."""
        assert _should_auto_skip_import(".hidden_image.tif") is False

    def test_resource_fork_prefix_only_skipped_for_dot_underscore(self):
        """Only ._* prefix triggers skip, not just underscore."""
        assert _should_auto_skip_import("._resource") is True
        assert _should_auto_skip_import("_normalfile.tif") is False

    def test_directory_name_matching_skip_filename_does_not_skip_contents(self):
        """A directory named 'thumbs.db' should not cause its contents to be skipped
        (only _ALWAYS_SKIP_DIRS entries trigger directory-level skipping)."""
        assert _should_auto_skip_import("thumbs.db/image.tif") is False

    def test_skip_dir_at_any_depth(self):
        """_ALWAYS_SKIP_DIRS matching works at any path depth."""
        assert _should_auto_skip_import("a/lost+found/b/file.tif") is True
        assert _should_auto_skip_import("x/y/$RECYCLE.BIN/file.tif") is True
