import argparse
import asyncio

from common.datatypes import SupportedType

from . import Server
from .databases import Map
from .databases.types import Database


class Args(argparse.Namespace):
    """
    Parsed command-line arguments for the server process.
    """

    host: str  # pyright: ignore[reportUninitializedInstanceVariable]
    port: int  # pyright: ignore[reportUninitializedInstanceVariable]
    database: str  # pyright: ignore[reportUninitializedInstanceVariable]


databases: dict[str, type[Database[SupportedType]]] = {
    'map': Map,
}


parser = argparse.ArgumentParser()
parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind the server to')
parser.add_argument('--port', type=int, default=8080, help='Port to bind the server to')
parser.add_argument('--database', type=str, choices=['map'], default='map', help='Database to use')
args = parser.parse_args(namespace=Args())

server = Server(host=args.host, port=args.port, database=databases[args.database]())
asyncio.run(server.run())
