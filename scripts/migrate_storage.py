"""Non-destructive image migration. Run from repository root; dry-run by default."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.storage import store

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    folders = sorted(p.name for p in (store.root/'img').iterdir() if p.is_dir())
    files = [p for f in folders for p in (store.root/'img'/f).iterdir() if p.is_file()]
    inventory = {p.relative_to(store.root).as_posix(): {'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}
    Path('.migration-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(folders)} books, {len(files)} files, {sum(v["size"] for v in inventory.values())} bytes')
    if args.apply:
        if not store.enabled: raise RuntimeError('Set STORAGE_BACKEND=b2')
        if any(v['size']==0 for v in inventory.values()): raise RuntimeError('Use a full original img checkout, not placeholders')
        # Refuse to overwrite an existing remote catalog; inspect/restore it first.
        store.restore()
        if store.entries: raise RuntimeError('Remote catalog already exists; migration aborted')
        with store.lock: store.publish(folders)
        print('Uploaded and verified; original files preserved')
    if args.verify:
        store.restore()
        for rel, entry in store.entries.items():
            store.verified(entry)
        print(f'Verified {len(store.entries)} remote objects')
if __name__ == '__main__': main()
