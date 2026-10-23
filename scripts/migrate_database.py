"""Copy SQLite to an EMPTY PostgreSQL DB, retaining IDs and source data.
Back up admin.db first; DATABASE_URL must point to the new database.
"""
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
TABLES = ('users', 'book_requests', 'scraps', 'system_config')
def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('source')
    p.add_argument('--apply', action='store_true')
    a=p.parse_args()
    source=sqlite3.connect('file:'+str(Path(a.source).resolve())+'?mode=ro',uri=True)
    with psycopg.connect(os.environ['DATABASE_URL']) as target:
        for table in TABLES:
            columns=[r[1] for r in source.execute('PRAGMA table_info('+table+')')]
            rows=source.execute('SELECT * FROM '+table).fetchall()
            print(table,len(rows))
            if not a.apply: continue
            schema=source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0]
            schema=schema.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ',1).replace('INTEGER PRIMARY KEY AUTOINCREMENT','SERIAL PRIMARY KEY')
            target.execute(schema)
            if target.execute('SELECT count(*) FROM '+table).fetchone()[0]:
                raise RuntimeError('Destination must be empty; transaction rolled back')
            from psycopg import sql
            statement=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder()*len(columns)))
            with target.cursor() as c: c.executemany(statement,rows)
            actual=target.execute('SELECT '+','.join(columns)+' FROM '+table).fetchall()
            if sorted(map(repr,actual)) != sorted(map(repr,rows)):
                # PostgreSQL timestamps are datetime objects; normalize for comparison.
                norm=lambda rs: sorted(tuple(str(v) for v in r) for r in rs)
                if norm(actual)!=norm(rows): raise RuntimeError('Row verification failed')
            if 'id' in columns:
                target.execute("SELECT setval(pg_get_serial_sequence(%s,'id'), GREATEST(COALESCE((SELECT MAX(id) FROM "+table+"),0),1), EXISTS(SELECT 1 FROM "+table+"))",(table,))
    source.close()
if __name__=='__main__': main()
