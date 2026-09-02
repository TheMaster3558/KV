.. KV documentation master file, created by
   sphinx-quickstart on Tue Sep  1 12:28:34 2026.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

KV documentation
================

KV is a small asynchronous key-value server and client written in Python
with ``asyncio``. A single server process handles client requests over a
lightweight, length-prefixed binary TCP protocol, backed by a pluggable
storage abstraction. The client library mirrors this simplicity, offering
both a direct connection and a reusable connection pool for higher
throughput workloads.

Features
--------

- Asynchronous server and client built entirely on ``asyncio``
- Compact binary wire protocol with typed values (``str``, ``int``, ``float``)
- ``GET``, ``SET``, ``DELETE``, ``DELETE_MANY``, and ``KEYS`` actions
- Swappable storage backends behind a simple ``Database`` protocol,
  with an in-memory ``Map`` backend included by default
- A connection pool that keeps idle connections warm and evicts stale ones

Installation
------------

.. code-block::

   git clone https://github.com/TheMaster3558/kv.git
   cd kv

.. code-block:: bash

    pip install .[dev]

This installs the project along with ``pyright`` and ``ruff`` for
development.

Where to go next
-----------------

- :doc:`quick_usage` walks through starting the server and using the
  client, including connection pooling.
- :doc:`api` is the full reference for the server and client packages.
- :doc:`technical_details` explains the wire protocol, architecture,
  and the reasoning behind key design decisions.

.. toctree::
   :maxdepth: 2
   :hidden:

   quick_usage
   api
   technical_details