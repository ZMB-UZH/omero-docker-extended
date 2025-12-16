import importlib
import importlib.util
import os
import sys
import types
import unittest


class DummyRString:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class GetterNamedValue:
    """Simulate MapAnnotation values that expose getName/getValue methods."""

    def __init__(self, name, value):
        self._name = DummyRString(name)
        self._value = DummyRString(value)

    def getName(self):
        return self._name

    def getValue(self):
        return self._value


class TupleNamedValue(tuple):
    """Simple tuple that mimics (name, value) pairs."""


class ValOnly:
    """Object exposing only `.val` to mimic some rtypes wrappers."""

    def __init__(self, value):
        self.val = value

    def __str__(self):
        return str(self.val)


class MapValueWrapper:
    """Container exposing getValue() for map values."""

    def __init__(self, pairs):
        self._pairs = pairs

    def getValue(self):
        return list(self._pairs)


class MapAnnotationStub:
    def __init__(self, pairs):
        self._pairs = pairs

    def getMapValue(self):
        return list(self._pairs)


class CoreImportMixin:
    @classmethod
    def setUpClass(cls):
        # Preserve any existing modules to restore later
        cls._orig_modules = {
            name: sys.modules.get(name) for name in ("omero", "omero.model", "omero.rtypes")
        }

        # Stub modules expected by services.core
        omero_mod = types.ModuleType("omero")
        model_mod = types.ModuleType("omero.model")
        rtypes_mod = types.ModuleType("omero.rtypes")
        sys_mod = types.ModuleType("omero.sys")

        class MapAnnotationI:
            pass

        class NamedValue:
            def __init__(self, name, value):
                self.name = name
                self.value = value

        class ImageAnnotationLinkI:
            pass

        def rstring(val):
            return DummyRString(val)

        def rlong(val):
            return DummyRString(val)

        class ParametersI:
            def __init__(self):
                self.params = {}

            def add(self, key, value):
                self.params[key] = value

        model_mod.MapAnnotationI = MapAnnotationI
        model_mod.NamedValue = NamedValue
        model_mod.ImageAnnotationLinkI = ImageAnnotationLinkI
        rtypes_mod.rstring = rstring
        rtypes_mod.rlong = rlong
        sys_mod.ParametersI = ParametersI

        sys.modules["omero"] = omero_mod
        sys.modules["omero.model"] = model_mod
        sys.modules["omero.rtypes"] = rtypes_mod
        sys.modules["omero.sys"] = sys_mod

        # Stub package structure to avoid importing Django-heavy __init__
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        package_name = "omeroweb_filenamemetadata"
        services_path = os.path.join(repo_root, "services")

        pkg_mod = types.ModuleType(package_name)
        pkg_mod.__path__ = [repo_root]
        sys.modules[package_name] = pkg_mod

        services_pkg = types.ModuleType(f"{package_name}.services")
        services_pkg.__path__ = [services_path]
        services_pkg.__package__ = package_name
        sys.modules[f"{package_name}.services"] = services_pkg

        const_spec = importlib.util.spec_from_file_location(
            f"{package_name}.constants", os.path.join(repo_root, "constants.py")
        )
        constants_mod = importlib.util.module_from_spec(const_spec)
        const_spec.loader.exec_module(constants_mod)
        sys.modules[f"{package_name}.constants"] = constants_mod

        core_spec = importlib.util.spec_from_file_location(
            f"{package_name}.services.core", os.path.join(services_path, "core.py")
        )
        core_mod = importlib.util.module_from_spec(core_spec)
        core_spec.loader.exec_module(core_mod)
        sys.modules[f"{package_name}.services.core"] = core_mod

        cls.core = core_mod

    @classmethod
    def tearDownClass(cls):
        # Restore prior modules
        sys.modules.pop("services.core", None)
        for name in [
            "omeroweb_filenamemetadata",
            "omeroweb_filenamemetadata.constants",
            "omeroweb_filenamemetadata.services",
            "omeroweb_filenamemetadata.services.core",
            "omero.sys",
        ]:
            sys.modules.pop(name, None)
        for name, mod in cls._orig_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


class TestPluginAnnotation(CoreImportMixin, unittest.TestCase):
    def test_detects_named_values_with_getters(self):
        mapping = {"Var1": "A", "Var2": "B"}
        mapping[self.core.HASH_KEY] = self.core.compute_plugin_hash(mapping)
        pairs = [GetterNamedValue(k, v) for k, v in mapping.items()]
        ann = MapAnnotationStub(pairs)

        self.assertTrue(self.core.is_plugin_annotation(ann))

    def test_detects_tuple_pairs(self):
        mapping = {"VarX": "123"}
        mapping[self.core.HASH_KEY] = self.core.compute_plugin_hash(mapping)
        pairs = [TupleNamedValue((k, v)) for k, v in mapping.items()]
        ann = MapAnnotationStub(pairs)

        self.assertTrue(self.core.is_plugin_annotation(ann))

    def test_rejects_invalid_hash(self):
        pairs = [GetterNamedValue("foo", "bar"), GetterNamedValue(self.core.HASH_KEY, "wrong")]
        ann = MapAnnotationStub(pairs)

        self.assertFalse(self.core.is_plugin_annotation(ann))

    def test_detects_wrapper_map_value_and_val_only_entries(self):
        mapping = {"Var1": "AAA", "Var2": "BBB"}
        mapping[self.core.HASH_KEY] = self.core.compute_plugin_hash(mapping)

        pairs = [
            self.core.NamedValue(ValOnly(k), ValOnly(v)) for k, v in mapping.items()
        ]
        wrapped = MapValueWrapper(pairs)

        class MapAnnotationWithWrapper(MapAnnotationStub):
            def getMapValue(self):
                return wrapped

        ann = MapAnnotationWithWrapper(pairs)

        self.assertTrue(self.core.is_plugin_annotation(ann))

    def test_fetches_map_values_via_query_service_when_absent(self):
        mapping = {"Var1": "foo"}
        mapping[self.core.HASH_KEY] = self.core.compute_plugin_hash(mapping)

        class MapAnnotationWithoutValues(MapAnnotationStub):
            def __init__(self, ann_id):
                super().__init__([])
                self._id = ann_id

            def getMapValue(self):
                return []

            def getId(self):
                class Dummy:
                    def __init__(self, v):
                        self._v = v

                    def getValue(self):
                        return self._v

                return Dummy(self._id)

        class DummyQueryService:
            def projection(self, hql, params, opts):
                return [
                    [DummyRString(k), DummyRString(v)] for k, v in mapping.items()
                ]

        ann = MapAnnotationWithoutValues(ann_id=42)

        qs = DummyQueryService()

        self.assertTrue(self.core.is_plugin_annotation(ann, qs=qs, service_opts=None))


if __name__ == "__main__":
    unittest.main()
