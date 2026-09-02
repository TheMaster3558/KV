from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Generator
from typing import TYPE_CHECKING, Self

from .connection import Connection

if TYPE_CHECKING:
    from types import TracebackType


class _PoolConnection(Connection):
    """
    Internal connection wrapper that tracks pool idle timeouts.
    """

    def __init__(self, pool: Pool, host: str, port: int, connection_timeout: float) -> None:
        super().__init__(host, port)
        self._pool = pool
        self._connection_timeout = connection_timeout
        self._handle: asyncio.Handle | None = None

    def _start_idle_timeout(self) -> None:
        """
        Schedule the connection for eviction after a period of inactivity.
        """
        loop = asyncio.get_running_loop()
        self._handle = loop.call_later(
            self._connection_timeout,
            lambda: asyncio.create_task(self._pool._kill_connection(self)),
        )

    def _clear_idle_timeout(self) -> None:
        """
        Cancel the idle timeout when the connection is borrowed again.
        """
        assert self._handle is not None
        self._handle.cancel()
        self._handle = None


class Pool:
    """
    Manage a pool of reusable client connections.

    .. note::

        This class should not be directly instantiated. Use the :func:`create_pool` factory function instead.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        min_connections: int,
        max_connections: int,
        connection_timeout: float,
    ) -> None:
        """
        Initialize a connection pool configuration.

        Parameters
        ----------
        host: str
            Server hostname.
        port: int
            Server port.
        min_connections: int
            Minimum number of idle connections to keep.
        max_connections: int
            Maximum number of connections allowed.
        connection_timeout: float
            Idle timeout in seconds before a connection is discarded.
        """
        self._min_connections = min_connections
        self._max_connections = max_connections
        self._host = host
        self._port = port
        self._connection_timeout = connection_timeout

        self._num_connections = 0
        self._idle: list[_PoolConnection] = []

        self._cond = asyncio.Condition()
        self._closed = False

    def __await__(self) -> Generator[None, None, Self]:
        """
        Create the minimum number of idle connections when awaited.

        Returns
        -------
        Self
            The initialized pool instance.
        """
        yield from self._init().__await__()
        return self

    async def __aenter__(self) -> Self:
        """
        Initialize the pool and use it as an async context manager.

        Returns
        -------
        Self
            The initialized pool instance.
        """
        return await self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        """
        Close the pool when leaving an async context block.

        Parameters
        ----------
        exc_type: type[BaseException] | None
            Exception type that triggered the context exit, if any.
        exc_val: BaseException | None
            Exception value that triggered the context exit, if any.
        exc_tb: TracebackType | None
            Traceback for the exiting exception, if any.
        """
        await self.close()

    async def _init(self) -> None:
        """
        Create the configured minimum number of idle connections.
        """
        if self._num_connections >= self._min_connections:
            return
        for _ in range(self._min_connections):
            conn = await self._create_connection()
            async with self._cond:
                self._idle.append(conn)
                conn._start_idle_timeout()
                self._num_connections += 1
                self._cond.notify_all()

    @contextlib.asynccontextmanager
    async def acquire(self):
        """
        Yield a checked-out connection and return it to the pool afterwards.

        Yields
        ------
        _PoolConnection
            A reusable database connection.
        """
        conn = await self._acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    async def _acquire(self) -> _PoolConnection:
        """
        Borrow an idle connection or create a new one up to the max.

        Returns
        -------
        _PoolConnection
            A checked-out connection from the pool.
        """
        while True:
            async with self._cond:
                if self._closed:
                    raise RuntimeError('Pool is closed')
                if self._idle:
                    conn = self._idle.pop()
                    conn._clear_idle_timeout()
                    return conn
                elif self._num_connections < self._max_connections:
                    self._num_connections += 1
                    break
                await self._cond.wait()

        try:
            return await self._create_connection()
        except Exception:
            async with self._cond:
                self._num_connections -= 1
                self._cond.notify_all()
            raise

    async def release(self, conn: _PoolConnection) -> None:
        """
        Return a connection to the idle queue.

        Parameters
        ----------
        conn: _PoolConnection
            Connection being returned to the pool.
        """
        async with self._cond:
            self._idle.append(conn)
            conn._start_idle_timeout()
            self._cond.notify_all()

    async def close(self):
        """
        Close the pool and all idle connections.
        """
        self._closed = True
        async with self._cond:
            self._cond.notify_all()
        while self._idle:
            conn = self._idle.pop()
            await conn.close()

    async def _create_connection(self) -> _PoolConnection:
        """
        Create and return a pool-managed connection to the server.

        Returns
        -------
        _PoolConnection
            Newly initialized pool connection.
        """
        conn = _PoolConnection(self, self._host, self._port, self._connection_timeout)
        await conn._connect()
        return conn

    async def _kill_connection(self, conn: _PoolConnection) -> None:
        """
        Discard an idle connection when its timeout expires.

        Parameters
        ----------
        conn: _PoolConnection
            Idle connection scheduled for disposal.
        """
        if self._num_connections <= self._min_connections:
            conn._start_idle_timeout()
        else:
            async with self._cond:
                self._idle.remove(conn)
                self._num_connections -= 1
                self._cond.notify_all()
            await conn.close()


def create_pool(
    host: str,
    port: int,
    *,
    min_connections: int,
    max_connections: int,
    connection_timeout: float,
) -> Pool:
    """
    Create a reusable pool of client connections.

    Parameters
    ----------
    host: str
        Server hostname to connect to.
    port: int
        Server port.
    min_connections: int
        Number of idle connections the pool should keep warm.
    max_connections: int
        Maximum number of connections allowed in the pool.
    connection_timeout: float
        Seconds to keep an idle socket before it is discarded.

    Returns
    -------
    Pool
        Initialized connection pool.

    Examples
    --------
    .. code-block:: pycon

        >>> pool = await create_pool(
        ...     '127.0.0.1',
        ...     8080,
        ...     min_connections=1,
        ...     max_connections=4,
        ...     connection_timeout=5.0,
        ... )

        >>> try:
        ...     conn = await pool.acquire()
        ...     await conn.set('job', 'done')
        >>> finally:
        ...     await pool.release(conn)

    Or with context managers

    .. code-block:: pycon

        >>> async with create_pool(
        ...     '127.0.0.1',
        ...     8080,
        ...     min_connections=1,
        ...     max_connections=4,
        ...     connection_timeout=5.0,
        ... ) as pool:
        ...     async with pool.acquire() as conn:
        ...         await conn.set('job', 'done')
    """
    return Pool(
        host,
        port,
        min_connections=min_connections,
        max_connections=max_connections,
        connection_timeout=connection_timeout,
    )
