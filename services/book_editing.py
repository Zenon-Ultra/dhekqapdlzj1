"""Edit selected B2 images; renumber other images by changing catalog references."""
import re
import shutil
import tempfile
import uuid
from pathlib import Path
import cv2
import numpy as np
from services.storage import safe_component

NUMBERED = re.compile(r'^(\d+)\.(png|webp|jpg|jpeg|bmp|gif)$', re.I)


def _split(data):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None: raise ValueError('이미지를 읽을 수 없습니다.')
    height = image.shape[0]
    if height < 4: raise ValueError('분할하기에 너무 작은 이미지입니다.')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blank = np.sum(gray < 220, axis=1) < 10
    start, end = max(1, int(height*.2)), min(height-1, int(height*.8))
    best, longest, run = height//2, 0, None
    for row in range(start, end+1):
        if row < end and blank[row]:
            if run is None: run = row
        elif run is not None:
            if row-run > longest: best, longest = (run+row)//2, row-run
            run = None
    return image[:best], image[best:]


def edit_selected(storage, folder, filenames, operation='split'):
    safe_component(folder)
    filenames = list(dict.fromkeys(filenames))
    if not filenames or operation not in ('split', 'crop'): raise ValueError('유효한 이미지를 선택해 주세요.')
    for name in filenames:
        safe_component(name)
        if not NUMBERED.fullmatch(name): raise ValueError('문제 이미지 파일명만 선택할 수 있습니다.')
    with storage.lock:
        if storage.pending_deletions: raise ValueError('대기 중인 교재 삭제를 먼저 완료해 주세요.')
        prefix = 'img/'+folder+'/'
        original = {p:e for p,e in storage.entries.items() if p.startswith(prefix)}
        if any(prefix+name not in original for name in filenames): raise ValueError('선택한 이미지가 없습니다.')
        storage.freeze_scraps(folder)
        chosen = {int(NUMBERED.fullmatch(name)[1]) for name in filenames}
        entries = dict(storage.entries)
        numbered = [(path,entry,NUMBERED.fullmatch(Path(path).name)) for path,entry in original.items()]
        numbered = [(p,e,m) for p,e,m in numbered if m]
        if len({int(m[1]) for _,_,m in numbered}) != len(numbered):
            raise ValueError('중복 문항 번호가 있어 먼저 파일명을 정리해야 합니다.')
        new_bytes = 0
        changed = operation == 'split'
        for path,_,_ in numbered: entries.pop(path)
        with tempfile.TemporaryDirectory(prefix='.storage-edit-', dir=storage.root) as temp:
            stage = Path(temp)
            for path,entry,match in numbered:
                number = int(match[1])
                offset = sum(selected < number for selected in chosen) if operation == 'split' else 0
                if Path(path).name not in filenames:
                    entries[prefix+f'{number+offset:03d}.'+match[2]] = entry
                    continue
                data = storage.verified(entry, local_path=storage.path(path))
                if operation == 'split':
                    outputs = _split(data)
                    for index,image in enumerate(outputs):
                        name = f'{number+offset+index:03d}.webp'
                        ok,encoded = cv2.imencode('.webp',image,[cv2.IMWRITE_WEBP_QUALITY,85])
                        if not ok: raise ValueError('이미지 인코딩에 실패했습니다.')
                        target = stage/name; target.write_bytes(encoded.tobytes())
                        from services.tasks import trim_all_whitespace
                        trim_all_whitespace(str(target))
                        value = target.read_bytes(); new_bytes += len(value)
                        if new_bytes > int(__import__('os').environ.get('B2_MAX_BATCH_BYTES','500000000')):
                            raise ValueError('선택한 이미지가 작업 용량을 초과했습니다.')
                        entries[prefix+name] = storage.put_verified(value,name)
                else:
                    target = stage/Path(path).name; target.write_bytes(data)
                    from services.tasks import trim_all_whitespace
                    trim_all_whitespace(str(target))
                    value = target.read_bytes(); new_bytes += len(value)
                    changed = changed or value != data
                    entries[path] = entry if value == data else storage.put_verified(value,target.name)
            # Asset generation needs filenames and metadata, not every image's bytes.
            image_dir = stage/'img'/folder; image_dir.mkdir(parents=True)
            for path,entry in entries.items():
                if not path.startswith(prefix): continue
                target = image_dir/Path(path).name
                target.write_bytes(storage.verified(entry) if target.suffix.lower()=='.json' else b'')
            from book_assets import generate_book_assets
            html_path,json_path = generate_book_assets(folder,image_dir=image_dir,
                output_dir=stage/'textbooks',index_path=stage/'templates'/'main.html',allow_empty=True)
            for path in (html_path,json_path):
                entries['textbooks/'+path.name] = storage.put_verified(path.read_bytes(),path.name)
            # Failure before this switch leaves all active image references unchanged.
            storage._commit_catalog(entries,storage.deleted_books)
            storage.fresh_asset_folders.add(folder)
            directory = storage.root/'img'/folder
            if directory.exists():
                recovery = storage.root/'.storage-recovery'/uuid.uuid4().hex/folder
                recovery.parent.mkdir(parents=True)
                shutil.move(str(directory),str(recovery))
            shutil.copytree(image_dir,directory)
            (storage.root/'textbooks').mkdir(exist_ok=True)
            for path in (html_path,json_path): shutil.copy2(path,storage.root/'textbooks'/path.name)
        return {'ok':True,'assets_ready':True,'edited':len(filenames),'changed':changed,
                'message':'선택한 이미지만 처리하고 교재 에셋을 갱신했습니다.'}
