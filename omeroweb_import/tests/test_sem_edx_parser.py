from __future__ import annotations

from iter_test_helpers import next_or_fail

import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from omeroweb_import.services.omero import sem_edx_parser


class _FakeId:
    """Test double for fake identifier."""

    def __init__(self, value):
        """Create `_FakeId` with `value`.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getValue(self):
        """Return `_FakeId`'s fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value


class _FakeColumn:
    """Test double for fake column."""

    def __init__(self, name, description, values):
        """Create `_FakeColumn` with `name`, `description`, and `values`.

        Inputs: `name`, `description`, `values`. Output: None.
        """
        self.name = name
        self.description = description
        self.values = list(values)


class _FakeOriginalFileRef:
    """Test double for fake original file ref."""

    def __init__(self, file_id, _loaded=False):
        """Create `_FakeOriginalFileRef` with `file_id` and `_loaded`.

        Inputs: `file_id`, `_loaded`. Output: None.
        """
        self.file_id = file_id


class _FakeOriginalFile:
    """Test double for fake original file."""

    def __init__(self, file_id):
        """Create `_FakeOriginalFile` with `file_id`.

        Inputs: `file_id`. Output: None.
        """
        self._id = _FakeId(file_id)

    def getId(self):
        """Return `_FakeOriginalFile`'s fake OMERO identifier.

        Inputs: none. Output: `self._id`.
        """
        return self._id


class _FakeFileAnnotationI:
    """Test double for fake file annotation i."""

    def __init__(self):
        """Create `_FakeFileAnnotationI` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.file = None
        self.namespace = None
        self.description = None
        self._id = None

    def setFile(self, value):
        """Set the file for `_FakeFileAnnotationI`.

        Inputs: `value` input value. Output: None.
        """
        self.file = value

    def setNs(self, value):
        """Set the ns for `_FakeFileAnnotationI`.

        Inputs: `value` input value. Output: None.
        """
        self.namespace = value

    def setDescription(self, value):
        """Set the description for `_FakeFileAnnotationI`.

        Inputs: `value` input value. Output: None.
        """
        self.description = value

    def getId(self):
        """Return `_FakeFileAnnotationI`'s fake OMERO identifier.

        Inputs: none. Output: `_FakeId` result.
        """
        return _FakeId(self._id)


class _FakeDatasetAnnotationLinkI:
    """Test double for fake dataset annotation link i."""

    def __init__(self):
        """Create `_FakeDatasetAnnotationLinkI` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.parent = None
        self.child = None

    def setParent(self, parent):
        """Set the parent for `_FakeDatasetAnnotationLinkI`.

        Inputs: `parent`. Output: None.
        """
        self.parent = parent

    def setChild(self, child):
        """Set the child for `_FakeDatasetAnnotationLinkI`.

        Inputs: `child`. Output: None.
        """
        self.child = child


class _FakeTable:
    """Test double for fake table."""

    def __init__(self, *, fail_add=False):
        """Create `_FakeTable` with its default state.

        Inputs: `fail_add`. Output: None.
        """
        self.fail_add = fail_add
        self.initialized = None
        self.added = None
        self.closed = False

    def initialize(self, columns):
        """Initialize the initialize for `_FakeTable`.

        Inputs: `columns`. Output: None.
        """
        self.initialized = columns

    def addData(self, columns):
        """Add the data for `_FakeTable`.

        Inputs: `columns`. Output: None. Raises: RuntimeError when validation or
        external operations fail.
        """
        if self.fail_add:
            raise RuntimeError("cannot populate table")
        self.added = columns

    @staticmethod
    def getOriginalFile():
        """Return `_FakeTable`'s fake original file.

        Inputs: none. Output: `_FakeOriginalFile` result.
        """
        return _FakeOriginalFile(123)

    def close(self):
        """Close `_FakeTable`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


class _FakeResources:
    """Test double for fake resources."""

    def __init__(self, *, table):
        """Create `_FakeResources` with its default state.

        Inputs: `table`. Output: None.
        """
        self._table = table

    @staticmethod
    def repositories():
        """Return the repositories for `_FakeResources`.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(
            descriptions=[SimpleNamespace(getId=lambda: _FakeId(17))]
        )

    def newTable(self, _repository_id, _table_name):
        """Return the new Table for `_FakeResources`.

        Inputs: `_repository_id`, `_table_name`. Output: `_table`.
        """
        return self._table


