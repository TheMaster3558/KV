from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import TYPE_CHECKING, Self, cast

from common.datatypes import DataType, SupportedType
from common.protocol import (
    Action,
    RequestHeader,
    ResponseHeader,
    ResponseItemHeader,
    StatusCode,
    pack,
    unpack,
)

if TYPE_CHECKING:
    from types import TracebackType


EMPTY_VALUE = ''


class ConnectionNotOpenError(Exception):
    """
    Raised when an operation is attempted before the socket is connected.
    """


class NotFoundError(Exception):
    """
    Raised when a requested key is absent on the server.
    """

    code = StatusCode.NOT_FOUND


class InvalidActionError(Exception):
    """
    Raised when a client sends an unsupported action enum.
    """

    code = StatusCode.INVALID_ACTION


class Connection:
    """
    The asynchronous client connection object for the key-value server.

    .. note::

        This class should not be directly instantiated. Use the :func:`connect` function to create a connection instance.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        self._lock = asyncio.Lock()

    def __await__(self) -> Generator[None, None, Self]:
        """
        Open the socket when the connection is awaited.

        Returns
        -------
        Self
            The connected connection instance.
        """
        yield from self._connect().__await__()
        return self

    async def __aenter__(self) -> Self:
        """
        Open and return the connection when used as an async context manager.

        Returns
        -------
        Self
            The connected connection instance.
        """
        return await self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Close the connection when leaving an async context block.

        Parameters
        ----------
        exc_type: type[BaseException] | None
            Exception type that triggered the context exit, if any.
        exc_val: BaseException | None
            Exception value that triggered the context exit, if any.
        exc_tb: TracebackType | None
            Traceback of the exiting exception, if any.
        """
        await self.close()

    async def close(self) -> None:
        """
        Close the active socket, if it is open.
        """
        if self._writer is None:
            return
        try:
            self._writer.close()
            await self._writer.wait_closed()
        finally:
            self._reader = None
            self._writer = None

    async def get(self, key: str) -> SupportedType:
        """
        Fetch a value from the server.

        Parameters
        ----------
        key: str
            Key to look up.

        Returns
        -------
        SupportedType
            Stored value.
        """
        resp = await self._send_action(Action.GET, key=key)
        return resp[0]

    async def set(self, key: str, value: SupportedType) -> None:
        """
        Store a value on the server.

        Parameters
        ----------
        key: str
            Key to assign.
        value: SupportedType
            Value to store.
        """
        await self._send_action(Action.SET, key=key, value=value)

    async def delete(self, key: str) -> None:
        """
        Delete a single key.

        Parameters
        ----------
        key: str
            Key to remove.
        """
        await self._send_action(Action.DELETE, key=key)

    async def delete_many(self, prefix: str) -> int:
        """
        Delete every key whose name begins with the prefix.

        Parameters
        ----------
        prefix: str
            Prefix to match.

        Returns
        -------
        int
            Number of deleted keys.
        """
        count = await self._send_action(Action.DELETE_MANY, key=prefix)
        assert isinstance(count, int)
        return count

    async def keys(self) -> list[str]:
        """
        List keys currently stored on the server.

        Returns
        -------
        list[str]
            All stored keys.
        """
        resp = await self._send_action(Action.KEYS)
        return cast(list[str], resp)

    async def _send_action(
        self, action: Action, *, key: str = EMPTY_VALUE, value: SupportedType = EMPTY_VALUE
    ) -> list[SupportedType]:
        """
        Send a protocol action and return the parsed response values.

        Parameters
        ----------
        action: Action
            Client action to transmit.
        key: str
            Key payload for the request.
        value: SupportedType
            Value payload for the request.

        Returns
        -------
        list[SupportedType]
            Decoded values returned by the server.
        """
        request = self._encode_request(action, key, value)

        async with self._lock:
            reader, writer = self._require_open_connection()

            writer.write(request)
            await writer.drain()

            status, response_values = await self._read_response(reader)

        self._raise_for_status(status)
        return response_values

    async def _connect(self) -> None:
        """
        Open the underlying TCP connection.
        """
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)

    def _require_open_connection(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """
        Validate the connection is open and return the io objects.

        Returns
        -------
        tuple[asyncio.StreamReader, asyncio.StreamWriter]
            Reader and writer for the active socket.
        """
        if self._reader is None or self._writer is None:
            raise ConnectionNotOpenError('Connection is not open')
        return self._reader, self._writer

    @staticmethod
    def _encode_request(action: Action, key: str, value: SupportedType) -> bytes:
        """
        Serialize a client request into the protocol wire format.

        Parameters
        ----------
        action: Action
            Operation being requested.
        key: str
            Key to send as the request payload.
        value: SupportedType
            Value to encode into the request.

        Returns
        -------
        bytes
            Serialized request packet.
        """
        datatype = DataType.determine_from_obj(value)
        encoded_key = key.encode()
        encoded_value = datatype.convert_obj_to_str(value).encode()
        header = pack(RequestHeader, action, len(encoded_key), len(encoded_value), datatype.code)
        return header + encoded_key + encoded_value

    @staticmethod
    async def _read_response(
        reader: asyncio.StreamReader,
    ) -> tuple[StatusCode, list[SupportedType]]:
        """
        Read a response frame from the server and decode the payload.

        Parameters
        ----------
        reader: asyncio.StreamReader
            Stream to read from.

        Returns
        -------
        tuple[StatusCode, list[SupportedType]]
            Server status and decoded response values.
        """
        try:
            raw_header = await reader.readexactly(ResponseHeader.STRUCT.size)
        except asyncio.IncompleteReadError as exc:
            raise ConnectionNotOpenError('Connection is not open, check server for errors') from exc
        response_header = unpack(raw_header, ResponseHeader)

        values: list[SupportedType] = []
        for _ in range(response_header.num_items):
            raw_item_header = await reader.readexactly(ResponseItemHeader.STRUCT.size)
            response_item_header = unpack(raw_item_header, ResponseItemHeader)

            datatype = DataType.from_code(response_item_header.value_datatype)
            raw_value = await reader.readexactly(response_item_header.value_length)
            value = datatype.convert_str_to_obj(raw_value.decode())

            values.append(value)

        return StatusCode(response_header.status_code), values

    @staticmethod
    def _raise_for_status(status: StatusCode) -> None:
        """
        Raise a typed exception for server-side error codes.

        Parameters
        ----------
        status: StatusCode
            Status returned by the server.
        """
        if status == StatusCode.NOT_FOUND:
            raise NotFoundError()
        elif status == StatusCode.INVALID_ACTION:
            raise InvalidActionError()


def connect(host: str, port: int) -> Connection:
    """
    Create a client connection to a running KV server.

    Parameters
    ----------
    host: str
        Hostname or IP address of the server.
    port: int
        TCP port used by the server.

    Returns
    -------
    Connection
        The connection object.

    Examples
    --------
    .. code-block:: pycon

        >>> conn = await connect('127.0.0.1', 8080)
        >>> try:
        ...     await conn.set('message', 'hello')
        ...     await conn.get('message')
        'hello'
        >>> finally:
        ...     await conn.close()


    Or with context managers

    .. code-block:: pycon

        >>> async with connect('127.0.0.1', 8080) as conn:
        ...     await conn.set('planet', 'Earth')
        ...     await conn.get('planet')
        'Earth'
    """
    return Connection(host, port)
