import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path
import pytest
from flask.testing import FlaskClient
from PIL import Image
from services.storage import Store
from tests.test_storage import MemoryS3

@pytest.fixture
def cloud(tmp_path, monkeypatch):
    import app as web
    import services.tasks as tasks
    import services.storage as storage
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    remote=MemoryS3();s=Store(tmp_path,remote)
    monkeypatch.setattr(storage,'store',s);monkeypatch.setattr(web,'store',s);monkeypatch.setattr(tasks,'store',s)
    monkeypatch.setattr(web,'BASE_DIR',str(tmp_path));monkeypatch.chdir(tmp_path)
    (tmp_path/'templates').mkdir();(tmp_path/'textbooks').mkdir();(tmp_path/'img'/'sample').mkdir(parents=True)
    (tmp_path/'templates'/'main.html').write_text('<html><head></head><body><div class="card-grid" id="cardGrid"></div></body></html>')
    for n,color in [(1,'black'),(2,'red')]:
        im=Image.new('RGB',(120,240),'white');im.paste(color,(20,40,100,200));im.save(tmp_path/'img'/'sample'/f'{n:03d}.webp')
    from book_assets import generate_book_assets
    generate_book_assets('sample',image_dir=tmp_path/'img'/'sample',output_dir=tmp_path/'textbooks',index_path=tmp_path/'templates'/'main.html')
    s.publish(['sample']);s.evict(['sample'])
    return s

def test_cloud_edit_scrap_and_restart(cloud):
    import app as web
    from services.tasks import split_image_task,merge_images_task,delete_image_task
    client=web.app.test_client()
    with client.session_transaction() as session: session['username']='cloud-admin';session['role']='admin'
    response=client.post('/api/scraps',json={'book_folder':'sample','items':[{'file':'../img/sample/002.webp','num':2}]})
    assert response.json['added']==1
    row=client.get('/api/scraps').json['scraps'][0];url=row['image_url']
    original=client.get(url);assert original.status_code==200;assert original.mimetype=='image/webp'
    list(split_image_task('sample',1))
    assert 'img/sample/003.webp' in cloud.entries, (list(cloud.entries), list((cloud.root/'img'/'sample').glob('*')))
    assert client.get(url).data==original.data
    assert client.get('/img/sample/003.webp').data==original.data
    list(merge_images_task('sample',1,2))
    list(delete_image_task('sample',1))
    list(delete_image_task('sample',1))
    assert not any(k.startswith('img/sample/') for k in cloud.entries)
    assert client.get(url).data==original.data
    cloud.restore()
    assert not list((cloud.root/'img'/'sample').glob('*.webp'))
    other=web.app.test_client()
    with other.session_transaction() as session:session['username']='other'
    assert other.get(url).status_code==404

def test_cloud_zip_restores_bytes_history_and_database(cloud,tmp_path):
    import app as web
    from services.backup import create_project_zip
    from scripts.restore_backup import restore
    client=web.app.test_client()
    with client.session_transaction() as session: session['username']='backup-user';session['role']='admin'
    client.post('/api/scraps',json={'book_folder':'sample','items':[{'file':'../img/sample/002.webp','num':2}]})
    original=cloud.verified(cloud.entries['img/sample/002.webp'])
    path,_=create_project_zip(str(cloud.root),storage=cloud)
    try:
        assert restore(path)>0
        destination=tmp_path/'restored'
        restore(path,destination)
        assert (destination/'img'/'sample'/'002.webp').read_bytes()==original
        with sqlite3.connect(destination/'admin.db') as conn:
            file,key=conn.execute("SELECT image_file,snapshot_key FROM scraps WHERE username='backup-user'").fetchone()
            assert key is None
            assert (destination/file.lstrip('/')).read_bytes()==original
        with pytest.raises(FileExistsError):restore(path,destination)
    finally:Path(path).unlink(missing_ok=True)

