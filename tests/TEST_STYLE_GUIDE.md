# Dolphin Test Style Guide

## Directory Structure

```
tests/
├── conftest.py              # Root fixtures (flag overrides)
├── TEST_STYLE_GUIDE.md      # This file
├── unittest/
│   ├── conftest.py          # Unit test fixtures (agent factory, mock executor)
│   ├── agent/
│   ├── system/
│   └── ...
└── integration_test/
    ├── test_runner.py
    ├── test_config.py
    └── dolphins/             # .dph test files
```

## Pytest Conventions

- Use `pytest` as the test runner (`make test-unit`).
- Test files: `test_*.py` or `*_test.py`.
- Test functions: `test_*`.
- Test classes: `Test*` (no `__init__`).

## Async Tests

All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`). Simply define `async def test_*` — no `@pytest.mark.asyncio` decorator required.

```python
async def test_my_async_function():
    result = await some_async_call()
    assert result is not None
```

## Fixtures

### Root Fixtures (`tests/conftest.py`)

| Fixture | Description |
|---------|-------------|
| `disable_explore_v2` | Disable `EXPLORE_BLOCK_V2` flag for the test |
| `enable_explore_v2` | Enable `EXPLORE_BLOCK_V2` flag for the test |

### Unit Test Fixtures (`tests/unittest/conftest.py`)

| Fixture | Description |
|---------|-------------|
| `mock_executor` | Fully mocked `DolphinExecutor` with async methods |
| `mock_context` | Mocked `Context` instance |
| `dolphin_agent` | Factory fixture: `agent = dolphin_agent(content=..., name=...)` |

## Feature Flags in Tests

Use the `flags.override()` context manager or the provided fixtures:

```python
# Option 1: Use fixture
def test_with_v1(disable_explore_v2):
    # EXPLORE_BLOCK_V2 is False here
    ...

# Option 2: Direct context manager
from dolphin.core import flags

def test_custom_flags():
    with flags.override({flags.EXPLORE_BLOCK_V2: False}):
        ...
```

Do **not** call `flags.set_flag()` / `flags.reset()` manually — prefer the context manager for automatic cleanup.

## Mocking

- Patch `DolphinAgent._validate_syntax` with `return_value=None` when creating agents in unit tests.
- Patch `DolphinExecutor` class when you don't need real execution.
- Use the `dolphin_agent` factory fixture to avoid boilerplate.

## Coverage

Run with coverage:

```bash
bash tests/run_tests.sh unit --coverage
```

Coverage configuration is in `pyproject.toml` under `[tool.coverage.*]`.
