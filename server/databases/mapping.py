from collections.abc import Sequence
from typing import override

from .types import Database


class Map[T](Database[T]):
    """
    In-memory database implementation backed by a dictionary.

    Examples
    --------
    .. code-block:: pycon

        >>> db = Map()
        >>> db.set('name', 'Ada')
        >>> db.get('name')
        'Ada'
    """

    def __init__(self) -> None:
        """
        Create an empty in-memory map.
        """
        self._map: dict[str, T] = {}

    @override
    def keys(self) -> Sequence[str]:
        """
        Return the currently stored keys.

        Returns
        -------
        Sequence[str]
            A snapshot of the current keys.
        """
        return list(self._map.keys())

    @override
    def get(self, key: str) -> T | None:
        """
        Look up a value by key.

        Parameters
        ----------
        key: str
            Key to retrieve.

        Returns
        -------
        T | None
            Stored value, or ``None`` if missing.
        """
        return self._map.get(key)

    @override
    def set(self, key: str, value: T) -> None:
        """
        Persist a value under a key.

        Parameters
        ----------
        key: str
            Key to assign.
        value: T
            Stored value.
        """
        self._map[key] = value

    @override
    def delete(self, key: str) -> None:
        """
        Delete a single key.

        Parameters
        ----------
        key: str
            Key to remove.
        """
        self._map.pop(key)

    @override
    def delete_many(self, prefix: str) -> int:
        """
        Delete all keys beginning with a prefix.

        Parameters
        ----------
        prefix: str
            Prefix to match.

        Returns
        -------
        int
            Number of removed entries.
        """
        count = 0
        for k in list(self._map):
            if k.startswith(prefix):
                self._map.pop(k)
                count += 1
        return count

    @override
    def __contains__(self, key: str) -> bool:
        """
        Return whether the given key is present.

        Parameters
        ----------
        key: str
            Key to test.

        Returns
        -------
        bool
            True when the key exists in the mapping.
        """
        return key in self._map

    @override
    def __repr__(self) -> str:
        """
        Return a repr of the underlying mapping.

        Returns
        -------
        str
            String representation of the mapping.
        """
        return repr(self._map)
