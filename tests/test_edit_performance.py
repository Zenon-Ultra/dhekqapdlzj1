import pytest
from PIL import Image, ImageDraw
from tests.test_cloud_integration import cloud
from services.book_editing import edit_selected


def instrument(storage):
    reads, writes = [], []
    get, put = storage.client.get_object, storage.client.put_object
    def counted_get(**kwargs): reads.append(kwargs['Key']); return get(**kwargs)
    def counted_put(**kwargs): writes.append(kwargs['Key']); return put(**kwargs)
    storage.client.get_object = counted_get
    storage.client.put_object = counted_put
    return reads,writes


def test_bulk_split_reads_only_selected_images_and_commits_once(cloud, monkeypatch):
    monkeypatch.setenv('B2_READ_CACHE_BYTES','0')
    cloud._read_cache.clear();cloud._read_cache_size=0
    cloud.hydrate('sample')
    for number in range(3,101):
        image=Image.new('RGB',(120,240),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((20,30,100,80),fill=(number,10,10));draw.rectangle((20,150,100,200),fill='black')
        image.save(cloud.root/'img/sample'/f'{number:03d}.webp')
    # Restore the two zero-byte placeholders before seeding the large fixture.
    cloud.publish(['sample']);cloud.evict(['sample'])
    before=dict(cloud.entries)
    reads,writes=instrument(cloud)
    result=edit_selected(cloud,'sample',['010.webp','050.webp'])
    assert result['edited']==2 and result['assets_ready']
    assert reads == [before['img/sample/010.webp']['key'],before['img/sample/050.webp']['key']]
    assert len(writes)==8  # Four split images, two assets, one snapshot, one live catalog.
    assert cloud.entries['img/sample/101.webp']==before['img/sample/099.webp']
    assert cloud.entries['img/sample/102.webp']==before['img/sample/100.webp']
    assert len([p for p in cloud.entries if p.startswith('img/sample/')])==102
    assert all((cloud.root/path).stat().st_size==0 for path in cloud.entries if path.startswith('img/sample/'))


def test_crop_then_legacy_rebuild_does_not_download_book_twice(cloud,monkeypatch):
    import app as web
    monkeypatch.setenv('B2_READ_CACHE_BYTES','0');cloud._read_cache.clear();cloud._read_cache_size=0
    reads,writes=instrument(cloud)
    client=web.app.test_client()
    with client.session_transaction() as session:session.update(username='fast-editor',role='admin')
    result=client.get('/api/run/crop_single?folder=sample&filename=001.webp')
    assert result.status_code==200 and result.json['assets_ready']
    assert len(reads)==1
    counts=len(reads),len(writes)
    assert client.get('/api/run/build_sync?folder=sample').json['assets_ready']
    assert (len(reads),len(writes))==counts


def test_split_catalog_failure_keeps_active_book_and_local_images(cloud):
    original=cloud.client.objects[cloud.key('catalog.json')]
    before=dict(cloud.entries)
    cloud.client.fail=True
    with pytest.raises(OSError):edit_selected(cloud,'sample',['001.webp','002.webp'])
    assert cloud.entries==before
    assert cloud.client.objects[cloud.key('catalog.json')]==original
    assert (cloud.root/'img/sample/001.webp').exists()


@pytest.mark.parametrize('name',['../001.webp','cover.webp','001.webp,002.webp'])
def test_fast_edit_rejects_non_question_paths(cloud,name):
    with pytest.raises(ValueError):edit_selected(cloud,'sample',[name])
