from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from omeroweb_import.services.omero import sem_edx_parser


class _FakeId:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _FakeColumn:
    def __init__(self, name, description, values):
        self.name = name
        self.description = description
        self.values = list(values)


class _FakeOriginalFileRef:
    def __init__(self, file_id, _loaded=False):
        self.file_id = file_id


class _FakeOriginalFile:
    def __init__(self, file_id):
        self._id = _FakeId(file_id)

    def getId(self):
        return self._id


class _FakeFileAnnotationI:
    def __init__(self):
        self.file = None
        self.namespace = None
        self.description = None
        self._id = None

    def setFile(self, value):
        self.file = value

    def setNs(self, value):
        self.namespace = value

    def setDescription(self, value):
        self.description = value

    def getId(self):
        return _FakeId(self._id)


class _FakeDatasetAnnotationLinkI:
    def __init__(self):
        self.parent = None
        self.child = None

    def setParent(self, parent):
        self.parent = parent

    def setChild(self, child):
        self.child = child


class _FakeTable:
    def __init__(self, *, fail_add=False):
        self.fail_add = fail_add
        self.initialized = None
        self.added = None
        self.closed = False

    def initialize(self, columns):
        self.initialized = columns

    def addData(self, columns):
        if self.fail_add:
            raise RuntimeError("cannot populate table")
        self.added = columns

    def getOriginalFile(self):
        return _FakeOriginalFile(123)

    def close(self):
        self.closed = True


class _FakeResources:
    def __init__(self, *, table):
        self._table = table

    def repositories(self):
        return SimpleNamespace(
            descriptions=[SimpleNamespace(getId=lambda: _FakeId(17))]
        )

    def newTable(self, _repository_id, _table_name):
        return self._table


class _FakeUpdateService:
    def __init__(self):
        self.saved_annotations = []
        self.saved_links = []

    def saveAndReturnObject(self, obj):
        if isinstance(obj, _FakeFileAnnotationI):
            obj._id = 999
            self.saved_annotations.append(obj)
            return obj
        return obj

    def saveObject(self, obj):
        self.saved_links.append(obj)


class _FakeDatasetParent:
    def __init__(self):
        self._obj = object()


class _FakeImage:
    def __init__(self, parents):
        self._parents = list(parents)

    def listParents(self):
        return list(self._parents)


def _build_label_specs(ax):
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
        getObject=lambda model, image_id: _FakeImage([_FakeDatasetParent()]) if (model, image_id) == ("Image", 7) else None,
        getUpdateService=lambda: update_service,
        c=SimpleNamespace(sf=SimpleNamespace(sharedResources=lambda: resources)),
    )
    return conn, update_service


def test_parse_emsa_file_extracts_title_metadata_elements_and_spectrum(tmp_path: Path):
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


def test_parse_emsa_file_returns_empty_payload_when_file_cannot_be_read(tmp_path: Path):
    parsed = sem_edx_parser.parse_emsa_file(tmp_path / "missing.txt")

    assert parsed == {"title": "", "metadata": {}, "elements": [], "spectrum": []}


def test_geometry_and_container_helpers_cover_overlap_crossing_and_copy():
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


def test_genetic_label_placer_covers_generation_mutation_selection_and_evolution(monkeypatch):
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
    separated_score = placer.calculate_fitness(initial)
    overlapping_score = placer.calculate_fitness(overlapping)
    assert overlapping_score > separated_score

    with monkeypatch.context() as mutation_patch:
        offsets = iter([1000.0, 1000.0, -1000.0, -1000.0])
        mutation_patch.setattr(sem_edx_parser.random, "random", lambda: 0.0)
        mutation_patch.setattr(sem_edx_parser.random, "uniform", lambda _a, _b: next(offsets))
        mutated = placer.mutate(initial)
    for gene, spec in zip(mutated.genes, label_specs):
        assert axes_bbox.x0 + 10 + spec["width"] / 2 <= gene.x <= axes_bbox.x1 - 10 - spec["width"] / 2
        assert spec["y_peak"] + 25 + spec["height"] / 2 <= gene.y <= axes_bbox.y1 - 10 - spec["height"] / 2

    initial.fitness = 5.0
    random_chromosome.fitness = 10.0
    overlapping.fitness = 15.0
    selected = placer.tournament_selection([initial, random_chromosome, overlapping], tournament_size=2)
    assert selected.fitness in {5.0, 10.0}

    sem_edx_parser.random.seed(1)
    evolved = placer.evolve()
    assert len(evolved.genes) == 2
    assert math.isfinite(evolved.fitness)

    sem_edx_parser.plt.close(fig)


