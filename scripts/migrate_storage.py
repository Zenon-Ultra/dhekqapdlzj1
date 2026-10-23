"""Non-destructive, resumable migration; cloud verification never rewrites originals."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.storage import store

def migrate(storage, apply=False, resume=False, verify=False):
    folders=sorted(p.name for p in (storage.root/'img').glob('*') if p.is_dir())
    files=[p for folder in folders for p in (storage.root/'img'/folder).glob('*') if p.is_file()]
    inventory={p.relative_to(storage.root).as_posix():{'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}
    print(f'{len(folders)} books, {len(files)} files, {sum(v["size"] for v in inventory.values())} bytes')
    if apply or verify:
        if not storage.enabled: raise RuntimeError('Set STORAGE_BACKEND=b2')
        storage.restore(materialize=False)
    if apply:
        if not inventory or any(v['size']==0 for v in inventory.values()): raise RuntimeError('Use a full original image checkout')
        if storage.entries and not resume: raise RuntimeError('Remote catalog exists; use --resume after reviewing inventory')
        for rel,entry in storage.entries.items():
            if rel.startswith('img/') and (rel not in inventory or inventory[rel]['sha256']!=entry['sha256']):
                raise RuntimeError('Existing remote data differs: '+rel)
        for folder in folders:
            with storage.lock: storage.publish([folder])
    if verify:
        for rel,entry in storage.entries.items(): storage.verified(entry)
        for rel,expected in inventory.items():
            actual=storage.entries.get(rel)
            if not actual or actual['sha256']!=expected['sha256'] or actual['size']!=expected['size']:
                raise ValueError('Inventory mismatch: '+rel)
        print('Remote checksums and source inventory verified')
    return inventory

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--verify',action='store_true')
    a=p.parse_args();inventory=migrate(store,a.apply,a.resume,a.verify)
    Path('.migration-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
