Technical Details
==================

Architecture
------------

The server is a single-process, asynchronous TCP service built on
``asyncio``. ``asyncio.start_server`` spawns one coroutine per client
connection (``Server._handle_client``), which loops reading and
answering requests until the socket closes. Each request is decoded
from a fixed-size binary header followed by raw key/value bytes,
dispatched to a storage backend through a small ``Database`` protocol,
and re-encoded into a typed response. The client mirrors this
structure: a ``Connection`` wraps one socket and speaks the same wire
format, and a ``Pool`` manages a bounded set of reusable connections.

.. code-block:: text

    Client
      │
      ▼
    Connection / Pool          (client/connection.py, client/pool.py)
      │   length-prefixed binary protocol over TCP
      ▼
    asyncio.start_server                (server/server.py)
      │
      ├── struct-based header decode
      ├── Action dispatch (match/case)
      ▼
    Database protocol           (server/databases/types.py)
      │
      ▼
    Map (dict-backed store)     (server/databases/mapping.py)

The server itself is started with a single call — ``run`` opens the
listening socket and serves forever inside one async context manager:

.. code-block:: python

    async def run(self) -> None:
        async with await asyncio.start_server(self._handle_client, self.host, self.port) as server:
            await server.serve_forever()

Design Decisions
-----------------

Length-Prefixed Binary Protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Requests and responses are framed with fixed ``struct`` headers
(``RequestHeader`` is packed as ``!BIII`` — action code, key length,
value length, datatype code) rather than a delimiter such as a
newline. The reader always knows exactly how many bytes to pull off
the socket via ``readexactly``, so keys and values can contain any
byte sequence without escaping:

.. code-block:: python

    class RequestHeader(NamedTuple):
        action_code: int
        key_length: int
        value_length: int
        datatype_code: int

        STRUCT = struct.Struct('!BIII')

    # server/server.py
    raw_header = await reader.readexactly(RequestHeader.STRUCT.size)
    header = unpack(raw_header, RequestHeader)

    raw_key = await reader.readexactly(header.key_length)
    raw_value = await reader.readexactly(header.value_length)

The three ``readexactly`` calls form the entire framing logic: one
fixed-size read for the header, then two variable-length reads whose
sizes came directly out of that header. There is no scanning for a
terminator anywhere in the read path.

The tradeoff is a fixed per-message overhead (13 bytes for a request
header alone) and length fields capped by the width of the packed
integers, versus the simplicity of a delimiter-based protocol.

Storage as a Structural Protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Database[T]`` is defined as a ``typing.Protocol`` (also inheriting
``Container[str]`` for ``in`` support) rather than an abstract base
class, and the server is parameterized over it instead of importing
``Map`` directly:

.. code-block:: python

    class Database[T](Container[str], Protocol):
        def keys(self) -> Sequence[str]: ...
        def get(self, key: str) -> T | None: ...
        def set(self, key: str, value: T) -> None: ...
        def delete(self, key: str) -> None: ...
        def delete_many(self, prefix: str) -> int: ...

``server/__main__.py`` then selects a concrete implementation at
startup from a ``--database`` CLI flag mapped through a lookup table,
rather than the server importing any specific backend module itself:

.. code-block:: python

    databases: dict[str, type[Database[SupportedType]]] = {
        'map': Map,
    }

    parser.add_argument('--database', type=str, choices=['map'], default='map')
    args = parser.parse_args(namespace=Args())

    server = Server(host=args.host, port=args.port, database=databases[args.database]())
    asyncio.run(server.run())

This keeps the protocol layer and the request-handling code fully
decoupled from any specific storage implementation — a new backend
only needs to match the Protocol's method shapes, no inheritance
required, and it becomes selectable by adding one entry to
``databases``. The tradeoff is that conformance is never checked until
a method is actually called; a backend with a typo in a method
signature fails at call time, not at definition time.

Typed Value Serialization
~~~~~~~~~~~~~~~~~~~~~~~~~~

Values are transmitted as UTF-8 text, but each message also carries a
``datatype_code`` resolved through the ``DataType`` enum, which pairs
each supported Python type (``str``, ``int``, ``float``) with
``convert_obj_to_str`` / ``convert_str_to_obj`` callables stored in a
frozen ``TypeSpec`` dataclass:

