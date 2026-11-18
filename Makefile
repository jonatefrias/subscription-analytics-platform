# Local workflow. Everything runs on DuckDB; no cloud account needed.
PY      := .venv/bin/python
DBT     := cd transform && DBT_PROFILES_DIR=. ../.venv/bin/dbt
SCALE   ?= 1.0
PY_SRC  := generator scripts orchestration semantic_agent analysis notebooks tests

.PHONY: setup data deps build test metrics orchestrate test-orchestration lint review readout docs clean

setup:            ## create the virtualenv and install pinned dependencies
	python3.11 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

data:             ## generate the synthetic raw layer (SCALE=0.2 for a quick run)
	$(PY) generator/generate.py --out data/raw --scale $(SCALE)

deps:
	$(DBT) deps

build: deps       ## run and test every model, seed and snapshot
	$(DBT) build

test:
	$(DBT) test

metrics:          ## validate the semantic layer and reconcile it with the marts
	cd transform && DBT_PROFILES_DIR=. ../.venv/bin/mf validate-configs && DBT_PROFILES_DIR=. ../.venv/bin/python ../scripts/check_semantic_layer.py

orchestrate:      ## open the Dagster UI with the full asset graph (http://localhost:3000)
	.venv/bin/dagster dev -m orchestration.definitions

test-orchestration: ## load the code location and run daily_refresh end to end on a temp copy
	.venv/bin/python -m pytest

lint:             ## sqlfluff (SQL through dbt) and ruff (Python)
	.venv/bin/ruff check $(PY_SRC) && .venv/bin/ruff format --check $(PY_SRC)
	cd transform && DBT_PROFILES_DIR=. ../.venv/bin/sqlfluff lint models tests macros

review:           ## print the AI review prompt for this branch (no API call); drop --dry-run to send it
	.venv/bin/python scripts/ai_review.py --base origin/main --dry-run

readout:          ## re-run the experiment readout notebook against the local warehouse, keeping its outputs
	.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/paywall_experiment_readout.ipynb

docs:             ## generate and serve the dbt docs site
	$(DBT) docs generate && $(DBT) docs serve

clean:
	rm -rf data transform/target transform/dbt_packages
