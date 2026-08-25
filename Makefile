.PHONY: install reference validate validate-forecast validate-migration validate-watermark validate-uncertainty validate-evidence validate-experiment validate-impact validate-reference validate-static-claims real-reference real-validate real-static-claims real-check incremental-reference incremental-validate incremental-static-claims reporting-reference reporting-validate incremental-check test check clean

install:
	python -m pip install -r requirements.txt
	python -m pip install -e .

reference:
	python scripts/build_reference.py --output-dir build/reference

validate:
	python scripts/validate_build.py build/reference

validate-forecast:
	python scripts/validate_forecast_plan.py build/reference

validate-migration:
	python scripts/validate_contract_migration.py build/reference

validate-watermark:
	python scripts/validate_watermark_backtest.py build/reference

validate-uncertainty:
	python scripts/validate_uncertainty_certification.py build/reference

validate-evidence:
	python scripts/validate_evidence_plan.py build/reference

validate-experiment:
	python scripts/validate_pricing_experiment.py build/reference

validate-impact:
	python scripts/validate_impact_plan.py build/reference

validate-reference:
	python scripts/validate_reference_claims.py build/reference

validate-static-claims:
	python scripts/validate_static_claim_ledger.py build/reference

real-reference:
	python scripts/build_real_retail_reference.py --output-dir build/real-retail

real-validate:
	python scripts/validate_real_retail_reference.py build/real-retail

real-static-claims:
	python scripts/validate_real_static_claims.py build/real-retail

real-check: real-reference real-validate real-static-claims

incremental-reference:
	python scripts/build_incremental_retail_reference.py --output-dir build/incremental-retail

incremental-validate:
	python scripts/validate_incremental_retail_reference.py build/incremental-retail

incremental-static-claims:
	python scripts/validate_incremental_static_claims.py build/incremental-retail

reporting-reference:
	python scripts/build_reporting_product_reference.py --incremental-dir build/incremental-retail

reporting-validate:
	python scripts/validate_reporting_product_reference.py build/incremental-retail

incremental-check: incremental-reference incremental-validate incremental-static-claims reporting-reference reporting-validate

test:
	pytest -q

check: test reference validate validate-forecast validate-migration validate-watermark validate-uncertainty validate-evidence validate-experiment validate-impact validate-reference validate-static-claims

clean:
	rm -rf build .pytest_cache