def test_backup_failure_and_budget(cloud,monkeypatch):
    from services.backup import create_project_zip
    monkeypatch.setenv('BACKUP_MAX_BYTES','1')
    with pytest.raises(ValueError):create_project_zip(str(cloud.root),storage=cloud)

def test_csrf_requires_session_token_and_same_origin():
    from app import app
    client=FlaskClient(app)
    assert client.post('/login',data={}).status_code==403
    response=client.get('/login')
    assert b'/static/security.js' in response.data and b'name="_csrf"' in response.data
    with client.session_transaction() as session:token=session['_csrf'];session['username']='csrf-admin';session['role']='admin'
    assert client.get('/api/run/build_sync?folder=sample').status_code==403
    assert client.post('/api/admin/maintenance',json={'enabled':False},headers={'X-CSRF-Token':token,'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/admin/maintenance',json={'enabled':False},headers={'X-CSRF-Token':token}).status_code==200

def test_migration_verification_preserves_source(cloud):
    from scripts.migrate_storage import migrate
    cloud.hydrate('sample')
    before={p:p.read_bytes() for p in cloud.root.rglob('*') if p.is_file()}
    migrate(cloud,verify=True)
    assert all(p.read_bytes()==data for p,data in before.items())
    with pytest.raises(RuntimeError):migrate(cloud,apply=True)
    migrate(cloud,apply=True,resume=True,verify=True)

def test_malicious_catalog_rejected_before_writes(cloud):
    cloud.client.objects[cloud.key('catalog.json')]=json.dumps({'version':1,'files':{'img/../../escape':{'key':'bad','sha256':'0'*64}}}).encode()
    with pytest.raises(ValueError):cloud.restore()
    assert not (cloud.root.parent/'escape').exists()

def test_cloud_edit_error_does_not_publish(cloud,monkeypatch):
    from services.tasks import split_image_task
    before=cloud.client.objects[cloud.key('catalog.json')]
    cloud.client.fail=True
    with pytest.raises(OSError): list(split_image_task('sample',1))
    assert cloud.client.objects[cloud.key('catalog.json')]==before

def test_single_crop_cover_and_sync_cloud(cloud):
    import app as web
    client=web.app.test_client()
    with client.session_transaction() as session:session['username']='cloud-editor';session['role']='admin'
    response=client.get('/api/run/crop_single?folder=sample&filename=001.webp')
    assert response.status_code==200 and response.json['changed']
    original=Image.open(io.BytesIO(cloud.verified(cloud.entries['img/sample/001.webp'])))
    assert original.width<120
    response=client.post('/api/upload_cover',data={'folder':'sample','file':(io.BytesIO(cloud.verified(cloud.entries['img/sample/002.webp'])),'cover.webp')})
    assert response.status_code==200
    assert 'img/sample/cover.webp' in cloud.entries
    response=client.post('/api/sync_books')
    assert response.status_code==200 and not response.json['errors']
    assert 'viewer' not in [book['name'] for book in client.get('/api/books').json['books']]

def test_no_cloud_keys_in_backup(cloud):
    from services.backup import create_project_zip
    (cloud.root/'.env').write_text('B2_APPLICATION_KEY=do-not-export')
    (cloud.root/'.env.production').write_text('DATABASE_URL=do-not-export')
    path,_=create_project_zip(str(cloud.root),storage=cloud)
    try:
        with zipfile.ZipFile(path) as archive:
            assert not any(name.startswith('.env') for name in archive.namelist())
    finally:Path(path).unlink(missing_ok=True)

def test_backup_background_finishes_and_survives_status_write_error(cloud,monkeypatch):
    import app as web
    import services.backup as backup
    monkeypatch.setattr(backup,'_write_status',lambda data: None)
    web._run_zip_background(str(cloud.root))
    assert web.ZIP_TASK_STATUS['ready']
    assert not web.ZIP_TASK_STATUS['error']
    path=Path(web.ZIP_TASK_STATUS['filepath'])
    assert path.exists()
    path.unlink()
    web.ZIP_TASK_STATUS.update({'ready':False,'filepath':None})
