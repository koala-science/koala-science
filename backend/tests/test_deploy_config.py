"""
Guards the v0/v1 split in the production deployment config.

The archive (`coalescence` + the `koalascience-storage` bucket) and the
iteration platform (`coalescence_v1` + `koalascience-storage-v1`) are served by
two stacks sharing one VM. The catastrophic failure mode is a v1 service
resolving to archive state and writing into the evidence, so these tests parse
the real deploy files and assert the invariants that keep the two apart.
"""
from pathlib import Path

import pytest
import yaml

DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "docker"
ARCHIVE_DB = "coalescence"
ITERATION_DB = "coalescence_v1"
ARCHIVE_BUCKET = "koalascience-storage"
ITERATION_BUCKET = "koalascience-storage-v1"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY_DIR / "docker-compose.prod.yml").read_text())


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return (DEPLOY_DIR / "Caddyfile").read_text()


def _environment(service: dict) -> dict[str, str]:
    """Compose allows both list and mapping forms for `environment`."""
    env = service.get("environment", {})
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return env


def _database_of(service: dict) -> str | None:
    url = _environment(service).get("DATABASE_URL")
    return url.rsplit("/", 1)[-1] if url else None


def _services(compose: dict, *, v0: bool) -> dict[str, dict]:
    return {
        name: service
        for name, service in compose["services"].items()
        if name.endswith("-v0") is v0
    }


def _db_backed_services(compose: dict, *, v0: bool) -> dict[str, dict]:
    """
    Services that reach Postgres: either they load the VM's .env, which names
    the archive database, or they declare a connection of their own.
    """
    return {
        name: service
        for name, service in _services(compose, v0=v0).items()
        if "env_file" in service or "DATABASE_URL" in _environment(service)
    }


def _v0_block(caddyfile: str) -> str:
    _, _, after = caddyfile.partition("v0.koala.science")
    body, _, _ = after.partition("\n}")
    return body


def test_v1_services_that_load_env_pin_the_iteration_database(compose):
    """
    `env_file: .env` supplies the archive DATABASE_URL and POSTGRES_DB, and
    `assemble_db_connection` rebuilds the DSN from POSTGRES_DB whenever
    DATABASE_URL is unset. A v1 service must therefore override both, or it
    reaches the archive.
    """
    services = _db_backed_services(compose, v0=False)
    assert services, "expected at least one v1 service loading .env"
    for name, service in services.items():
        env = _environment(service)
        assert _database_of(service) == ITERATION_DB, (
            f"v1 service {name!r} does not pin DATABASE_URL to {ITERATION_DB!r}"
        )
        assert env.get("POSTGRES_DB") == ITERATION_DB, (
            f"v1 service {name!r} does not pin POSTGRES_DB to {ITERATION_DB!r}"
        )


def test_v1_services_write_to_the_iteration_bucket(compose):
    for name, service in _db_backed_services(compose, v0=False).items():
        assert _environment(service).get("GCS_STORAGE_BUCKET") == ITERATION_BUCKET, (
            f"v1 service {name!r} would write objects into the archive bucket"
        )


def test_v0_backend_uses_the_archive_database_and_bucket(compose):
    env = _environment(compose["services"]["backend-v0"])
    assert _database_of(compose["services"]["backend-v0"]) == ARCHIVE_DB
    assert env["POSTGRES_DB"] == ARCHIVE_DB
    assert env["GCS_STORAGE_BUCKET"] == ARCHIVE_BUCKET


def test_v1_and_v0_do_not_share_a_storage_volume(compose):
    def mounts(service):
        return {v.split(":", 1)[0] for v in service.get("volumes", [])}

    v1 = mounts(compose["services"]["backend"])
    v0 = mounts(compose["services"]["backend-v0"])
    assert v1 and v0
    assert not (v1 & v0), f"v1 and v0 share volumes: {v1 & v0}"


def test_v0_services_are_digest_pinned(compose):
    services = _services(compose, v0=True)
    assert services, "expected at least one -v0 service"
    for name, service in services.items():
        image = service["image"]
        assert "@sha256:" in image, f"{name} is not digest-pinned"
        assert ":latest" not in image, f"{name} still resolves a mutable tag"


def test_v0_has_no_writer_services(compose):
    assert set(_services(compose, v0=True)) == {"backend-v0", "frontend-v0"}
    for name, service in _services(compose, v0=True).items():
        labels = service.get("labels", {})
        assert not any(str(label).startswith("ofelia") for label in labels), (
            f"{name} carries ofelia cron labels; the archive must not run jobs"
        )


def test_v0_signups_are_disabled(compose):
    assert _environment(compose["services"]["backend-v0"])["SIGNUPS_ENABLED"] == "false"


def test_v0_redis_keyspace_is_separate(compose):
    v0_redis = _environment(compose["services"]["backend-v0"])["REDIS_URL"]
    v1_redis = _environment(compose["services"]["backend"])["REDIS_URL"]
    assert v0_redis != v1_redis


def test_each_frontend_talks_to_its_own_backend(compose):
    v1 = _environment(compose["services"]["frontend"])["INTERNAL_API_URL"]
    v0 = _environment(compose["services"]["frontend-v0"])["INTERNAL_API_URL"]
    assert v1 == "http://backend:8000/api/v1"
    assert v0 == "http://backend-v0:8000/api/v1"


def test_caddy_routes_the_public_hostnames_to_v1_services(caddyfile):
    block, _, _ = caddyfile.partition("v0.koala.science")
    assert "backend:8000" in block
    assert "frontend:3000" in block
    assert "backend-v0" not in block
    assert "frontend-v0" not in block


def test_archive_cannot_enqueue_onto_the_shared_temporal_queue(compose):
    """
    The task queue name is baked into the pinned digest and the only poller is
    the v1 worker, which runs against coalescence_v1. The archive must not
    reach the broker at all.
    """
    v0_host = _environment(compose["services"]["backend-v0"])["TEMPORAL_HOST"]
    v1_hosts = {
        _environment(s).get("TEMPORAL_HOST")
        for s in _db_backed_services(compose, v0=False).values()
    }
    assert v0_host not in v1_hosts


def test_archive_does_not_run_migrations(compose):
    """`alembic upgrade head` is the last automatic write path into the archive."""
    command = compose["services"]["backend-v0"]["command"]
    assert "alembic" not in " ".join(command)
    assert "uvicorn" in " ".join(command)


def test_caddy_routes_v0_hostname_to_v0_services(caddyfile):
    block = _v0_block(caddyfile)
    assert "backend-v0:8000" in block
    assert "frontend-v0:3000" in block
    assert "backend:8000" not in block
    assert "frontend:3000" not in block


def test_eval_service_is_gone(compose, caddyfile):
    assert "eval" not in compose["services"]
    assert "/eval" not in caddyfile
