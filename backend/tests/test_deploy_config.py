"""
Guards the deployment config, which CI otherwise never executes.

Two failure modes, both silent. The first is the v0/v1 split: the archive
(`coalescence` + the `koalascience-storage` bucket) and the iteration platform
(`coalescence_v1` + `koalascience-storage-v1`) are served by two stacks sharing
one VM, and a v1 service resolving to archive state would write into the
evidence.

The second is an unsupplied `${VAR}`. Compose does not fail on one — it
substitutes the empty string and warns where nobody is reading.
`verification-worker` shipped naming `${ANTHROPIC_API_KEY}` that no workflow
wrote to the VM's .env, and the check it powers sat pending forever while all
seven CI checks stayed green.

So these tests parse the real deploy files rather than a fixture, and assert
what only a deploy would otherwise discover.
"""
import re
import subprocess
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


# The .env keys provisioned by hand on the VM rather than by CI: the database
# credentials, the domain, the registry. A name belongs here only if someone
# put it on the VM — anything CI owns has to be written by the deploy workflow.
VM_PROVISIONED = frozenset({
    "COALESCENCE_REGISTRY", "DOMAIN", "POSTGRES_PASSWORD", "POSTGRES_SERVER",
    "POSTGRES_USER", "TEMPORAL_ADMIN_HASH", "TEMPORAL_UI_ADDRESS",
})

# Secrets the workflow writes but whose value may be empty. Distinct from
# NOT_REQUIRED_IN_PRODUCTION below, which is about names a deploy need not
# write at all: a name here is still written, just not asserted non-empty.
# HF_TOKEN is used only by scripts/ingest_hf.py, a manual ingest that falls back
# to anonymous access when it is unset. This cannot be derived — GEMINI_API_KEY
# and ANTHROPIC_API_KEY carry the same empty default in `config.py`; what
# separates them is that a running service reads those two.
# RESEND_API_KEY is here under protest and temporarily. Production needs it —
# unset, the verification mail is only logged, the account never redeems a
# password hash, and every login answers 401 "Invalid email or password".
# It is written but not asserted, so the deploy is not blocked while the
# account is set up; move it back to REQUIRED_IN_PRODUCTION once the secret
# exists, along with FRONTEND_URL and RESEND_FROM_EMAIL being correct.
OPTIONAL_SECRETS = frozenset({"HF_TOKEN", "RESEND_API_KEY"})

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

DEPLOYMENTS = [
    ("docker-compose.prod.yml", "deploy.yml"),
    ("docker-compose.staging.yml", "staging.yml"),
]


def _interpolated_without_default(compose_text: str) -> set[str]:
    """`${NAME}`, but not `${NAME:-fallback}` — a default needs no supplier."""
    return {
        name
        for name, default in re.findall(r"\$\{([A-Z][A-Z0-9_]*)(:?-[^}]*)?\}", compose_text)
        if not default
    }


def _env_snippet_script(workflow_text: str) -> str:
    """
    The one shell script that builds the .env snippet.

    Each `run:` block is its own shell, so a guard in a neighbouring step —
    or, worse, a neighbouring job — protects nothing. Everything asserted about
    writing .env has to be asserted about this script and no other text.
    """
    scripts = [
        step["run"]
        for job in yaml.safe_load(workflow_text)["jobs"].values()
        for step in job["steps"]
        if "> /tmp/env.snippet" in step.get("run", "")
    ]
    assert len(scripts) == 1, (
        f"expected exactly one step to build the snippet, found {len(scripts)}"
    )
    return scripts[0]


def _written_by_workflow(snippet_script: str) -> set[str]:
    """The names the deploy step appends to the VM's .env, per its printf format."""
    return set(re.findall(r"([A-Z][A-Z0-9_]*)=%s", snippet_script))


def _deleted_by_workflow(workflow_text: str) -> set[str]:
    """
    The names the deploy step strips from .env before appending.

    Unscoped, unlike the helpers above, because the `sed` runs in the step that
    ships the snippet rather than the one that builds it. Nothing is lost: a
    misplaced strip leaves duplicate .env lines, which Compose resolves
    last-wins, rather than a service starting without its key.
    """
    match = re.search(r"sed -i -E '/\^\[\[:space:\]\]\*\(([^)]+)\)", workflow_text)
    assert match, "could not find the .env-stripping sed line; has it been reformatted?"
    return set(match.group(1).split("|"))


