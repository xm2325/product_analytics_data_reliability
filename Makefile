.PHONY: install reference validate validate-watermark validate-uncertainty validate-evidence validate-experiment validate-reference validate-static-claims test check clean

install:
	python -m pip install -r requirements.txt
	python -m pip install -e .

reference:
	python scripts/run_workbench.py --output-dir build/reference

validate:
	python scripts/validate_build.py build/reference

validate-watermark:
	python scripts/validate_watermark_backtest.py build/reference

validate-uncertainty:
	python scripts/validate_uncertainty_certification.py build/reference

validate-evidence:
	python scripts/validate_evidence_plan.py build/reference

validate-experiment:
	python scripts/validate_pricing_experiment.py build/reference

validate-reference:
	python scripts/validate_reference_claims.py build/reference

validate-static-claims:
	python scripts/validate_static_claim_ledger.py build/reference

test:
	pytest -q

check: test reference validate validate-watermark validate-uncertainty validate-evidence validate-experiment validate-reference validate-static-claims

clean:
	rm -rf build .pytest_cache
