PYTHON ?= .venv/bin/python
PIPELINE = $(PYTHON) scripts/run_pipeline.py

.PHONY: setup ingest transform test forecast experiment causal dashboard all pytest lint clean

setup:
	uv venv --python 3.11 .venv
	uv pip install --python .venv/bin/python -e ".[dev]"

ingest:
	$(PIPELINE) ingest

transform:
	$(PIPELINE) transform

test:
	$(PIPELINE) test

forecast:
	$(PIPELINE) forecast

forecast-smoke:
	$(PIPELINE) forecast --smoke

experiment:
	$(PIPELINE) experiment

causal:
	$(PIPELINE) causal

dashboard:
	$(PYTHON) -m streamlit run dashboard/app.py --server.port 8501

all:
	$(PIPELINE) all

pytest:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check gridload dashboard scripts tests
	$(PYTHON) -m ruff format --check gridload dashboard scripts tests

clean:
	rm -rf dbt/target dbt/logs logs .pytest_cache .ruff_cache
