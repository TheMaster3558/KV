# Copilot instructions for this repository

## Quick start

**Start the server:**

```bash
python -m server --host '127.0.0.1' --port 8080
```

**Connect from Python:**

```python
import asyncio
from client import connect

async def main():
    async with connect('127.0.0.1', 8080) as conn:
        await conn.set('key', 'value')
        print(await conn.get('key'))

asyncio.run(main())
```

**Use a connection pool:**

```python
import asyncio
from client import create_pool

async def main():
    async with create_pool('127.0.0.1', 8080, min_connections=1, max_connections=4, connection_timeout=5.0) as pool:
        async with pool.acquire() as conn:
            await conn.set('job', 'done')
            print(await conn.get('job'))

asyncio.run(main())
```

See README.md for more complete examples and architecture details.

## Project shape

This repository is a compact Python asyncio key-value server/client library.

- `server/server.py` is the main server implementation. It starts an `asyncio` TCP server, reads one request at a time, dispatches actions, and sends a typed response.
- `common/protocol.py` defines the wire format: operation enums (`Action`), status codes (`StatusCode`), and the binary `NamedTuple` headers used for requests and responses.
- `common/datatypes.py` is the protocol type layer. It restricts supported values to `str | int | float` and converts them to/from their serialized string representations.
- `server/databases/types.py` defines the storage interface and `server/databases/mapping.py` provides the in-memory `Map` backend.
- `client/connection.py` implements the per-connection client API (`connect`, `Connection`, request/response serialization, and typed error mapping).
- `client/pool.py` implements `Pool` and `_PoolConnection` for reusable async connections with idle timeout behavior.
- `main.py` and `server/__main__.py` are the runtime entrypoints used to launch the server.

The server and client are intentionally small and protocol-driven. If a change affects the binary protocol, type mapping, or request/response flow, check both the client and server sides together.

## Commands

Install dev dependencies:

```bash
python -m pip install --upgrade pip
pip install .[dev]
```

Lint:

```bash
ruff check .
```

Format:

```bash
ruff format .
```

Type-check:

```bash
basedpyright .
```

Targeted smoke validation without a test suite:

```bash
python -m compileall main.py server client common
```

For a single file, use:

```bash
python -m py_compile path/to/file.py
```

There is no dedicated unit test runner configured in this repository at the moment. Validation is done with the repo's lint/type-check workflow and targeted compile checks.

## Key conventions

- Prefer `asyncio` patterns already used in the codebase: `async with`, `await`, and `asyncio.start_server`.
- Keep the network layer and storage layer separated. Do not let `server/server.py` become dependent on a specific DB implementation beyond the `Database` interface.
- For protocol-related changes, update both the encode/decode path and the matching server-side handling in the same patch.
- The project uses single quotes in code examples and source formatting.
- Docstrings should follow the repository's NumPy-style pattern: descriptive text starts on the line after the opening `"""`, use `Parameters`, `Returns`, `Attributes`, `Examples`, etc., and avoid Sphinx field directives like `:param:` or `:returns:`.
- For examples in docstrings, use:
  - `.. code-block:: python` for standalone script examples
  - `.. code-block:: pycon` for REPL/interactive examples
  - single-quoted literals in example code
- When adding exported API examples, include an `Examples` section in the docstring so the public API remains self-documenting.

## Typical change patterns

- If a new public client method is added, it typically belongs in `client/connection.py` and should be mirrored in the exported `__all__` API surface if it is intended to be used directly.
- If a new server action is added, update the `Action` enum in `common/protocol.py`, the request handling in `server/server.py`, and the client-side request logic in `client/connection.py` together.
- If the value format changes, adjust the serialization behavior in `common/datatypes.py` and ensure both the server and client decode/encode the same type codes.

## Repository behavior

- The default backend is a transient in-memory `Map`; data is not persisted across server restarts.
- The server is designed as a small, local async service and not as a production-grade distributed or durable store.
- The pool and connection objects are awaitable convenience wrappers around `__await__` and async context managers.