def _written(workflow_name: str) -> set[str]:
    workflow_text = (WORKFLOWS_DIR / workflow_name).read_text()
    return _written_by_workflow(_env_snippet_script(workflow_text))


def _all_interpolated() -> set[str]:
    return set().union(*(
        _interpolated_without_default((DEPLOY_DIR / compose_name).read_text())
        for compose_name, _ in DEPLOYMENTS
    ))


@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_every_interpolated_variable_has_a_supplier(compose_name, workflow_name):
    compose_text = (DEPLOY_DIR / compose_name).read_text()
    workflow_text = (WORKFLOWS_DIR / workflow_name).read_text()

    referenced = _interpolated_without_default(compose_text)
    assert referenced, f"expected {compose_name} to interpolate something"

    unsupplied = referenced - _written(workflow_name) - VM_PROVISIONED
    assert not unsupplied, (
        f"{compose_name} interpolates {sorted(unsupplied)}, which {workflow_name} "
        "never writes to the VM's .env and which is not provisioned by hand. "
        "Compose will substitute the empty string and the service will start "
        "misconfigured. Add it to the workflow's env snippet, or to VM_PROVISIONED."
    )


@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_the_workflow_strips_every_key_it_appends(compose_name, workflow_name):
    """Otherwise each deploy appends a second copy of the key to .env."""
    workflow_text = (WORKFLOWS_DIR / workflow_name).read_text()
    written = _written(workflow_name)
    assert written, f"expected {workflow_name} to write an env snippet"
    missing = written - _deleted_by_workflow(workflow_text)
    assert not missing, (
        f"{workflow_name} appends {sorted(missing)} to .env without first "
        "deleting the previous value"
    )


@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_the_workflow_refuses_to_deploy_an_empty_secret(compose_name, workflow_name):
    """
    An unset secret is not a build failure: `printf` writes a bare `NAME=` and
    Compose substitutes the empty string, which is how the verification worker
    shipped without a key. The name being in the format string proves nothing
    about the value, so each one is asserted non-empty in the same shell that
    writes it.
    """
    script = _env_snippet_script((WORKFLOWS_DIR / workflow_name).read_text())
    for name in _written(workflow_name) - OPTIONAL_SECRETS:
        assert f'"${{{name}:?' in script, (
            f"{workflow_name} writes {name} to .env without first asserting it "
            "is non-empty; a missing secret would deploy silently misconfigured"
        )


# Settings the running platform reads from the VM's .env, which no compose file
# interpolates — so the `${VAR}` guard above cannot see them. Each is a feature
# that fails closed when unset, and each has silently shipped that way.
# Enforced against staging too: it runs the same signup and check code.
REQUIRED_IN_PRODUCTION = frozenset({
    "GEMINI_API_KEY",       # moderation, validity, relevance, uniqueness
    "ANTHROPIC_API_KEY",    # the verification check
    "OPENREVIEW_USERNAME",  # the profile lookup every signup makes
    "OPENREVIEW_PASSWORD",
})

# Settings a deploy may legitimately leave empty, and why.
NOT_REQUIRED_IN_PRODUCTION = frozenset({
    "GCS_STORAGE_BUCKET",   # every v1 service pins it in the compose file
    "HF_TOKEN",             # see OPTIONAL_SECRETS
    "OPENREVIEW_TOKEN",     # short-lived alternative to the username/password
    "ORCID_CLIENT_ID",      # a post-signup linking flow that 501s when unset
    "ORCID_CLIENT_SECRET",
    "RESEND_API_KEY",       # temporary; see OPTIONAL_SECRETS
})

assert REQUIRED_IN_PRODUCTION.isdisjoint(OPTIONAL_SECRETS), (
    "a setting cannot be both required and allowed to be empty"
)


def test_required_settings_are_real_settings():
    """A renamed or misspelled setting would otherwise be guarded in name only."""
    from app.core.config import Settings

    unknown = REQUIRED_IN_PRODUCTION - set(Settings.model_fields)
    assert not unknown, f"REQUIRED_IN_PRODUCTION names {sorted(unknown)}, absent from Settings"


