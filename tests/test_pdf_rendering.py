import pytest
import fitz
from services.pdf_rendering import open_document, render_page


@pytest.fixture
def pdf_source(tmp_path):
    document=fitz.open();page=document.new_page(width=200,height=300)
    page.draw_rect(fitz.Rect(20,50,120,100),color=(0,0,0),fill=(0,0,0))
    annotation=page.add_rect_annot(fitz.Rect(30,180,160,230))
    annotation.set_colors(stroke=(1,0,0),fill=(1,0,0));annotation.set_opacity(1);annotation.update()
    path=tmp_path/'render.pdf';document.save(path);document.close()
    return path


@pytest.mark.parametrize('engine',['pdfium','mupdf'])
def test_renderers_produce_opaque_rgb_and_keep_page_content(pdf_source,engine):
    with open_document(pdf_source,engine) as document:
        pixels=render_page(document,0,engine,False,scale=1)
    assert pixels.shape==(300,200,3)
    assert (pixels[0,0]==255).all()
    assert (pixels[70,40]<20).all()


@pytest.mark.parametrize('engine',['pdfium','mupdf'])
def test_annotation_setting_is_explicit_and_preserves_original(pdf_source,engine):
    original=pdf_source.read_bytes()
    with open_document(pdf_source,engine) as document:
        visible=render_page(document,0,engine,True,scale=1)
        hidden=render_page(document,0,engine,False,scale=1)
    assert visible[200,60,0]>200 and visible[200,60,1]<30
    assert (hidden[200,60]>240).all()
    assert pdf_source.read_bytes()==original


def test_pdf_preview_is_admin_only_and_validates_page(pdf_source,monkeypatch):
    import app as web
    monkeypatch.setattr(web,'UPLOAD_FOLDER',str(pdf_source.parent))
    client=web.app.test_client()
    with client.session_transaction() as session:session.update(username='preview-user',role='user')
    assert client.get('/api/admin/pdf_preview?name=render').status_code==403
    with client.session_transaction() as session:session['role']='admin'
    response=client.get('/api/admin/pdf_preview?name=render&renderer=pdfium&annotations=0')
    assert response.status_code==200 and response.mimetype=='image/png'
    assert response.data.startswith(b'\x89PNG')
    assert client.get('/api/admin/pdf_preview?name=render&page=999').status_code==400
    assert client.get('/api/admin/pdf_preview?name=render&renderer=bad').status_code==400
