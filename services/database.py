"""SQLite locally, PostgreSQL (e.g. Neon Free) in production."""
import os
import sqlite3
from contextlib import contextmanager

class Cursor:
    def __init__(self, cursor): self.raw = cursor
    def execute(self, sql, params=()):
        sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        sql = sql.replace("ADD COLUMN role", "ADD COLUMN IF NOT EXISTS role").replace("ADD COLUMN snapshot_key", "ADD COLUMN IF NOT EXISTS snapshot_key")
        self.raw.execute(sql.replace('?', '%s'), params)
        return self
    def __getattr__(self, name): return getattr(self.raw, name)

class Connection:
    def __init__(self, raw): self.raw = raw
    def cursor(self): return Cursor(self.raw.cursor())
    def commit(self): self.raw.commit()

@contextmanager
def connect(path):
    url = os.environ.get('DATABASE_URL')
    if url:
        import psycopg
        with psycopg.connect(url) as raw:
            yield Connection(raw)
    else:
        if os.environ.get('RENDER'):
            raise RuntimeError('DATABASE_URL is required on ephemeral Render hosting')
        raw = sqlite3.connect(path)
        try:
            with raw: yield raw
        finally: raw.close()
