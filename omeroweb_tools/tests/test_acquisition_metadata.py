from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from omeroweb_tools.services.acquisition_metadata import extract_search_document


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _UnitValue(_Value):
    """Test double for unit value behavior in this module."""

    def __init__(self, value, symbol):
        """Create `_UnitValue` with `value` and `symbol`.

        Inputs: `value`, `symbol`. Output: None.
        """
        super().__init__(value)
        self._symbol = symbol

    def getSymbol(self):
        """Return the symbol for `_UnitValue`.

        Inputs: none. Output: `_symbol`.
        """
        return self._symbol


class _PlaneInfo:
    """Test double for plane info behavior in this module."""

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
        """Create `_PlaneInfo` with `the_c`, `the_z`, `the_t`, `delta_t`, `exposure_time`, `position_x`, `position_y`, and `position_z`.

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
        """Return the fake delta t value used by this test double.

        Inputs: `units`. Output: get delta t result.
        """
        assert units == "SECOND"
        return None if self._delta_t is None else _Value(self._delta_t)

    def getExposureTime(self, units="SECOND"):
        """Return the fake exposure time value used by this test double.

        Inputs: `units`. Output: get exposure time result.
        """
        assert units == "SECOND"
        return None if self._exposure_time is None else _Value(self._exposure_time)

    def getPositionX(self):
        """Return the fake position x value used by this test double.

        Inputs: none. Output: get position x result.
        """
        return None if self._position_x is None else _Value(self._position_x)

    def getPositionY(self):
        """Return the fake position y value used by this test double.

        Inputs: none. Output: get position y result.
        """
        return None if self._position_y is None else _Value(self._position_y)

    def getPositionZ(self):
        """Return the fake position z value used by this test double.

        Inputs: none. Output: get position z result.
        """
        return None if self._position_z is None else _Value(self._position_z)


class _Pixels:
    """Test double for pixels behavior in this module."""

    def __init__(self):
        """Create `_Pixels` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
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
        """Return `_Pixels`'s fake SizeX value.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2048)

    @staticmethod
    def getSizeY():
        """Return `_Pixels`'s fake SizeY value.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(1024)

    @staticmethod
    def getSizeZ():
        """Return `_Pixels`'s fake SizeZ value.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getSizeC():
        """Return `_Pixels`'s fake channel count.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getSizeT():
        """Return `_Pixels`'s fake timepoint count.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(2)

    @staticmethod
    def getPhysicalSizeX():
        """Return `_Pixels`'s fake physical X size.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPhysicalSizeY():
        """Return `_Pixels`'s fake physical Y size.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPhysicalSizeZ():
        """Return `_Pixels`'s fake physical Z size.

        Inputs: none. Output: `_UnitValue` result.
        """
        return _UnitValue("0.400", "µm")

    def copyPlaneInfo(self, theC=None, theZ=None):
        """Copy the plane Info for `_Pixels`.

        Inputs: `theC`, `theZ`. Output: `get` result.
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
    """Test double for detector settings behavior in this module."""

    gain = _Value("1.5")
    offsetValue = _Value("2")

    @staticmethod
    def getBinning():
        """Return the binning for `_DetectorSettings`.

        Inputs: none. Output: `str`.
        """
        return "2x2"

    @staticmethod
    def getGain():
        """Return the gain for `_DetectorSettings`.

        Inputs: none. Output: `_Value` result.
        """
        return _Value("1.5")

    @staticmethod
    def getDetector():
        """Return the detector for `_DetectorSettings`.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Hamamatsu", model="Orca Flash")


class _LightSourceSettings:
    """Test double for light source settings behavior in this module."""

    attenuation = _Value("0.5")
    wavelength = _Value("488")

    @staticmethod
    def getLightSource():
        """Return the fake light source value used by this test double.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Coherent", model="Sapphire")


