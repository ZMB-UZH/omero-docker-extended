from __future__ import annotations

import importlib.util
import runpy
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "startup" / "job_service_group_sync.py"


class FakeApiUsageException(Exception):
    pass


class FakeValidationException(Exception):
    pass


class FakeRValue:
    def __init__(self, value):
        self.val = value


class FakeExperimenterI:
    def __init__(self, id_value=None, loaded=True):
        self.id = FakeRValue(id_value) if id_value is not None else None
        self.loaded = loaded
        self.omeName = None
        self.firstName = None
        self.lastName = None
        self.ldap = None


class FakeGroup:
    def __init__(self, id_value: int, name: str):
        self.id = FakeRValue(id_value)
        self.name = FakeRValue(name)


class FakeAdmin:
    def __init__(
        self,
        groups: list[FakeGroup],
        member_group_ids: list[int],
        existing_user: bool = True,
        create_exception: BaseException | None = None,
    ):
        self.groups = groups
        self.member_group_ids = member_group_ids
        self.existing_user = existing_user
        self.create_exception = create_exception
        self.created_users: list[tuple[str, str, object, list[object]]] = []
        self.added_groups: list[tuple[FakeExperimenterI, list[FakeGroup]]] = []
        self.lookup_calls = 0

    def lookupExperimenter(self, name: str):
        self.lookup_calls += 1
        if not self.existing_user and not self.created_users:
            raise FakeApiUsageException(name)
        experimenter = FakeExperimenterI(42, False)
        experimenter.omeName = FakeRValue(name)
        return experimenter

    def lookupGroup(self, name: str):
        return FakeGroup(2, name)

    def createExperimenterWithPassword(
        self,
        experimenter: FakeExperimenterI,
        password: FakeRValue,
        default_group: FakeGroup,
        groups: list[object],
    ):
        if self.create_exception is not None:
            if isinstance(self.create_exception, FakeValidationException):
                self.existing_user = True
            raise self.create_exception
        self.created_users.append(
            (experimenter.omeName.val, password.val, default_group, groups)
        )
        return 42

    def getMemberOfGroupIds(self, experimenter: FakeExperimenterI):
        return list(self.member_group_ids)

    def lookupGroups(self):
        return list(self.groups)

    def addGroups(self, experimenter: FakeExperimenterI, groups: list[FakeGroup]):
        self.added_groups.append((experimenter, list(groups)))


class FakeConnection:
    def __init__(self, admin: FakeAdmin, connect_result: bool = True):
        self.admin = admin
        self.connect_result = connect_result
        self.closed = False
        self.init_args = None
        self.init_kwargs = None

    def __call__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        return self

    def connect(self):
        return self.connect_result

    def getAdminService(self):
        return self.admin

    def close(self):
        self.closed = True


@pytest.fixture()
def helper_module(monkeypatch):
    fake_omero = types.ModuleType("omero")
    fake_omero.ApiUsageException = FakeApiUsageException
    fake_omero.ValidationException = FakeValidationException

    fake_gateway = types.ModuleType("omero.gateway")
    fake_gateway.BlitzGateway = None
    fake_model = types.ModuleType("omero.model")
    fake_model.ExperimenterI = FakeExperimenterI
    fake_rtypes = types.ModuleType("omero.rtypes")
    fake_rtypes.rbool = lambda value: FakeRValue(value)
    fake_rtypes.rstring = lambda value: FakeRValue(value)

    monkeypatch.setitem(sys.modules, "omero", fake_omero)
    monkeypatch.setitem(sys.modules, "omero.gateway", fake_gateway)
    monkeypatch.setitem(sys.modules, "omero.model", fake_model)
    monkeypatch.setitem(sys.modules, "omero.rtypes", fake_rtypes)

    spec = importlib.util.spec_from_file_location(
        "job_service_group_sync_under_test", HELPER_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_bool_accepts_only_explicit_boolean_values(helper_module):
    module = helper_module

    assert module._parse_bool("true") is True
    assert module._parse_bool("1") is True
    assert module._parse_bool("false") is False
    assert module._parse_bool("0") is False
    with pytest.raises(ValueError, match="invalid boolean"):
        module._parse_bool("maybe")


def test_required_env_rejects_missing_values(helper_module, monkeypatch):
    module = helper_module
    monkeypatch.delenv("ROOTPASS", raising=False)

    with pytest.raises(ValueError, match="ROOTPASS is required"):
        module._required_env("ROOTPASS")


def test_eligible_groups_excludes_builtin_groups(helper_module):
    module = helper_module

    groups = [
        FakeGroup(0, "root"),
        FakeGroup(1, "system"),
        FakeGroup(2, "user"),
        FakeGroup(3, "science"),
    ]

    assert module._eligible_groups(groups) == [groups[-1]]


def test_sync_memberships_uses_one_connection_and_batches_missing_groups(
    helper_module, monkeypatch, capsys
):
    module = helper_module
    admin = FakeAdmin(
        groups=[
            FakeGroup(1, "system"),
            FakeGroup(2, "user"),
            FakeGroup(3, "users_private"),
            FakeGroup(4, "users_read"),
        ],
        member_group_ids=[3],
    )
    fake_connection = FakeConnection(admin)
    module.BlitzGateway = fake_connection
    monkeypatch.setenv("ROOTPASS", "root-secret")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "job-secret")

    rc = module.main(
        [
            "--host",
            "omeroserver",
            "--port",
            "4064",
            "--secure",
            "true",
            "--root-user",
            "root",
            "--job-user",
            "job-service",
            "--user-retries",
            "2",
        ]
    )

    assert rc == 0
    assert fake_connection.init_args == ("root", "root-secret")
    assert fake_connection.init_kwargs == {
        "host": "omeroserver",
        "port": 4064,
        "secure": True,
    }
    assert fake_connection.closed is True
    assert [(group.id.val, group.name.val) for group in admin.added_groups[0][1]] == [
        (4, "users_read")
    ]
    assert (
        "eligible_groups=2 added_groups=1 already_member=1" in capsys.readouterr().out
    )


