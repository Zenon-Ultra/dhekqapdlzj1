"""Complete ZIP backup of local/cloud assets and a consistent portable database export."""
import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

EXCLUDE_DIRS = {'.git','__pycache__','venv','.venv','node_modules','scratch','tmp','temp','.gemini','.agents','.codex'}
EXCLUDE_FILES = {'.env','.git_sync.lock','.DS_Store','database.json','backup-manifest.json'}
def backup_directory():
    from services.storage import store
    path=Path(os.environ.get('BACKUP_DIRECTORY',str(store.root/'.storage-backup')))
    path.mkdir(parents=True,exist_ok=True)
    return path

def _write_status(data):
    try:
        path=backup_directory()/'status.json'
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data),encoding='utf-8')
        os.replace(tmp,path)
    except OSError:
        # The single-worker in-memory state remains available even on a read-only disk.
        pass

def read_zip_status():
    try: return json.loads((backup_directory()/'status.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return {'running':False,'ready':False,'error':None}

def get_seoul_now_str():
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d_%H-%M-%S')

def _collect_files(root_dir):
    files=[]
    for directory, dirs, names in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for name in names:
            path=Path(directory)/name
            if name in EXCLUDE_FILES or name.startswith('.env') or name.startswith('.') or path.suffix in ('.zip','.pyc','.pyo','.db') or '.db-' in name: continue
            if path.is_symlink(): continue
            files.append((str(path),path.relative_to(root_dir).as_posix()))
    return files

def create_project_zip(root_dir, progress_callback=None, storage=None):
    from services.storage import store
    from services.data_export import database_snapshot
    storage = storage or store
    root=Path(root_dir)
    filename=f'HYPERX_Backup_{get_seoul_now_str()}_{uuid.uuid4().hex[:6]}.zip'
    output=backup_directory()/filename
    budget=int(os.environ.get('BACKUP_MAX_BYTES','500000000'))
    # Freeze edits for a coherent assets + DB view. No mass hydration on disk.
    with storage.lock:
        entries=dict(storage.entries) if storage.enabled else {}
        local=[(p,rel) for p,rel in _collect_files(root) if rel not in entries]
        size=sum(Path(p).stat().st_size for p,_ in local)+sum(e.get('size',0) for e in entries.values())
        if size>budget: raise ValueError('Backup exceeds BACKUP_MAX_BYTES; export fewer books separately')
        snapshot=database_snapshot(os.environ.get('DB_PATH',str(root/'admin.db')))
        db_bytes=json.dumps(snapshot,ensure_ascii=False).encode('utf-8')
        if size+len(db_bytes)>budget: raise ValueError('Backup including database exceeds budget')
        inventory={}
        try:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
                written=0
                def put(rel,data):
                    nonlocal written
                    written += len(data)
                    if written > budget: raise ValueError('Backup exceeded byte budget')
                    archive.writestr(rel,data)
                    inventory[rel]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                for idx,(path,rel) in enumerate(local):
                    put(rel,Path(path).read_bytes())
                    if progress_callback: progress_callback(idx+1,len(local)+len(entries)+1,rel)
                for idx,(rel,entry) in enumerate(entries.items(),start=len(local)+1):
                    put(rel,storage.verified(entry))
                    if progress_callback: progress_callback(idx,len(local)+len(entries)+1,rel)
                # Include historical images referenced by scraps even after renumber/delete.
                for row in snapshot['tables']['scraps']['rows']:
                    columns=snapshot['tables']['scraps']['columns']
                    key=row[columns.index('snapshot_key')] if 'snapshot_key' in columns else None
                    if key and storage.enabled:
                        digest=key.rsplit('/',1)[-1]
                        if key!=storage.key('objects/'+digest): raise ValueError('Invalid scrap snapshot key')
                        rel='cloud-objects/'+digest
                        if rel not in inventory: put(rel,storage.verified({'key':key,'sha256':digest}))
                put('database.json',db_bytes)
                archive.writestr('backup-manifest.json',json.dumps({'version':1,'files':inventory},ensure_ascii=False))
            if output.stat().st_size>budget: raise ValueError('Backup exceeded byte budget')
        except Exception:
            output.unlink(missing_ok=True)
            raise
    if progress_callback: progress_callback(1,1,'complete')
    return str(output),filename
