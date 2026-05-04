"""Tests for _should_auto_skip_import and related constants."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_import.views.core_functions import (
    _ALWAYS_SKIP_DIRS,
    _ALWAYS_SKIP_FILENAMES,
    _should_auto_skip_import,
)


# ── helpers ──────────────────────────────────────────────────────────


class TestConstantsAreLowercase:
    """All entries in the skip sets must be lowercase (matching is case-folded)."""

    @staticmethod
    def test_filenames_all_lowercase():
        """Verify filenames all lowercase.

        Inputs: import-job fakes. Output: fails on regressions in filenames all lowercase.
        """
        for name in _ALWAYS_SKIP_FILENAMES:
            assert name == name.lower(), f"{name!r} is not lowercase"

    @staticmethod
    def test_dirs_all_lowercase():
        """Verify dirs all lowercase.

        Inputs: import-job fakes. Output: fails on regressions in dirs all lowercase.
        """
        for name in _ALWAYS_SKIP_DIRS:
            assert name == name.lower(), f"{name!r} is not lowercase"


# ── Windows OS files ─────────────────────────────────────────────────


class TestWindowsJunkFiles:
    """Test double for test windows junk files behavior in this module."""

    @pytest.mark.parametrize(
        "filename",
        [
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
        ],
    )
    def test_windows_files_skipped(self, filename):
        """Verify windows files skipped.

        Inputs: pytest provides `filename`. Output: fails on regressions in windows files skipped.
        """
        assert _should_auto_skip_import(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "Thumbs.db",
            "desktop.ini",
        ],
    )
    def test_windows_files_in_subdirectory_skipped(self, filename):
        """Verify windows files in subdirectory skipped.

        Inputs: pytest provides `filename`. Output: fails on regressions in windows files in subdirectory skipped.
        """
        assert _should_auto_skip_import(f"experiment/{filename}") is True


# ── macOS OS files ───────────────────────────────────────────────────


class TestMacOSJunkFiles:
    """Test double for test mac osjunk files behavior in this module."""

    @pytest.mark.parametrize(
        "filename",
        [
            ".DS_Store",
            ".ds_store",
            ".DS_STORE",
            ".apdisk",
            ".VolumeIcon.icns",
            ".fseventsd",
            ".Spotlight-V100",
            ".TemporaryItems",
            ".Trashes",
        ],
    )
    def test_macos_files_skipped(self, filename):
        """Verify macos files skipped.

        Inputs: pytest provides `filename`. Output: fails on regressions in macos files skipped.
        """
        assert _should_auto_skip_import(filename) is True

    @staticmethod
    def test_macos_resource_fork_files():
        """Verify macos resource fork files.

        Inputs: import-job fakes. Output: fails on regressions in macos resource fork files.
        """
        assert _should_auto_skip_import("._image.tif") is True
        assert _should_auto_skip_import("folder/._data.xml") is True
        assert _should_auto_skip_import("a/b/._anything") is True


# ── Linux OS files ───────────────────────────────────────────────────


class TestLinuxJunkFiles:
    """Test double for test linux junk files behavior in this module."""

    @staticmethod
    def test_directory_file_skipped():
        """Verify directory file skipped.

        Inputs: import-job fakes. Output: fails on regressions in directory file skipped.
        """
        assert _should_auto_skip_import(".directory") is True

    @staticmethod
    def test_trash_sentinel_skipped():
        """Verify trash sentinel skipped.

        Inputs: import-job fakes. Output: fails on regressions in trash sentinel skipped.
        """
        assert _should_auto_skip_import(".Trash-1000") is True


# ── Application metadata files ───────────────────────────────────────


class TestApplicationJunkFiles:
    """Test double for test application junk files behavior in this module."""

    @pytest.mark.parametrize(
        "filename",
        [
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
        ],
    )
    def test_app_metadata_skipped(self, filename):
        """Verify app metadata skipped.

        Inputs: pytest provides `filename`. Output: fails on regressions in app metadata skipped.
        """
        assert _should_auto_skip_import(filename) is True


# ── OS junk directories ──────────────────────────────────────────────


class TestJunkDirectories:
    """Test double for test junk directories behavior in this module."""

    @staticmethod
    def test_lost_and_found_contents_skipped():
        """Verify lost and found contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in lost and found contents skipped.
        """
        assert _should_auto_skip_import("lost+found/file.tif") is True
        assert _should_auto_skip_import("lost+found/subdir/image.png") is True

    @staticmethod
    def test_lost_and_found_case_insensitive():
        """Verify lost and found case insensitive.

        Inputs: import-job fakes. Output: fails on regressions in lost and found case insensitive.
        """
        assert _should_auto_skip_import("Lost+Found/file.tif") is True
        assert _should_auto_skip_import("LOST+FOUND/file.tif") is True

    @staticmethod
    def test_recycle_bin_contents_skipped():
        """Verify recycle bin contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in recycle bin contents skipped.
        """
        assert _should_auto_skip_import("$RECYCLE.BIN/file.tif") is True
        assert _should_auto_skip_import("$Recycle.Bin/S-1-5/image.jpg") is True

    @staticmethod
    def test_system_volume_information_skipped():
        """Verify system volume information skipped.

        Inputs: import-job fakes. Output: fails on regressions in system volume information skipped.
        """
        assert _should_auto_skip_import("System Volume Information/file.tif") is True

    @staticmethod
    def test_spotlight_dir_contents_skipped():
        """Verify spotlight dir contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in spotlight dir contents skipped.
        """
        assert _should_auto_skip_import(".Spotlight-V100/store.db") is True

    @staticmethod
    def test_fseventsd_dir_contents_skipped():
        """Verify fseventsd dir contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in fseventsd dir contents skipped.
        """
        assert _should_auto_skip_import(".fseventsd/000001") is True

    @staticmethod
    def test_trashes_dir_contents_skipped():
        """Verify trashes dir contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in trashes dir contents skipped.
        """
        assert _should_auto_skip_import(".Trashes/501/image.tif") is True

    @staticmethod
    def test_temporaryitems_dir_contents_skipped():
        """Verify temporaryitems dir contents skipped.

        Inputs: import-job fakes. Output: fails on regressions in temporaryitems dir contents skipped.
        """
        assert _should_auto_skip_import(".TemporaryItems/temp.tif") is True

    @staticmethod
    def test_junk_dir_nested_deep():
        """Verify junk dir nested deep.

        Inputs: import-job fakes. Output: fails on regressions in junk dir nested deep.
        """
        assert _should_auto_skip_import("volume/lost+found/deep/file.tif") is True


# ── XML files: MUST NOT be skipped ───────────────────────────────────


class TestXMLFilesNeverSkipped:
    """XML files must always be forwarded to OMERO regardless of location."""

    @staticmethod
    def test_plain_xml_not_skipped():
        """Verify plain xml not skipped.

        Inputs: import-job fakes. Output: fails on regressions in plain xml not skipped.
        """
        assert _should_auto_skip_import("data.xml") is False

    @staticmethod
    def test_ome_xml_not_skipped():
        """Verify ome xml not skipped.

        Inputs: import-job fakes. Output: fails on regressions in ome xml not skipped.
        """
        assert _should_auto_skip_import("image.ome.xml") is False

    @staticmethod
    def test_companion_ome_not_skipped():
        """Verify companion ome not skipped.

        Inputs: import-job fakes. Output: fails on regressions in companion ome not skipped.
        """
        assert _should_auto_skip_import("image.companion.ome") is False

    @staticmethod
    def test_xml_in_root_not_skipped():
        """Verify xml in root not skipped.

        Inputs: import-job fakes. Output: fails on regressions in xml in root not skipped.
        """
        assert _should_auto_skip_import("settings.xml") is False

    @staticmethod
    def test_xml_in_metadata_dir_not_skipped():
        """Verify xml in metadata dir not skipped.

        Inputs: import-job fakes. Output: fails on regressions in xml in metadata dir not skipped.

        OMERO should decide whether it can import them.
        """
        assert _should_auto_skip_import("metadata/data.xml") is False
        assert _should_auto_skip_import("_metadata/info.xml") is False
        assert _should_auto_skip_import(".metadata/config.xml") is False

    @staticmethod
    def test_xml_in_arbitrary_dir_not_skipped():
        """Verify xml in arbitrary dir not skipped.

        Inputs: import-job fakes. Output: fails on regressions in xml in arbitrary dir not skipped.
        """
        assert _should_auto_skip_import("experiment/data.xml") is False
        assert _should_auto_skip_import("project/subfolder/config.xml") is False

    @staticmethod
    def test_xml_in_deeply_nested_dir_not_skipped():
        """Verify xml in deeply nested dir not skipped.

        Inputs: import-job fakes. Output: fails on regressions in xml in deeply nested dir not skipped.
        """
        assert _should_auto_skip_import("a/b/c/d/image.xml") is False

    @staticmethod
    def test_ome_xml_in_metadata_dir_not_skipped():
        """Verify ome xml in metadata dir not skipped.

        Inputs: import-job fakes. Output: fails on regressions in ome xml in metadata dir not skipped.
        """
        assert _should_auto_skip_import("metadata/image.ome.xml") is False

    @staticmethod
    def test_xml_with_various_cases_not_skipped():
        """Verify xml with various cases not skipped.

        Inputs: import-job fakes. Output: fails on regressions in xml with various cases not skipped.
        """
        assert _should_auto_skip_import("DATA.XML") is False
        assert _should_auto_skip_import("Image.Xml") is False
        assert _should_auto_skip_import("folder/FILE.XML") is False


# ── Legitimate image / data files: MUST NOT be skipped ───────────────


class TestLegitimateFilesNotSkipped:
    """Regular files must pass through to OMERO."""

    @pytest.mark.parametrize(
        "path",
        [
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
        ],
    )
    def test_image_and_data_files_not_skipped(self, path):
        """Verify image and data files not skipped.

        Inputs: pytest provides `path`. Output: fails on regressions in image and data files not skipped.
        """
        assert _should_auto_skip_import(path) is False

    @staticmethod
    def test_files_in_subdirectories_not_skipped():
        """Verify files in subdirectories not skipped.

        Inputs: import-job fakes. Output: fails on regressions in files in subdirectories not skipped.
        """
        assert _should_auto_skip_import("experiment/image.tif") is False
        assert _should_auto_skip_import("project/data/image.czi") is False
        assert _should_auto_skip_import("a/b/c/scan.nd2") is False

    @staticmethod
    def test_files_in_metadata_named_dir_not_skipped():
        """Verify files in metadata named dir not skipped.

        Inputs: import-job fakes. Output: fails on regressions in files in metadata named dir not skipped.

        (only OS junk dirs trigger skipping).
        """
        assert _should_auto_skip_import("metadata/image.tif") is False
        assert _should_auto_skip_import("_metadata/scan.nd2") is False


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    """Test double for test edge cases behavior in this module."""

    @staticmethod
    def test_empty_string_not_skipped():
        """Verify empty string not skipped.

        Inputs: import-job fakes. Output: fails on regressions in empty string not skipped.
        """
        assert _should_auto_skip_import("") is False

    @staticmethod
    def test_none_like_empty_not_skipped():
        # The function checks `if not relative_path`
        """Verify none like empty not skipped.

        Inputs: import-job fakes. Output: fails on regressions in none like empty not skipped.
        """
        assert _should_auto_skip_import("") is False

    @staticmethod
    def test_filename_only_no_directory():
        """Verify filename only no directory.

        Inputs: import-job fakes. Output: fails on regressions in filename only no directory.
        """
        assert _should_auto_skip_import("Thumbs.db") is True
        assert _should_auto_skip_import("image.tif") is False

    @staticmethod
    def test_hidden_regular_file_not_skipped():
        """Verify hidden regular file not skipped.

        Inputs: import-job fakes. Output: fails on regressions in hidden regular file not skipped.
        """
        assert _should_auto_skip_import(".hidden_image.tif") is False

    @staticmethod
    def test_resource_fork_prefix_only_skipped_for_dot_underscore():
        """Verify resource fork prefix only skipped for dot underscore.

        Inputs: import-job fakes. Output: fails on regressions in resource fork prefix only skipped for dot underscore.
        """
        assert _should_auto_skip_import("._resource") is True
        assert _should_auto_skip_import("_normalfile.tif") is False

    @staticmethod
    def test_directory_name_matching_skip_filename_does_not_skip_contents():
        """Verify directory name matching skip filename does not skip contents.

        Inputs: import-job fakes. Output: fails on regressions in directory name matching skip filename does not skip contents.

        (only _ALWAYS_SKIP_DIRS entries trigger directory-level skipping).
        """
        assert _should_auto_skip_import("thumbs.db/image.tif") is False

    @staticmethod
    def test_skip_dir_at_any_depth():
        """Verify skip dir at any depth.

        Inputs: import-job fakes. Output: fails on regressions in skip dir at any depth.
        """
        assert _should_auto_skip_import("a/lost+found/b/file.tif") is True
        assert _should_auto_skip_import("x/y/$RECYCLE.BIN/file.tif") is True
