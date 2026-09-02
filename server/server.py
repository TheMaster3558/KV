from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

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

from .databases import Map

if TYPE_CHECKING:
    from .databases.types import Database

EMPTY_VALUE = ''


@dataclass(frozen=True)
class _Request:
    """
    Single request parsed from the wire protocol.

    Attributes
    ----------
    action: Action
        Client action to apply.
    key: str
        Lookup key for the request.
    value: SupportedType
        Optional value payload.
    """

    action: Action
    key: str
    value: SupportedType


class Server:
    """
    Asynchronous key-value server backed by a database implementation.

    Examples
    --------
    .. code-block:: python
        :linenos:

        import asyncio

        server = Server('127.0.0.1', 8080)
        asyncio.run(server.run())

    """

    def __init__(self, host: str, port: int, database: Database[SupportedType] | None = None) -> None:
        """
        Create a server bound to a host and port.

        Parameters
        ----------
        host: str
            Interface to bind.
        port: int
            TCP port to listen on.
        database: Database[SupportedType] | None, optional
            Storage backend; defaults to an in-memory map.
        """
        self.host = host
        self.port = port

        self._db: Database[SupportedType] = database or Map()

    async def run(self) -> None:
        """
        Run the server forever until the event loop is stopped.
        """
        async with await asyncio.start_server(self._handle_client, self.host, self.port) as server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """
        Handle a single client connection until it disconnects.

        Parameters
        ----------
        reader: asyncio.StreamReader
            Stream for incoming client data.
        writer: asyncio.StreamWriter
            Stream for sending responses to the client.
        """
        try:
            while await self._process_one_request(reader, writer):
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_one_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """
        Read one request, process it, and send the response.

        Parameters
        ----------
        reader: asyncio.StreamReader
            Stream for incoming data.
        writer: asyncio.StreamWriter
            Stream for the client connection.

        Returns
        -------
        bool
            True while more requests remain to be processed, otherwise False.
        """
        request = await self._read_request(reader)
        if request is None:
            return False

        try:
            status_code, response_values = self._handle_action(request)
        except ValueError:
            status_code, response_values = StatusCode.INVALID_ACTION, EMPTY_VALUE

        response = self._encode_response(status_code, response_values)
        await self._send_response(writer, response)
        return True

    @staticmethod
    async def _read_request(reader: asyncio.StreamReader) -> _Request | None:
        """
        Decode a request from the socket stream.

        Parameters
        ----------
        reader: asyncio.StreamReader
            Stream to decode a request from.

        Returns
        -------
        _Request | None
            Parsed request, or None when the client disconnects.
        """
        try:
            raw_header = await reader.readexactly(RequestHeader.STRUCT.size)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            return None

        header = unpack(raw_header, RequestHeader)

        raw_key = await reader.readexactly(header.key_length)
        raw_value = await reader.readexactly(header.value_length)

        datatype = DataType.from_code(header.datatype_code)
        value = datatype.convert_str_to_obj(raw_value.decode())

        return _Request(action=Action(header.action_code), key=raw_key.decode(), value=value)

    def _handle_action(self, request: _Request) -> tuple[int, Iterable[SupportedType]]:
        """
        Execute one parsed request against the backing database.

        Parameters
        ----------
        request: _Request
            Parsed request to execute.

        Returns
        -------
        tuple[int, Iterable[SupportedType]]
            Status code and response payload values.
        """
        match request.action:
            case Action.GET:
                value = self._db.get(request.key)
                if value is None:
                    return StatusCode.NOT_FOUND, EMPTY_VALUE
                return StatusCode.OK, (value,)

            case Action.SET:
                self._db.set(request.key, request.value)
                return StatusCode.OK, (EMPTY_VALUE,)

            case Action.DELETE:
                self._db.delete(request.key)
                return StatusCode.OK, (EMPTY_VALUE,)

            case Action.DELETE_MANY:
                count = self._db.delete_many(request.key)
                return StatusCode.OK, (count,)

            case Action.KEYS:
                return StatusCode.OK, self._db.keys()

            case _:
                assert_never(request.action)

    @staticmethod
    def _encode_response(status_code: int, values: Iterable[SupportedType]) -> bytes:
        """
        Serialize a response into the network protocol format.

        Parameters
        ----------
        status_code: int
            Status code to report in the response header.
        values: Iterable[SupportedType]
            Values to encode into the payload.

        Returns
        -------
        bytes
            Encoded response packet.
        """
        payload = b''
        num_values = 0
        for value in values:
            num_values += 1
            datatype = DataType.determine_from_obj(value)
            encoded_value = datatype.convert_obj_to_str(value).encode()
            item_header = pack(ResponseItemHeader, len(encoded_value), datatype.code)
            payload += item_header + encoded_value

        header = pack(ResponseHeader, status_code, num_values)
        return header + payload

    @staticmethod
    async def _send_response(writer: asyncio.StreamWriter, response: bytes) -> None:
        """
        Write response bytes to the client socket.

        Parameters
        ----------
        writer: asyncio.StreamWriter
            Destination socket.
        response: bytes
            Encoded response to send.
        """
        writer.write(response)
        await writer.drain()
