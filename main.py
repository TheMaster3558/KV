import asyncio

import client


async def main():
    """
    Run a small smoke test against the local key-value server.

    Examples
    --------
    .. code-block:: pycon

        >>> await main()
    """
    async with client.create_pool(
        '127.0.0.1', 8080, min_connections=1, max_connections=10, connection_timeout=1
    ) as pool:
        async with pool.acquire() as conn:
            await conn.set('foo0', 1.0)
            await conn.set('foo1', 2.0)
            print(await conn.keys())

        await asyncio.sleep(10)


asyncio.run(main())