class _FakeUpdateService:
    """Test double for fake update service."""

    def __init__(self):
        """Create `_FakeUpdateService` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.saved_annotations = []
        self.saved_links = []

    def saveAndReturnObject(self, obj):
        """Return the fake saved OMERO object from SEM-EDX tests.

        Inputs: `obj`. Output: `obj`.
        """
        if isinstance(obj, _FakeFileAnnotationI):
            obj._id = 999
            self.saved_annotations.append(obj)
            return obj
        return obj

    def saveObject(self, obj):
        """Save the object for `_FakeUpdateService`.

        Inputs: `obj`. Output: None.
        """
        self.saved_links.append(obj)


class _FakeDatasetParent:
    """Test double for fake dataset parent."""

    def __init__(self):
        """Create `_FakeDatasetParent` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self._obj = object()


class _FakeImage:
    """Test double for fake image."""

    def __init__(self, parents):
        """Create `_FakeImage` with `parents`.

        Inputs: `parents`. Output: None.
        """
        self._parents = list(parents)

    def listParents(self):
        """Return `_FakeImage`'s fake parent listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._parents)


def _build_label_specs(ax):
    """Build the label specs.

    Inputs: `ax`. Output: `list`.
    """
    first_x, first_y = ax.transData.transform((1.0, 42.0))
    second_x, second_y = ax.transData.transform((2.5, 58.0))
    return [
        {
            "id": 0,
            "peak_energies": [1.0],
            "spectrum_y": 42.0,
            "x_peak": first_x,
            "y_peak": first_y,
            "width": 40.0,
            "height": 18.0,
        },
        {
            "id": 1,
            "peak_energies": [2.5],
            "spectrum_y": 58.0,
            "x_peak": second_x,
            "y_peak": second_y,
            "width": 42.0,
            "height": 18.0,
        },
    ]


def _install_fake_omero_table_modules(monkeypatch, *, table):
    """Install the fake OMERO table modules.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `table`. Output: `tuple`.
    """
    omero_pkg = types.ModuleType("omero")
    omero_pkg.__path__ = []
    grid_module = types.ModuleType("omero.grid")
    grid_module.DoubleColumn = _FakeColumn
    grid_module.LongColumn = _FakeColumn
    model_module = types.ModuleType("omero.model")
    model_module.OriginalFileI = _FakeOriginalFileRef
    model_module.FileAnnotationI = _FakeFileAnnotationI
    model_module.DatasetAnnotationLinkI = _FakeDatasetAnnotationLinkI
    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rstring = lambda value: value

    monkeypatch.setitem(sys.modules, "omero", omero_pkg)
    monkeypatch.setitem(sys.modules, "omero.grid", grid_module)
    monkeypatch.setitem(sys.modules, "omero.model", model_module)
    monkeypatch.setitem(sys.modules, "omero.rtypes", rtypes_module)

    update_service = _FakeUpdateService()
    resources = _FakeResources(table=table)
    conn = SimpleNamespace(
        getObject=lambda model, image_id: (
            _FakeImage([_FakeDatasetParent()])
            if (model, image_id) == ("Image", 7)
            else None
        ),
        getUpdateService=lambda: update_service,
        c=SimpleNamespace(sf=SimpleNamespace(sharedResources=lambda: resources)),
    )
    return conn, update_service


def test_parse_emsa_file_extracts_metadata_elements_and_spectrum(tmp_path: Path):
    """Verify parse emsa file extracts metadata elements and spectrum.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in parse emsa file extracts metadata elements and spectrum.
    """
    txt_path = tmp_path / "spectrum.txt"
    txt_path.write_text(
        "\n".join(
            [
                "#TITLE : Sample spectrum",
                "#DATE : 2026-03-25",
                "#DATE : 2026-03-26",
                "##OXINSTLABEL: 29, 8.048, Cu",
                "##OXINSTLABEL: invalid,label",
                "#SPECTRUM : counts",
                "0.01000, 1057.0 0.02000 900.0",
                "0.03000 not-a-number",
                "#ENDOFDATA : done",
            ]
        ),
        encoding="utf-8",
    )

    parsed = sem_edx_parser.parse_emsa_file(txt_path)

    assert parsed["title"] == "Sample spectrum"
    assert parsed["metadata"]["TITLE"] == "Sample spectrum"
    assert parsed["metadata"]["DATE"] == "2026-03-25"
    assert parsed["metadata"]["DATE_1"] == "2026-03-26"
    assert parsed["metadata"]["SPECTRUM"] == "counts"
    assert parsed["elements"] == [
        {"atomic_number": 29, "energy_kev": 8.048, "symbol": "Cu"}
    ]
    assert parsed["spectrum"] == [(0.01, 1057.0), (0.02, 900.0)]
    assert sem_edx_parser.parse_emsa_file(tmp_path / "missing.txt") == {
        "title": "",
        "metadata": {},
        "elements": [],
        "spectrum": [],
    }


def test_parse_emsa_file_enforces_configured_resource_limits(
    monkeypatch, tmp_path: Path
):
    """Verify SEM EDX parsing enforces file, element, and spectrum limits.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions
    in SEM EDX parser resource limits.
    """
    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_FILE_BYTES_ENV, "10")
    oversized = tmp_path / "oversized.txt"
    oversized.write_text("x" * 11, encoding="utf-8")
    assert sem_edx_parser.parse_emsa_file(oversized) == {
        "title": "",
        "metadata": {},
        "elements": [],
        "spectrum": [],
    }

    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_FILE_BYTES_ENV, "10000")
    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_ELEMENTS_ENV, "1")
    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_SPECTRUM_POINTS_ENV, "2")
    capped = tmp_path / "capped.txt"
    capped.write_text(
        "\n".join(
            [
                "#TITLE : capped",
                "##OXINSTLABEL: 29, 8.048, Cu",
                "##OXINSTLABEL: 30, 8.638, Zn",
                "#SPECTRUM : counts",
                "1, 10 2, 20 3, 30",
            ]
        ),
        encoding="utf-8",
    )
    parsed = sem_edx_parser.parse_emsa_file(capped)
    assert parsed["elements"] == [
        {"atomic_number": 29, "energy_kev": 8.048, "symbol": "Cu"}
    ]
    assert parsed["spectrum"] == [(1.0, 10.0), (2.0, 20.0)]


def test_sem_edx_geometry_and_genetic_label_helpers_cover_selection_mutation_and_layout(
    monkeypatch,
):
    """Verify SEM EDX geometry and genetic label helpers cover selection mutation and layout.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in SEM EDX geometry and genetic label helpers cover selection mutation and layout.
    """
    assert sem_edx_parser._nearest_spectrum_point([], 1.0) is None
    spectrum = [(0.5, 10.0), (1.0, 20.0), (2.0, 30.0)]
    assert sem_edx_parser._nearest_spectrum_point(spectrum, 0.1) == (0.5, 10.0)
    assert sem_edx_parser._nearest_spectrum_point(spectrum, 3.0) == (2.0, 30.0)
    assert sem_edx_parser._nearest_spectrum_point(spectrum, 1.4) == (1.0, 20.0)

    left = sem_edx_parser.BBox(0, 0, 10, 10)
    right = sem_edx_parser.BBox(5, 5, 15, 15)
    separate = sem_edx_parser.BBox(20, 20, 30, 30)
    assert left.overlaps(right) is True
    assert left.overlaps(separate) is False
    assert left.overlap_area(right) == 25
    assert left.overlap_area(separate) == 0.0
    assert sem_edx_parser.lines_cross(0, 0, 10, 10, 0, 10, 10, 0) is True
    assert sem_edx_parser.lines_cross(0, 0, 10, 0, 0, 5, 10, 5) is False

    gene = sem_edx_parser.LabelGene(3, 12.5, 18.0)
    chromosome = sem_edx_parser.Chromosome([gene])
    chromosome.fitness = 9.5
    clone = chromosome.copy()
    clone.genes[0].x = 20.0
    assert repr(gene) == "Gene(id=3, x=12.5, y=18.0)"
    assert repr(chromosome) == "Chromosome(genes=1, fitness=9.50)"
    assert chromosome.genes[0].x == 12.5
    assert clone.genes[0].x == 20.0

    fig, ax = sem_edx_parser.plt.subplots(figsize=(4, 3), dpi=100)
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 100)
    fig.canvas.draw()
    axes_bbox = sem_edx_parser.BBox(0, 0, 400, 300)
    label_specs = _build_label_specs(ax)
    placer = sem_edx_parser.GeneticLabelPlacer(
        label_specs=label_specs,
        axes_bbox=axes_bbox,
        ax=ax,
        population_size=4,
        generations=2,
        mutation_rate=1.0,
        elite_size=1,
    )

    initial = placer.generate_initial_chromosome()
    random_chromosome = placer.generate_random_chromosome()
    crossover_child, _ = placer.crossover(initial, random_chromosome)
    assert len(crossover_child.genes) == 2

    overlapping = sem_edx_parser.Chromosome(
        [
            sem_edx_parser.LabelGene(0, initial.genes[0].x, initial.genes[0].y),
            sem_edx_parser.LabelGene(1, initial.genes[0].x, initial.genes[0].y),
        ]
    )
    assert placer.calculate_fitness(overlapping) > placer.calculate_fitness(initial)

    with monkeypatch.context() as mutation_patch:
        offsets = iter([1000.0, 1000.0, -1000.0, -1000.0])
        mutation_patch.setattr(sem_edx_parser.random, "random", lambda: 0.0)
        mutation_patch.setattr(
            sem_edx_parser.random,
            "uniform",
            lambda _a, _b: next_or_fail(offsets),
        )
        mutated = placer.mutate(initial)
    for gene, spec in zip(mutated.genes, label_specs):
        assert (
            axes_bbox.x0 + 10 + spec["width"] / 2
            <= gene.x
            <= axes_bbox.x1 - 10 - spec["width"] / 2
        )
        assert (
            spec["y_peak"] + 25 + spec["height"] / 2
            <= gene.y
            <= axes_bbox.y1 - 10 - spec["height"] / 2
        )

    initial.fitness = 5.0
    random_chromosome.fitness = 10.0
    overlapping.fitness = 15.0
    assert placer.tournament_selection(
        [initial, random_chromosome, overlapping], tournament_size=2
    ).fitness in {5.0, 10.0}

    sem_edx_parser.random.seed(1)
    evolved = placer.evolve()
    assert len(evolved.genes) == 2
    assert math.isfinite(evolved.fitness)

    renderer = fig.canvas.get_renderer()
    axes_bbox_raw = ax.get_window_extent(renderer=renderer)
    monkeypatch.setattr(
        sem_edx_parser.GeneticLabelPlacer,
        "evolve",
        lambda self: sem_edx_parser.Chromosome(
            [
                sem_edx_parser.LabelGene(0, 110.0, 190.0),
                sem_edx_parser.LabelGene(1, 210.0, 220.0),
            ]
        ),
    )
    positions = sem_edx_parser.genetic_label_placement(
        [(1.00, 80.0, "Cu"), (1.20, 75.0, "Cu"), (1.35, 20.0, "Cu")],
        sem_edx_parser.BBox(
            axes_bbox_raw.x0,
            axes_bbox_raw.y0,
            axes_bbox_raw.x1,
            axes_bbox_raw.y1,
        ),
        fig,
        ax,
        renderer,
    )
    assert len(positions) == 2
    assert positions[0][5] == [1.0, 1.2]
    assert positions[1][5] == [1.35]
    sem_edx_parser.plt.close(fig)


def test_sem_edx_plot_and_table_helpers_cover_png_generation_table_persistence_and_failures(
    monkeypatch,
    tmp_path: Path,
):
    """Verify SEM EDX plot and table helpers cover png generation table persistence and failures.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in SEM EDX plot and table helpers cover png generation table persistence and failures.
    """
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text(
        "\n".join(
            [
                "#TITLE : Spectrum",
                "##OXINSTLABEL: 29, 8.048, Cu",
                "#SPECTRUM : counts",
                "7.900, 10",
                "8.048, 42",
                "8.200, 5",
                "#ENDOFDATA : done",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "sample_edx.png"
    monkeypatch.setattr(
        sem_edx_parser,
        "genetic_label_placement",
        lambda *args, **kwargs: [(8.048, 42.0, "Cu", 120.0, 140.0, [8.048])],
    )
    assert sem_edx_parser.create_edx_spectrum_plot(txt_path, output_path) == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [], "elements": []},
    )
    assert sem_edx_parser.create_edx_spectrum_plot(tmp_path / "missing.txt") is None

    table = _FakeTable()
    conn, update_service = _install_fake_omero_table_modules(monkeypatch, table=table)
    columns = sem_edx_parser.build_spectrum_columns(7, [(1.0, 10.0), (2.0, 20.0)])
    assert [column.name for column in columns] == ["Image", "Energy_keV", "Counts"]
    assert columns[0].values == [7, 7]
    assert columns[1].values == [1.0, 2.0]
    assert columns[2].values == [10.0, 20.0]
    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_SPECTRUM_POINTS_ENV, "1")
    limited_columns = sem_edx_parser.build_spectrum_columns(
        7, [(1.0, 10.0), (2.0, 20.0)]
    )
    assert limited_columns[0].values == [7]
    assert limited_columns[1].values == [1.0]
    assert limited_columns[2].values == [10.0]
    assert (
        sem_edx_parser.create_spectrum_table(
            conn,
            image_id=7,
            spectrum=[(1.0, 10.0), (2.0, 20.0)],
            txt_filename="sample.txt",
            columns=columns,
        )
        == 999
    )
    assert table.initialized is not None
    assert table.added == columns
    assert table.closed is True
    assert update_service.saved_links[0].parent is not None
    assert update_service.saved_links[0].child is not None
    real_create_spectrum_table = sem_edx_parser.create_spectrum_table

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {
            "spectrum": [(3.0, 30.0)],
            "elements": [],
            "metadata": {},
            "title": "",
        },
    )
    monkeypatch.setattr(
        sem_edx_parser,
        "create_spectrum_table",
        lambda *_args, **_kwargs: 321,
    )
    assert sem_edx_parser.attach_sem_edx_tables(conn, 7, tmp_path / "sample.txt") == 321
    monkeypatch.setattr(
        sem_edx_parser,
        "create_spectrum_table",
        real_create_spectrum_table,
    )

    failing_table = _FakeTable(fail_add=True)
    failing_conn, _ = _install_fake_omero_table_modules(
        monkeypatch,
        table=failing_table,
    )
    assert (
        sem_edx_parser.create_spectrum_table(failing_conn, 7, [], "sample.txt") is None
    )
    assert (
        sem_edx_parser.create_spectrum_table(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: None,
                getUpdateService=SimpleNamespace,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        sharedResources=lambda: _FakeResources(table=failing_table)
                    )
                ),
            ),
            7,
            [(1.0, 10.0)],
            "sample.txt",
        )
        is None
    )
    assert (
        sem_edx_parser.create_spectrum_table(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: _FakeImage([]),
                getUpdateService=SimpleNamespace,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        sharedResources=lambda: _FakeResources(table=failing_table)
                    )
                ),
            ),
            7,
            [(1.0, 10.0)],
            "sample.txt",
        )
        is None
    )
    resource_calls = []

    def _track_shared_resources():
        """Return the track shared resources.

        Inputs: none. Output: `_FakeResources` result.
        """
        resource_calls.append(True)
        return _FakeResources(table=failing_table)

    assert (
        sem_edx_parser.create_spectrum_table(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: _FakeImage([SimpleNamespace()]),
                getUpdateService=SimpleNamespace,
                c=SimpleNamespace(
                    sf=SimpleNamespace(sharedResources=_track_shared_resources)
                ),
            ),
            7,
            [(1.0, 10.0)],
            "sample.txt",
        )
        is None
    )
    assert resource_calls == []
    assert (
        sem_edx_parser.create_spectrum_table(
            SimpleNamespace(
                getObject=lambda model, image_id: (
                    _FakeImage([_FakeDatasetParent()])
                    if (model, image_id) == ("Image", 7)
                    else None
                ),
                getUpdateService=SimpleNamespace,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        sharedResources=lambda: _FakeResources(table=None)
                    )
                ),
            ),
            7,
            [(1.0, 10.0)],
            "sample.txt",
        )
        is None
    )
    assert (
        sem_edx_parser.create_spectrum_table(
            failing_conn, 7, [(1.0, 10.0)], "sample.txt"
        )
        is None
    )

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {
            "spectrum": [(3.0, 30.0)],
            "elements": [],
            "metadata": {},
            "title": "",
        },
    )
    assert (
        sem_edx_parser.attach_sem_edx_tables(
            failing_conn, 7, tmp_path / "sample.txt", persist_table=False
        )
        is None
    )
    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [], "elements": [], "metadata": {}, "title": ""},
    )
    assert (
        sem_edx_parser.attach_sem_edx_tables(failing_conn, 7, tmp_path / "sample.txt")
        is None
    )


def test_sem_edx_parser_remaining_edges_cover_empty_layouts_and_default_plot_path(
    monkeypatch,
    tmp_path: Path,
):
    """Check SEM EDX parser remaining edges cover empty layouts and default plot path parsing against the documented contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when SEM EDX parser remaining edges cover empty layouts and default plot path accepts unsafe input.
    """
    sem_edx_parser.plt.close(None)
    assert (
        sem_edx_parser.genetic_label_placement(
            [],
            sem_edx_parser.BBox(0, 0, 10, 10),
            None,
            None,
            None,
        )
        == []
    )

    txt_path = tmp_path / "spectrum.txt"
    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {
            "spectrum": [(0.5, 10.0), (1.0, 20.0)],
            "elements": [
                {"energy_kev": "bad", "symbol": "Cu"},
                {"energy_kev": 0.2, "symbol": ""},
                {"energy_kev": 9.0, "symbol": "Zn"},
                {"energy_kev": 1.0, "symbol": "Cu"},
            ],
        },
    )
    monkeypatch.setattr(
        sem_edx_parser,
        "genetic_label_placement",
        lambda *args, **kwargs: [],
    )

    output_path = sem_edx_parser.create_edx_spectrum_plot(txt_path)
    assert output_path == tmp_path / "spectrum_edx.png"
    assert output_path.exists()


def test_create_edx_spectrum_plot_caps_labels_before_layout(monkeypatch, tmp_path):
    """Verify SEM EDX plot creation caps labels before expensive layout.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions
    in SEM EDX label placement bounds.
    """
    captured = {}
    txt_path = tmp_path / "labels.txt"
    txt_path.write_text("synthetic", encoding="utf-8")

    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_PLOT_LABELS_ENV, "2")
    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {
            "title": "",
            "metadata": {},
            "spectrum": [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)],
            "elements": [
                {"energy_kev": 1.0, "symbol": "A"},
                {"energy_kev": 2.0, "symbol": "B"},
                {"energy_kev": 3.0, "symbol": "C"},
            ],
        },
    )

    def fake_label_placement(labels_data, *_args):
        """Capture labels passed to the expensive layout step.

        Inputs: `labels_data`, `*_args`. Output: empty placements.
        """
        captured["labels_data"] = list(labels_data)
        return []

    monkeypatch.setattr(
        sem_edx_parser,
        "genetic_label_placement",
        fake_label_placement,
    )

    output_path = tmp_path / "labels.png"
    assert sem_edx_parser.create_edx_spectrum_plot(txt_path, output_path) == output_path
    assert captured["labels_data"] == [(1.0, 10.0, "A"), (2.0, 20.0, "B")]


def test_sem_edx_table_creation_covers_cleanup_and_attach_failure_logging(
    monkeypatch,
    tmp_path: Path,
):
    """Check SEM EDX table creation covers cleanup and attach failure logging cleanup behavior.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: None after assertions pass. Raises: RuntimeError when validation or
    external operations fail.
    """

    class _ClosingFailTable(_FakeTable):
        """Test double for closing fail table behavior in this module."""

        def close(self):
            """Close `_ClosingFailTable`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    failing_table = _ClosingFailTable(fail_add=True)
    failing_conn, _ = _install_fake_omero_table_modules(
        monkeypatch,
        table=failing_table,
    )
    assert (
        sem_edx_parser.create_spectrum_table(
            failing_conn,
            image_id=7,
            spectrum=[(1.0, 10.0)],
            txt_filename="sample.txt",
        )
        is None
    )

    broken_conn = SimpleNamespace(
        getObject=lambda *_args, **_kwargs: _FakeImage([_FakeDatasetParent()]),
        getUpdateService=SimpleNamespace,
        c=SimpleNamespace(
            sf=SimpleNamespace(
                sharedResources=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        ),
    )
    assert (
        sem_edx_parser.create_spectrum_table(
            broken_conn,
            image_id=7,
            spectrum=[(1.0, 10.0)],
            txt_filename="sample.txt",
        )
        is None
    )

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {
            "spectrum": [(1.0, 10.0)],
            "elements": [],
            "metadata": {},
            "title": "",
        },
    )
    monkeypatch.setattr(
        sem_edx_parser, "create_spectrum_table", lambda *args, **kwargs: None
    )
    assert (
        sem_edx_parser.attach_sem_edx_tables(failing_conn, 7, tmp_path / "sample.txt")
        is None
    )


