import pytest
import sqlite3
import os
from app import app, DB_PATH, init_db

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key'
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client

def test_signup_and_login(client):
    # 1. 회원가입
    res = client.post('/signup', data={
        'username': 'testuser1',
        'password': 'password123',
        'password_confirm': 'password123'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert "회원가입이 완료되었습니다".encode('utf-8') in res.data or "로그인".encode('utf-8') in res.data

    # DB 역할 확인
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE username='testuser1'")
        row = c.fetchone()
        assert row is not None
        assert row[0] == 'user'

    # 2. 일반유저 로그인
    res_login = client.post('/login', data={
        'username': 'testuser1',
        'password': 'password123'
    }, follow_redirects=True)
    assert res_login.status_code == 200

    # 3. /main 접근 성공 확인
    res_main = client.get('/main')
    assert res_main.status_code == 200

    # 4. 일반유저의 관리자 API 접근 시도 -> 403 Forbidden
    res_admin_api = client.get('/api/run/split?folder=test&num=1')
    assert res_admin_api.status_code == 403

def test_scraps_feature(client):
    # 일반 유저 로그인
    client.post('/signup', data={'username': 'scrapuser', 'password': 'pw', 'password_confirm': 'pw'})
    client.post('/login', data={'username': 'scrapuser', 'password': 'pw'})

    # 1. 스크랩 추가
    scrap_data = {
        'book_folder': '미적쎈',
        'book_title': '미적쎈',
        'items': [
            {'file': '../img/미적쎈/001.png', 'num': 1},
            {'file': '../img/미적쎈/002.png', 'num': 2}
        ]
    }
    res_post = client.post('/api/scraps', json=scrap_data)
    assert res_post.status_code == 200
    assert res_post.get_json()['added'] == 2

    # 2. 스크랩 조회
    res_get = client.get('/api/scraps')
    assert res_get.status_code == 200
    scraps = res_get.get_json()['scraps']
    assert len(scraps) == 2
    assert scraps[0]['book_folder'] == '미적쎈'

    # 3. 스크랩 삭제
    scrap_id = scraps[0]['id']
    res_del = client.delete('/api/scraps', json={'scrap_id': scrap_id})
    assert res_del.status_code == 200

    res_get2 = client.get('/api/scraps')
    assert len(res_get2.get_json()['scraps']) == 1

def test_admin_delete_api(client):
    # 관리자 로그인
    client.post('/login', data={'username': 'admin123', 'password': 'admin123'})

    # /api/user_info 확인
    res_info = client.get('/api/user_info')
    assert res_info.get_json()['role'] == 'admin'

    # /admin 접근 허용
    res_admin_page = client.get('/admin')
    assert res_admin_page.status_code == 200

def test_service_account_json_parser_accepts_wrapped_json(monkeypatch):
    from services.gdrive_backup import parse_service_account_json

    raw = ''''{
      "type": "service_account",
      "project_id": "demo-project"
    }' '''

    parsed = parse_service_account_json(raw)
    assert parsed["type"] == "service_account"
    assert parsed["project_id"] == "demo-project"


if __name__ == '__main__':
    pytest.main(['-v', __file__])
