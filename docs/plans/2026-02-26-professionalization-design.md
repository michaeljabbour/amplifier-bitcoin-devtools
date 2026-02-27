# Professionalization Design

## Goal

Take the amplifier-bitcoin-devtools repository from its current audit score of 7.5/10 to 10/10 across all dimensions: testing, code quality, security, error handling, documentation, commit discipline, observability, and dependency hygiene. Work happens on the forked repo (michaeljabbour/amplifier-bitcoin-devtools) on a `professional` branch, preserving the original `master` history.

## Background

The repo is an Amplifier bundle providing AI-assisted Bitcoin Core (L1), Lightning Network (L2), and Aggeus prediction market tooling. It contains 3 Python tool modules (17 tool classes, ~2,069 lines), 3 agent definitions, 3 composable behaviors, and context/protocol documentation.

An exhaustive audit identified the following gaps:

| Dimension | Current Score | Gap |
|-----------|--------------|-----|
| Testing | 1/10 | Zero surviving tests |
| Commit Discipline | 5/10 | Inconsistent messages ("hmm", "adding some stuff") |
| Security | 6/10 | Reactive patterns, no input validation |
| Error Handling | 7/10 | 3 real bugs, incomplete failure-mode coverage |
| Code Quality | 7.5/10 | Duplication across 7 constructors, 3 RPC helpers |
| Documentation | 8/10 | Placeholder in README, no CHANGELOG/CONTRIBUTING |
| Architecture | 9/10 | Minor: unpinned deps, unused `cryptography`, no root pyproject |
| Amplifier Alignment | 9/10 | Already near-perfect |
| Domain Expertise | 9.5/10 | Already strong |

## Approach

All decisions were validated through structured brainstorming and Amplifier ecosystem expert consultation:

- **Git strategy:** Hybrid -- preserve `master`, professionalize on a `professional` branch. PR back when complete.
- **Testing:** TDD/BDD + unit tests with `respx` mocks + contract tests for API shape validation + BIP-340/NIP-01 crypto test vectors.
- **Refactoring:** Composition over inheritance -- client helpers injected via `mount()`, following Amplifier's canonical Pattern B (matching `tool-lsp` and `provider-ollama`).
- **Observability:** Standard `logging.getLogger(__name__)` in each module's `client.py`.
- **Security:** Defensive hardening -- fix identified bugs, systematic input validation, credential validation at mount time.
- **CI/CD:** GitHub Actions workflow (lint, typecheck, test) -- present but not enforced.
- **Documentation:** Fix README placeholder, add CHANGELOG, CONTRIBUTING, root `pyproject.toml` for shared tooling config.

## Architecture

Work is sequenced to minimize merge noise, with each commit independently valid:

```
master (preserved, untouched)
  └── professional (all work here)
        ├── 1. Bug fixes (3 commits)
        ├── 2. Refactoring (structural)
        ├── 3. Tests (against refactored code)
        ├── 4. Security hardening
        ├── 5. Observability
        ├── 6. Documentation & CI
        └── 7. Dependency hygiene
```

When complete, a single PR from `professional` to `master` on the fork provides one reviewable artifact.

## Components

### 1. Bug Fixes

Three surgical commits establishing a correct baseline.

**Race condition** (`ConsolidateUtxosTool._wallet_url`):
- Make `wallet_url` a local variable in `execute()` passed to `_rpc()` as a parameter.
- Eliminated naturally by the RpcClient refactor, but fixed independently first for a clean commit history.

**Resource leak** (`_load_credentials`):
- Replace bare `open()` with `with open(...) as f:`.
- Add `try/except FileNotFoundError` raising `ValueError` with an actionable message: "Cookie file not found at {path} -- check BITCOIN_COOKIE_FILE".

**Uncaught JSONDecodeError** (`SplitUtxosTool._rpc_call`):
- Add `response.raise_for_status()` before `response.json()`, matching the pattern already used in `ListUtxosTool`.

### 2. Refactoring -- Composition Pattern

Validated by the Amplifier ecosystem expert as canonical Pattern B (client-holding, matching `tool-lsp` and `provider-ollama`).

**File structure** -- Split each module into 3 files following `tool-lsp` precedent:

```
amplifier_module_tool_bitcoin_rpc/
    __init__.py    # mount() wiring only (~25 lines)
    client.py      # BitcoinRpcClient
    tools.py       # 7 thin tool classes

amplifier_module_tool_lnd/
    __init__.py    # mount() wiring only
    client.py      # LndClient
    tools.py       # 6 thin tool classes

amplifier_module_tool_aggeus_markets/
    __init__.py    # mount() wiring only
    client.py      # NostrClient
    tools.py       # 4 thin tool classes
```

