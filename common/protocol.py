import enum
import struct
from typing import NamedTuple


class StatusCode(enum.IntEnum):
    """
    Protocol status returned by the server.

    Attributes
    ----------
    OK: int
        The request succeeded.
    NOT_FOUND: int
        The requested key does not exist.
    INVALID_ACTION: int
        The action code is not supported.
    """

    OK = 0
    NOT_FOUND = 1
    INVALID_ACTION = 2


class Action(enum.IntEnum):
    """
    Supported client actions for the key-value protocol.
    """

    GET = 0
    SET = 1
    DELETE = 2
    DELETE_MANY = 3
    KEYS = 4


def pack(namedtuple_type: type[NamedTuple], *args: object) -> bytes:
    """
    Pack protocol header fields into their binary wire format.

    Parameters
    ----------
    namedtuple_type: type[NamedTuple]
        Header definition with a ``STRUCT`` attribute.
    *args: object
        Values to serialize.

    Returns
    -------
    bytes
        Encoded network payload.
    """
    return namedtuple_type.STRUCT.pack(*args)  # pyright: ignore


def unpack[T: NamedTuple](data: bytes, namedtuple_type: type[T]) -> T:
    """
    Unpack a binary protocol header into a named tuple.

    Parameters
    ----------
    data: bytes
        Raw serialized header bytes.
    namedtuple_type: type[T]
        Header definition to decode into.

    Returns
    -------
    T
        A populated named tuple with protocol fields.
    """
    unpacked_data: tuple[object, ...] = namedtuple_type.STRUCT.unpack(data)  # pyright: ignore
    return namedtuple_type(*unpacked_data)  # pyright: ignore


class RequestHeader(NamedTuple):
    """
    Request header for a key-value operation.

    Attributes
    ----------
    action_code: int
        Operation sent by the client.
    key_length: int
        Length of the serialized key in bytes.
    value_length: int
        Length of the serialized value in bytes.
    datatype_code: int
        Type code for the value.
    """

    action_code: int
    key_length: int
    value_length: int
    datatype_code: int

    STRUCT = struct.Struct('!BIII')


class ResponseHeader(NamedTuple):
    """
    Response header returned by the server.
    """

    status_code: int
    num_items: int

    STRUCT = struct.Struct('!BI')


class ResponseItemHeader(NamedTuple):
    """
    Header for each item in a multi-value response.
    """

    value_length: int
    value_datatype: int

    STRUCT = struct.Struct('!II')
