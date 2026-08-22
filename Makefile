.PHONY: install reference validate validate-reference test check clean

install:
	python -m pip install -r requirements.txt
	python -m pip install -e .

reference:
	python scripts/run_workbench.py --output-dir build/reference

validate:
	python scripts/validate_build.py build/reference

validate-reference:
	python scripts/validate_reference_claims.py build/reference

test:
	pytest -q

check: test reference validate validate-reference

clean:
	rm -rf build .pytest_cache
