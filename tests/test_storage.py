import io
import hashlib
import json
from pathlib import Path
import pytest
from services.storage import Store, safe_component

class MemoryS3:
    def __init__(self): self.objects = {}; self.fail = False; self.versions = []; self.fail_delete = False
    def put_object(self, Bucket, Key, Body, **kw):
        if self.fail and Key.endswith('catalog.json'): raise OSError('network failure')
        self.objects[Key]=Body
        self.versions.append({'Key':Key,'VersionId':str(len(self.versions)+1),'Body':Body})
        return {'ETag': chr(34)+hashlib.md5(Body).hexdigest()+chr(34)}
    def get_object(self, Bucket, Key): return {'Body':io.BytesIO(self.objects[Key])}
    def generate_presigned_url(self,*a,**kw): return 'https://example.test/object'
    def get_paginator(self, operation):
        remote = self
        class Pages:
            def paginate(self, Bucket, Prefix):
                if operation == 'list_object_versions':
                    yield {'Versions':[dict(Key=v['Key'],VersionId=v['VersionId']) for v in remote.versions if v['Key'].startswith(Prefix)]}
                else:
                    yield {'Contents':[{'Key':k,'Size':len(v),'ETag':hashlib.md5(v).hexdigest()} for k,v in remote.objects.items() if k.startswith(Prefix)]}
        return Pages()
    def delete_objects(self, Bucket, Delete):
        if self.fail_delete: return {'Errors':[{'Code':'AccessDenied'}]}
        for target in Delete['Objects']:
            self.versions = [v for v in self.versions if (v['Key'],v['VersionId']) != (target['Key'],target['VersionId'])]
            remaining = [v for v in self.versions if v['Key'] == target['Key']]
            if remaining: self.objects[target['Key']] = remaining[-1]['Body']
            else: self.objects.pop(target['Key'],None)
        return {}

def test_roundtrip_and_failed_publish_keeps_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    s=Store(tmp_path,MemoryS3())
    p=tmp_path/'img'/'교재'/'001.webp';p.parent.mkdir(parents=True);p.write_bytes(b'original')
    s.publish(['교재'])
    catalog=s.client.objects[s.key('catalog.json')]
    s.evict(['교재']);assert p.stat().st_size==0
    s.hydrate('교재');assert p.read_bytes()==b'original'
    p.write_bytes(b'edited');s.client.fail=True
    with pytest.raises(OSError): s.publish(['교재'])
    assert s.client.objects[s.key('catalog.json')]==catalog
    assert any(v==b'original' for v in s.client.objects.values())

def test_restore_rejects_corrupt_object(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    s=Store(tmp_path,MemoryS3())
    with pytest.raises(ValueError):s.path('img/../../outside')
    s.client.objects['bad']=b'bad'
    with pytest.raises(ValueError):s.verified({'key':'bad','sha256':'wrong'})

@pytest.mark.parametrize('name',['../x','x/y','x\\y','..','C:foo'])
def test_path_validation(name):
    with pytest.raises(ValueError):safe_component(name)

def test_default_admin_disabled():
    from app import app
    client = app.test_client()
    r=client.post('/login', data={'username':'admin123','password':'admin123'})
    with client.session_transaction() as session: assert session.get('role') != 'admin'
def test_webp_pdf_extraction_and_editing(tmp_path, monkeypatch):
    import fitz
    from PIL import Image
    from services.tasks import extract_pdf_task, split_image_task, merge_images_task, cleanup_images_task
    monkeypatch.chdir(tmp_path)
    pdf=fitz.open();page=pdf.new_page(width=400,height=600)
    page.draw_rect(fitz.Rect(40,100,340,180), color=(0,0,0),fill=(0,0,0))
    page.draw_rect(fitz.Rect(40,300,340,380), color=(0,0,0),fill=(0,0,0))
    source=tmp_path/'source.pdf';pdf.save(source);pdf.close()
    messages=list(extract_pdf_task(str(source),'sample',False))
    assert not any('🚨' in m for m in messages)
    files=list((tmp_path/'img'/'sample').glob('*.webp'))
    assert files
    with Image.open(files[0]) as im: assert im.format=='WEBP'
    assert not any('🚨' in m for m in split_image_task('sample',1))
    assert not any('🚨' in m for m in merge_images_task('sample',1,2))
    assert not any('🚨' in m for m in cleanup_images_task(['sample']))

def test_etag_upload_rejects_corrupt_server_checksum(tmp_path,monkeypatch):
    monkeypatch.setenv('STORAGE_BACKEND','b2')
    monkeypatch.setenv('B2_UPLOAD_VERIFICATION','etag')
    remote=MemoryS3();s=Store(tmp_path,remote)
    p=tmp_path/'img'/'book'/'001.webp';p.parent.mkdir(parents=True);p.write_bytes(b'original')
    s.publish(['book'])
    catalog=remote.objects[s.key('catalog.json')]
    original_put=remote.put_object
    def corrupt(**kwargs):
        result=original_put(**kwargs)
        if '/objects/' in kwargs['Key']:result['ETag']='wrong'
        return result
    remote.put_object=corrupt
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):s.publish(['book'])
    assert remote.objects[s.key('catalog.json')]==catalog
