"""Deployment contracts for offline issuance and least-privilege TLS mounts."""

import json
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]


def compose():
    """Inputs: tracked Compose. Output: topology without operator env rendering."""
    return yaml.safe_load((REPO / "docker-compose.yml").read_text())


def test_authority_is_offline_and_has_no_application_or_docker_mounts():
    """Inputs: issuer topology. Output: only dedicated PKI volumes are writable."""
    service = compose()["services"]["internal-tls"]
    assert service["network_mode"] == "none"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert set(service["cap_add"]) == {"CHOWN", "DAC_OVERRIDE", "FOWNER"}
    assert "no-new-privileges:true" in service["security_opt"]
    writable = [mount for mount in service["volumes"] if not mount.endswith(":ro")]
    assert len(writable) == 7
    assert all(mount.startswith("internal-tls-") for mount in writable)
    assert all(":/pki/" in mount for mount in writable)
    assert "check" in service["healthcheck"]["test"]


def test_image_healthcheck_matches_the_deployed_certificate_check():
    """Inputs: image and Compose probes. Output: both verify the same persisted PKI."""
    source = (REPO / "docker/internal-tls.Dockerfile").read_text()
    healthcheck = source.split("HEALTHCHECK ", 1)[1].split("ENTRYPOINT ", 1)[0]
    command = json.loads(healthcheck.split("CMD ", 1)[1].strip())
    deployed = compose()["services"]["internal-tls"]["healthcheck"]
    assert ["CMD", *command] == deployed["test"]
    assert "--interval=30s" in healthcheck
    assert "--timeout=10s" in healthcheck
    assert "--start-period=30s" in healthcheck
    assert "--retries=3" in healthcheck


def test_every_server_has_only_its_own_private_key_and_readonly_public_trust():
    """Inputs: service mounts. Output: no client receives CA or other service keys."""
    document = compose()
    identities = json.loads((REPO / "monitoring/tls/identities.json").read_text())
    services = document["services"]
    for identity in identities:
        name = identity["name"]
        mounts = services[name]["volumes"]
        own_volume = "internal-tls-" + name.replace("_", "-")
        assert own_volume in document["volumes"]
        assert f"{own_volume}:/run/omero-tls/server:ro" in mounts
        assert "internal-tls-trust:/run/omero-tls/trust:ro" in mounts
    for name, service in services.items():
        if name == "internal-tls":
            continue
        for mount in service.get("volumes", []):
            if isinstance(mount, str) and mount.startswith("internal-tls-"):
                assert mount.endswith(":ro")
                assert not mount.startswith("internal-tls-authority:")
                if mount.startswith("internal-tls-trust:"):
                    continue
                assert mount.startswith("internal-tls-" + name.replace("_", "-") + ":")


def test_python_clients_and_exporters_receive_explicit_trust():
    """Inputs: client settings. Output: explicit trust limited to intended consumers."""
    services = compose()["services"]
    assert services["omeroweb"]["environment"]["ADMIN_TOOLS_TLS_CA_FILE"] == (
        "/run/omero-tls/trust/ca-bundle.pem"
    )
    for name in ("postgres-exporter", "postgres-exporter-plugin", "pg-maintenance"):
        assert services[name]["environment"]["PGSSLROOTCERT"] == (
            "/run/omero-tls/trust/ca.pem"
        )
        assert "internal-tls-trust:/run/omero-tls/trust:ro" in services[name]["volumes"]
    assert services["pg-maintenance"]["environment"]["PGSSLMODE"] == "verify-full"


def test_tls_runtime_lockfile_has_automated_dependency_updates():
    """Inputs: dependency configuration. Output: locked and update-tracked TLS runtime."""
    updates = yaml.safe_load((REPO / ".github/dependabot.yml").read_text())["updates"]
    assert any(
        update["package-ecosystem"] == "pip"
        and update["directory"] == "/monitoring/tls"
        for update in updates
    )
    dockerfile = (REPO / "docker/internal-tls.Dockerfile").read_text()
    assert "--require-hashes" in dockerfile
    assert "monitoring/tls/requirements.txt" in dockerfile
    assert "USER 65532:65532" in dockerfile


def test_tls_image_installs_the_patched_distribution_zlib():
    """Inputs: TLS image recipe. Output: base-image zlib is explicitly upgraded."""
    dockerfile = (REPO / "docker/internal-tls.Dockerfile").read_text()
    assert "ARG ZLIB_APK_VERSION=1.3.2-r1\n" in dockerfile
    install = dockerfile.split("RUN apk add --no-cache ", 1)[1].split("\nCOPY ", 1)[0]
    assert '"zlib=${ZLIB_APK_VERSION}"' in install


def test_tls_code_directories_remain_traversable_by_the_default_user():
    """Inputs: immutable code copies. Output: non-root imports can traverse parents."""
    dockerfile = (REPO / "docker/internal-tls.Dockerfile").read_text()
    permissions = "chmod 0555 /app/monitoring /app/monitoring/tls /etc/omero-tls"
    assert (
        dockerfile.index("COPY --chmod=0444 monitoring/tls/*.py")
        < (dockerfile.index(permissions))
        < dockerfile.index("USER 65532:65532")
    )
    assert "chmod 0700 /pki/private" in dockerfile
