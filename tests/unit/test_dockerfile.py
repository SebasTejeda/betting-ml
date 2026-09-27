"""Static checks of the Dockerfile (Docker is not available in CI or on the dev machine)."""

from betting_ml.config import PROJECT_ROOT

DOCKERFILE = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_slim_non_root_image_serving_the_api() -> None:
    assert "FROM python:3.12-slim" in DOCKERFILE
    assert "USER app" in DOCKERFILE
    assert DOCKERFILE.index("USER app") > DOCKERFILE.index("RUN uv sync --frozen --no-dev\n")
    assert "EXPOSE 8000" in DOCKERFILE
    assert "betting_ml.api.main:app" in DOCKERFILE


def test_secrets_and_data_are_not_copied() -> None:
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in (".env", "data", "models", ".git", ".venv"):
        assert entry in ignored
    assert "COPY .env" not in DOCKERFILE


def test_makefile_has_docker_target() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker build -t betting-ml:latest ." in makefile