def test_sem_edx_parser_covers_remaining_parse_and_fitness_edges(tmp_path: Path):
    """Check SEM EDX parser covers remaining parse and fitness edges parsing against the documented contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in SEM EDX parser covers remaining parse and fitness edges.
    """
    txt_path = tmp_path / "demo.txt"
    txt_path.write_text(
        "\n#TITLE: demo\n##OXINSTLABEL: bad, 8.0, Cu\n#SPECTRUM : yes\n"
        "#ignored inside spectrum\n0.10 bad\nENDOFDATA\n",
        encoding="utf-8",
    )
    parsed = sem_edx_parser.parse_emsa_file(txt_path)
    assert parsed["title"] == "demo"
    assert parsed["spectrum"] == []
    assert parsed["elements"] == []

    placer = sem_edx_parser.GeneticLabelPlacer(
        [
            {
                "id": 0,
                "peak_energies": [1.0],
                "spectrum_y": 0.0,
                "width": 40.0,
                "height": 20.0,
                "x_peak": 10.0,
                "y_peak": 10.0,
            },
            {
                "id": 1,
                "peak_energies": [9.0],
                "spectrum_y": 0.0,
                "width": 40.0,
                "height": 20.0,
                "x_peak": 90.0,
                "y_peak": 10.0,
            },
        ],
        sem_edx_parser.BBox(0.0, 0.0, 100.0, 100.0),
        SimpleNamespace(transData=SimpleNamespace(transform=lambda point: point)),
        population_size=2,
        generations=1,
        mutation_rate=0.0,
        elite_size=1,
    )

    tight_placer = sem_edx_parser.GeneticLabelPlacer(
        [
            {
                "id": 0,
                "peak_energies": [1.0],
                "spectrum_y": 0.0,
                "width": 200.0,
                "height": 200.0,
                "x_peak": 10.0,
                "y_peak": 10.0,
            }
        ],
        sem_edx_parser.BBox(0.0, 0.0, 50.0, 50.0),
        SimpleNamespace(transData=SimpleNamespace(transform=lambda point: point)),
        population_size=1,
        generations=1,
        mutation_rate=0.0,
        elite_size=1,
    )
    gene = tight_placer.generate_random_chromosome().genes[0]
    assert (gene.x, gene.y) == (10.0, 140.0)

    fitness = placer.calculate_fitness(
        sem_edx_parser.Chromosome(
            [
                sem_edx_parser.LabelGene(0, 80.0, 0.0),
                sem_edx_parser.LabelGene(1, 20.0, 0.0),
            ]
        )
    )
    assert fitness > 0

    crossing_and_bounds_fitness = placer.calculate_fitness(
        sem_edx_parser.Chromosome(
            [
                sem_edx_parser.LabelGene(0, 320.0, 340.0),
                sem_edx_parser.LabelGene(1, -40.0, 340.0),
            ]
        )
    )
    assert crossing_and_bounds_fitness > fitness


