import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

SupportedType = str | int | float


@dataclass(frozen=True)
class TypeSpec:
    """
    Definition of a supported serializable value type.

    Attributes
    ----------
    code: int
        Wire-format identifier for the datatype.
    py_type: type
        Python type represented by the datatype.
    convert_obj_to_str: Callable[[SupportedType], str]
        Callable used to serialize a Python object.
    convert_str_to_obj: Callable[[str], SupportedType]
        Callable used to deserialize a Python object.
    """

    code: int
    py_type: type
    convert_obj_to_str: Callable[[SupportedType], str]
    convert_str_to_obj: Callable[[str], SupportedType]


class DataType(enum.Enum):
    """
    Enum of supported protocol value types.

    Notes
    -----
    The enum stores metadata used to encode and decode values over the socket.
    """

    STR = TypeSpec(0, str, convert_obj_to_str=str, convert_str_to_obj=str)
    INT = TypeSpec(1, int, convert_obj_to_str=str, convert_str_to_obj=int)
    FLOAT = TypeSpec(2, float, convert_obj_to_str=str, convert_str_to_obj=float)

    @classmethod
    def determine_from_obj(cls, obj: SupportedType) -> Self:
        """
        Return the datatype that matches a Python object.

        Parameters
        ----------
        obj: SupportedType
            Python value to identify.

        Returns
        -------
        DataType
            Matching enum value.
        """
        for member in cls:
            if isinstance(obj, member.py_type):
                return member
        raise TypeError(f'Unsupported type: {type(obj)!r}')

    @classmethod
    def from_code(cls, code: int) -> Self:
        """
        Look up a datatype by its serialized protocol code.

        Parameters
        ----------
        code: int
            Network type identifier.

        Returns
        -------
        DataType
            Matching enum value.
        """
        for member in cls:
            if member.value.code == code:
                return member
        raise ValueError(f'Unknown type code: {code}')

    @property
    def code(self) -> int:
        """
        Protocol code used on the wire.

        Returns
        -------
        int
            Serialized wire identifier for the datatype.
        """
        return self.value.code

    @property
    def py_type(self) -> type:
        """
        Python type represented by the enum member.

        Returns
        -------
        type
            Python type associated with the enum member.
        """
        return self.value.py_type

    def convert_obj_to_str(self, obj: SupportedType) -> str:
        """
        Serialize a supported Python value as a string.

        Parameters
        ----------
        obj: SupportedType
            Value to serialize.

        Returns
        -------
        str
            Serialized representation.
        """
        return self.value.convert_obj_to_str(obj)

    def convert_str_to_obj(self, s: str) -> SupportedType:
        """
        Deserialize a stored value into Python.

        Parameters
        ----------
        s: str
            Serialized value.

        Returns
        -------
        SupportedType
            Rehydrated Python object.
        """
        return self.value.convert_str_to_obj(s)
