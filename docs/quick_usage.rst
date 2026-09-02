Quick usage
===========

Running the server (command line)
---------------------------------

.. code-block:: bash

    python -m server --host '127.0.0.1' --port 8080

You can also select the default in-memory backend explicitly:

.. code-block:: bash

    python -m server --host '127.0.0.1' --port 8080 --database map

From Python code
----------------

.. code-block:: python

    import asyncio
    from server import Server

    server = Server('127.0.0.1', 8080)
    asyncio.run(server.run())

Client usage
------------

Single connection
~~~~~~~~~~~~~~~~~

Async context manager version

.. code-block:: python

    import asyncio
    from client import connect

    async def main():
        async with connect('127.0.0.1', 8080) as conn:
            await conn.set('planet', 'Earth')
            print(await conn.get('planet'))

    asyncio.run(main())

Await + try/finally version

.. code-block:: python

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

Connection pooling
~~~~~~~~~~~~~~~~~~

Async context manager version

.. code-block:: python

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

Await + try/finally version

.. code-block:: python

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

Notes
-----

The connect and create_pool helpers are awaitable as convenience patterns, but the context manager forms are the clearest option for resource cleanup.