.. code-block:: python

    @dataclass(frozen=True)
    class TypeSpec:
        code: int
        py_type: type
        convert_obj_to_str: Callable[[SupportedType], str]
        convert_str_to_obj: Callable[[str], SupportedType]

    class DataType(enum.Enum):
        STR = TypeSpec(0, str, convert_obj_to_str=str, convert_str_to_obj=str)
        INT = TypeSpec(1, int, convert_obj_to_str=str, convert_str_to_obj=int)
        FLOAT = TypeSpec(2, float, convert_obj_to_str=str, convert_str_to_obj=float)

        @classmethod
        def determine_from_obj(cls, obj: SupportedType) -> Self:
            for member in cls:
                if isinstance(obj, member.py_type):
                    return member
            raise TypeError(f'Unsupported type: {type(obj)!r}')

        @classmethod
        def from_code(cls, code: int) -> Self:
            for member in cls:
                if member.value.code == code:
                    return member
            raise ValueError(f'Unknown type code: {code}')

A client that stores an ``int`` gets an actual Python ``int`` back on
``GET``, not a string that needs manual casting. Both directions of
the encode/decode path route through these two classmethods rather
than an ``if``/``elif`` chain, so adding a fourth supported type is a
one-line addition to the enum — every call site (``_encode_request``,
``_encode_response``, ``_read_request``, ``_read_response``) already
goes through ``determine_from_obj``/``from_code``.

The tradeoff is that ``SupportedType`` is a closed union — there is no
generic path for nested structures like lists or dicts — and every
value still round-trips through ``str()`` rather than a compact binary
encoding, so numeric payloads are larger on the wire than they would
be with fixed-width binary packing.

Self-Describing Header NamedTuples
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every wire header (``RequestHeader``, ``ResponseHeader``,
``ResponseItemHeader``) is a ``typing.NamedTuple`` that carries its own
``struct.Struct`` as a class attribute right alongside its fields:

.. code-block:: python

    class ResponseHeader(NamedTuple):
        status_code: int
        num_items: int

        STRUCT = struct.Struct('!BI')

    class ResponseItemHeader(NamedTuple):
        value_length: int
        value_datatype: int

        STRUCT = struct.Struct('!II')

Because the format string lives next to the fields it describes,
there is no separate lookup table mapping header types to formats,
and no way for a header's fields to silently drift out of sync with
its packed layout — renaming or reordering a field is a one-line
change in a single class.

That, in turn, is what lets ``pack`` and ``unpack`` be written once
and reused for all three header types, instead of once per header:

.. code-block:: python

    def pack(namedtuple_type: type[NamedTuple], *args: object) -> bytes:
        return namedtuple_type.STRUCT.pack(*args)

    def unpack[T: NamedTuple](data: bytes, namedtuple_type: type[T]) -> T:
        unpacked_data: tuple[object, ...] = namedtuple_type.STRUCT.unpack(data)
        return namedtuple_type(*unpacked_data)

``unpack`` is generic over ``T: NamedTuple`` (a PEP 695 type
parameter), so ``unpack(raw, RequestHeader)`` is statically known to
return a ``RequestHeader``, not a bare tuple — callers get real
attribute access (``header.key_length``) with no casting. Every
caller reads the same way, on both the server and client:

.. code-block:: python

    # server/server.py
    header = unpack(raw_header, RequestHeader)
    raw_key = await reader.readexactly(header.key_length)

    # client/connection.py
    response_header = unpack(raw_header, ResponseHeader)
    for _ in range(response_header.num_items):
        ...

The tradeoff is that ``NamedTuple`` was repurposed slightly beyond its
usual role — ``STRUCT`` is a class-level attribute sitting among
instance fields, which works because ``NamedTuple`` ignores class
attributes without type annotations when building the tuple's field
list, but it does mean the pattern relies on that particular quirk of
how ``NamedTuple`` distinguishes fields from ordinary class attributes
rather than on something more explicit like a separate registry.

Single In-Flight Request per Connection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The protocol has no request IDs, so a response is implicitly matched
to whichever request was sent most recently on that socket. To keep
that assumption valid under concurrent callers, ``Connection`` guards
every request/response round trip with an ``asyncio.Lock``:

