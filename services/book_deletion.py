"""Explicit whole-book purge, including B2 versions, with a durable retry plan."""
import json
from services.database import connect
from services.storage import safe_component
import os


def _database(storage):
    return connect(os.environ.get('DB_PATH', str(storage.root/'admin.db')))


def _matching(storage, folder, relative_path):
    return relative_path.startswith('img/'+folder+'/') or relative_path in {
        'textbooks/'+name for name in storage.book_asset_names(folder)}


def _version_list(storage):
    versions = []
    for page in storage.s3().get_paginator('list_object_versions').paginate(
            Bucket=storage.bucket, Prefix=storage.prefix+'/'):
        versions.extend(page.get('Versions', []))
        versions.extend(page.get('DeleteMarkers', []))
    return versions


def _plan(storage, folder, versions):
    candidates, protected = set(), set()
    catalogs = [storage.entries]
    snapshot_keys = {v['Key'] for v in versions if v['Key'].startswith(storage.key('snapshots/'))}
    for key in sorted(snapshot_keys):
        # Catalog snapshots are content addressed; reject corruption before deleting anything.
        import hashlib
        content = storage.read(key)
        if hashlib.sha256(content).hexdigest() != key.rsplit('/', 1)[-1].removesuffix('.json'):
            raise ValueError('Snapshot checksum mismatch; nothing deleted')
        catalogs.append(json.loads(content)['files'])
    for entries in catalogs:
        for path, entry in entries.items():
            if not _matching(storage, folder, path) and any(_matching(storage, deleted, path) for deleted in storage.deleted_books):
                continue
            key = entry['key']
            digest = entry['sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or key != storage.key('objects/'+digest):
                raise ValueError('Invalid object in deletion inventory')
            (candidates if _matching(storage, folder, path) else protected).add(key)
    with _database(storage) as connection:
        cursor = connection.cursor()
        cursor.execute('SELECT book_folder,snapshot_key FROM scraps WHERE snapshot_key IS NOT NULL')
        for book, key in cursor.fetchall():
            (candidates if book == folder else protected).add(key)
    # Shared content is retained for other books and their historical snapshots/scraps.
    keys = candidates - protected
    for key in keys:
        digest = key.rsplit('/', 1)[-1]
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or key != storage.key('objects/'+digest):
            raise ValueError('Deletion key outside object prefix')
    return sorted(keys), len(candidates & protected)


def _purge(storage, keys, versions):
    targets = [{'Key':v['Key'], 'VersionId':v['VersionId']} for v in versions if v['Key'] in keys]
    for start in range(0, len(targets), 1000):
        response = storage.s3().delete_objects(Bucket=storage.bucket,
            Delete={'Objects':targets[start:start+1000], 'Quiet':True})
        if response.get('Errors'):
            raise RuntimeError('B2 deletion incomplete; retry this book to finish')
    remaining = [v for v in _version_list(storage) if v['Key'] in keys]
    if remaining: raise RuntimeError('B2 versions remain; retry this book to finish')
    return len(targets)


def delete_book(storage, folder):
    safe_component(folder)
    with storage.lock:
        if folder not in storage.pending_deletions and not (storage.root/'img'/folder).is_dir() and not any(k.startswith('img/'+folder+'/') for k in storage.entries):
            raise FileNotFoundError('Book not found')
        for sibling in (storage.root/'img').glob('*'):
            if sibling.is_dir() and sibling.name != folder and storage.book_asset_names(folder).intersection(storage.book_asset_names(sibling.name)):
                raise ValueError('Another book shares generated filenames; rename it first')
        deleted_versions, shared = 0, 0
        if storage.enabled:
            versions = _version_list(storage)
            if folder not in storage.pending_deletions:
                keys, shared = _plan(storage, folder, versions)
                entries = {k:v for k,v in storage.entries.items() if not _matching(storage, folder, k)}
                pending = dict(storage.pending_deletions, **{folder:keys})
                # Persist the exact purge plan before the first irreversible operation.
                storage._commit_catalog(entries, storage.deleted_books | {folder}, pending)
            keys = set(storage.pending_deletions[folder])
        with _database(storage) as connection:
            cursor = connection.cursor()
            cursor.execute('DELETE FROM scraps WHERE book_folder=?', (folder,))
            scraps_deleted = cursor.rowcount
            connection.commit()
        if storage.enabled:
            deleted_versions = _purge(storage, keys, versions)
            pending = {k:v for k,v in storage.pending_deletions.items() if k != folder}
            storage._commit_catalog(storage.entries, storage.deleted_books, pending)
        # Preserve the independent local original backup; remove these working assets from the app.
        storage._archive_book_files(folder)
        return {'deleted_versions':deleted_versions, 'shared_objects_retained':shared, 'scraps_deleted':scraps_deleted}
