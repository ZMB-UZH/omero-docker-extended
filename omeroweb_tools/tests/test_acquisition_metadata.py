from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

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


class _PlaneInfo:
    def __init__(
        self,
        the_c,
        the_z,
        the_t,
        delta_t=None,
        exposure_time=None,
        position_x=None,
        position_y=None,
        position_z=None,
    ):
        self.theC = the_c
        self.theZ = the_z
        self.theT = the_t
        self._delta_t = delta_t
        self._exposure_time = exposure_time
        self._position_x = position_x
        self._position_y = position_y
        self._position_z = position_z

    def getDeltaT(self, units="SECOND"):
        assert units == "SECOND"
        return None if self._delta_t is None else _Value(self._delta_t)

    def getExposureTime(self, units="SECOND"):
        assert units == "SECOND"
        return None if self._exposure_time is None else _Value(self._exposure_time)

    def getPositionX(self):
        return None if self._position_x is None else _Value(self._position_x)

    def getPositionY(self):
        return None if self._position_y is None else _Value(self._position_y)

    def getPositionZ(self):
        return None if self._position_z is None else _Value(self._position_z)


class _Pixels:
    def __init__(self):
        self.copy_plane_info_calls = []
        self._plane_infos = {
            (0, 0): [
                _PlaneInfo(
                    0,
                    0,
                    0,
                    delta_t=0.0,
                    exposure_time=0.125,
                    position_x=10.0,
                    position_y=20.0,
                ),
                _PlaneInfo(0, 0, 1, delta_t=1.25, exposure_time=0.125),
            ],
            (0, 1): [_PlaneInfo(0, 1, 0, delta_t=2.5, position_z=0.4)],
            (1, 0): [_PlaneInfo(1, 0, 0, delta_t=0.6240005493164062)],
        }

    def getSizeX(self):
        return _Value(2048)

    def getSizeY(self):
        return _Value(1024)

    def getSizeZ(self):
        return _Value(2)

    def getSizeC(self):
        return _Value(2)

    def getSizeT(self):
        return _Value(2)

    def getPhysicalSizeX(self):
        return _UnitValue("0.108", "µm")

    def getPhysicalSizeY(self):
        return _UnitValue("0.108", "µm")

    def getPhysicalSizeZ(self):
        return _UnitValue("0.400", "µm")

    def copyPlaneInfo(self, theC=None, theZ=None):
        self.copy_plane_info_calls.append((theC, theZ))
        if theC is None and theZ is None:
            return [
                plane_info
                for group in self._plane_infos.values()
                for plane_info in group
            ]
        return self._plane_infos.get((theC, theZ), [])


class _DetectorSettings:
    gain = _Value("1.5")
    offsetValue = _Value("2")

    def getBinning(self):
        return "2x2"

    def getGain(self):
        return _Value("1.5")


class _LogicalChannel:
    name = "GFP logical"
    fluor = "EGFP"
    ndFilter = _Value("0.2")

    def getDetectorSettings(self):
        return _DetectorSettings()


class _Channel:
    def __init__(self, index, label, excitation, emission, logical_channel=None):
        self._index = index
        self._label = label
        self._excitation = excitation
        self._emission = emission
        self._logical_channel = logical_channel

    def getIndex(self):
        return self._index

    def getLabel(self):
        return self._label

    def getExcitationWave(self):
        return self._excitation

    def getEmissionWave(self):
        return self._emission

    def getLogicalChannel(self):
        return self._logical_channel


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

    def getObjective(self):
        return SimpleNamespace(
            manufacturer="Nikon",
            model="Plan Apo Lambda",
            serialNumber="OBJ-001",
            nominalMagnification=_Value("60"),
            lensNA=_Value("1.4"),
        )


class _Microscope:
    manufacturer = "Zeiss"
    model = "LSM 980"
    serialNumber = "MS-42"

    def getMicroscopeType(self):
        return "inverted"


class _Instrument:
    def getMicroscope(self):
        return _Microscope()

    def getObjectives(self):
        return [
            SimpleNamespace(
                manufacturer="Nikon",
                model="Plan Apo Lambda",
                nominalMagnification=_Value("60"),
                lensNA=_Value("1.4"),
            )
        ]


