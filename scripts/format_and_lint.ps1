uv run ruff format src tests
uv run ruff check --fix src tests
uv run ruff check --fix --unsafe-fixes src tests
uv run ruff check --fix --select I src tests

uv run pip-audit
uv run ruff check src tests
uv run ruff format --check src tests

uv run vulture src tests --min-confidence 80

uv run mypy --strict src tests

# uv run mypy --explicit-package-bases src tests
# uv run mypy --explicit-package-bases --check-untyped-defs src tests
# uv run mypy --strict src tests

uv run semgrep --config=auto --config=p/security-audit --error src tests

uv run coverage run -m pytest tests/
uv run coverage report
uv run coverage xml