class _LightPath:
    """Test double for light path behavior in this module."""

    @staticmethod
    def getDichroic():
        """Return the dichroic for `_LightPath`.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(manufacturer="Chroma", model="T495lpxr")

    @staticmethod
    def getEmissionFilters():
        """Return the fake emission filters value used by this test double.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET525/50m")]

    @staticmethod
    def getExcitationFilters():
        """Return the fake excitation filters value used by this test double.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET470/40x")]


class _LogicalChannel:
    """Test double for logical channel behavior in this module."""

    name = "GFP logical"
    fluor = "EGFP"
    ndFilter = _Value("0.2")

    @staticmethod
    def getDetectorSettings():
        """Return `_LogicalChannel`'s fake detector settings.

        Inputs: none. Output: `_DetectorSettings` result.
        """
        return _DetectorSettings()

    @staticmethod
    def getLightSourceSettings():
        """Return the fake light source settings value used by this test double.

        Inputs: none. Output: `_LightSourceSettings` result.
        """
        return _LightSourceSettings()

    @staticmethod
    def getLightPath():
        """Return the fake light path value used by this test double.

        Inputs: none. Output: `_LightPath` result.
        """
        return _LightPath()


class _Channel:
    """Test double for channel behavior in this module."""

    def __init__(self, index, label, excitation, emission, logical_channel=None):
        """Create `_Channel` with `index`, `label`, `excitation`, `emission`, and `logical_channel`.

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
        """Return the index for `_Channel`.

        Inputs: none. Output: `_index`.
        """
        return self._index

    def getLabel(self):
        """Return the label for `_Channel`.

        Inputs: none. Output: `_label`.
        """
        return self._label

    def getExcitationWave(self):
        """Return the fake excitation wave value used by this test double.

        Inputs: none. Output: `self._excitation`.
        """
        return self._excitation

    def getEmissionWave(self):
        """Return the fake emission wave value used by this test double.

        Inputs: none. Output: `self._emission`.
        """
        return self._emission

    def getLogicalChannel(self):
        """Return the fake logical channel value used by this test double.

        Inputs: none. Output: `self._logical_channel`.
        """
        return self._logical_channel


class _NamedObject:
    """Test double for named object behavior in this module."""

    def __init__(self, object_id, name, parents=None):
        """Create `_NamedObject` with `object_id`, `name`, and `parents`.

        Inputs: `object_id`, `name`, `parents`. Output: None.
        """
        self._id = object_id
        self._name = name
        self._parents = list(parents or [])

    def getId(self):
        """Return `_NamedObject`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._id)

    def getName(self):
        """Return `_NamedObject`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def listParents(self):
        """Return `_NamedObject`'s fake parent listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._parents)


class _ObjectiveSettings:
    """Test double for objective settings behavior in this module."""

    @staticmethod
    def getCorrectionCollar():
        """Return the fake correction collar value used by this test double.

        Inputs: none. Output: `_Value` result.
        """
        return _Value("0.17")

    @staticmethod
    def getID():
        """Return the ID for `_ObjectiveSettings`.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(31)

    @staticmethod
    def getObjective():
        """Return the objective for `_ObjectiveSettings`.

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
    """Test double for microscope behavior in this module."""

    manufacturer = "Zeiss"
    model = "LSM 980"
    serialNumber = "MS-42"

    @staticmethod
    def getMicroscopeType():
        """Return the fake microscope type value used by this test double.

        Inputs: none. Output: 'inverted'.
        """
        return "inverted"


class _Instrument:
    """Test double for instrument behavior in this module."""

    @staticmethod
    def getMicroscope():
        """Return the microscope for `_Instrument`.

        Inputs: none. Output: `_Microscope` result.
        """
        return _Microscope()

    @staticmethod
    def getObjectives():
        """Return the objectives for `_Instrument`.

        Inputs: none. Output: `list`.
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
        """Return the filters for `_Instrument`.

        Inputs: none. Output: `list`.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="ET525/50m")]

    @staticmethod
    def getDichroics():
        """Return the dichroics for `_Instrument`.

        Inputs: none. Output: `list`.
        """
        return [SimpleNamespace(manufacturer="Chroma", model="T495lpxr")]

    @staticmethod
    def getDetectors():
        """Return the detectors for `_Instrument`.

        Inputs: none. Output: `list`.
        """
        return [SimpleNamespace(manufacturer="Hamamatsu", model="Orca Flash")]

    @staticmethod
    def getLightSources():
        """Return the fake light sources value used by this test double.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(manufacturer="Coherent", model="Sapphire")]


