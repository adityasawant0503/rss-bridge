# One-command workflows for the whole portfolio. Run `make help`.
PY ?= .venv/bin/python
.PHONY: help setup data test lint figures reproduce dashboard serve clean

help:
	@echo "make setup      create .venv and install both packages"
	@echo "make data       download the Nifty datasets"
	@echo "make test       run all tests (Python + dashboard JS check)"
	@echo "make lint       ruff lint"
	@echo "make reproduce  data + figures + every study, printed to the terminal"
	@echo "make dashboard  rebuild dashboard/data from both projects"
	@echo "make serve      open the dashboard at http://localhost:8000"

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt -e ./quant-finance -e ./options-lab

data:
	bash quant-finance/data/fetch_data.sh
	bash options-lab/data/fetch_data.sh

test:
	cd quant-finance && ../$(PY) -m pytest -q
	cd options-lab && ../$(PY) -m pytest -q
	@if [ -f dashboard/data/results.json ]; then node dashboard/test_lib.mjs; else echo "skip dashboard check: run make dashboard first"; fi

lint:
	$(PY) -m ruff check .

figures:
	cd quant-finance && ../$(PY) scripts/make_figures.py
	cd options-lab && ../$(PY) scripts/make_figures.py

reproduce: data figures
	cd quant-finance && ../$(PY) scripts/var_backtest.py --csv data/nifty50_index.csv
	cd quant-finance && ../$(PY) scripts/monte_carlo_var.py --dir data/nifty50_stocks
	cd quant-finance && ../$(PY) scripts/ma_sweep.py --csv data/nifty50_index.csv
	cd quant-finance && ../$(PY) scripts/pairs_scan.py --dir data/nifty50_stocks
	cd options-lab && ../$(PY) scripts/nifty_hedge_backtest.py --csv data/nifty50_index.csv

dashboard:
	$(PY) dashboard/build_data.py
	node dashboard/test_lib.mjs

serve: dashboard
	cd dashboard && ../$(PY) -m http.server 8000

clean:
	find . -name __pycache__ -o -name .pytest_cache -o -name "*.egg-info" | xargs rm -rf
