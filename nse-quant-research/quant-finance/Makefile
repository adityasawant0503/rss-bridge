.PHONY: install test data figures reproduce

install:
	pip install -e ".[dev,data]"

test:
	python -m pytest -q

data:
	bash data/fetch_data.sh

figures:
	python scripts/make_figures.py

# Re-run every analysis in the README on the downloaded data
reproduce: data figures
	python scripts/var_backtest.py --csv data/nifty50_index.csv
	python scripts/monte_carlo_var.py --dir data/nifty50_stocks
	python scripts/ma_sweep.py --csv data/nifty50_index.csv
	python scripts/pairs_scan.py --dir data/nifty50_stocks
