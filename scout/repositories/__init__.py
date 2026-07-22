"""Scout repository layer.

Repositories are the ONLY place in the application that executes SQL.
Every other layer - services (later phase), agents, and API routes -
must go through a repository method and receive typed domain models
back (see models.py), never a raw sqlite3.Row, a dict, or SQL itself.

This keeps the SQL surface area small and auditable: if you want to
know every query Scout can run against the database, you only need to
read the four *_repository.py files in this package.
"""
