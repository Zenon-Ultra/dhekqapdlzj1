"""Verify a backup and restore to a NEW directory only; originals are never overwritten."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.data_export import restore_sqlite

def restore(archive_path, destination=None):
    with zipfile.ZipFile(archive_path) as archive:
        manifest=json.loads(archive.read('backup-manifest.json'))
        if manifest.get('version')!=1: raise ValueError('Unsupported backup version')
        names=archive.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate backup entries')
        if set(names)!=set(manifest['files'])|{'backup-manifest.json'}: raise ValueError('Unlisted backup entries')
        for name,entry in manifest['files'].items():
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name: raise ValueError('Unsafe backup path')
            data=archive.read(name)
            if len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']: raise ValueError('Backup checksum mismatch: '+name)
        if destination:
            destination=Path(destination)
            destination.mkdir(parents=True,exist_ok=False)
            for name in manifest['files']:
                target=destination/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(name))
            snapshot=json.loads(archive.read('database.json'))
            # Offline restored scraps must refer to restored immutable bytes, not live B2.
            scraps=snapshot['tables']['scraps']
            if 'snapshot_key' in scraps['columns']:
                key_idx=scraps['columns'].index('snapshot_key'); file_idx=scraps['columns'].index('image_file')
                for row in scraps['rows']:
                    if row[key_idx]:
                        digest=row[key_idx].rsplit('/',1)[-1]
                        source=destination/'cloud-objects'/digest
                        if not source.is_file(): raise ValueError('Missing scrap history object')
                        name=Path(row[file_idx]).name
                        rel='img/_restored_scraps/'+digest+'/'+name
                        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(source.read_bytes())
                        row[file_idx]='/'+rel;row[key_idx]=None
            restore_sqlite(snapshot,destination/'admin.db')
        return len(manifest['files'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--destination')
    a=p.parse_args();print('Verified',restore(a.archive,a.destination),'files')
