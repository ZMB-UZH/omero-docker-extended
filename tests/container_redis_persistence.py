"""Actual Redis lifecycle tests, invoked explicitly by the container gate."""

from __future__ import annotations

import json
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import uuid

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def redis_factory():
    """Inputs: a Linux Docker engine. Output: isolated containers and owned-volume cleanup."""
    docker = shutil.which("docker")
    assert docker, "Container tests require Docker."
    service = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"][
        "redis"
    ]
    containers, volumes = [], []

    def command(*args, input=None, timeout=60, binary=False):
        """Inputs: Docker arguments and optional fixture bytes. Output: checked command text."""
        result = subprocess.run(
            [docker, *args],
            input=input,
            text=not binary,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
        return result.stdout if binary else result.stdout.strip()

    def create(*, legacy=False, volume=None, start=True):
        """Inputs: storage mode. Output: a new isolated Redis instance without published ports."""
        if not legacy and volume is None:
            volume = "redis-persistence-test-" + uuid.uuid4().hex
            command("volume", "create", volume)
            volumes.append(volume)
        storage = (
            ["--tmpfs", "/data"]
            if legacy
            else ["--mount", f"type=volume,source={volume},target=/data"]
        )
        identifier = command(
            "create",
            "--network",
            "none",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,source={ROOT / 'docker/redis-healthcheck.sh'},target=/healthcheck.sh,readonly",
            *storage,
            service["image"],
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no" if legacy else "yes",
            "--maxmemory",
            "16mb",
            "--maxmemory-policy",
            "allkeys-lru" if legacy else "noeviction",
        )
        containers.append(identifier)
        instance = RedisInstance(command, identifier, volume)
        if start:
            instance.start()
        return instance

    try:
        yield create
    finally:
        for identifier in reversed(containers):
            command("rm", "--force", identifier)
        for volume in reversed(volumes):
            command("volume", "rm", volume)


class RedisInstance:
    """A fixture-owned Redis process; no deployment discovery or live data access."""

    def __init__(self, command, identifier, volume):
        """Inputs: fixture command and owned objects. Output: isolated instance handle."""
        self.command, self.identifier, self.volume = command, identifier, volume

    def cli(self, *args, db=0, input=None):
        """Inputs: Redis arguments and fixture database. Output: parsed native JSON."""
        interactive = ["-i"] if input is not None else []
        text = self.command(
            "exec",
            *interactive,
            self.identifier,
            "redis-cli",
            "--json",
            "-e",
            "-n",
            str(db),
            *args,
            input=input,
        )
        return text if args[0] == "INFO" else json.loads(text)

    def start(self):
        """Inputs: created container. Output: a responding Redis process or explicit timeout."""
        self.command("start", self.identifier)
        deadline = time.monotonic() + 30
        while True:
            try:
                assert self.cli("PING") == "PONG"
                return
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    def persistence_ready(self):
        """Inputs: running instance. Output: AOF creation completed successfully."""
        deadline = time.monotonic() + 30
        while True:
            info = self.cli("INFO", "persistence")
            fields = dict(
                line.split(":", 1) for line in info.splitlines() if ":" in line
            )
            if (
                fields.get("aof_rewrite_in_progress")
                == fields.get("aof_rewrite_scheduled")
                == "0"
            ):
                assert fields["aof_enabled"] == "1"
                assert fields["aof_last_bgrewrite_status"] == "ok"
                assert fields["aof_last_write_status"] == "ok"
                return
            assert time.monotonic() < deadline, "AOF rewrite did not finish."
            time.sleep(0.1)

    def health(self):
        """Inputs: running instance. Output: execution of the exact mounted product health check."""
        return self.command("exec", self.identifier, "sh", "/healthcheck.sh")

    def snapshot(self):
        """Inputs: deterministic fixture databases. Output: values and absolute expirations."""
        return {
            (db, key): (
                self.cli("GET", key, db=db),
                self.cli("PEXPIRETIME", key, db=db),
            )
            for db in (0, 1, 2)
            for key in self.cli("KEYS", "fixture:*", db=db)
        }


def seed(instance):
    """Inputs: isolated instance. Output: expiring and durable fixtures in three databases."""
    for db in (0, 1, 2):
        assert (
            instance.cli(
                "SET",
                "fixture:session",
                f"original-session-{db}",
                "PX",
                "3600000",
                db=db,
            )
            == "OK"
        )
        assert instance.cli("SET", "fixture:work", f"queued-work-{db}", db=db) == "OK"
    return instance.snapshot()


def test_fresh_instance_survives_restart_replacement_and_memory_pressure(redis_factory):
    """Inputs: actual AOF Redis. Output: original sessions survive lifecycle and denied writes."""
    instance = redis_factory()
    before = seed(instance)
    instance.persistence_ready()
    instance.health()
    instance.command("restart", "--time", "30", instance.identifier)
    instance.persistence_ready()
    assert instance.snapshot() == before
    instance.command("stop", "--time", "30", instance.identifier)
    replacement = redis_factory(volume=instance.volume)
    replacement.persistence_ready()
    assert replacement.snapshot() == before
    for number in range(128):
        try:
            replacement.cli("-x", "SET", f"pressure:{number}", input="x" * 262144)
        except subprocess.CalledProcessError as error:
            assert "OOM" in error.stdout + error.stderr
            break
    else:
        pytest.fail("The isolated memory limit did not reject excess writes.")
    assert replacement.snapshot() == before
    assert "evicted_keys:0" in replacement.cli("INFO", "stats").splitlines()
    replacement.health()


def test_legacy_tmpfs_migration_preserves_values_and_absolute_expiry(
    redis_factory, tmp_path
):
    """Inputs: legacy volatile Redis. Output: complete AOF migration without extending session lifetime."""
    legacy = redis_factory(legacy=True)
    before = seed(legacy)
    with pytest.raises(subprocess.CalledProcessError):
        legacy.health()
    assert legacy.cli("CONFIG", "SET", "appendonly", "yes") == "OK"
    assert legacy.cli("CONFIG", "SET", "appendfsync", "always") == "OK"
    assert legacy.cli("CONFIG", "SET", "auto-aof-rewrite-percentage", "0") == "OK"
    legacy.persistence_ready()
    # A stopped container loses its tmpfs. Copy while writes/expiry are paused,
    # with AOF fsynced and no background rewrite able to replace its manifest.
    assert legacy.cli("CLIENT", "PAUSE", "120000", "WRITE") == "OK"
    paused_at = time.monotonic()
    archive = legacy.command(
        "exec", legacy.identifier, "tar", "-C", "/data", "-cf", "-", ".", binary=True
    )
    (tmp_path / "snapshot.tar").write_bytes(archive)
    assert time.monotonic() - paused_at < 60, "Snapshot exceeded its safe pause window."
    with tarfile.open(fileobj=io.BytesIO(archive)) as snapshot:
        assert any(
            member.name.endswith(".manifest") for member in snapshot.getmembers()
        ), "Multipart AOF manifest was not retained."
    replacement = redis_factory(start=False)
    replacement.command(
        "cp", "-", f"{replacement.identifier}:/data", input=archive, binary=True
    )
    replacement.start()
    replacement.persistence_ready()
    replacement.health()
    assert replacement.snapshot() == before

    legacy.command("stop", "--time", "30", legacy.identifier)
    assert replacement.snapshot() == before


@pytest.mark.parametrize(
    ("setting", "value"), [("appendonly", "no"), ("maxmemory-policy", "allkeys-lru")]
)
def test_health_rejects_unsafe_runtime_configuration(redis_factory, setting, value):
    """Inputs: live persistence/eviction regression. Output: unhealthy rather than a false-ready ping."""
    instance = redis_factory()
    instance.persistence_ready()
    instance.health()
    assert instance.cli("CONFIG", "SET", setting, value) == "OK"
    with pytest.raises(subprocess.CalledProcessError):
        instance.health()