def test_sem_edx_parser_covers_env_limits_and_read_failures(monkeypatch, tmp_path):
    """Verify SEM-EDX parser limit and file-read fallback branches.

    Inputs: pytest fixtures. Output: asserts safe parser defaults and caps.
    """
    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_LINES_ENV, "not-an-int")
    assert sem_edx_parser._sem_edx_max_lines() == (
        sem_edx_parser.DEFAULT_SEM_EDX_MAX_LINES
    )

    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_LINES_ENV, "1")
    limited = tmp_path / "limited.txt"
    limited.write_text("#TITLE: Demo\n#DATE: ignored\n", encoding="utf-8")
    parsed = sem_edx_parser.parse_emsa_file(limited)
    assert parsed["title"] == "Demo"
    assert "DATE" not in parsed["metadata"]

    class _UnreadablePath:
        """Path-like object whose read open fails."""

        def __init__(self, path):
            """Create `_UnreadablePath` with `path`.

            Inputs: `path` filesystem path. Output: initialized fake path.
            """
            self.path = path

        def __fspath__(self):
            """Return filesystem path text.

            Inputs: none. Output: path string.
            """
            return str(self.path)

        def exists(self):
            """Report existence.

            Inputs: none. Output: bool.
            """
            return True

        def stat(self):
            """Return small file stats.

            Inputs: none. Output: object with `st_size`.
            """
            return SimpleNamespace(st_size=1)

        def open(self, *args, **kwargs):
            """Raise a deterministic read failure.

            Inputs: file open args. Output: none. Raises: OSError.
            """
            raise OSError("denied")

    empty = sem_edx_parser.parse_emsa_file(_UnreadablePath(tmp_path / "blocked.txt"))
    assert empty == {"title": "", "metadata": {}, "elements": [], "spectrum": []}

    monkeypatch.setenv(sem_edx_parser.SEM_EDX_MAX_PLOT_LABELS_ENV, "0")
    assert (
        sem_edx_parser.genetic_label_placement(
            [(1.0, 1.0, "A")],
            sem_edx_parser.BBox(0.0, 0.0, 1.0, 1.0),
            object(),
            object(),
            object(),
        )
        == []
    )
