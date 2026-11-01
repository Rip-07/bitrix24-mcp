# Contributing

Thanks for helping! Issues labelled
[good first issue](https://github.com/Rip-07/bitrix24-mcp/labels/good%20first%20issue) and
[help wanted](https://github.com/Rip-07/bitrix24-mcp/labels/help%20wanted) are a good start.
Comment on an issue before you begin so two people do not work on the same thing.
Questions and ideas: [Discussions](https://github.com/Rip-07/bitrix24-mcp/discussions).

## Setup

Python 3.10 or newer.

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Tests and linters

```sh
pytest -q
ruff check .
ruff format --check .   # optional, not enforced in CI yet
```

CI runs `ruff check` and `pytest` on Python 3.10, 3.12 and 3.13, then builds the Docker image.

Tests never call a real portal: `tests/conftest.py` runs a fake Bitrix24 REST endpoint on localhost (the `fake` fixture).
Do not commit real webhook URLs, tokens or customer data, not even in tests.

## Adding a tool

1. Add the REST call in `src/bitrix24_mcp/server.py` inside `build_server()`:
   read tools with `annotations=_READ`, write tools inside `if not read_only:` with `annotations=_WRITE`.
2. Return compact data: pick fields with `select`, flatten phone/email with `_simplify()`.
3. Cover it in `tests/test_server.py`, including the read-only case for write tools.
4. Add a row to the tools table in `README.md` and a line to `CHANGELOG.md`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add get_lead tool
fix(client): retry on QUERY_LIMIT_EXCEEDED for list calls
docs: describe MCP_ALLOWED_HOSTS
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
Keep one logical change per pull request.
