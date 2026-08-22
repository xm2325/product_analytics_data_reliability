.PHONY: install reference validate test check clean

install:
	python -m pip install -r requirements.txt
	python -m pip install -e .

reference:
	python scripts/run_workbench.py --output-dir build/reference

validate:
	python scripts/validate_build.py build/reference

test:
	pytest -q

check: test reference validate

clean:
	rm -rf build .pytest_cache
