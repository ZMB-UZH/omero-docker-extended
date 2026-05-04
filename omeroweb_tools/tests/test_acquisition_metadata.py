from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from omeroweb_tools.services.acquisition_metadata import extract_search_document


class _Value:
    """Represent value."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _UnitValue(_Value):
    """Represent unit value."""

    def __init__(self, value, symbol):
        """Initialize the instance.

        Inputs: `value`, `symbol`. Output: None.
        """
        super().__init__(value)
        self._symbol = symbol

    def getSymbol(self):
        """Return Symbol.

        Inputs: none. Output: `self._symbol`.
        """
        return self._symbol


class _PlaneInfo:
    """Represent plane info."""

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
        """Initialize the instance.

        Inputs: `the_c`, `the_z`, `the_t`, `delta_t`, `exposure_time`, `position_x`,
        `position_y`, `position_z`. Output: None.
        """
        self.theC = the_c
        self.theZ = the_z
        self.theT = the_t
        self._delta_t = delta_t
        self._exposure_time = exposure_time
        self._position_x = position_x
        self._position_y = position_y
        self._position_z = position_z

    def getDeltaT(self, units="SECOND"):
        """Return Delta T.

        Inputs: `units`. Output: computed value.
        """
        assert units == "SECOND"
        return None if self._delta_t is None else _Value(self._delta_t)

    def getExposureTime(self, units="SECOND"):
        """Return Exposure Time.

        Inputs: `units`. Output: computed value.
        """
        assert units == "SECOND"
        return None if self._exposure_time is None else _Value(self._exposure_time)

    def getPositionX(self):
        """Return Position X.

        Inputs: none. Output: computed value.
        """
        return None if self._position_x is None else _Value(self._position_x)

    def getPositionY(self):
        """Return Position Y.

        Inputs: none. Output: computed value.
        """
        return None if self._position_y is None else _Value(self._position_y)

    def getPositionZ(self):
        """Return Position Z.

        Inputs: none. Output: computed value.
        """
        return None if self._position_z is None else _Value(self._position_z)


class _Pixels:
    """Represent pixels."""

    def __init__(self):
        """Initialize the instance.

        Inputs: none. Output: None.
        """
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

    @staticmethod
    def getSizeX():
        """Return Size X.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2048)

    @staticmethod
    def getSizeY():
        """Return Size Y.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(1024)

    @staticmethod
    def getSizeZ():
        """Return Size Z.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getSizeC():
        """Return Size C.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getSizeT():
        """Return Size T.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getPhysicalSizeX():
        """Return Physical Size X.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPhysicalSizeY():
        """Return Physical Size Y.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPhysicalSizeZ():
        """Return Physical Size Z.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.400", "µm")

    def copyPlaneInfo(self, theC=None, theZ=None):
        """Copy Plane Info.

        Inputs: `theC`, `theZ`. Output: computed value.
        """
        self.copy_plane_info_calls.append((theC, theZ))
        if theC is None and theZ is None:
            return [
                plane_info
                for group in self._plane_infos.values()
                for plane_info in group
            ]
        return self._plane_infos.get((theC, theZ), [])


class _DetectorSettings:
    """Represent detector settings."""

    gain = _Value("1.5")
    offsetValue = _Value("2")

    @staticmethod
    def getBinning():
        """Return Binning.

        Inputs: none. Output: '2x2'.
        """
        return "2x2"

    @staticmethod
    def getGain():
        """Return Gain.

        Inputs: none. Output: `_Value` result.
        """
        return _Value("1.5")

    @staticmethod
    def getDetector():
        """Return Detector.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Hamamatsu", model="Orca Flash")


class _LightSourceSettings:
    """Represent light source settings."""

    attenuation = _Value("0.5")
    wavelength = _Value("488")

    @staticmethod
    def getLightSource():
        """Return Light Source.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Coherent", model="Sapphire")


class _LightPath:
    """Represent light path."""

    @staticmethod
    def getDichroic():
        """Return Dichroic.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Chroma", model="T495lpxr")

    @staticmethod
    def getEmissionFilters():
        """Return Emission Filters.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET525/50m")]

    @staticmethod
    def getExcitationFilters():
        """Return Excitation Filters.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET470/40x")]


class _LogicalChannel:
    """Represent logical channel."""

    name = "GFP logical"
    fluor = "EGFP"
    ndFilter = _Value("0.2")

    @staticmethod
    def getDetectorSettings():
        """Return Detector Settings.

        Inputs: none. Output: `_DetectorSettings` result.
        """
        return _DetectorSettings()

    @staticmethod
    def getLightSourceSettings():
        """Return Light Source Settings.

        Inputs: none. Output: `_LightSourceSettings` result.
        """
        return _LightSourceSettings()

    @staticmethod
    def getLightPath():
        """Return Light Path.

        Inputs: none. Output: `_LightPath` result.
        """
        return _LightPath()


