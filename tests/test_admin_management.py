import json
import sqlite3
import pytest
from services.storage import Store
from tests.test_storage import MemoryS3


def setup_book(tmp_path, monkeypatch, cloud=True):
    import app as application
    monkeypatch.setenv('STORAGE_BACKEND', 'b2' if cloud else 'local')
    database = tmp_path/'admin.db'
    monkeypatch.setenv('DB_PATH', str(database))
    monkeypatch.setattr(application, 'DB_PATH', str(database))
    application.init_db()
    store = Store(tmp_path, MemoryS3())
    monkeypatch.setattr(application, 'store', store)
    image = tmp_path/'img'/'교재 이름'/'001.webp'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'original-image')
    (image.parent/'cover.webp').write_bytes(b'cover')
    (image.parent/'meta.json').write_text('{}')
    (tmp_path/'textbooks').mkdir()
    (tmp_path/'textbooks/교재_이름.html').write_text('viewer')
    (tmp_path/'textbooks/교재_이름.json').write_text('{}')
    (tmp_path/'textbooks/viewer.html').write_text('shared')
    (tmp_path/'uploads').mkdir()
    (tmp_path/'uploads/교재 이름.pdf').write_bytes(b'pdf')
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO scraps(username,book_folder,book_title,image_file) VALUES ('owner','교재 이름','교재','../img/교재 이름/001.webp')")
    if cloud: store.publish(['교재 이름'])
    return application, store, image, database


def test_delete_book_cloud_purges_versions_scraps_and_restart_tombstone(tmp_path, monkeypatch):
    application, store, image, database = setup_book(tmp_path, monkeypatch)
    other = tmp_path/'img/other/001.webp'; other.parent.mkdir(); other.write_bytes(b'other')
    store.publish(['other'])
    original_key = store.entries['img/교재 이름/001.webp']['key']
    store.client.put_object(Bucket=store.bucket, Key=original_key, Body=b'original-image')
    client = application.app.test_client()
    with client.session_transaction() as session:
        session.update(username='test-admin', role='admin', logged_in=True)
    assert client.post('/api/admin/books/delete',json={'folder':'교재 이름','confirm_name':'wrong'}).status_code == 400
    assert client.post('/api/admin/books/delete',json={'folder':'교재 이름','confirm_name':'교재 이름'}).status_code == 200
    assert not image.parent.exists()
    assert not (tmp_path/'textbooks/교재_이름.html').exists()
    assert not (tmp_path/'textbooks/교재_이름.json').exists()
    assert not (tmp_path/'uploads/교재 이름.pdf').exists()
    assert (tmp_path/'textbooks/viewer.html').exists() and other.exists()
    assert list((tmp_path/'.storage-deleted').rglob('001.webp'))[0].read_bytes() == b'original-image'
    assert not any(path.startswith('img/교재 이름/') for path in store.entries)
    with sqlite3.connect(database) as conn: assert conn.execute('SELECT COUNT(*) FROM scraps').fetchone()[0] == 0
    assert original_key not in store.client.objects
    assert not any(v['Key'] == original_key for v in store.client.versions)
    assert client.post('/api/scraps',json={'book_folder':'교재 이름','items':[{'file':'001.webp','num':1}]}).status_code == 410
    assert client.get('/img/교재 이름/001.webp').status_code == 404
    # A fresh Render checkout must not bring removed files back into active use.
    image.parent.mkdir(); image.write_bytes(b'old-checkout')
    (tmp_path/'textbooks/교재_이름.html').write_text('old-checkout')
    restarted = Store(tmp_path,store.client); restarted.restore()
    assert '교재 이름' in restarted.deleted_books and not image.exists()
    assert not (tmp_path/'textbooks/교재_이름.html').exists()


def test_failed_delete_keeps_active_book(tmp_path, monkeypatch):
    _, store, image, _ = setup_book(tmp_path, monkeypatch)
    catalog = store.client.objects[store.key('catalog.json')]
    store.client.fail = True
    with pytest.raises(OSError): store.delete_book('교재 이름')
    assert image.read_bytes() == b'original-image'
    assert store.client.objects[store.key('catalog.json')] == catalog
    assert not store.deleted_books