**Bitcoin RPC module:**
- `BitcoinRpcClient` holds `rpc_url`, `rpc_user`, `rpc_password`, and a lazy-initialized shared `httpx.AsyncClient`. Exposes a single `async rpc(method, params, wallet="")` method that handles URL construction, JSON-RPC envelope, `raise_for_status()`, error extraction, and all exception types.
- Each tool's `__init__` takes a `BitcoinRpcClient` instead of raw credentials. Tools become thin -- just `name`, `description`, `input_schema`, and `execute()` logic.
- `_load_credentials()` moves into `client.py` with the resource leak fix and `FileNotFoundError` handling.
- `mount()` creates one `BitcoinRpcClient`, passes it to all 7 tools, returns async cleanup function.

**LND module:**
- `LndClient` wraps the existing `_make_client`, `_load_macaroon`, and `_lnd_error` helpers. Exposes `async get(path)`, `async post(path, json)`.
- `_STATE` dict becomes a module-level `INVOICE_STATE_LABELS` constant.
- 6 tools receive `LndClient` via constructor.
- `mount()` returns cleanup function.

**Aggeus module:**
- `NostrClient` holds relay URL and optional signing credentials. Groups `_query_relay`, `_publish_event`, `_build_signed_event`.
- WebSocket connections are one-shot (REQ->EOSE->close), so no connection pool. `NostrClient` is a credential holder and method namespace with a no-op `close()`.
- Conditional mounting of `CreateMarketTool` preserved -- gated on whether `NostrClient` has signing credentials.
- `mount()` returns cleanup function.

**Cross-cutting patterns:**
- **Lazy client initialization** -- Following `provider-ollama` convention, `httpx.AsyncClient` is created on first use, not at `mount()` time. Client class owns the transport lifecycle.
- **`mount()` returns cleanup function** -- This is the lifecycle contract the kernel provides. Current `mount()` functions return nothing. Refactored version returns `async def cleanup()` that calls `client.close()`.

### 3. Security Hardening

One commit layering defensive patterns across all modules.

- **Credential validation at `mount()` for bitcoin-rpc** -- Add eager validation matching LND's existing fail-fast pattern. Currently bitcoin-rpc silently proceeds and fails at first tool call.
- **Input validation on all `execute()` methods** -- Verify required fields exist and have correct types before making any RPC/REST/WebSocket calls. Return `ToolResult(success=False, error=...)` with a clear message; never let `KeyError` or `TypeError` propagate.
- **Error message sanitization** -- Ensure no internal file paths, credential fragments, or stack traces leak through `ToolResult` error messages. Scrub before returning.

### 4. Test Architecture

TDD/BDD with three test layers, organized per module.

**Test structure:**

```
modules/tool-bitcoin-rpc/tests/
    conftest.py          # Shared fixtures (mock RpcClient, respx routes)
    test_client.py       # BitcoinRpcClient unit tests
    test_tools.py        # 7 tool behavior tests
    test_contracts.py    # JSON-RPC request/response shape validation

modules/tool-lnd/tests/
    conftest.py
    test_client.py
    test_tools.py
    test_contracts.py

modules/tool-aggeus-markets/tests/
    conftest.py
    test_client.py       # NostrClient unit tests
    test_tools.py
    test_crypto.py       # Pure function tests with BIP-340/NIP-01 test vectors
    test_contracts.py    # Nostr event shape validation
```

**Layer 1 -- Unit tests (BDD-style):**
Each tool gets behavior-focused tests using `respx` (HTTP) or mock WebSocket fixtures. Tests describe *what the tool does*, not implementation details:
- `test_list_utxos_returns_formatted_table_on_success`
- `test_list_utxos_returns_error_when_node_unreachable`
- `test_manage_wallet_distinguishes_empty_string_from_none`
- `test_mine_blocks_warns_below_101_blocks`

**Layer 2 -- Crypto test vectors:**
Pure function tests for `_nostr_event_id`, `_derive_pubkey`, `_schnorr_sign` using known vectors from BIP-340 and NIP-01 specs. No mocking needed -- these are deterministic functions with published expected outputs.

**Layer 3 -- Contract tests:**
Validate that JSON-RPC request envelopes, LND REST request shapes, and Nostr event structures match actual API schemas. No live services -- shape validation against documented schemas. Catches drift if Bitcoin Core/LND/Nostr specs change.

**Test dependencies** added to all three `pyproject.toml` files (currently only bitcoin-rpc declares them). All modules get `pytest>=8.0`, `pytest-asyncio>=0.24`, `respx>=0.22`. Aggeus also gets `pytest-mock` for WebSocket mocking.

### 5. Observability

Standard `logging.getLogger(__name__)` in each module's `client.py`.

| Level | What gets logged |
|-------|-----------------|
| `DEBUG` | Every RPC/REST/WebSocket request (method, endpoint, params summary) and response (status, truncated body) |
| `INFO` | Successful `mount()` with tool count and endpoint (no credentials) |
| `WARNING` | Retryable situations (connection timeouts, transient errors). Pattern in place for future use. |
| `ERROR` | Failed requests with full context (method, status code, error message). Sanitized -- no credentials, no internal paths. |

Logger lives in `client.py` per module. Tools don't log directly -- they return `ToolResult`, and the client logs the underlying transport. Keeps tools thin and logging centralized.

