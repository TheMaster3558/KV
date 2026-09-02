# KV

A small asynchronous key-value server and client written in Python with `asyncio`. The project provides a lightweight TCP-based API for storing and retrieving values, along with a simple in-memory database backend. It is intentionally compact: a single server process handles client requests, a typed binary protocol serializes messages, and the client exposes both a direct connection and a reusable connection pool.

## Editing the project

Install pyright and ruff using this command:

```bash
pip install .[dev]
```

## Quick description

The server listens for incoming connections and accepts a small set of actions:

- `GET`
- `SET`
- `DELETE`
- `DELETE_MANY`
- `KEYS`

Values are serialized with a fixed type system and supported types include `str`, `int`, and `float`. The default storage backend is an in-memory `Map`, while the server uses a `Database` abstraction so a different backend could be swapped in later without changing the protocol or client API.

## Running the server

### From the command line

The project includes a CLI entry point in `server/__main__.py`, so the server can be started directly as a module:

```bash
python -m server --host '127.0.0.1' --port 8080
```

You can also select the default in-memory backend explicitly:

```bash
python -m server --host '127.0.0.1' --port 8080 --database map
```

All of these commands start the server and keep it running until you stop it with `Ctrl+C`.

### From Python code

This is the server startup pattern shown in the project docstrings:

```python
import asyncio

from server import Server

server = Server('127.0.0.1', 8080)
asyncio.run(server.run())
```

## Client usage

### Single connection

The exported `connect` helper can be used either as an async context manager or by awaiting the connection directly and closing it in a `try`/`finally` block.

Async context manager version:

```python
import asyncio

from client import connect


async def main():
    async with connect('127.0.0.1', 8080) as conn:
        await conn.set('planet', 'Earth')
        print(await conn.get('planet'))


asyncio.run(main())
```

Await + `try`/`finally` version:

```python
import asyncio

from client import connect


async def main():
    conn = await connect('127.0.0.1', 8080)
    try:
        await conn.set('planet', 'Earth')
        print(await conn.get('planet'))
    finally:
        await conn.close()


asyncio.run(main())
```


### Connection pooling

For higher throughput or repeated operations, the project exposes a reusable connection pool via `create_pool`. You can use it with async context managers or by awaiting the pool directly and releasing connections manually.

Async context manager version:

```python
import asyncio

from client import create_pool


async def main():
    async with create_pool(
        '127.0.0.1',
        8080,
        min_connections=1,
        max_connections=4,
        connection_timeout=5.0,
    ) as pool:
        async with pool.acquire() as conn:
            await conn.set('job', 'done')
            print(await conn.get('job'))


asyncio.run(main())
```

Await + `try`/`finally` version:

```python
import asyncio

from client import create_pool


async def main():
    pool = await create_pool(
        '127.0.0.1',
        8080,
        min_connections=1,
        max_connections=4,
        connection_timeout=5.0,
    )
    try:
        conn = await pool.acquire()
        try:
            await conn.set('job', 'done')
            print(await conn.get('job'))
        finally:
            await pool.release(conn)
    finally:
        await pool.close()


asyncio.run(main())
```

The pool keeps a small number of idle connections warm and automatically evicts connections that sit idle too long. This reduces the cost of repeatedly establishing new sockets while still maintaining a bounded number of connections.

The `connect` and `create_pool` helpers are also awaitable. In other words, `await connect(...)` and `await create_pool(...)` are supported as convenience patterns, but the direct context manager forms remain the clearest option for resource cleanup.