class _Channel:
    """Represent channel."""

    def __init__(self, index, label, excitation, emission, logical_channel=None):
        """Initialize the instance.

        Inputs: `index`, `label`, `excitation`, `emission`, `logical_channel`. Output:
        None.

        None.
        """
        self._index = index
        self._label = label
        self._excitation = excitation
        self._emission = emission
        self._logical_channel = logical_channel

    def getIndex(self):
        """Return Index.

        Inputs: none. Output: `self._index`.
        """
        return self._index

    def getLabel(self):
        """Return Label.

        Inputs: none. Output: `self._label`.
        """
        return self._label

    def getExcitationWave(self):
        """Return Excitation Wave.

        Inputs: none. Output: `self._excitation`.
        """
        return self._excitation

    def getEmissionWave(self):
        """Return Emission Wave.

        Inputs: none. Output: `self._emission`.
        """
        return self._emission

    def getLogicalChannel(self):
        """Return Logical Channel.

        Inputs: none. Output: `self._logical_channel`.
        """
        return self._logical_channel


class _NamedObject:
    """Represent named object."""

    def __init__(self, object_id, name, parents=None):
        """Initialize the instance.

        Inputs: `object_id`, `name`, `parents`. Output: None.
        """
        self._id = object_id
        self._name = name
        self._parents = list(parents or [])

    def getId(self):
        """Return the fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._id)

    def getName(self):
        """Return the fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def listParents(self):
        """Return list parents.

        Inputs: none. Output: `list` result.
        """
        return list(self._parents)


class _ObjectiveSettings:
    """Represent objective settings."""

    @staticmethod
    def getCorrectionCollar():
        """Return Correction Collar.

        Inputs: none. Output: `_Value` result.
        """
        return _Value("0.17")

    @staticmethod
    def getID():
        """Return ID.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(31)

    @staticmethod
    def getObjective():
        """Return Objective.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(
            manufacturer="Nikon",
            model="Plan Apo Lambda",
            serialNumber="OBJ-001",
            nominalMagnification=_Value("60"),
            lensNA=_Value("1.4"),
        )


class _Microscope:
    """Represent microscope."""

    manufacturer = "Zeiss"
    model = "LSM 980"
    serialNumber = "MS-42"

    @staticmethod
    def getMicroscopeType():
        """Return Microscope Type.

        Inputs: none. Output: 'inverted'.
        """
        return "inverted"


class _Instrument:
    """Represent instrument."""

    @staticmethod
    def getMicroscope():
        """Return Microscope.

        Inputs: none. Output: `_Microscope` result.
        """
        return _Microscope()

    @staticmethod
    def getObjectives():
        """Return Objectives.

        Inputs: none. Output: list.
        """
        return [
            SimpleNamespace(
                manufacturer="Nikon",
                model="Plan Apo Lambda",
                nominalMagnification=_Value("60"),
                lensNA=_Value("1.4"),
            )
        ]

    @staticmethod
    def getFilters():
        """Return Filters.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET525/50m")]

    @staticmethod
    def getDichroics():
        """Return Dichroics.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="T495lpxr")]

    @staticmethod
    def getDetectors():
        """Return Detectors.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Hamamatsu", model="Orca Flash")]

    @staticmethod
    def getLightSources():
        """Return Light Sources.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Coherent", model="Sapphire")]


class _OriginalFile:
    """Represent original file."""

    @staticmethod
    def getName():
        """Return the fake object name.

        Inputs: none. Output: 'synthetic-generated.dv'.
        """
        return "synthetic-generated.dv"

    @staticmethod
    def getMimetype():
        """Return Mimetype.

        Inputs: none. Output: 'application/octet-stream'.
        """
        return "application/octet-stream"

    @staticmethod
    def getSize():
        """Return Size.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(4096)

    @staticmethod
    def getPath():
        """Return Path.

        Inputs: none. Output: None. Raises on invalid or unavailable state.
        """
        raise AssertionError("private file paths must not be indexed")


class _UsedFile:
    """Represent used file."""

    @staticmethod
    def getOriginalFile():
        """Return Original File.

        Inputs: none. Output: `_OriginalFile` result.
        """
        return _OriginalFile()


class _Fileset:
    """Represent fileset."""

    @staticmethod
    def copyUsedFiles():
        """Copy Used Files.

        Inputs: none. Output: list.
        """
        return [_UsedFile()]


class _MapAnnotation:
    """Represent map annotation."""

    OMERO_CLASS = "MapAnnotation"

    @staticmethod
    def getValue():
        """Return the fake OMERO value.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(name="Treatment", value="DMSO")]