.. code-block:: python

    async def _send_action(
        self, action: Action, *, key: str = EMPTY_VALUE, value: SupportedType = EMPTY_VALUE
    ) -> list[SupportedType]:
        request = self._encode_request(action, key, value)

        async with self._lock:
            reader, writer = self._require_open_connection()
            writer.write(request)
            await writer.drain()
            status, response_values = await self._read_response(reader)

        self._raise_for_status(status)
        return response_values

Everything between acquiring and releasing the lock — the write, the
``drain``, and the matching read — happens as one atomic unit from the
caller's point of view, which is what keeps a second coroutine's
request from being written into the middle of another request's
response.

The tradeoff is that a single ``Connection`` cannot pipeline requests
— at most one request is in flight per socket. This is the reason the
project pairs ``Connection`` with ``Pool``: concurrency comes from
running several connections at once rather than multiplexing one
socket.

Idle-Timeout Connection Pooling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Pool`` keeps ``min_connections`` warm, allows growth up to
``max_connections``, and evicts a connection that has sat idle for
``connection_timeout`` seconds. Eviction is scheduled with
``loop.call_later`` when a connection is released and cancelled if it
is reacquired before the timer fires:

.. code-block:: python

    class _PoolConnection(Connection):
        def _start_idle_timeout(self) -> None:
            loop = asyncio.get_running_loop()
            self._handle = loop.call_later(
                self._connection_timeout,
                lambda: asyncio.create_task(self._pool._kill_connection(self)),
            )

        def _clear_idle_timeout(self) -> None:
            assert self._handle is not None
            self._handle.cancel()
            self._handle = None

``_kill_connection`` only actually closes the socket when doing so
would not drop the pool below its floor — otherwise it just re-arms
the timer instead of skipping it:

.. code-block:: python

    async def _kill_connection(self, conn: _PoolConnection) -> None:
        if self._num_connections <= self._min_connections:
            conn._start_idle_timeout()
        else:
            async with self._cond:
                self._idle.remove(conn)
                self._num_connections -= 1
                self._cond.notify_all()
            await conn.close()

Note that the floor isn't enforced by refusing to start a timer on a
protected connection — it's enforced by re-arming that same timer
every time it fires while the pool is at its minimum, so there's a
single code path for "idle connection timed out" instead of a
separate always-on/never-on branch.

The tradeoff is one scheduled ``asyncio.Handle`` per idle connection
and a bit of bookkeeping complexity, in exchange for bounded resource
usage and back-pressure under load instead of unconstrained connection
growth.

Implementation Highlights
--------------------------

CLI Entry Point and Backend Registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``server/__main__.py`` gives the server a ``python -m server`` entry
point built on ``argparse``, with a typed ``Args`` namespace so the
rest of the module gets real attribute types instead of ``Namespace``'s
``Any``:

.. code-block:: python

    class Args(argparse.Namespace):
        host: str
        port: int
        database: str

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--database', type=str, choices=['map'], default='map')
    args = parser.parse_args(namespace=Args())

Passing ``namespace=Args()`` is what makes this work — ``argparse``
populates the attributes of the object it's given rather than
constructing its own, so a plain subclass with annotations but no
``__init__`` logic is enough to type the parsed result.

Full Request Lifecycle
~~~~~~~~~~~~~~~~~~~~~~~~

Each accepted connection runs a simple loop: process one request,
repeat until the client disconnects, then always close the socket:

.. code-block:: python

    async def _handle_client(self, reader, writer) -> None:
        try:
            while await self._process_one_request(reader, writer):
                pass
        finally:
            writer.close()
            await writer.wait_closed()

A single request/response cycle reads a request, executes it against
the database, and always produces *some* response — even a malformed
action doesn't crash the handler or drop the connection, it's turned
into a status code:

.. code-block:: python

    async def _process_one_request(self, reader, writer) -> bool:
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

``_read_request`` returning ``None`` (rather than raising) is what
signals a clean disconnect back to the loop above, which is what lets
``_handle_client`` treat "no more requests" and "client hung up"
identically:

.. code-block:: python

    @staticmethod
    async def _read_request(reader: asyncio.StreamReader) -> _Request | None:
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

