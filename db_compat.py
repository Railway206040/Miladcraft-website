"""Small compatibility layer for the site's existing SQLite-style SQL on PostgreSQL."""
import re
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import DictCursor


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def lastrowid(self):
        with self._cursor.connection.cursor() as cur:
            cur.execute("SELECT LASTVAL()")
            return cur.fetchone()[0]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class Connection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = sql.strip()
        # SQLite schema inspection -> PostgreSQL information_schema.
        if "sqlite_master" in sql:
            if "SELECT sql FROM sqlite_master" in sql:
                sql = "SELECT '' AS sql FROM information_schema.tables WHERE table_schema='public' AND table_name=%s"
            else:
                sql = "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s"
        elif sql.upper().startswith("PRAGMA TABLE_INFO"):
            table = re.search(r"PRAGMA\s+table_info\(([^)]+)\)", sql, re.I).group(1).strip("'")
            sql = "SELECT column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s"
            params = (table,)
        else:
            ignore_conflict = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", sql, re.I))
            sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.I)
            sql = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", sql, flags=re.I)
            sql = re.sub(r"\s+COLLATE\s+NOCASE", "", sql, flags=re.I)
            sql = sql.replace("?", "%s")
            if ignore_conflict:
                sql += " ON CONFLICT DO NOTHING"
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return Cursor(cur)

    def executescript(self, script):
        # DDL in init_db consists of ordinary semicolon-separated statements.
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                statement = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", statement, flags=re.I)
                statement = re.sub(r"\s+COLLATE\s+NOCASE", "", statement, flags=re.I)
                statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()
        return False


def connect(database_url):
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor, connect_timeout=15)
    conn.autocommit = False
    return Connection(conn)


IntegrityError = psycopg2.IntegrityError