def test_sync_memberships_creates_missing_job_user(helper_module, monkeypatch):
    module = helper_module
    admin = FakeAdmin(
        groups=[FakeGroup(3, "users_private")],
        member_group_ids=[],
        existing_user=False,
    )
    module.BlitzGateway = FakeConnection(admin)
    monkeypatch.setenv("ROOTPASS", "root-secret")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "job-secret")

    assert (
        module.main(
            [
                "--host",
                "localhost",
                "--port",
                "4064",
                "--job-user",
                "job-service",
            ]
        )
        == 0
    )

    assert admin.created_users[0][0] == "job-service"
    assert admin.created_users[0][1] == "job-secret"


def test_sync_memberships_skips_batch_call_when_memberships_are_current(
    helper_module, monkeypatch
):
    module = helper_module
    admin = FakeAdmin(
        groups=[FakeGroup(3, "users_private")],
        member_group_ids=[3],
    )
    module.BlitzGateway = FakeConnection(admin)
    monkeypatch.setenv("ROOTPASS", "root-secret")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "job-secret")

    assert (
        module.main(
            [
                "--host",
                "localhost",
                "--port",
                "4064",
                "--job-user",
                "job-service",
            ]
        )
        == 0
    )
    assert admin.added_groups == []


def test_ensure_job_user_handles_create_race(helper_module):
    module = helper_module
    admin = FakeAdmin(
        groups=[],
        member_group_ids=[],
        existing_user=False,
        create_exception=FakeValidationException("already exists"),
    )

    experimenter = module.ensure_job_user(admin, "job-service", "secret", retries=1)

    assert experimenter.omeName.val == "job-service"
    assert admin.lookup_calls == 2


def test_ensure_job_user_retries_and_reports_last_failure(helper_module, monkeypatch):
    module = helper_module
    admin = FakeAdmin(
        groups=[],
        member_group_ids=[],
        existing_user=False,
        create_exception=RuntimeError("database busy"),
    )
    sleeps: list[int] = []
    monkeypatch.setattr(module.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="failed to ensure OMERO user"):
        module.ensure_job_user(admin, "job-service", "secret", retries=2)

    assert sleeps == [2]


def test_main_reports_failed_connection(helper_module, monkeypatch, capsys):
    module = helper_module
    module.BlitzGateway = FakeConnection(FakeAdmin([], []), connect_result=False)
    monkeypatch.setenv("ROOTPASS", "root-secret")
    monkeypatch.setenv("OMERO_JOB_SERVICE_PASS", "job-secret")

    rc = module.main(["--host", "localhost", "--port", "4064", "--job-user", "job"])

    assert rc == 1
    assert "failed to connect to OMERO" in capsys.readouterr().err


def test_main_rejects_invalid_positive_counts(helper_module):
    module = helper_module

    with pytest.raises(SystemExit):
        module.main(["--host", "localhost", "--port", "0", "--job-user", "job"])

    with pytest.raises(SystemExit):
        module.main(
            [
                "--host",
                "localhost",
                "--port",
                "4064",
                "--job-user",
                "job",
                "--user-retries",
                "0",
            ]
        )


def test_script_entrypoint_exits_through_main(helper_module, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [str(HELPER_PATH), "--host", "localhost", "--port", "0", "--job-user", "job"],
    )

    with pytest.raises(SystemExit):
        runpy.run_path(str(HELPER_PATH), run_name="__main__")
