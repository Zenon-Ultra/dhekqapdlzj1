"""Immutable B2 objects and an atomic catalog. Explicit book deletion purges versions.
Use one Render instance/worker; the file lock serializes its editing requests.
"""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote
from services.config import load_settings
load_settings()
from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
IMAGE_MIME = {'.webp':'image/webp','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.bmp':'image/bmp'}
def content_type(filename):
    return IMAGE_MIME.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def safe_component(value):
    if not value or value in ('.', '..') or any(c in value for c in '/\\\x00:'):
        raise ValueError('Invalid folder or filename')
    return value

class Store:
    def __init__(self, root=ROOT, client=None):
        self.root = Path(root)
        self.enabled = os.environ.get('STORAGE_BACKEND', 'local') == 'b2'
        self.client = client
        self.entries = {}
        self.deleted_books = set()
        self.pending_deletions = {}
        self.bucket = os.environ.get('B2_BUCKET', '')
        self.prefix = os.environ.get('B2_PREFIX', 'hyperx').strip('/')
        self.lock = FileLock(str(self.root / '.storage.lock'))

    def s3(self):
        if self.client is None:
            import boto3
            from botocore.config import Config
            endpoint = os.environ['B2_ENDPOINT_URL']
            if not endpoint.startswith('https://') or not endpoint.endswith('.backblazeb2.com'):
                raise ValueError('Expected HTTPS Backblaze S3 endpoint')
            self.client = boto3.client('s3', endpoint_url=endpoint,
                region_name=os.environ['B2_REGION'],
                config=Config(connect_timeout=5, read_timeout=15, retries={'max_attempts': 1}),
                aws_access_key_id=os.environ['B2_KEY_ID'],
                aws_secret_access_key=os.environ['B2_APPLICATION_KEY'])
        return self.client

    def key(self, name): return self.prefix + '/' + name

    def read(self, key):
        return self.s3().get_object(Bucket=self.bucket, Key=key)['Body'].read()

    def restore(self, materialize=True):
        if not self.enabled: return
        try:
            data = json.loads(self.read(self.key('catalog.json')))
        except Exception as exc:
            # Only an explicitly missing catalog means a new installation.
            if getattr(exc, 'response', {}).get('Error', {}).get('Code') not in ('NoSuchKey', '404'):
                raise
            return
        if data.get('version') != 1 or not isinstance(data.get('files'), dict):
            raise ValueError('Invalid catalog')
        for rel, entry in data['files'].items():
            self.path(rel)
            digest = entry.get('sha256', '')
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid object checksum')
            if entry.get('key') != self.key('objects/' + digest):
                raise ValueError('Object outside configured prefix')
        self.entries = {k:v for k,v in data['files'].items() if k != 'templates/main.html'}
        deleted = data.get('deleted_books', [])
        if not isinstance(deleted, list): raise ValueError('Invalid deleted book list')
        self.deleted_books = {safe_component(name) for name in deleted}
        self.pending_deletions = data.get('pending_deletions', {})
        if not isinstance(self.pending_deletions, dict): raise ValueError('Invalid deletion jobs')
        for folder, keys in self.pending_deletions.items():
            safe_component(folder)
            if not isinstance(keys, list): raise ValueError('Invalid deletion keys')
            for key in keys:
                digest = key.rsplit('/', 1)[-1]
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or key != self.key('objects/'+digest):
                    raise ValueError('Invalid deletion object')
        if not materialize: return
        for folder in self.deleted_books: self._archive_book_files(folder)
        for path in (self.root/'img').rglob('*'):
            if path.is_file() and path.stat().st_size == 0 and path.relative_to(self.root).as_posix() not in self.entries:
                path.unlink()
        for rel, entry in self.entries.items():
            path = self.path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            if rel.startswith('img/') and Path(rel).suffix.lower() != '.json':
                if not path.exists(): path.touch()  # directory listings without disk usage
            else:
                path.write_bytes(self.verified(entry))

    def path(self, rel):
        if not (rel.startswith('img/') or rel.startswith('textbooks/') or rel == 'templates/main.html'):
            raise ValueError('Invalid catalog path')
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()): raise ValueError('Unsafe path')
        return path

    def verified(self, entry):
        data = self.read(entry['key'])
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Object checksum mismatch')
        return data

    def serve_entry(self, entry, filename):
        from flask import Response
        data = self.verified(entry)
        response = Response(data, mimetype=content_type(filename))
        response.headers['Cache-Control'] = 'private, max-age=300'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.set_etag(entry['sha256'])
        return response

    def freeze_scraps(self, folder):
        from services.database import connect
        db_path = os.environ.get('DB_PATH', str(self.root/'admin.db'))
        with connect(db_path) as conn:
            c = conn.cursor()
            c.execute('SELECT id, image_file FROM scraps WHERE book_folder=? AND snapshot_key IS NULL', (folder,))
            for scrap_id, filename in c.fetchall():
                entry = self.entries.get('img/'+folder+'/'+filename.split('/')[-1])
                if not self.enabled:
                    path = self.root/'img'/folder/filename.split('/')[-1]
                    if path.is_file():
                        data = path.read_bytes()
                        digest = hashlib.sha256(data).hexdigest()
                        target = self.root/'cloud-objects'/digest
                        target.parent.mkdir(exist_ok=True)
                        if not target.exists(): target.write_bytes(data)
                        entry = {'key': self.key('objects/'+digest)}
                if entry:
                    c.execute('UPDATE scraps SET snapshot_key=? WHERE id=?', (entry['key'], scrap_id))
            conn.commit()

    def hydrate(self, folder):
        safe_component(folder)
        # Preserve failed-edit remnants before rebuilding the local working copy.
        directory = self.root/'img'/folder
        if not any(k.startswith('img/'+folder+'/') for k in self.entries):
            return
        extras = [p for p in directory.glob('*') if p.is_file() and p.relative_to(self.root).as_posix() not in self.entries]
        if extras:
            import shutil, uuid
            recovery = self.root/'.storage-recovery'/uuid.uuid4().hex/folder
            recovery.mkdir(parents=True)
            for path in extras:
                shutil.copy2(path, recovery/path.name)
                path.unlink()
        for rel, entry in self.entries.items():
            if rel.startswith('img/' + folder + '/'):
                self.path(rel).write_bytes(self.verified(entry))

    def publish(self, folders, progress=None):
        if not self.enabled: return
        if self.pending_deletions:
            raise ValueError('Finish pending book deletion before publishing more files')
        entries = dict(self.entries)
        for folder in folders:
            safe_component(folder)
            entries = {k:v for k,v in entries.items() if not k.startswith('img/' + folder + '/')}
        paths = [p for folder in folders for p in (self.root/'img'/folder).glob('*') if p.is_file()]
        paths += list((self.root/'textbooks').glob('*'))
        # Application templates are code; restore only generated textbooks and image data.
        total = sum(p.stat().st_size for p in paths if p.is_file())
        if total > int(os.environ.get('B2_MAX_BATCH_BYTES', '500000000')):
            raise ValueError('Batch exceeds upload budget; publish fewer books')
        paths = [path for path in paths if path.is_file()]
        client = self.s3()
        mode = os.environ.get('B2_UPLOAD_VERIFICATION', 'readback')
        if mode not in ('readback', 'etag'):
            raise ValueError('Unknown upload verification mode')
        def upload(path):
            rel = path.relative_to(self.root).as_posix()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            old = self.entries.get(rel)
            if old and old['sha256'] == digest:
                return rel, old
            key = self.key('objects/' + digest)
            import base64
            md5 = hashlib.md5(data).digest()
            response = client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type(path.name), ContentMD5=base64.b64encode(md5).decode('ascii')) or {}
            entry = {'key':key, 'sha256':digest, 'size':len(data)}
            if mode == 'etag':
                if response.get('ETag', '').strip(chr(34)) != md5.hex():
                    raise ValueError('Server object MD5 mismatch; catalog unchanged')
                entry['verification'] = 'content-md5-and-etag'
            elif self.verified(entry) != data:
                raise ValueError('Upload verification failed')
            else:
                entry['verification'] = 'sha256-readback'
            return rel, entry
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(8, int(os.environ.get('B2_UPLOAD_WORKERS', '2'))))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for index, (rel, entry) in enumerate(executor.map(upload, paths), 1):
                entries[rel] = entry
                if progress: progress(index, len(paths), rel)
        deleted = self.deleted_books.difference(folders)
        self._commit_catalog(entries, deleted)

    def _commit_catalog(self, entries, deleted, pending=None):
        pending = self.pending_deletions if pending is None else pending
        payload = json.dumps({'version':1, 'files':entries, 'deleted_books':sorted(deleted), 'pending_deletions':pending}, ensure_ascii=False).encode()
        # Keep a recoverable immutable catalog before switching the live catalog.
        self.s3().put_object(Bucket=self.bucket, Key=self.key('snapshots/'+hashlib.sha256(payload).hexdigest()+'.json'), Body=payload)
        self.s3().put_object(Bucket=self.bucket, Key=self.key('catalog.json'), Body=payload, ContentType='application/json')
        self.entries = entries
        self.deleted_books = set(deleted)
        self.pending_deletions = dict(pending)

    def book_asset_names(self, folder):
        from book_assets import slugify
        return {name+suffix for name in (folder, slugify(folder)) for suffix in ('.html', '.json')}

    def is_deleted_asset(self, filename):
        return any(filename in self.book_asset_names(folder) for folder in self.deleted_books)

    def _archive_book_files(self, folder):
        """Move working files out of the app; keep recoverable originals locally."""
        import shutil, uuid
        paths = [self.root/'img'/folder, self.root/'uploads'/(folder+'.pdf')]
        paths += [self.root/'textbooks'/name for name in self.book_asset_names(folder)]
        archive = self.root/'.storage-deleted'/uuid.uuid4().hex
        for path in paths:
            if path.exists():
                target = archive/path.relative_to(self.root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))

    def delete_book(self, folder):
        from services.book_deletion import delete_book
        return delete_book(self, folder)

    def evict(self, folders):
        for folder in folders:
            for rel in self.entries:
                if rel.startswith('img/'+folder+'/') and Path(rel).suffix.lower() != '.json':
                    self.path(rel).write_bytes(b'')

    def serve(self, filename):
        from flask import send_from_directory
        rel = 'img/' + filename
        self.path(rel)
        if filename.split('/')[0] in self.deleted_books:
            from flask import abort
            abort(404)
        if self.enabled and rel in self.entries:
            return self.serve_entry(self.entries[rel], filename)
        return send_from_directory(self.root/'img', filename)

store = Store()

def durable_task(func, plural=False):
    from functools import wraps
    @wraps(func)
    def wrapped(first, *args, **kwargs):
        folders = first if plural else [first]
        for folder in folders: safe_component(folder)
        if not store.enabled:
            for message in func(first, *args, **kwargs):
                if json.loads(message.removeprefix('data: ').strip()).get('error'):
                    raise ValueError('Editing failed: '+message)
                yield message
            return
        with store.lock:
            for folder in folders:
                store.freeze_scraps(folder)
                store.hydrate(folder)
            messages = list(func(first, *args, **kwargs))
            if any('🚨' in message or '⚠️' in message for message in messages):
                raise RuntimeError('Editing failed; remote catalog unchanged, local files retained')
            if func.__name__ in ('split_image_task', 'merge_images_task', 'delete_image_task'):
                from book_assets import generate_book_assets
                for folder in folders:
                    generate_book_assets(folder, image_dir=store.root/'img'/folder,
                        output_dir=store.root/'textbooks', index_path=store.root/'templates'/'main.html', allow_empty=True)
            store.publish(folders)
            store.evict(folders)
            yield from messages
    return wrapped
