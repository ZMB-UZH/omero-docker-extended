"""Exercise generated spectrum artifacts with real Linux filesystem boundaries."""

from __future__ import annotations

import errno
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from omeroweb_import.services.omero import sem_edx_parser
from omeroweb_import.views import core_functions


@pytest.fixture
def spectrum(tmp_path):
    """Inputs: temporary directory. Output: job root and staged valid spectrum."""
    root = tmp_path / "job"
    source = root / "_staged" / "images" / "sample.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        "#SPECTRUM : counts\n1.0, 2\n2.0, 5\n3.0, 1\n#ENDOFDATA\n",
        encoding="utf-8",
    )
    return root, source


def test_generated_plots_are_distinct_private_files_with_real_png_content(spectrum):
    """Inputs: staged spectrum. Output: assertions of isolated, private, valid PNGs."""
    root, source = spectrum
    original_text = source.read_bytes()
    uploaded_png = source.with_name("sample_edx.png")
    uploaded_png.write_bytes(b"existing uploaded file")
    paths = [core_functions._create_job_edx_plot(root, source) for _ in range(2)]
    assert paths[0] != paths[1]
    for path in paths:
        assert path.relative_to(root).parts[:2] == ("_derived", "sem-edx")
        assert path.name == "sample_edx.png"
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        with Image.open(path) as image:
            image.load()
            assert image.format == "PNG"
            assert image.size == (1275, 750)
            assert any(low != high for low, high in image.getextrema())
    assert uploaded_png.read_bytes() == b"existing uploaded file"
    assert source.read_bytes() == original_text


def test_same_named_spectra_in_different_folders_keep_separate_plots(spectrum):
    """Inputs: staged spectra. Output: proof that duplicate names retain distinct data."""
    root, first = spectrum
    second = root / "_staged" / "second" / first.name
    second.parent.mkdir()
    second.write_text(
        "#SPECTRUM : counts\n1.0, 8\n2.0, 1\n3.0, 9\n#ENDOFDATA\n",
        encoding="utf-8",
    )
    first_plot = core_functions._create_job_edx_plot(root, first)
    second_plot = core_functions._create_job_edx_plot(root, second)
    assert first_plot != second_plot
    assert first_plot.name == second_plot.name
    assert first_plot.read_bytes() != second_plot.read_bytes()


@pytest.mark.parametrize("stem", ["x" * 251, "\u03b1" * 125])
def test_valid_long_spectrum_name_produces_valid_output_name(spectrum, stem):
    """Inputs: spectrum and long stem. Output: valid bounded filename and PNG."""
    root, source = spectrum
    long_source = source.with_name(f"{stem}.txt")
    long_source.write_bytes(source.read_bytes())
    plot = core_functions._create_job_edx_plot(root, long_source)
    assert plot.name.endswith("_edx.png")
    assert len(os.fsencode(plot.name)) <= core_functions.MAX_UPLOAD_PATH_COMPONENT_BYTES
    assert stem.startswith(plot.name.removesuffix("_edx.png"))
    assert long_source.read_bytes() == source.read_bytes()
    with Image.open(plot) as image:
        image.verify()


def test_plot_renderer_writes_only_the_supplied_stream(spectrum):
    """Inputs: spectrum and memory stream. Output: PNG without pathname side effects."""
    root, source = spectrum
    unused_path = root / "must-not-be-created" / "figure.png"
    with io.BytesIO() as stream:
        assert (
            sem_edx_parser.create_edx_spectrum_plot(
                source, unused_path, output_stream=stream
            )
            == unused_path
        )
        assert not stream.closed
        stream.seek(0)
        with Image.open(stream) as image:
            image.verify()
    assert not unused_path.parent.exists()


def test_no_spectrum_removes_empty_generated_output(spectrum):
    """Inputs: metadata-only spectrum. Output: no empty generated import artifact."""
    root, source = spectrum
    source.write_text("#TITLE: metadata only\n", encoding="utf-8")
    assert core_functions._create_job_edx_plot(root, source) is None
    assert list((root / "_derived").rglob("*.png")) == []
    assert source.read_text(encoding="utf-8") == "#TITLE: metadata only\n"


@pytest.mark.parametrize(
    "component", ["_derived", "_derived/sem-edx", "_derived/sem-edx/fixed"]
)
def test_generated_output_rejects_symlink_ancestors(spectrum, monkeypatch, component):
    """Inputs: staged spectrum and ancestor symlink. Output: rejection without writes."""
    root, source = spectrum
    outside = root.parent / "outside"
    outside.mkdir()
    sentinel = outside / "sample_edx.png"
    sentinel.write_bytes(b"untouched")
    link = root / component
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        core_functions.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed")
    )
    with pytest.raises(ValueError):
        core_functions._create_job_edx_plot(root, source)
    assert sentinel.read_bytes() == b"untouched"
    assert sorted(path.name for path in outside.iterdir()) == ["sample_edx.png"]


