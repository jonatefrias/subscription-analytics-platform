# Local workflow. Everything runs on DuckDB; no cloud account needed.
PY      := .venv/bin/python
DBT     := cd transform && DBT_PROFILES_DIR=. ../.venv/bin/dbt
SCALE   ?= 1.0

.PHONY: setup data deps build test docs clean

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

docs:             ## generate and serve the dbt docs site
	$(DBT) docs generate && $(DBT) docs serve

clean:
	rm -rf data transform/target transform/dbt_packages
