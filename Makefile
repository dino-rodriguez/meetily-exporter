test:
	uv run python -m unittest discover tests -v -b

lint:
	uv run ruff check .

format:
	uv run ruff format .