def test_local_delete_removes_related_scraps(tmp_path, monkeypatch):
    application, store, image, database = setup_book(tmp_path, monkeypatch, cloud=False)
    store.delete_book('교재 이름')
    assert not image.exists()
    client = application.app.test_client()
    with client.session_transaction() as session:
        session.update(username='owner',role='user',logged_in=True)
    with sqlite3.connect(database) as conn: assert conn.execute('SELECT COUNT(*) FROM scraps').fetchone()[0] == 0
    with client.session_transaction() as session: session['username'] = 'someone-else'
    assert client.get('/api/scraps/1/image').status_code == 404
    assert client.post('/api/admin/books/delete',json={'folder':'../other','confirm_name':'../other'}).status_code == 403


def test_purge_preserves_other_books_shared_content_and_scraps(tmp_path, monkeypatch):
    _, store, image, database = setup_book(tmp_path, monkeypatch)
    other = tmp_path/'img/other/001.webp'; other.parent.mkdir(); other.write_bytes(image.read_bytes())
    store.publish(['other'])
    shared = store.entries['img/other/001.webp']['key']
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO scraps(username,book_folder,book_title,image_file,snapshot_key) VALUES ('owner','other','other','001.webp',?)",(shared,))
    result = store.delete_book('교재 이름')
    assert result['shared_objects_retained'] >= 1
    assert store.verified(store.entries['img/other/001.webp']) == b'original-image'
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT book_folder FROM scraps').fetchall() == [('other',)]


def test_failed_purge_is_persisted_and_retryable_after_restart(tmp_path, monkeypatch):
    _, store, _, _ = setup_book(tmp_path, monkeypatch)
    original_key = store.entries['img/교재 이름/001.webp']['key']
    store.client.fail_delete = True
    with pytest.raises(RuntimeError): store.delete_book('교재 이름')
    assert '교재 이름' in store.pending_deletions
    assert original_key in store.client.objects
    with pytest.raises(ValueError): store.publish(['other'])
    restarted = Store(tmp_path,store.client); restarted.restore()
    assert '교재 이름' in restarted.pending_deletions
    restarted.client.fail_delete = False
    result = restarted.delete_book('교재 이름')
    assert result['deleted_versions'] > 0
    assert original_key not in restarted.client.objects
    assert not restarted.pending_deletions


def test_shared_file_is_purged_when_last_book_is_deleted(tmp_path, monkeypatch):
    _, store, image, _ = setup_book(tmp_path, monkeypatch)
    other = tmp_path/'img/other/001.webp'; other.parent.mkdir(); other.write_bytes(image.read_bytes())
    store.publish(['other'])
    key = store.entries['img/other/001.webp']['key']
    store.delete_book('교재 이름')
    assert key in store.client.objects
    store.delete_book('other')
    assert key not in store.client.objects


def test_usage_dashboard_is_admin_only_and_measures_current_assets(tmp_path, monkeypatch):
    application, store, _, _ = setup_book(tmp_path, monkeypatch)
    client = application.app.test_client()
    with client.session_transaction() as session:
        session.update(username='owner',role='user',logged_in=True)
    assert client.get('/api/admin/storage_usage').status_code == 403
    with client.session_transaction() as session: session['role'] = 'admin'
    response = client.get('/api/admin/storage_usage')
    assert response.status_code == 200
    usage = response.get_json()
    assert usage['database']['bytes'] > 0
    assert usage['database']['counts']['scraps'] == 1
    assert usage['assets']['active_bytes'] == sum(e['size'] for e in store.entries.values())
    assert usage['assets']['includes_history'] is False
    assert usage['server_disk']['free_bytes'] > 0
    assert 'password' not in response.text and 'DATABASE_URL' not in response.text
    store.delete_book('교재 이름')
    assert client.get('/api/admin/storage_usage').get_json()['assets']['books'] == 0
