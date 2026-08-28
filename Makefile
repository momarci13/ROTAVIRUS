# Reproducible pipeline entry points. On Windows install GNU Make (e.g. via
# `winget install GnuWin32.Make` or Git-for-Windows' `make`), or run the
# equivalent `python -m scraper.<cmd>` shown under each target.

PY ?= python
PIP ?= $(PY) -m pip

.PHONY: setup collect validate panel costs allocate report test lint typecheck all clean

setup:                       ## Install the package (base + dev extras) in editable mode
	$(PIP) install -e ".[dev]"
	@echo "Optional extras: $(PIP) install -e \".[pdf,spatial,render,era5,bayes]\""

collect:                     ## Run every collector: discover -> fetch -> parse -> validate
	$(PY) -m scraper.run --all

validate:                    ## Run the full validation rule-set over intermediate/processed tables
	$(PY) -m scraper.validate --all

geo:                         ## Build the canonical district / settlement registry
	$(PY) -m scraper.geography build

panel:                       ## Assemble the county weekly panel and the modelled district panel
	$(PY) -m scraper.process panel --resolution county
	$(PY) -m scraper.process panel --resolution district

costs:                       ## Resolve cost parameters (fails loudly on missing required values)
	$(PY) -m scraper.costs resolve

allocate:                    ## Run all allocation scenarios and the equity comparison
	$(PY) -m scraper.allocate --all-scenarios --compare

report:                      ## Regenerate the data dictionary and the availability matrix
	$(PY) -m scraper.report dictionary
	$(PY) -m scraper.report availability

test:                        ## Run the test suite with coverage (geography/validation/costs/allocation, target >=85%)
	$(PY) -m pytest --cov --cov-report=term-missing --cov-fail-under=85

lint:                        ## ruff
	$(PY) -m ruff check .

typecheck:                   ## mypy
	$(PY) -m mypy src

all: setup geo collect validate panel costs allocate report test

clean:                       ## Remove caches (keeps data/raw and data/metadata)
	rm -rf .cache .requests_cache.sqlite .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