No Amplifier event emission from tool modules. That's the orchestrator/hook layer's job. Tools are mechanisms; they don't observe themselves.

### 6. Documentation & CI/CD

**Documentation fixes** (1 commit):
- **README.md line 44** -- Replace `<your-org>` placeholder with actual repo URL.
- **CHANGELOG.md** -- Create with a single `v0.1.0` entry summarizing what exists (3 modules, 17 tools, 3 agents, 3 behaviors). Follow Keep a Changelog format.
- **CONTRIBUTING.md** -- Lightweight guide: dev environment setup (`pip install -e modules/tool-*[test]`), running tests (`pytest`), commit message conventions, and the composition pattern for adding new tools.

**CI/CD** (1 commit):
- **`.github/workflows/ci.yaml`** -- Single workflow, three jobs:
  - `lint` -- `ruff check` + `ruff format --check` across all modules
  - `typecheck` -- `pyright` on all three module packages
  - `test` -- `pytest` for each module
- Triggered on push to any branch and on PRs. Not enforced with branch protection.

**Root `pyproject.toml`** (1 commit):
- Workspace-level config for shared tooling: ruff settings, pyright config, pytest defaults. Not a package -- just tooling configuration. Each module remains its own independent package.

### 7. Dependency Hygiene

- **Pin foundation bundle** -- Change `git+https://github.com/microsoft/amplifier-foundation@main` in `bundle.md` to a specific release tag or commit SHA.
- **Pin `httpx` in tool-lnd** -- Currently unpinned. Match bitcoin-rpc's pattern: `httpx>=0.27`.
- **Remove `cryptography`** from tool-aggeus-markets `pyproject.toml` -- Declared but never imported. Dead dependency.
- **Add test dependencies** to tool-lnd and tool-aggeus-markets `pyproject.toml` (`pytest>=8.0`, `pytest-asyncio>=0.24`, `respx>=0.22`, plus `pytest-mock` for aggeus).
- **Root `pyproject.toml`** -- Shared tool config for ruff, pyright, and pytest.

## Data Flow

Tools interact with external services through a single transport layer:

```
mount() creates Client
     │
     ▼
Tool.execute(input)
     │
     ├── Validate input (types, required fields)
     │
     ├── Client.rpc(method, params) / Client.get(path) / Client.query(filter)
     │       │
     │       ├── Construct request envelope
     │       ├── Log DEBUG: request details
     │       ├── Send via httpx / websockets
     │       ├── raise_for_status()
     │       ├── Extract response / handle errors
     │       └── Log DEBUG: response summary
     │
     └── Return ToolResult(success, output/error)
```

Cleanup lifecycle:
```
mount() → returns cleanup()
  ...tools used during session...
cleanup() → client.close() → httpx.AsyncClient.aclose()
```

## Error Handling

Three tiers of error handling, from outer to inner:

1. **Input validation** (tool layer) -- Missing/malformed fields caught before any network call. Returns `ToolResult(success=False, error="descriptive message")`.

2. **Transport errors** (client layer) -- `httpx.ConnectError`, `httpx.TimeoutException`, `httpx.HTTPStatusError` caught and wrapped. Error messages sanitized to remove internal paths and credentials.

3. **Domain errors** (client layer) -- Bitcoin Core JSON-RPC error codes, LND gRPC status codes, and Nostr relay NOTICEs extracted and surfaced as structured error messages in `ToolResult`.

All three tiers log at appropriate levels (DEBUG for expected flow, ERROR for failures) and never let raw exceptions propagate to the caller.

## Testing Strategy

See Section 4 (Test Architecture) for full details.

Summary: three layers providing coverage without requiring live infrastructure.

| Layer | Scope | Tool |
|-------|-------|------|
| Unit (BDD-style) | Tool behavior with mocked clients | `pytest` + `respx` + `pytest-mock` |
| Crypto vectors | Pure crypto functions against spec vectors | `pytest` (no mocking) |
| Contract | Request/response shape validation | `pytest` + JSON schema assertions |

Run with: `pytest` from each module directory, or from root via the root `pyproject.toml` config.

CI runs all three layers on every push and PR.

## Amplifier Expert Validation

The refactoring pattern was validated by the Amplifier ecosystem expert:

- Client helper injected via `mount()` is the canonical Pattern B (`tool-lsp`, `provider-ollama`)
- Split into `__init__.py` / `client.py` / `tools.py` is recommended at this scale (`tool-lsp` precedent)
- Client owns `httpx` lifecycle with lazy initialization (`provider-ollama` convention)
- `mount()` returning cleanup function is the required lifecycle contract
- Conditional tool registration in aggeus should be preserved
- Thin tools (name/desc/schema/execute) is the correct Pattern B approach

## Open Questions

- Exact foundation bundle tag/SHA to pin to (check latest stable release at implementation time).
- Whether to add a `py.typed` marker file to each module for PEP 561 compliance (nice to have, not critical).