On the way out, ``_encode_response`` builds the payload by looping
over however many values the action produced (zero for a bare
``SET``/``DELETE``, one for ``GET``, many for ``KEYS``) and prefixing
each with its own item header, so the response format naturally
supports single values and lists with the same code path:

.. code-block:: python

    @staticmethod
    def _encode_response(status_code: int, values: Iterable[SupportedType]) -> bytes:
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

Exhaustive Action Dispatch
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Server._handle_action`` dispatches on the ``Action`` enum with a
``match`` statement, ending in ``case _: assert_never(request.action)``.
Because ``assert_never`` is typed to accept nothing, adding a new
``Action`` member without adding a matching ``case`` is a static type
error rather than a bug that only shows up when that action is sent
at runtime:

.. code-block:: python

    match request.action:
        case Action.GET:
            value = self._db.get(request.key)
            if value is None:
                return StatusCode.NOT_FOUND, EMPTY_VALUE
            return StatusCode.OK, (value,)

        case Action.SET:
            self._db.set(request.key, request.value)
            return StatusCode.OK, (EMPTY_VALUE,)

        case Action.DELETE_MANY:
            count = self._db.delete_many(request.key)
            return StatusCode.OK, (count,)

        case Action.KEYS:
            return StatusCode.OK, self._db.keys()

        case _:
            assert_never(request.action)

Note ``GET`` on a missing key returns ``NOT_FOUND`` rather than an
empty value silently — the "value is absent" case is distinguished
from "value is the empty string" at the protocol level, not left
ambiguous.

In-Memory Map and the ``Container`` Protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Map`` is a thin, generic wrapper around a ``dict[str, T]`` that
fulfills the ``Database`` protocol, including the ``Container``
methods it inherits (``__contains__``) and a debugging-friendly
``__repr__`` that just delegates to the dict's own:

.. code-block:: python

    class Map[T](Database[T]):
        def __init__(self) -> None:
            self._map: dict[str, T] = {}

        def get(self, key: str) -> T | None:
            return self._map.get(key)

        def delete(self, key: str) -> None:
            self._map.pop(key)

        def __contains__(self, key: str) -> bool:
            return key in self._map

        def __repr__(self) -> str:
            return repr(self._map)

Every method is a near-direct pass-through to the equivalent dict
operation, which is what makes ``Map``'s complexity guarantees just
CPython's dict guarantees — there's no additional bookkeeping layer
between the protocol and the underlying hash table.

Prefix Deletion Over a Live Dict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``delete_many`` removes every key sharing a prefix by iterating a
snapshot of the key list (``list(self._map)``) while mutating the
underlying dict, avoiding the ``RuntimeError`` that comes from
mutating a dict during iteration over its live view:

.. code-block:: python

    def delete_many(self, prefix: str) -> int:
        count = 0
        for k in list(self._map):
            if k.startswith(prefix):
                self._map.pop(k)
                count += 1
        return count

Dual-Mode Connections: Awaitable and Async Context Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Both ``Connection`` and ``Pool`` implement ``__await__`` in addition
to ``__aenter__``/``__aexit__``, so the same object supports either
``await connect(...)`` with manual cleanup or ``async with
connect(...)`` with automatic cleanup:

.. code-block:: python

    def __await__(self) -> Generator[None, None, Self]:
        yield from self._connect().__await__()
        return self

    async def __aenter__(self) -> Self:
        return await self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

``__aenter__`` is implemented by simply ``await``-ing ``self``, so the
connection logic is written exactly once in ``__await__`` and reused
by both entry points — there's no duplicated "open the socket" code
between the two usage styles:

.. code-block:: python

    # main.py
    async with client.create_pool(
        '127.0.0.1', 8080, min_connections=1, max_connections=10, connection_timeout=1
    ) as pool:
        async with pool.acquire() as conn:
            await conn.set('foo0', 1.0)
            await conn.set('foo1', 2.0)
            print(await conn.keys())

Typed Exceptions Mapped from Status Codes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rather than handing callers a raw ``StatusCode`` to check, the client
translates non-OK statuses into dedicated exception types, each
carrying the status code that produced it as a class attribute:

