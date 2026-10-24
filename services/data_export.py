"""Consistent, portable snapshots of application tables; no cloud credentials exported."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

TABLES = ('users', 'book_requests', 'scraps', 'system_config')
SCHEMA = (
    "CREATE TABLE users (username TEXT PRIMARY KEY, password TEXT, role TEXT DEFAULT 'user')",
    "CREATE TABLE book_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, book_name TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE scraps (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, book_folder TEXT NOT NULL, book_title TEXT NOT NULL, image_file TEXT NOT NULL, question_num INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, snapshot_key TEXT, UNIQUE(username,book_folder,image_file))",
    'CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)',
)

def database_snapshot(path):
    url = os.environ.get('DATABASE_URL')
    if url:
        import psycopg
        connection = psycopg.connect(url)
    else:
        connection = sqlite3.connect('file:'+Path(path).resolve().as_posix()+'?mode=ro', uri=True)
    with closing(connection) as conn:
        if url: conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        else: conn.execute('BEGIN')
        tables = {}
        for table in TABLES:
            cursor = conn.execute('SELECT * FROM '+table)
            tables[table] = {'columns':[col[0] for col in cursor.description],
                'rows':[[v.isoformat(sep=' ') if hasattr(v,'isoformat') else v for v in row] for row in cursor.fetchall()]}
        conn.rollback()
    return {'version':1, 'tables':tables}

def restore_sqlite(snapshot, path):
    path = Path(path)
    # Exclusive creation prevents overwriting any original database.
    with path.open('xb'): pass
    try:
        with closing(sqlite3.connect(path)) as conn:
            with conn:
                for schema in SCHEMA: conn.execute(schema)
                for table in TABLES:
                    data = snapshot['tables'][table]
                    allowed = {r[1] for r in conn.execute('PRAGMA table_info('+table+')')}
                    if not set(data['columns']) <= allowed: raise ValueError('Unknown backup columns')
                    columns = ','.join('"'+c+'"' for c in data['columns'])
                    conn.executemany('INSERT INTO '+table+' ('+columns+') VALUES ('+','.join('?' for _ in data['columns'])+')', data['rows'])
                    actual = conn.execute('SELECT '+columns+' FROM '+table).fetchall()
                    if sorted(map(repr,actual)) != sorted(map(lambda row:repr(tuple(row)),data['rows'])):
                        raise ValueError('Restored rows failed verification')
    except Exception:
        # Leave the failed new restore for investigation; original is never touched.
        raise