def test_genetic_label_placement_merges_nearby_peaks_but_preserves_distinct_height_clusters(monkeypatch):
    fig, ax = sem_edx_parser.plt.subplots(figsize=(4, 3), dpi=100)
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 120)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox_raw = ax.get_window_extent(renderer=renderer)
    axes_bbox = sem_edx_parser.BBox(
        axes_bbox_raw.x0,
        axes_bbox_raw.y0,
        axes_bbox_raw.x1,
        axes_bbox_raw.y1,
    )

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
        [
            (1.00, 80.0, "Cu"),
            (1.20, 75.0, "Cu"),
            (1.35, 20.0, "Cu"),
        ],
        axes_bbox,
        fig,
        ax,
        renderer,
    )

    assert len(positions) == 2
    assert positions[0][2] == "Cu"
    assert positions[0][5] == [1.0, 1.2]
    assert positions[0][3:5] == (110.0, 190.0)
    assert positions[1][5] == [1.35]
    assert positions[1][3:5] == (210.0, 220.0)

    sem_edx_parser.plt.close(fig)


def test_create_edx_spectrum_plot_writes_png_with_label_positions(monkeypatch, tmp_path: Path):
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

    result = sem_edx_parser.create_edx_spectrum_plot(txt_path, output_path)

    assert result == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_create_edx_spectrum_plot_returns_none_without_spectrum(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [], "elements": []},
    )

    assert sem_edx_parser.create_edx_spectrum_plot(tmp_path / "missing.txt") is None


def test_build_spectrum_columns_create_tables_and_attach_sem_edx_data(monkeypatch, tmp_path: Path):
    table = _FakeTable()
    conn, update_service = _install_fake_omero_table_modules(monkeypatch, table=table)

    columns = sem_edx_parser.build_spectrum_columns(7, [(1.0, 10.0), (2.0, 20.0)])
    assert [column.name for column in columns] == ["Image", "Energy_keV", "Counts"]
    assert columns[0].values == [7, 7]
    assert columns[1].values == [1.0, 2.0]
    assert columns[2].values == [10.0, 20.0]

    table_id = sem_edx_parser.create_spectrum_table(
        conn,
        image_id=7,
        spectrum=[(1.0, 10.0), (2.0, 20.0)],
        txt_filename="sample.txt",
        columns=columns,
    )
    assert table_id == 999
    assert table.initialized is not None
    assert table.added == columns
    assert table.closed is True
    assert update_service.saved_links[0].parent is not None
    assert update_service.saved_links[0].child is not None

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [(3.0, 30.0)], "elements": [], "metadata": {}, "title": ""},
    )
    monkeypatch.setattr(
        sem_edx_parser,
        "create_spectrum_table",
        lambda *_args, **_kwargs: 321,
    )
    attached = sem_edx_parser.attach_sem_edx_tables(conn, 7, tmp_path / "sample.txt")
    assert attached == 321


def test_create_spectrum_table_and_attach_helpers_cover_failure_paths(monkeypatch, tmp_path: Path):
    table = _FakeTable(fail_add=True)
    conn, _update_service = _install_fake_omero_table_modules(monkeypatch, table=table)

    assert sem_edx_parser.create_spectrum_table(conn, 7, [], "sample.txt") is None
    assert (
        sem_edx_parser.create_spectrum_table(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: None,
                getUpdateService=lambda: SimpleNamespace(),
                c=SimpleNamespace(sf=SimpleNamespace(sharedResources=lambda: _FakeResources(table=table))),
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
                getUpdateService=lambda: SimpleNamespace(),
                c=SimpleNamespace(sf=SimpleNamespace(sharedResources=lambda: _FakeResources(table=table))),
            ),
            7,
            [(1.0, 10.0)],
            "sample.txt",
        )
        is None
    )

    failing_resources = _FakeResources(table=None)
    failing_conn = SimpleNamespace(
        getObject=lambda model, image_id: _FakeImage([_FakeDatasetParent()]) if (model, image_id) == ("Image", 7) else None,
        getUpdateService=lambda: SimpleNamespace(),
        c=SimpleNamespace(sf=SimpleNamespace(sharedResources=lambda: failing_resources)),
    )
    assert sem_edx_parser.create_spectrum_table(failing_conn, 7, [(1.0, 10.0)], "sample.txt") is None
    assert sem_edx_parser.create_spectrum_table(conn, 7, [(1.0, 10.0)], "sample.txt") is None

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [(3.0, 30.0)], "elements": [], "metadata": {}, "title": ""},
    )
    assert sem_edx_parser.attach_sem_edx_tables(conn, 7, tmp_path / "sample.txt", persist_table=False) is None

    monkeypatch.setattr(
        sem_edx_parser,
        "parse_emsa_file",
        lambda _path: {"spectrum": [], "elements": [], "metadata": {}, "title": ""},
    )
    assert sem_edx_parser.attach_sem_edx_tables(conn, 7, tmp_path / "sample.txt") is None
