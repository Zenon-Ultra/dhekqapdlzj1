def test_design_and_csrf_coexist_on_auth_page():
    from app import app
    response=app.test_client().get('/login')
    html=response.get_data(as_text=True)
    assert html.count('data-hyperx-design')==1
    assert 'data-hx-page="auth"' in html
    assert 'csrf-token' in html and 'name="_csrf"' in html
    assert '/static/motion.css' in html and '/static/motion.js' in html


def test_previously_generated_viewer_gets_shared_design_without_rewriting_file(tmp_path,monkeypatch):
    import app as web
    from services.storage import Store
    path=tmp_path/'textbooks/old.html';path.parent.mkdir()
    original='<html><head><title>Old</title></head><body>Question</body></html>'
    path.write_text(original)
    monkeypatch.setattr(web,'store',Store(tmp_path))
    client=web.app.test_client()
    with client.session_transaction() as session:session.update(username='reader',role='user')
    response=client.get('/textbooks/old.html')
    assert response.status_code==200
    assert 'data-hx-page="viewer"' in response.text
    assert '/static/motion.css' in response.text
    assert path.read_text()==original
