"""On-demand usage measurements. Never enumerate remote object versions."""
import os
import shutil
from datetime import datetime, timezone
from services.database import connect


def storage_usage(storage, db_path):
    postgres = bool(os.environ.get('DATABASE_URL'))
    with connect(db_path) as connection:
        cursor = connection.cursor()
        if postgres:
            cursor.execute('SELECT pg_database_size(current_database())')
            database_bytes = cursor.fetchone()[0]
        else:
            cursor.execute('PRAGMA page_count')
            pages = cursor.fetchone()[0]
            cursor.execute('PRAGMA page_size')
            database_bytes = pages * cursor.fetchone()[0]
        counts = {}
        for table in ('users', 'scraps', 'book_requests'):
            cursor.execute('SELECT COUNT(*) FROM '+table)
            counts[table] = cursor.fetchone()[0]
    if storage.enabled:
        active_bytes = sum(entry['size'] for entry in storage.entries.values())
        files = len(storage.entries)
        books = len({path.split('/')[1] for path in storage.entries if path.startswith('img/')})
    else:
        paths = [p for name in ('img','textbooks') for p in (storage.root/name).rglob('*') if p.is_file() and not p.is_symlink()]
        active_bytes = sum(path.stat().st_size for path in paths)
        files = len(paths)
        books = sum(p.is_dir() for p in (storage.root/'img').glob('*'))
    disk = shutil.disk_usage(storage.root)
    return {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'database': {'backend': 'PostgreSQL' if postgres else 'SQLite', 'bytes': database_bytes,
                     'free_limit_bytes': int(os.environ.get('DB_FREE_STORAGE_BYTES','1000000000')) if postgres else None,
                     'counts': counts},
        'assets': {'backend': 'Backblaze B2' if storage.enabled else '로컬', 'active_bytes': active_bytes,
                   'files': files, 'books': books, 'includes_history': False},
        'server_disk': {'total_bytes': disk.total, 'used_bytes': disk.used, 'free_bytes': disk.free},
    }