@pytest.mark.parametrize("symlink", [False, True])
def test_exclusive_output_never_replaces_existing_file(spectrum, monkeypatch, symlink):
    """Inputs: colliding regular file or symlink. Output: unchanged original bytes."""
    root, source = spectrum
    output = root / "_derived" / "sem-edx" / "fixed" / "sample_edx.png"
    output.parent.mkdir(parents=True)
    if symlink:
        original = root.parent / "original.png"
        original.write_bytes(b"original bytes")
        output.symlink_to(original)
    else:
        original = output
        original.write_bytes(b"original bytes")
    monkeypatch.setattr(
        core_functions.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed")
    )
    with pytest.raises(ValueError if symlink else FileExistsError):
        core_functions._create_job_edx_plot(root, source)
    assert output.is_symlink() is symlink
    assert original.read_bytes() == b"original bytes"


@pytest.mark.parametrize("failure", ["render", "stream", "fsync"])
def test_failed_output_is_removed_and_all_descriptors_close(
    spectrum, monkeypatch, failure
):
    """Inputs: spectrum and failing I/O stage. Output: error, cleanup and closed handles."""
    root, source = spectrum
    original = source.read_bytes()
    failure_error = OSError(errno.ENOSPC, "injected output failure")

    def fail_render(_source, _output, *, output_stream):
        """Inputs: render stream. Output: partial bytes followed by the injected error."""
        output_stream.write(b"partial PNG")
        raise failure_error

    def fail_io(*_args, **_kwargs):
        """Inputs: I/O arguments. Output: the selected filesystem exception."""
        raise failure_error

    if failure == "render":
        monkeypatch.setattr(sem_edx_parser, "create_edx_spectrum_plot", fail_render)
    elif failure == "stream":
        monkeypatch.setattr(core_functions.os, "fdopen", fail_io)
    else:
        monkeypatch.setattr(core_functions.os, "fsync", fail_io)
    descriptors_before = set(Path("/proc/self/fd").iterdir())
    with pytest.raises(OSError) as caught:
        core_functions._create_job_edx_plot(root, source)
    assert caught.value is failure_error
    assert set(Path("/proc/self/fd").iterdir()) == descriptors_before
    assert list((root / "_derived").rglob("*.png")) == []
    assert source.read_bytes() == original


def test_cleanup_failure_preserves_primary_render_error(spectrum, monkeypatch, caplog):
    """Inputs: failed render and cleanup. Output: retained primary error and warning."""
    root, source = spectrum
    failure = OSError(errno.ENOSPC, "original rendering error")

    def fail_render(_source, _output, *, output_stream):
        """Inputs: render stream. Output: owned partial output and rendering failure."""
        output_stream.write(b"incomplete")
        raise failure

    def fail_unlink(*_args, **_kwargs):
        """Inputs: unlink arguments. Output: an injected permission failure."""
        raise PermissionError(errno.EACCES, "cannot unlink output")

    monkeypatch.setattr(sem_edx_parser, "create_edx_spectrum_plot", fail_render)
    monkeypatch.setattr(core_functions.os, "unlink", fail_unlink)
    with pytest.raises(OSError) as caught:
        core_functions._create_job_edx_plot(root, source)
    assert caught.value is failure
    assert "Could not remove incomplete SEM-EDX plot" in caplog.text
    assert [path.read_bytes() for path in (root / "_derived").rglob("*.png")] == [
        b"incomplete"
    ]


@pytest.mark.parametrize("failure", ["layout", "save"])
def test_plot_renderer_releases_figure_on_render_or_write_failure(
    spectrum, monkeypatch, failure
):
    """Inputs: failing render stage. Output: proof that the real figure is released."""
    _root, source = spectrum
    figures = []
    closed = []
    actual_subplots = sem_edx_parser.plt.subplots
    actual_close = sem_edx_parser.plt.close

    def fail(*_args, **_kwargs):
        """Inputs: rendering arguments. Output: an identifiable rendering error."""
        raise RuntimeError("injected rendering failure")

    def subplots(*args, **kwargs):
        """Inputs: plot arguments. Output: recorded real figure and axes."""
        fig, ax = actual_subplots(*args, **kwargs)
        figures.append(fig)
        if failure == "save":
            monkeypatch.setattr(fig, "savefig", fail)
        return fig, ax

    def close(fig):
        """Inputs: actual figure. Output: recorded cleanup with axes released."""
        closed.append(fig)
        actual_close(fig)

    monkeypatch.setattr(sem_edx_parser.plt, "subplots", subplots)
    monkeypatch.setattr(sem_edx_parser.plt, "close", close)
    if failure == "layout":
        monkeypatch.setattr(sem_edx_parser, "genetic_label_placement", fail)
    with (
        io.BytesIO() as stream,
        pytest.raises(RuntimeError, match="injected rendering failure"),
    ):
        sem_edx_parser.create_edx_spectrum_plot(source, output_stream=stream)
    assert len(figures) == 1
    assert closed == figures
    assert figures[0].axes == []