class _TextAnnotation:
    """Represent text annotation."""

    OMERO_CLASS = "TextAnnotation"

    @staticmethod
    def getTextValue():
        """Return Text Value.

        Inputs: none. Output: 'QC passed'.
        """
        return "QC passed"


class _Image:
    """Represent image."""

    def __init__(self):
        """Initialize the instance.

        Inputs: none. Output: None.
        """
        project = _NamedObject(200, "Cell Cycle")
        self._dataset = _NamedObject(100, "Mitotic Entry", parents=[project])
        self._pixels = _Pixels()

    @staticmethod
    def getName():
        """Return the fake object name.

        Inputs: none. Output: 'img-001'.
        """
        return "img-001"

    @staticmethod
    def getDescription():
        """Return Description.

        Inputs: none. Output: 'Synthetic search fixture'.
        """
        return "Synthetic search fixture"

    @staticmethod
    def getAcquisitionDate():
        """Return Acquisition Date.

        Inputs: none. Output: `datetime` result.
        """
        return datetime(2026, 4, 12, 10, 30, 0)

    @staticmethod
    def getChannels():
        """Return Channels.

        Inputs: none. Output: list.
        """
        return [
            _Channel(0, "DAPI", _Value("405"), _Value("450")),
            _Channel(1, "GFP", _Value("488"), _Value("525"), _LogicalChannel()),
        ]

    @staticmethod
    def getObjectiveSettings():
        """Return Objective Settings.

        Inputs: none. Output: `_ObjectiveSettings` result.
        """
        return _ObjectiveSettings()

    @staticmethod
    def getDetectorSettings():
        """Return Detector Settings.

        Inputs: none. Output: list.
        """
        return [_DetectorSettings()]

    @staticmethod
    def getPixelSizeX(units=True):
        """Return Pixel Size X.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPixelSizeY(units=True):
        """Return Pixel Size Y.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPixelSizeZ(units=True):
        """Return Pixel Size Z.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.400", "µm")

    def getPrimaryPixels(self):
        """Return Primary Pixels.

        Inputs: none. Output: `self._pixels`.
        """
        return self._pixels

    @staticmethod
    def getInstrument():
        """Return Instrument.

        Inputs: none. Output: `_Instrument` result.
        """
        return _Instrument()

    @staticmethod
    def getImagingEnvironment():
        """Return Imaging Environment.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(temperature=_Value("37"), humidity=_Value("40"))

    @staticmethod
    def getStageLabel():
        """Return Stage Label.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(
            name="Well A1",
            x=_Value("1.0"),
            y=_Value("2.0"),
            z=_Value("3.0"),
        )

    @staticmethod
    def getFileset():
        """Return Fileset.

        Inputs: none. Output: `_Fileset` result.
        """
        return _Fileset()

    @staticmethod
    def listAnnotations():
        """Return list annotations.

        Inputs: none. Output: list.
        """
        return [_MapAnnotation(), _TextAnnotation()]

    @staticmethod
    def loadOriginalMetadata():
        """Return load original metadata.

        Inputs: none. Output: tuple.
        """
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
        """Return list parents.

        Inputs: none. Output: list.
        """
        return [self._dataset]


def test_extract_search_document_builds_canonical_fields_and_metadata_attributes():
    """Verify extract search document builds canonical fields and metadata attributes.

    Inputs: none. Output: None.
    """
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
    assert attributes["channel_1_detector_model"].attribute_text == "Orca Flash"
    assert attributes["channel_1_light_source_model"].attribute_text == "Sapphire"
    assert attributes["channel_1_dichroic_model"].attribute_text == "T495lpxr"
    assert attributes["channel_1_emission_filter_1_model"].attribute_text == "ET525/50m"
    assert (
        attributes["channel_1_excitation_filter_1_model"].attribute_text == "ET470/40x"
    )
    assert attributes["imaging_environment_temperature"].attribute_text == "37"
    assert attributes["stage_label_name"].attribute_text == "Well A1"
    assert attributes["instrument_filter_1_model"].attribute_text == "ET525/50m"
    assert attributes["instrument_dichroic_1_model"].attribute_text == "T495lpxr"
    assert attributes["instrument_detector_1_model"].attribute_text == "Orca Flash"
    assert attributes["instrument_light_source_1_model"].attribute_text == "Sapphire"
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