class _OriginalFile:
    def getName(self):
        return "synthetic-generated.dv"

    def getMimetype(self):
        return "application/octet-stream"

    def getSize(self):
        return _Value(4096)

    def getPath(self):
        raise AssertionError("private file paths must not be indexed")


class _Fileset:
    def copyUsedFiles(self):
        return [SimpleNamespace(getOriginalFile=lambda: _OriginalFile())]


class _MapAnnotation:
    OMERO_CLASS = "MapAnnotation"

    def getValue(self):
        return [SimpleNamespace(name="Treatment", value="DMSO")]


class _TextAnnotation:
    OMERO_CLASS = "TextAnnotation"

    def getTextValue(self):
        return "QC passed"


class _Image:
    def __init__(self):
        project = _NamedObject(200, "Cell Cycle")
        self._dataset = _NamedObject(100, "Mitotic Entry", parents=[project])
        self._pixels = _Pixels()

    def getName(self):
        return "img-001"

    def getDescription(self):
        return "Synthetic search fixture"

    def getAcquisitionDate(self):
        return datetime(2026, 4, 12, 10, 30, 0)

    def getChannels(self):
        return [
            _Channel(0, "DAPI", _Value("405"), _Value("450")),
            _Channel(1, "GFP", _Value("488"), _Value("525"), _LogicalChannel()),
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

    def getPrimaryPixels(self):
        return self._pixels

    def getInstrument(self):
        return _Instrument()

    def getFileset(self):
        return _Fileset()

    def listAnnotations(self):
        return [_MapAnnotation(), _TextAnnotation()]

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
    image = _Image()
    document, context = extract_search_document(image)

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
    assert (
        document.channel_summary
        == "DAPI / Ex 405 nm / Em 450 nm; GFP / Ex 488 nm / Em 525 nm"
    )
    assert "LSM 980" in document.search_document
    assert "delta t seconds" in document.search_document
    assert "0.6240005493164062 seconds" in document.search_document
    assert "Exposure Time" not in document.search_document
    assert "125 ms" in document.search_document
    assert "img-001" in document.search_document
    assert "Mitotic Entry" in document.search_document
    assert "Cell Cycle" in document.search_document
    assert "synthetic-generated.dv" in document.search_document
    assert "private" not in document.search_document
    assert document.raw_metadata["BF_Exposure Time"] == "125 ms"

    attributes = {
        attribute.attribute_key: attribute for attribute in document.attributes
    }
    assert attributes["instrument_model"].attribute_text == "LSM 980"
    assert attributes["exposure_time"].attribute_text == "125 ms"
    assert attributes["laser_line_nm"].attribute_numeric == 488.0
    assert (
        attributes["channel_0_z1_delta_t_seconds"].attribute_text
        == "t1 0.0 seconds; t2 1.25 seconds"
    )
    assert (
        attributes["channel_0_z1_exposure_time_seconds"].attribute_text
        == "t1 0.125 seconds; t2 0.125 seconds"
    )
    assert attributes["channel_0_z1_position_x"].attribute_text == "t1 10.0"
    assert attributes["channel_0_z2_delta_t_seconds"].attribute_text == "t1 2.5 seconds"
    assert (
        attributes["channel_1_z1_delta_t_seconds"].attribute_text
        == "t1 0.6240005493164062 seconds"
    )
    assert attributes["pixels_size_x"].attribute_numeric == 2048.0
    assert attributes["channel_1_fluor"].attribute_text == "EGFP"
    assert attributes["original_file_1_name"].attribute_text == "synthetic-generated.dv"
    assert "original_file_1_path" not in attributes
    assert attributes["annotation_map_treatment"].attribute_text == "DMSO"
    assert attributes["textannotation"].attribute_text == "QC passed"
    assert image._pixels.copy_plane_info_calls == [(None, None)]
    assert context == {
        "dataset_id": 100,
        "dataset_name": "Mitotic Entry",
        "project_id": 200,
        "project_name": "Cell Cycle",
    }
