"""Immutable B2 objects and an atomic catalog. No remote object is ever deleted.
Use one Render instance/worker; the file lock serializes its editing requests.
"""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote
from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]

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
        self.bucket = os.environ.get('B2_BUCKET', '')
        self.prefix = os.environ.get('B2_PREFIX', 'hyperx').strip('/')
        self.lock = FileLock(str(self.root / '.storage.lock'))

    def s3(self):
        if self.client is None:
            import boto3
            endpoint = os.environ['B2_ENDPOINT_URL']
            if not endpoint.startswith('https://') or not endpoint.endswith('.backblazeb2.com'):
                raise ValueError('Expected HTTPS Backblaze S3 endpoint')
            self.client = boto3.client('s3', endpoint_url=endpoint,
                region_name=os.environ['B2_REGION'],
                aws_access_key_id=os.environ['B2_KEY_ID'],
                aws_secret_access_key=os.environ['B2_APPLICATION_KEY'])
        return self.client

    def key(self, name): return self.prefix + '/' + name

    def read(self, key):
        return self.s3().get_object(Bucket=self.bucket, Key=key)['Body'].read()

    def restore(self):
        if not self.enabled: return
        try:
            data = json.loads(self.read(self.key('catalog.json')))
        except Exception as exc:
            # Only an explicitly missing catalog means a new installation.
            if getattr(exc, 'response', {}).get('Error', {}).get('Code') not in ('NoSuchKey', '404'):
                raise
            return
        self.entries = data['files']
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

    def snapshot_url(self, key):
        return self.s3().generate_presigned_url('get_object', Params={'Bucket':self.bucket,'Key':key}, ExpiresIn=3600) if self.enabled else None

    def freeze_scraps(self, folder):
        from services.database import connect
        db_path = os.environ.get('DB_PATH', str(self.root/'admin.db'))
        with connect(db_path) as conn:
            c = conn.cursor()
            c.execute('SELECT id, image_file FROM scraps WHERE book_folder=? AND snapshot_key IS NULL', (folder,))
            for scrap_id, filename in c.fetchall():
                entry = self.entries.get('img/'+folder+'/'+filename.split('/')[-1])
                if entry:
                    c.execute('UPDATE scraps SET snapshot_key=? WHERE id=?', (entry['key'], scrap_id))
            conn.commit()

    def hydrate(self, folder):
        safe_component(folder)
        for rel, entry in self.entries.items():
            if rel.startswith('img/' + folder + '/'):
                self.path(rel).write_bytes(self.verified(entry))

    def publish(self, folders):
        if not self.enabled: return
        entries = dict(self.entries)
        for folder in folders:
            safe_component(folder)
            entries = {k:v for k,v in entries.items() if not k.startswith('img/' + folder + '/')}
        paths = [p for folder in folders for p in (self.root/'img'/folder).glob('*') if p.is_file()]
        paths += list((self.root/'textbooks').glob('*'))
        paths += [self.root/'templates'/'main.html']
        total = sum(p.stat().st_size for p in paths if p.is_file())
        if total > int(os.environ.get('B2_MAX_BATCH_BYTES', '500000000')):
            raise ValueError('Batch exceeds upload budget; publish fewer books')
        for path in paths:
            if not path.is_file(): continue
            rel = path.relative_to(self.root).as_posix()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            old = self.entries.get(rel)
            if old and old['sha256'] == digest:
                entries[rel] = old
                continue
            key = self.key('objects/' + digest)
            self.s3().put_object(Bucket=self.bucket, Key=key, Body=data,
                ContentType=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            entry = {'key':key, 'sha256':digest, 'size':len(data)}
            if self.verified(entry) != data: raise ValueError('Upload verification failed')
            entries[rel] = entry
        payload = json.dumps({'version':1, 'files':entries}, ensure_ascii=False).encode()
        # Keep a recoverable immutable catalog before switching the live catalog.
        self.s3().put_object(Bucket=self.bucket, Key=self.key('snapshots/'+hashlib.sha256(payload).hexdigest()+'.json'), Body=payload)
        self.s3().put_object(Bucket=self.bucket, Key=self.key('catalog.json'), Body=payload, ContentType='application/json')
        self.entries = entries

    def evict(self, folders):
        for folder in folders:
            for rel in self.entries:
                if rel.startswith('img/'+folder+'/') and Path(rel).suffix.lower() != '.json':
                    self.path(rel).write_bytes(b'')

    def serve(self, filename):
        from flask import redirect, send_from_directory, abort
        rel = 'img/' + filename
        self.path(rel)
        if self.enabled and rel in self.entries:
            url = self.s3().generate_presigned_url('get_object', Params={'Bucket':self.bucket,'Key':self.entries[rel]['key']}, ExpiresIn=3600)
            response = redirect(url)
            response.headers['Cache-Control'] = 'private, max-age=300'
            return response
        return send_from_directory(self.root/'img', filename)

store = Store()

def durable_task(func, plural=False):
    from functools import wraps
    @wraps(func)
    def wrapped(first, *args, **kwargs):
        folders = first if plural else [first]
        for folder in folders: safe_component(folder)
        if not store.enabled:
            yield from func(first, *args, **kwargs)
            return
        with store.lock:
            for folder in folders:
                store.freeze_scraps(folder)
                store.hydrate(folder)
            messages = list(func(first, *args, **kwargs))
            if any('🚨' in message or '⚠️' in message for message in messages):
                raise RuntimeError('Editing failed; remote catalog unchanged, local files retained')
            store.publish(folders)
            store.evict(folders)
            yield from messages
    return wrapped