def test_every_credential_setting_is_classified():
    """
    The list above cannot catch what nobody adds to it — which is exactly how
    the OpenReview pair reached production unset. Every setting that defaults to
    empty has to be called required or explicitly not, so a new credential
    cannot be introduced without someone deciding which it is.
    """
    from app.core.config import Settings

    candidates = {
        name for name, field in Settings.model_fields.items()
        if field.annotation is str and field.default == ""
    }
    unclassified = candidates - REQUIRED_IN_PRODUCTION - NOT_REQUIRED_IN_PRODUCTION
    assert not unclassified, (
        f"{sorted(unclassified)} default to empty but are listed neither as "
        "required in production nor as safe to leave unset"
    )


@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_the_workflow_supplies_every_setting_production_needs(compose_name, workflow_name):
    """
    The `${VAR}` guard only sees what Compose interpolates. Anything the app
    reads from .env itself is invisible to it, which is how the OpenReview
    credentials reached production unset.
    """
    missing = REQUIRED_IN_PRODUCTION - _written(workflow_name)
    assert not missing, (
        f"{workflow_name} does not write {sorted(missing)} to the VM's .env. "
        "The setting will be empty and the feature that reads it will fail closed."
    )


def _password_guard(script: str) -> str:
    """The shape check itself, so a test can run it rather than describe it."""
    match = re.search(r'(case "\$OPENREVIEW_PASSWORD".*?esac)', script, re.DOTALL)
    assert match, "no OPENREVIEW_PASSWORD shape guard in the snippet step"
    return match.group(1)


@pytest.mark.parametrize("value,accepted", [
    ("goodpassword123", True),
    ("Str0ng-p_ass.w0rd!", True),
    ("has space", False),
    ("has$dollar", False),
    ("has#hash", False),
    ("trailing ", False),
])
@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_the_workflow_rejects_a_value_the_env_parser_would_mangle(
    compose_name, workflow_name, value, accepted
):
    """
    The VM's .env is read by compose-go, not python-dotenv: it expands `$VAR`
    in unquoted values and strips inline `#`. A password is the first
    user-chosen value here, and a mangled one logs into OpenReview as a wrong
    password — which surfaces as the same 503 this guard exists to prevent.

    Runs the guard rather than matching its text: a `case` reduced to `*) ;;`
    reads the same and protects nothing.
    """
    guard = _password_guard(_env_snippet_script((WORKFLOWS_DIR / workflow_name).read_text()))
    result = subprocess.run(
        ["bash", "-c", guard],
        env={"OPENREVIEW_PASSWORD": value},
        capture_output=True,
    )
    assert (result.returncode == 0) is accepted, (
        f"{workflow_name} {'rejected' if accepted else 'accepted'} {value!r}"
    )


def _resend_alarm(script: str) -> str:
    """The non-blocking warning, so a test can run it rather than describe it."""
    match = re.search(r'(if \[ -z "\$RESEND_API_KEY" \].*?\n *fi)', script, re.DOTALL)
    assert match, "no RESEND_API_KEY alarm in the snippet step"
    return match.group(1)


@pytest.mark.parametrize("value,warns", [("", True), ("re_livekey", False)])
@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_the_workflow_warns_while_resend_is_unset(
    compose_name, workflow_name, value, warns
):
    """
    RESEND_API_KEY is exempt from the non-empty guard so a missing secret does
    not block the deploy, but production signup is broken until it exists —
    every login answers 401. A comment cannot say so on the deploy that ships
    it, and cannot fall silent once the secret arrives. This can do both.
    """
    alarm = _resend_alarm(_env_snippet_script((WORKFLOWS_DIR / workflow_name).read_text()))
    result = subprocess.run(
        ["bash", "-c", alarm],
        env={"RESEND_API_KEY": value},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "the alarm must never block the deploy"
    assert ("::warning::" in result.stdout) is warns, result.stdout


def test_vm_provisioned_lists_nothing_stale():
    """
    A name here is a standing claim that someone put it on the VM. One that no
    compose file interpolates pre-authorises a variable nobody has checked.
    """
    stale = VM_PROVISIONED - _all_interpolated()
    assert not stale, f"VM_PROVISIONED names {sorted(stale)}, which nothing interpolates"


@pytest.mark.parametrize("compose_name,workflow_name", DEPLOYMENTS)
def test_optional_secrets_lists_nothing_stale(compose_name, workflow_name):
    """An exemption for a key the workflow no longer writes exempts nothing."""
    written = _written(workflow_name)
    assert OPTIONAL_SECRETS <= written, (
        f"OPTIONAL_SECRETS names {sorted(OPTIONAL_SECRETS - written)}, which "
        f"{workflow_name} does not write to .env"
    )
