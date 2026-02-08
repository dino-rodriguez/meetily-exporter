test:
	uv run python -m unittest discover tests -v

lint:
	uv run ruff check .

format:
	uv run ruff format .
