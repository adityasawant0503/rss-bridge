.PHONY: install test data figures reproduce

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

data:
	bash data/fetch_data.sh

figures:
	python scripts/make_figures.py

reproduce: data figures
	python scripts/nifty_hedge_backtest.py --csv data/nifty50_index.csv
