import hashlib
import io
import json
from pathlib import Path
import pytest
from botocore.exceptions import ClientError
from services.storage import Store
from tests.test_storage import MemoryS3


def test_default_upload_works_without_download_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    monkeypatch.delenv('B2_UPLOAD_VERIFICATION',raising=False)
    remote=MemoryS3()
    def no_download(**kwargs): raise AssertionError('Upload must not consume GET quota')
    remote.get_object=no_download
    storage=Store(tmp_path,remote)
    image=tmp_path/'img/book/001.webp';image.parent.mkdir(parents=True);image.write_bytes(b'image')
    storage.publish(['book'])
    entry=storage.entries['img/book/001.webp']
    assert entry['verification']=='content-md5-and-etag'
    storage.evict(['book'])
    assert storage.verified(entry)==b'image'


def test_original_copy_and_browser_etag_avoid_remote_get(tmp_path,monkeypatch):
    from flask import Flask
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    remote=MemoryS3()
    def no_download(**kwargs):raise AssertionError('Verified original or 304 must not download')
    remote.get_object=no_download
    storage=Store(tmp_path,remote)
    image=tmp_path/'img/book/001.webp';image.parent.mkdir(parents=True);image.write_bytes(b'original')
    digest=hashlib.sha256(b'original').hexdigest()
    entry={'key':storage.key('objects/'+digest),'sha256':digest,'size':8}
    storage.entries['img/book/001.webp']=entry
    application=Flask(__name__)
    with application.test_request_context('/'):
        assert storage.serve('book/001.webp').data==b'original'
    storage._read_cache.clear();image.write_bytes(b'stale')
    with application.test_request_context('/',headers={'If-None-Match':'"'+digest+'"'}):
        assert storage.serve('book/001.webp').status_code==304
    with application.test_request_context('/'):
        with pytest.raises(AssertionError):storage.serve('book/001.webp')


def test_memory_cache_respects_byte_limit(tmp_path,monkeypatch):
    monkeypatch.setenv('B2_READ_CACHE_BYTES','6')
    storage=Store(tmp_path,MemoryS3())
    storage._cache_read('one',b'1234');storage._cache_read('two',b'5678')
    assert list(storage._read_cache)==['two']
    assert storage._read_cache_size==4
    storage._cache_read('large',b'1234567')
    assert storage._read_cache_size==4


def test_upload_retry_reuses_identical_pdf_without_overwriting(tmp_path,monkeypatch):
    import app as application
    monkeypatch.setattr(application,'UPLOAD_FOLDER',str(tmp_path))
    client=application.app.test_client()
    with client.session_transaction() as session:
        session.update(username='test-admin',role='admin',logged_in=True)
    def upload(content):
        return client.post('/api/upload_pdf',data={'name':'retry','file':(io.BytesIO(content),'book.pdf')})
    assert upload(b'original').status_code==200
    assert upload(b'original').get_json()['reused'] is True
    assert upload(b'different').status_code==409
    assert (tmp_path/'retry.pdf').read_bytes()==b'original'


def test_quota_error_is_streamed_and_unpublished_pdf_can_be_retried(tmp_path,monkeypatch):
    import services.tasks as tasks
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    remote=MemoryS3();storage=Store(tmp_path,remote)
    monkeypatch.setattr(tasks,'store',storage)
    monkeypatch.setattr(tasks,'generate_book_assets',lambda *args,**kwargs:None)
    folder=tmp_path/'img/retry'
    def extract(*args):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'001.webp').write_bytes(b'extracted')
        yield tasks.yield_msg('extracted',100)
    monkeypatch.setattr(tasks,'_original_extract',extract)
    original_put=remote.put_object
    def limited_put(**kwargs):
        raise ClientError({'Error':{'Code':'AccessDenied','Message':'transaction (Class B) cap exceeded'}},'PutObject')
    remote.put_object=limited_put
    messages=[json.loads(m.removeprefix('data: ').strip()) for m in tasks.extract_pdf_task('retry.pdf','retry',False)]
    assert messages[0]['percent']==0
    assert messages[-1]['error'] and 'B2 무료' in messages[-1]['msg']
    assert all(m.get('percent',0)<100 for m in messages[:-1])
    assert (folder/'001.webp').read_bytes()==b'extracted'
    remote.put_object=original_put
    retried=[json.loads(m.removeprefix('data: ').strip()) for m in tasks.extract_pdf_task('retry.pdf','retry',False)]
    assert retried[-1]['percent']==100 and not retried[-1]['error']
    assert storage.entries['img/retry/001.webp']['verification']=='content-md5-and-etag'
    assert (folder/'001.webp').stat().st_size==0
    assert list((tmp_path/'.storage-recovery').rglob('001.webp'))


def test_store_recreates_lock_and_network_pool_in_new_worker(tmp_path,monkeypatch):
    import services.storage as module
    storage=Store(tmp_path)
    old_lock=storage.lock
    storage.client=object()  # Simulate a boto3 client created during master startup.
    storage._cache_read('old',b'master-data')
    process_id=storage._process_id
    monkeypatch.setattr(module.os,'getpid',lambda:process_id+1)
    new_lock=storage.lock
    assert new_lock is not old_lock
    assert storage.client is None
    assert not storage._read_cache
    assert storage.lock is new_lock
    with new_lock: pass
