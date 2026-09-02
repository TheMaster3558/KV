from collections.abc import Container, Sequence
from typing import Protocol


class Database[T](Container[str], Protocol):
    """
    Protocol for a key-value storage backend.

    Implementations provide the operations required by the server.
    """

    def keys(self) -> Sequence[str]:
        """
        Return the stored keys.

        Returns
        -------
        Sequence[str]
            Ordered collection of keys.
        """
        ...

    def get(self, key: str) -> T | None:
        """
        Fetch a key from the database.

        Parameters
        ----------
        key: str
            Lookup key.

        Returns
        -------
        T | None
            Stored value or ``None`` when absent.
        """
        ...

    def set(self, key: str, value: T) -> None:
        """
        Set a key to a new value.

        Parameters
        ----------
        key: str
            Store key.
        value: T
            Value to persist.
        """
        ...

    def delete(self, key: str) -> None:
        """
        Delete a single key.

        Parameters
        ----------
        key: str
            Key to remove.
        """
        ...

    def delete_many(self, prefix: str) -> int:
        """
        Delete all keys sharing a prefix.

        Parameters
        ----------
        prefix: str
            Prefix used to match keys.

        Returns
        -------
        int
            Number of removed keys.
        """
        ...
