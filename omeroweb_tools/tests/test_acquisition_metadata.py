from __future__ import annotations

from datetime import datetime

from omeroweb_tools.services.acquisition_metadata import extract_search_document


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _UnitValue(_Value):
    def __init__(self, value, symbol):
        super().__init__(value)
        self._symbol = symbol

    def getSymbol(self):
        return self._symbol


class _Channel:
    def __init__(self, index, label, excitation, emission):
        self._index = index
        self._label = label
        self._excitation = excitation
        self._emission = emission

    def getIndex(self):
        return self._index

    def getLabel(self):
        return self._label

    def getExcitationWave(self):
        return self._excitation

    def getEmissionWave(self):
        return self._emission


class _NamedObject:
    def __init__(self, object_id, name, parents=None):
        self._id = object_id
        self._name = name
        self._parents = list(parents or [])

    def getId(self):
        return _Value(self._id)

    def getName(self):
        return self._name

    def listParents(self):
        return list(self._parents)


class _ObjectiveSettings:
    def getCorrectionCollar(self):
        return _Value("0.17")

    def getID(self):
        return _Value(31)


class _DetectorSettings:
    def getBinning(self):
        return "2x2"

    def getGain(self):
        return _Value("1.5")


class _Image:
    def __init__(self):
        project = _NamedObject(200, "Cell Cycle")
        self._dataset = _NamedObject(100, "Mitotic Entry", parents=[project])

    def getName(self):
        return "img-001"

    def getAcquisitionDate(self):
        return datetime(2026, 4, 12, 10, 30, 0)

    def getChannels(self):
        return [
            _Channel(0, "DAPI", _Value("405"), _Value("450")),
            _Channel(1, "GFP", _Value("488"), _Value("525")),
        ]

    def getObjectiveSettings(self):
        return _ObjectiveSettings()

    def getDetectorSettings(self):
        return [_DetectorSettings()]

    def getPixelSizeX(self, units=True):
        return _UnitValue("0.108", "µm")

    def getPixelSizeY(self, units=True):
        return _UnitValue("0.108", "µm")

    def getPixelSizeZ(self, units=True):
        return _UnitValue("0.400", "µm")

    def loadOriginalMetadata(self):
        return (
            None,
            [
                ("Instrument Manufacturer", "Zeiss"),
                ("Instrument Model", "LSM 980"),
                ("Objective Model", "Plan-Apochromat"),
                ("Objective Magnification", "63"),
                ("Objective NA", "1.4"),
                ("Laser Line", "488 nm"),
                ("Exposure Time", "125 ms"),
            ],
            [("Detector Model", "Airyscan 2")],
        )

    def listParents(self):
        return [self._dataset]


def test_extract_search_document_builds_canonical_fields_and_metadata_attributes():
    document, context = extract_search_document(_Image())

    assert document.instrument_manufacturer == "Zeiss"
    assert document.instrument_model == "LSM 980"
    assert document.objective_model == "Plan-Apochromat"
    assert document.objective_magnification == 63.0
    assert document.objective_na == 1.4
    assert document.detector_model == "Airyscan 2"
    assert document.detector_binning == "2x2"
    assert document.detector_gain == 1.5
    assert document.pixel_size_x_um == 0.108
    assert document.pixel_size_y_um == 0.108
    assert document.z_step_um == 0.4
    assert document.channel_summary == "DAPI / Ex 405 nm / Em 450 nm; GFP / Ex 488 nm / Em 525 nm"
    assert "LSM 980" in document.search_document
    assert "Exposure Time" not in document.search_document
    assert "125 ms" in document.search_document
    assert document.raw_metadata["BF_Exposure Time"] == "125 ms"

    attributes = {attribute.attribute_key: attribute for attribute in document.attributes}
    assert attributes["instrument_model"].attribute_text == "LSM 980"
    assert attributes["exposure_time"].attribute_text == "125 ms"
    assert attributes["laser_line_nm"].attribute_numeric == 488.0
    assert context == {
        "dataset_id": 100,
        "dataset_name": "Mitotic Entry",
        "project_id": 200,
        "project_name": "Cell Cycle",
    }
