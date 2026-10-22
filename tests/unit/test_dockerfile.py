"""Static checks of the Dockerfile (Docker is not available in CI or on the dev machine)."""

import re

from betting_ml.config import PROJECT_ROOT

DOCKERFILE = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")


DIGEST = r"@sha256:[0-9a-f]{64}"


def test_slim_non_root_image_serving_the_api() -> None:
    assert "USER app" in DOCKERFILE
    assert DOCKERFILE.index("USER app") > DOCKERFILE.index("RUN uv sync --frozen --no-dev\n")
    assert DOCKERFILE.index("USER app") < DOCKERFILE.index("CMD [")
    assert "EXPOSE 8000" in DOCKERFILE
    assert 'CMD ["betting-ml", "serve", "--host", "0.0.0.0", "--port", "8000"]' in DOCKERFILE


def test_every_base_image_is_pinned_by_digest() -> None:
    """Spec 003, T020: a tag can be moved to other content; a digest cannot."""
    images = re.findall(r"^FROM (\S+)|--from=(\S+)", DOCKERFILE, flags=re.MULTILINE)
    references = [a or b for a, b in images]
    assert len(references) == 2
    assert re.fullmatch(rf"python:3\.12\.\d+-slim{DIGEST}", references[0])
    assert re.fullmatch(rf"ghcr\.io/astral-sh/uv:[\d.]+{DIGEST}", references[1])


def test_the_code_is_not_writable_by_the_app_user() -> None:
    chown = next(line for line in DOCKERFILE.splitlines() if "chown" in line)
    assert "chown app:app /app/data /app/models /app/reports" in chown
    assert "-R" not in chown and "/app\n" not in chown


def test_healthcheck_uses_the_allowed_host() -> None:
    assert (
        'HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD ["betting-ml", "healthcheck"]'
        in DOCKERFILE
    )


def test_secrets_and_data_are_not_copied() -> None:
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in (".env", "data", "models", ".git", ".venv"):
        assert entry in ignored
    assert "COPY .env" not in DOCKERFILE


def test_makefile_has_docker_target() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker build -t betting-ml:latest ." in makefile


def test_the_api_does_not_trust_forwarded_headers_by_itself() -> None:
    """Spec 003, T010/T020: X-Forwarded-For chooses the client IP of the login lockout, so it
    is believed only from FORWARDED_ALLOW_IPS (``betting-ml serve``), never from the image."""
    assert "--proxy-headers" not in DOCKERFILE
    assert "--forwarded-allow-ips" not in DOCKERFILE
    assert "FORWARDED_ALLOW_IPS=" not in DOCKERFILE  # never set in the image
