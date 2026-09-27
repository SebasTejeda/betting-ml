# Comandos del proyecto (ver plan.md §8). Todos delegan en `uv run` y en la CLI `betting-ml`.
.PHONY: backtest-002 backtest-002-final setup lint test data baselines exp select holdout report train-prod serve track docker all

UV ?= uv
RUN = $(UV) run
CLI = $(RUN) betting-ml
# Experimentos corridos (E10, E11, E13-E15 no se corrieron por la regla de parada).
EXPERIMENTS ?= E02 E03 E04 E05 E06 E07 E08 E09 E12

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
	$(CLI) report

train-prod:
	$(CLI) train-prod

serve:
	$(CLI) serve --host 0.0.0.0 --port 8000

track:
	$(CLI) track

docker:
	docker build -t betting-ml:latest .

# Reproduce la cadena sin sobrescribir resultados ya registrados (--skip-existing).
all: data
	$(CLI) exp E01 --skip-existing
	@for id in $(EXPERIMENTS); do $(CLI) exp $$id --skip-existing || exit 1; done
	$(CLI) select --skip-if-locked
	$(CLI) holdout --skip-if-done
	$(MAKE) report train-prod

# ---- Spec 002
backtest-002:
	$(CLI) backtest-002

backtest-002-final:
	$(CLI) backtest-002-final

backtest-002-report:
	$(CLI) backtest-002-report

db-upgrade:
	$(CLI) db-upgrade

odds:
	$(CLI) odds