class _OriginalFile:
    """Test double for original file behavior in this module."""

    @staticmethod
    def getName():
        """Return `_OriginalFile`'s fake object name.

        Inputs: none. Output: 'synthetic-generated.dv'.
        """
        return "synthetic-generated.dv"

    @staticmethod
    def getMimetype():
        """Return the mimetype for `_OriginalFile`.

        Inputs: none. Output: `str`.
        """
        return "application/octet-stream"

    @staticmethod
    def getSize():
        """Return the size for `_OriginalFile`.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(4096)

    @staticmethod
    def getPath():
        """Return the path for `_OriginalFile`.

        Inputs: caller provides no extra arguments. Output: returns the fake value described above.
        """
        raise AssertionError("private file paths must not be indexed")


class _UsedFile:
    """Test double for used file behavior in this module."""

    @staticmethod
    def getOriginalFile():
        """Return `_UsedFile`'s fake original file.

        Inputs: none. Output: `_OriginalFile` result.
        """
        return _OriginalFile()


class _Fileset:
    """Test double for fileset behavior in this module."""

    @staticmethod
    def copyUsedFiles():
        """Copy the used Files for `_Fileset`.

        Inputs: none. Output: `list`.
        """
        return [_UsedFile()]


class _MapAnnotation:
    """Test double for map annotation behavior in this module."""

    OMERO_CLASS = "MapAnnotation"

    @staticmethod
    def getValue():
        """Return `_MapAnnotation`'s fake OMERO value.

        Inputs: none. Output: list.
        """
        return [SimpleNamespace(name="Treatment", value="DMSO")]


class _TextAnnotation:
    """Test double for text annotation behavior in this module."""

    OMERO_CLASS = "TextAnnotation"

    @staticmethod
    def getTextValue():
        """Return the fake text payload used by this test double.

        Inputs: none. Output: 'QC passed'.
        """
        return "QC passed"


class _Image:
    """Test double for image behavior in this module."""

    def __init__(self):
        """Create `_Image` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        project = _NamedObject(200, "Cell Cycle")
        self._dataset = _NamedObject(100, "Mitotic Entry", parents=[project])
        self._pixels = _Pixels()

    @staticmethod
    def getName():
        """Return `_Image`'s fake object name.

        Inputs: none. Output: 'img-001'.
        """
        return "img-001"

    @staticmethod
    def getDescription():
        """Return the description for `_Image`.

        Inputs: none. Output: `str`.
        """
        return "Synthetic search fixture"

    @staticmethod
    def getAcquisitionDate():
        """Return `_Image`'s fake acquisition date.

        Inputs: none. Output: `datetime` result.
        """
        return datetime(2026, 4, 12, 10, 30, 0)

    @staticmethod
    def getChannels():
        """Return the channels for `_Image`.

        Inputs: none. Output: `list`.
        """
        return [
            _Channel(0, "DAPI", _Value("405"), _Value("450")),
            _Channel(1, "GFP", _Value("488"), _Value("525"), _LogicalChannel()),
        ]

    @staticmethod
    def getObjectiveSettings():
        """Return `_Image`'s fake objective settings.

        Inputs: none. Output: `_ObjectiveSettings` result.
        """
        return _ObjectiveSettings()

    @staticmethod
    def getDetectorSettings():
        """Return `_Image`'s fake detector settings.

        Inputs: none. Output: list.
        """
        return [_DetectorSettings()]

    @staticmethod
    def getPixelSizeX(units=True):
        """Return `_Image`'s fake physical X size.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPixelSizeY(units=True):
        """Return `_Image`'s fake physical Y size.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.108", "µm")

    @staticmethod
    def getPixelSizeZ(units=True):
        """Return `_Image`'s fake physical Z size.

        Inputs: `units`. Output: `_UnitValue` result.
        """
        return _UnitValue("0.400", "µm")

    def getPrimaryPixels(self):
        """Return the fake primary pixels value used by this test double.

        Inputs: none. Output: `self._pixels`.
        """
        return self._pixels

    @staticmethod
    def getInstrument():
        """Return the instrument for `_Image`.

        Inputs: none. Output: `_Instrument` result.
        """
        return _Instrument()

    @staticmethod
    def getImagingEnvironment():
        """Return the fake imaging environment value used by this test double.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(temperature=_Value("37"), humidity=_Value("40"))

    @staticmethod
    def getStageLabel():
        """Return the fake stage label value used by this test double.

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
        """Return the fileset for `_Image`.

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
        """Return `_Image`'s fake original-metadata payload.

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
        """Return `_Image`'s fake parent listing.

        Inputs: none. Output: list.
        """
        return [self._dataset]


def test_extract_search_document_builds_canonical_fields_and_metadata_attributes():
    """Verify extract search document builds canonical fields and metadata attributes.

    Inputs: tools-service fixtures. Output: fails on regressions in extract search document builds canonical fields and metadata attributes.
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
