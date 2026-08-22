.PHONY: install reference test clean

install:
	python -m pip install -r requirements.txt
	python -m pip install -e .

reference:
	python scripts/run_workbench.py --output-dir build/reference

test:
	pytest -q

clean:
	rm -rf build .pytest_cache
