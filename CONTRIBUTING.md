# Contributing to bitcoin-devtools

## Development Setup

Each tool module is an independent Python package. Install them in editable
mode with test dependencies:

```bash
pip install -e modules/tool-bitcoin-rpc[test]
pip install -e modules/tool-lnd[test]
pip install -e modules/tool-aggeus-markets[test]
```

Run the tests for a single module:

```bash
cd modules/tool-bitcoin-rpc
python -m pytest tests/ -v
```

## Code Structure

Every tool module follows **Pattern B** — a three-file layout:

```
modules/tool-<name>/
  src/tool_<name>/
    client.py       # Low-level API client (httpx/websockets calls)
    tools.py        # Amplifier tool functions (one function per tool)
    __init__.py     # Module registration (entry point for Amplifier)
  tests/
    conftest.py     # Shared fixtures
    test_client.py  # Client unit tests
    test_tools.py   # Tool unit tests
  pyproject.toml    # Package metadata and dependencies
```

- **client.py** owns all network I/O. It speaks the service protocol
  (JSON-RPC, REST, WebSocket) and returns plain Python dicts/lists.
- **tools.py** contains one function per tool. Each function calls the client,
  formats the result, and returns a string for the agent.
- **__init__.py** registers the module with Amplifier via the
  `amplifier.modules` entry point and exposes the tool list.

## Adding a New Tool

1. **Add the client method** in `client.py` — a single async method that calls
   the underlying API and returns raw data.
2. **Add the tool function** in `tools.py` — call the client method, format the
   result into a human-readable string, and return it.
3. **Register the tool** in `__init__.py` — add the function to the module's
   tool list so Amplifier discovers it.
4. **Write tests** — add a client test (mocked HTTP/WS) and a tool test
   (mocked client) in the `tests/` directory.
5. **Update the behavior YAML** — add the tool name to the relevant behavior
   file in `behaviors/` so the agent can use it.
6. **Update the agent description** — mention the new tool in the agent's
   markdown file in `agents/` so the agent knows when to use it.

## Commit Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(optional scope): <description>
```

Types:

| Type | Purpose |
|------|---------|
| `feat` | A new feature or tool |
| `fix` | A bug fix |
| `refactor` | Code restructuring without behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation changes |
| `chore` | Maintenance tasks (deps, CI, config) |

Examples:

```
feat(bitcoin-rpc): add split_utxos tool
fix(lnd): handle missing macaroon path gracefully
test(aggeus): add WebSocket reconnect tests
docs: update README with new prerequisites
```