.. code-block:: python

    class NotFoundError(Exception):
        code = StatusCode.NOT_FOUND

    class InvalidActionError(Exception):
        code = StatusCode.INVALID_ACTION

    @staticmethod
    def _raise_for_status(status: StatusCode) -> None:
        if status == StatusCode.NOT_FOUND:
            raise NotFoundError()
        elif status == StatusCode.INVALID_ACTION:
            raise InvalidActionError()

A missing key surfaces to calling code as ``except NotFoundError``
instead of an ``if response.status == StatusCode.NOT_FOUND`` check
that every caller would otherwise have to repeat. A third exception,
``ConnectionNotOpenError``, covers the separate failure mode of
calling a method before the socket is open or after the server has
gone away — raised both defensively in ``_require_open_connection``
and when a response read comes back short:

.. code-block:: python

    def _require_open_connection(self):
        if self._reader is None or self._writer is None:
            raise ConnectionNotOpenError('Connection is not open')
        return self._reader, self._writer

Pool Acquisition, Growth, and Back-Pressure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Pool._acquire`` reuses an idle connection if one is available,
opens a new one if the pool has room to grow, or waits on the shared
condition variable if it's already at capacity:

.. code-block:: python

    async def _acquire(self) -> _PoolConnection:
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

The connection count is reserved (``self._num_connections += 1``)
*before* the actual socket is opened, and rolled back in the
``except`` block if ``_create_connection`` fails — that reservation
is what stops two concurrent callers from both seeing room for "one
more" connection and overshooting ``max_connections``. ``acquire`` is
exposed as an async context manager built on top of ``_acquire`` /
``release``, so a checked-out connection is always returned to the
pool even if the caller's block raises:

.. code-block:: python

    @contextlib.asynccontextmanager
    async def acquire(self):
        conn = await self._acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

Performance
------------

.. list-table::
   :header-rows: 1

   * - Operation
     - Complexity
     - Notes
   * - ``GET``
     - O(1) average
     - dict lookup
   * - ``SET``
     - O(1) average
     - dict insert
   * - ``DELETE``
     - O(1) average
     - dict pop
   * - ``DELETE_MANY``
     - O(n)
     - scans every key for a prefix match
   * - ``KEYS``
     - O(n)
     - materializes all keys into a list

No load-testing numbers are included yet — these figures describe the
``Map`` backend's algorithmic behavior, not measured throughput or
connection limits.

Tradeoffs / Alternatives
--------------------------

**In-memory storage, no persistence.** ``Map`` is a plain dict with no
snapshotting or write-ahead log, so a restart discards all data. This
favors simplicity over durability; a disk-backed or replicated
``Database`` implementation could be added later without touching the
protocol or client, since the server only depends on the ``Database``
protocol.

**No request pipelining.** As covered above, a single connection
handles one request at a time by design, because the protocol carries
no request identifiers to disambiguate interleaved responses. Adding
request IDs would allow pipelining on a single socket, at the cost of
a more complex protocol and response-matching logic on both ends. The
current design instead scales concurrency out through the connection
pool.

**Single event loop, no sharding.** All connections run on one
``asyncio`` event loop in one process, which is a good fit here since
every operation is a fast, non-blocking dict access. A CPU-bound
storage backend would block every connection on that loop; supporting
one would likely require offloading work to a thread or process pool
rather than running it inline in the handler coroutine.

**Prefix scan instead of a prefix index.** ``delete_many`` walks every
key rather than maintaining a trie or sorted key structure. This keeps
``Map`` simple and keeps ``SET``/``DELETE`` at O(1), at the cost of an
O(n) prefix delete — a reasonable tradeoff unless prefix deletion
becomes a hot path.

**Static analysis over runtime validation.** The project leans on
``basedpyright`` and ``ruff`` (configured in ``pyproject.toml``) plus
constructs like ``assert_never`` and generic ``Protocol`` classes to
catch mistakes before the code runs, rather than adding runtime
schema validation on the wire protocol. That keeps the hot request
path free of validation overhead, at the cost of protocol violations
from a non-Python or misbehaving client being caught later and more
generically (as an ``INVALID_ACTION``/``ValueError`` or a decode
failure) instead of with a precise, targeted error.