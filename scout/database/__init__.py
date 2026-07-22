"""Scout SQLite database package: connections, schema, initialization, and seeding.

SQLite is the source of truth for product, store, inventory, and
promotion facts in this phase of Scout. Nothing outside this package
should open a raw sqlite3 connection - use connection.py so that
foreign-key enforcement stays consistent everywhere.
"""
