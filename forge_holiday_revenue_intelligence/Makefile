.PHONY: test run uk-market

test:
	pytest -q

run:
	python src/run_pipeline.py --output-dir reports/generated

uk-market:
	python src/run_pipeline.py --output-dir reports/generated --include-uk-market
