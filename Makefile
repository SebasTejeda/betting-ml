# Comandos del proyecto (ver plan.md §8). Todos delegan en `uv run` y en la CLI `betting-ml`.
.PHONY: setup lint test data baselines exp select holdout report train-prod serve track docker all

UV ?= uv
RUN = $(UV) run
CLI = $(RUN) betting-ml
EXPERIMENTS ?= E02 E03 E04 E05 E06 E07 E08 E09 E10 E11 E12 E13 E14 E15

setup:
	$(UV) sync --extra dev
	$(RUN) pre-commit install || echo "pre-commit no instalado (¿sin repo git?)"

lint:
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests
	$(RUN) mypy

test:
	$(RUN) pytest

data:
	$(CLI) data

baselines:
	$(CLI) exp E01

exp:
	$(CLI) exp $(ID)

select:
	$(CLI) select

holdout:
	$(CLI) holdout

report:
	@echo "pendiente"

train-prod:
	@echo "pendiente"

serve:
	@echo "pendiente"

track:
	@echo "pendiente"

docker:
	@echo "pendiente"

all: data baselines
	@for id in $(EXPERIMENTS); do $(MAKE) exp ID=$$id || exit 1; done
	$(MAKE) select
	$(CLI) holdout --skip-if-done
	$(MAKE) report train-prod
