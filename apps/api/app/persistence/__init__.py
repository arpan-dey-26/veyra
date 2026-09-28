"""Persistence ports + implementations.

Services depend only on the ``UnitOfWork`` protocol (repositories.py):
- ``sql.SqlUnitOfWork``: PostgreSQL via SQLAlchemy (the real implementation).
- ``memory.MemoryUnitOfWork``: in-process store for fast API tests without a database.
Both are exercised by the test suite; integration tests run the SQL one against Postgres.
"""
