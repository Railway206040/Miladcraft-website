"""Synchronous compatibility layer for the existing Flask routes over Cloudflare D1.

D1 operations are awaited through pyodide.ffi.run_sync because Flask is WSGI.
Each statement is executed immediately; context managers preserve the existing
call sites but are not SQLite transactions.
"""
from __future__ import annotations

from collections.abc import Mapping
from pyodide.ffi import run_sync


class D1Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _to_row(value):
    if isinstance(value, D1Row):
        return value
    if isinstance(value, Mapping):
        return D1Row(value)
    if hasattr(value, "to_py"):
        converted = value.to_py()
        if isinstance(converted, Mapping):
            return D1Row(converted)
    try:
        return D1Row(dict(value))
    except Exception as exc:
        raise TypeError("Unexpected D1 row representation") from exc


class D1Cursor:
    def __init__(self, rows=None, lastrowid=None, rowcount=-1):
        self._rows = [_to_row(row) for row in (rows or [])]
        self._index = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class D1Connection:
    def __init__(self, database):
        self.database = database
        self.row_factory = None

    def execute(self, sql, parameters=()):
        statement = self.database.prepare(sql)
        if parameters:
            statement = statement.bind(*tuple(parameters))
        verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if verb in {"SELECT", "WITH", "PRAGMA", "EXPLAIN"}:
            result = run_sync(statement.all())
            rows = getattr(result, "results", [])
            try:
                rows = list(rows)
            except TypeError:
                rows = []
            return D1Cursor(rows, rowcount=len(rows))
        result = run_sync(statement.run())
        meta = getattr(result, "meta", None)
        lastrowid = getattr(meta, "last_row_id", None) if meta is not None else None
        changes = getattr(meta, "changes", -1) if meta is not None else -1
        return D1Cursor(lastrowid=lastrowid, rowcount=changes)

    def executescript(self, script):
        cursor = None
        for statement in script.split(";"):
            if statement.strip():
                cursor = self.execute(statement)
        return cursor or D1Cursor()

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
