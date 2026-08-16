from flask import Flask, render_template, request, Response, jsonify, send_from_directory, session, redirect, url_for, send_file, after_this_request
import os
import sqlite3
from functools import wraps

from services.tasks import (
    extract_pdf_task, cleanup_images_task, generate_assets_task,
    split_image_task, merge_images_task, delete_image_task
)
from book_assets import generate_book_assets
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from services.github_sync import start_auto_sync, is_auto_sync_enabled, set_auto_sync_enabled

app = Flask(__name__)
app.secret_key = 'super_secret_admin_key_hyperx_2026'
DB_PATH = os.path.join(os.path.dirname(__file__), 'admin.db')

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # users 테이블 생성 (role 컬럼 포함)
        c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT DEFAULT 'user')''')
        
        # 기존 DB 호환을 위한 role 컬럼 추가 시도
        try:
            c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass

        # book_requests 테이블 생성
        c.execute('''
            CREATE TABLE IF NOT EXISTS book_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                book_name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # scraps 테이블 생성
        c.execute('''
            CREATE TABLE IF NOT EXISTS scraps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                book_folder TEXT NOT NULL,
                book_title TEXT NOT NULL,
                image_file TEXT NOT NULL,
                question_num INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, book_folder, image_file)
            )
        ''')

        # system_config 테이블 생성 (점검 모드 등 시스템 설정 저장)
        c.execute('''CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)''')

        # admin123 계정 생성 또는 역할 업데이트
        c.execute("SELECT role FROM users WHERE username='admin123'")
        row = c.fetchone()
        hashed = generate_password_hash('admin123')
        if not row:
            c.execute("INSERT INTO users (username, password, role) VALUES ('admin123', ?, 'admin')", (hashed,))
        else:
            c.execute("UPDATE users SET role='admin' WHERE username='admin123'")
        conn.commit()

def get_maintenance_mode():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
            c.execute("SELECT value FROM system_config WHERE key='maintenance_mode'")
            row = c.fetchone()
            if row:
                return row[0] == '1'
    except Exception:
        pass
    return False

def set_maintenance_mode(enabled: bool):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
        val = '1' if enabled else '0'
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('maintenance_mode', ?)", (val,))
        conn.commit()

@app.before_request
def check_maintenance_mode():
    # 관리자 로그인 사용자는 제한 없음
    if session.get('admin_logged_in'):
        return None
    
    # 점검 모드가 OFF면 통과
    if not get_maintenance_mode():
        return None

    # 허용되는 관리자/로그인/정적 자원 라우트
    path = request.path
    allowed_prefixes = ['/admin', '/api/admin', '/static', '/favicon.ico']
    if any(path.startswith(prefix) for prefix in allowed_prefixes):
        return None

    # 그 외 모든 일반 유저 접근(대시보드 메인, 교재 뷰어 등)은 점검 중 페이지 렌더링
    return render_template('maintenance.html'), 530

    # 앱 시작 시 교재 뷰어 에셋 자동 동기화 (ebsi_sc.html 변경사항 반영)
    base_img = os.path.join(os.path.dirname(__file__), 'img')
    if os.path.exists(base_img):
        for folder in os.listdir(base_img):
            folder_path = os.path.join(base_img, folder)
            if os.path.isdir(folder_path):
                try:
                    generate_book_assets(folder)
                except Exception:
                    pass

# 앱 시작 시 DB 초기화 및 교재 뷰어 갱신
init_db()

# 백그라운드 GitHub 자동 동기화 시작 (Render 환경 등)
start_auto_sync()

# ── 권한 데코레이터 ──
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login', next=request.url))
        if session.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({"error": "Forbidden: 관리자 권한이 필요합니다."}), 403
            return redirect(url_for('main_page'))
        return f(*args, **kwargs)
    return decorated_function


BASE_DIR = os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

# Render 배포 시 필요한 폴더들을 자동 생성
for _folder in ['uploads', 'static', 'img', 'textbooks']:
    os.makedirs(os.path.join(BASE_DIR, _folder), exist_ok=True)

# ==========================================
# Frontend Routes
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/main')
@login_required
def main_page():
    return render_template('main.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        password_confirm = request.form.get('password_confirm', '').strip()

        if not username or not password:
            return render_template('signup.html', error="아이디와 비밀번호를 모두 입력해주세요.")
        if password != password_confirm:
            return render_template('signup.html', error="비밀번호가 일치하지 않습니다.")
        if len(username) < 3:
            return render_template('signup.html', error="아이디는 3자 이상이어야 합니다.")

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT username FROM users WHERE username=?", (username,))
            if c.fetchone():
                return render_template('signup.html', error="이미 존재하는 아이디입니다.")
            hashed = generate_password_hash(password)
            c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'user')", (username, hashed))
            conn.commit()

        return render_template('login.html', success="회원가입이 완료되었습니다! 로그인해 주세요.")
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT password, role FROM users WHERE username=?", (username,))
            user = c.fetchone()
            if user and check_password_hash(user[0], password):
                session['logged_in'] = True
                session['username'] = username
                session['role'] = user[1] or 'user'
                next_url = request.args.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect(url_for('main_page'))
            else:
                return render_template('login.html', error="아이디 또는 비밀번호가 잘못되었습니다.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html')

@app.route('/tutorial.html')
def tutorial():
    return render_template('tutorial.html')

@app.route('/new-textbook.html')
@login_required
def new_textbook():
    return render_template('new-textbook.html')

@app.route('/template_editor.html')
@login_required
def template_editor():
    return render_template('template_editor.html')

@app.route('/ebsi_sc.html')
@login_required
def ebsi_sc():
    return render_template('ebsi_sc.html')

# ==========================================
# Static Files Routes (img / textbooks)
# ==========================================
@app.route('/img/<path:filename>')
def serve_img(filename):
    return send_from_directory('img', filename)

@app.route('/textbooks/<path:filename>')
@login_required
def serve_textbooks(filename):
    return send_from_directory('textbooks', filename)

# ==========================================
# APIs
# ==========================================
@app.route('/api/user_info', methods=['GET'])
def user_info():
    if 'username' in session:
        return jsonify({
            "logged_in": True,
            "username": session['username'],
            "role": session.get('role', 'user')
        })
    return jsonify({"logged_in": False, "username": None, "role": None})

@app.route('/api/folders', methods=['GET'])
def list_folders():
    base_dir = "img"
    if not os.path.exists(base_dir):
        return jsonify({"folders": []})
    folders = [f for f in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, f))]
    return jsonify({"folders": folders})

@app.route('/api/books', methods=['GET'])
@login_required
def list_books():
    """textbooks 폴더에 있는 HTML 파일 목록과 메타데이터를 반환합니다."""
    textbooks_dir = os.path.join(BASE_DIR, 'textbooks')
    img_dir = os.path.join(BASE_DIR, 'img')
    import json as _json
    from urllib.parse import quote
    from book_assets import slugify

    books = []
    if os.path.exists(textbooks_dir):
        for fname in sorted(os.listdir(textbooks_dir)):
            if not fname.endswith('.html'):
                continue
            book_name = fname[:-5]  # .html 제거
            meta = {}

            # img/ 폴더 검색 (정확한 폴더명 또는 slugify 일치 폴더)
            target_img_folder = None
            target_folder_name = None
            
            direct_path = os.path.join(img_dir, book_name)
            if os.path.exists(direct_path):
                target_img_folder = direct_path
                target_folder_name = book_name
            else:
                if os.path.exists(img_dir):
                    for d in os.listdir(img_dir):
                        d_path = os.path.join(img_dir, d)
                        if os.path.isdir(d_path):
                            if slugify(d) == book_name or d.replace(' ', '_') == book_name:
                                target_img_folder = d_path
                                target_folder_name = d
                                break

            if target_img_folder:
                meta_path = os.path.join(target_img_folder, 'meta.json')
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, encoding='utf-8') as mf:
                            meta = _json.load(mf)
                    except Exception:
                        pass

            cover_url = meta.get('custom_cover_url', '')
            if not cover_url and target_img_folder and target_folder_name:
                valid_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}
                imgs = sorted([f for f in os.listdir(target_img_folder)
                               if os.path.splitext(f)[1].lower() in valid_exts])
                if imgs:
                    cover_url = f'/img/{quote(target_folder_name)}/{quote(imgs[0])}'

            books.append({
                'name': book_name,
                'html': f'textbooks/{fname}',
                'cover_url': cover_url,
            })
    return jsonify({'books': books})

@app.route('/api/upload_cover', methods=['POST'])
@admin_required
def upload_cover():
    """교재 표지/로고 이미지 파일 업로드 API"""
    import json as _json
    from urllib.parse import quote
    from book_assets import slugify, generate_book_assets

    folder = request.form.get('folder', '').strip()
    if not folder:
        return jsonify({"error": "대상 교재 폴더가 지정되지 않았습니다."}), 400
    if 'file' not in request.files:
        return jsonify({"error": "업로드할 파일이 없습니다."}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({"error": "선택된 파일이 없습니다."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
        return jsonify({"error": "이미지 파일만 업로드할 수 있습니다."}), 400

    target_dir = os.path.join(BASE_DIR, 'img', folder)
    target_folder_name = folder
    if not os.path.exists(target_dir):
        if os.path.exists(os.path.join(BASE_DIR, 'img')):
            for d in os.listdir(os.path.join(BASE_DIR, 'img')):
                if slugify(d) == folder or d.replace(' ', '_') == folder:
                    target_dir = os.path.join(BASE_DIR, 'img', d)
                    target_folder_name = d
                    break

    os.makedirs(target_dir, exist_ok=True)
    cover_filename = f"cover{ext}"
    cover_path = os.path.join(target_dir, cover_filename)
    file.save(cover_path)

    cover_url = f"/img/{quote(target_folder_name)}/{cover_filename}"

    # meta.json 갱신
    meta_path = os.path.join(target_dir, 'meta.json')
    meta_data = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = _json.load(f)
        except Exception:
            pass
    meta_data['custom_cover_url'] = cover_url
    with open(meta_path, 'w', encoding='utf-8') as f:
        _json.dump(meta_data, f, ensure_ascii=False, indent=2)

    # 교재 에셋 갱신
    try:
        generate_book_assets(target_folder_name, custom_cover_url=cover_url)
    except Exception:
        pass

    return jsonify({"ok": True, "cover_url": cover_url})

@app.route('/api/sync_books', methods=['POST'])
@admin_required
def sync_books():
    """img 폴더를 스캔하여 없는 교재 에셋을 생성하고 main.html 카드를 동기화합니다."""
    img_dir = os.path.join(BASE_DIR, 'img')
    if not os.path.exists(img_dir):
        return jsonify({'ok': True, 'synced': 0, 'message': 'img 폴더가 없습니다.'})

    synced = []
    errors = []
    for folder in sorted(os.listdir(img_dir)):
        folder_path = os.path.join(img_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        try:
            generate_book_assets(folder)
            synced.append(folder)
        except Exception as e:
            errors.append({'folder': folder, 'error': str(e)})

    return jsonify({
        'ok': True,
        'synced': len(synced),
        'synced_folders': synced,
        'errors': errors,
        'message': f'{len(synced)}개 교재 동기화 완료'
    })

@app.route('/api/folder_images', methods=['GET'])
@login_required
def list_folder_images():
    folder = request.args.get('folder', '')
    base_dir = os.path.join("img", folder)
    if not folder or not os.path.exists(base_dir):
        return jsonify({"images": []})
    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    files = sorted([f for f in os.listdir(base_dir) if os.path.splitext(f)[1].lower() in valid_exts])
    return jsonify({"images": files})

# ── 스크랩 (Scrap) API ──
@app.route('/api/scraps', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_scraps():
    username = session['username']
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            book_folder = request.args.get('book_folder')
            if book_folder:
                c.execute("SELECT id, book_folder, book_title, image_file, question_num, created_at FROM scraps WHERE username=? AND book_folder=? ORDER BY question_num ASC, id ASC", (username, book_folder))
            else:
                c.execute("SELECT id, book_folder, book_title, image_file, question_num, created_at FROM scraps WHERE username=? ORDER BY created_at DESC", (username,))
            rows = c.fetchall()
            scraps = [{
                "id": r[0],
                "book_folder": r[1],
                "book_title": r[2],
                "image_file": r[3],
                "question_num": r[4],
                "created_at": r[5]
            } for r in rows]
            return jsonify({"scraps": scraps})

        elif request.method == 'POST':
            data = request.get_json(silent=True) or {}
            book_folder = data.get('book_folder', '')
            book_title = data.get('book_title', book_folder)
            items = data.get('items', [])
            if not book_folder or not items:
                return jsonify({"error": "book_folder 및 items 데이터가 필요합니다."}), 400
            
            added_count = 0
            for item in items:
                img_file = item.get('file', '')
                q_num = item.get('num', 0)
                if img_file:
                    try:
                        c.execute(
                            "INSERT OR IGNORE INTO scraps (username, book_folder, book_title, image_file, question_num) VALUES (?, ?, ?, ?, ?)",
                            (username, book_folder, book_title, img_file, q_num)
                        )
                        if c.rowcount > 0:
                            added_count += 1
                    except sqlite3.Error:
                        pass
            conn.commit()
            return jsonify({"ok": True, "added": added_count})

        elif request.method == 'DELETE':
            data = request.get_json(silent=True) or {}
            scrap_id = data.get('scrap_id')
            book_folder = data.get('book_folder')
            image_file = data.get('image_file')
            
            if scrap_id:
                c.execute("DELETE FROM scraps WHERE username=? AND id=?", (username, scrap_id))
            elif book_folder and image_file:
                c.execute("DELETE FROM scraps WHERE username=? AND book_folder=? AND image_file=?", (username, book_folder, image_file))
            elif data.get('all'):
                c.execute("DELETE FROM scraps WHERE username=?", (username,))
            conn.commit()
            return jsonify({"ok": True})

# ── Admin Only APIs ──
@app.route('/api/upload_pdf', methods=['POST'])
@admin_required
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "파일이 없습니다."}), 400
    file = request.files['file']
    name = request.form.get('name', 'upload').strip()
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "PDF 파일만 업로드할 수 있습니다."}), 400
    save_path = os.path.join(UPLOAD_FOLDER, f"{name}.pdf")
    file.save(save_path)
    return jsonify({"ok": True, "path": save_path})

@app.route('/api/run/extract', methods=['GET'])
@admin_required
def run_extract():
    name = request.args.get('name', '')
    col = request.args.get('col', '1') == '1'
    use_upload = request.args.get('use_upload', '0') == '1'
    if use_upload:
        path = os.path.join(UPLOAD_FOLDER, f"{name}.pdf")
    else:
        path = request.args.get('path', '')
    return Response(extract_pdf_task(path, name, col), mimetype='text/event-stream')

@app.route('/api/run/trim', methods=['GET'])
@admin_required
def run_trim():
    folder = request.args.get('folder', '')
    if folder == '__all__':
        img_dir = os.path.join(BASE_DIR, "img")
        folders = [f for f in sorted(os.listdir(img_dir)) if os.path.isdir(os.path.join(img_dir, f))]
        return Response(cleanup_images_task(folders), mimetype='text/event-stream')
    return Response(cleanup_images_task([folder]), mimetype='text/event-stream')

@app.route('/api/run/build', methods=['GET'])
@admin_required
def run_build():
    folder = request.args.get('folder', '')
    cover_url = request.args.get('cover_url', '') or None
    if folder == '__all__':
        img_dir = os.path.join(BASE_DIR, "img")
        folders = [f for f in sorted(os.listdir(img_dir)) if os.path.isdir(os.path.join(img_dir, f))]
        return Response(generate_assets_task(folders, cover_url=cover_url), mimetype='text/event-stream')
    return Response(generate_assets_task([folder], cover_url=cover_url), mimetype='text/event-stream')

@app.route('/api/run/crop_single', methods=['GET', 'POST'])
@admin_required
def run_crop_single():
    folder = request.args.get('folder', '') or (request.get_json(silent=True) or {}).get('folder', '')
    filename = request.args.get('filename', '') or (request.get_json(silent=True) or {}).get('filename', '')
    if not folder or not filename:
        return jsonify({'error': 'folder 및 filename 파라미터가 필요합니다.'}), 400

    img_path = os.path.join(BASE_DIR, 'img', folder, filename)
    if not os.path.exists(img_path):
        from book_assets import slugify
        img_dir = os.path.join(BASE_DIR, 'img')
        if os.path.exists(img_dir):
            for d in os.listdir(img_dir):
                if slugify(d) == folder or d.replace(' ', '_') == folder:
                    img_path = os.path.join(img_dir, d, filename)
                    folder = d
                    break

    if not os.path.exists(img_path):
        return jsonify({'error': '해당 이미지를 찾을 수 없습니다.'}), 404

    from services.tasks import trim_all_whitespace
    changed = trim_all_whitespace(img_path)
    
    from book_assets import generate_book_assets
    try:
        generate_book_assets(folder)
    except Exception:
        pass

    return jsonify({'ok': True, 'changed': changed, 'message': f'{filename} 여백 자르기 완료!'})

@app.route('/api/run/split_sync', methods=['GET'])
@admin_required
def run_split_sync():
    folder = request.args.get('folder', '')
    filename = request.args.get('filename', '')
    if filename:
        list(split_image_task(folder, filename))
    else:
        num_str = request.args.get('num', '')
        try:
            num = int(num_str)
        except ValueError:
            return jsonify({"error": "숫자 형식이 잘못되었습니다."}), 400
        list(split_image_task(folder, num))
    return jsonify({"ok": True})

@app.route('/api/run/build_sync', methods=['GET'])
@admin_required
def run_build_sync():
    folder = request.args.get('folder', '')
    cover_url = request.args.get('cover_url', '') or None
    list(generate_assets_task([folder], cover_url=cover_url))
    return jsonify({"ok": True})

@app.route('/api/run/split', methods=['GET'])
@admin_required
def run_split():
    folder = request.args.get('folder', '')
    num_str = request.args.get('num', '')
    try:
        num = int(num_str)
    except ValueError:
        return Response("data: {\"msg\": \"🚨 숫자 형식이 잘못되었습니다.\", \"percent\": 100}\n\n", mimetype='text/event-stream')
    return Response(split_image_task(folder, num), mimetype='text/event-stream')

@app.route('/api/run/merge', methods=['GET'])
@admin_required
def run_merge():
    folder = request.args.get('folder', '')
    try:
        start = int(request.args.get('start', ''))
        end   = int(request.args.get('end', ''))
    except ValueError:
        return Response("data: {\"msg\": \"🚨 숫자 형식이 잘못되었습니다.\", \"percent\": 100}\n\n", mimetype='text/event-stream')
    return Response(merge_images_task(folder, start, end), mimetype='text/event-stream')

@app.route('/api/run/merge_sync', methods=['GET'])
@admin_required
def run_merge_sync():
    folder = request.args.get('folder', '')
    files = request.args.get('files', '')
    if files:
        list(merge_images_task(folder, files))
    else:
        try:
            start = int(request.args.get('start', ''))
            end   = int(request.args.get('end', ''))
        except ValueError:
            return jsonify({"error": "숫자 형식이 잘못되었습니다."}), 400
        list(merge_images_task(folder, start, end))
    return jsonify({"ok": True})

@app.route('/api/run/delete', methods=['GET'])
@admin_required
def run_delete():
    folder = request.args.get('folder', '')
    target = request.args.get('target', '') or request.args.get('filename', '') or request.args.get('num', '')
    return Response(delete_image_task(folder, target), mimetype='text/event-stream')

@app.route('/api/run/delete_sync', methods=['GET'])
@admin_required
def run_delete_sync():
    folder = request.args.get('folder', '')
    target = request.args.get('target', '') or request.args.get('filename', '') or request.args.get('num', '')
    list(delete_image_task(folder, target))
    return jsonify({"ok": True})

# ── 교재 추가 요청 (Book Request) API ──
@app.route('/api/book_requests/my', methods=['GET'])
@login_required
def get_my_book_request():
    username = session['username']
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, book_name, status, created_at FROM book_requests WHERE username=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (username,))
        row = c.fetchone()
        if row:
            return jsonify({"has_request": True, "request": {"id": row[0], "book_name": row[1], "status": row[2], "created_at": row[3]}})
        return jsonify({"has_request": False})

@app.route('/api/book_requests', methods=['POST'])
@login_required
def create_book_request():
    username = session['username']
    data = request.get_json(silent=True) or {}
    book_name = data.get('book_name', '').strip()
    if not book_name:
        return jsonify({"error": "교재 이름이 필요합니다."}), 400
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # 이미 대기중인 요청이 있는지 확인
        c.execute("SELECT id FROM book_requests WHERE username=? AND status='pending'", (username,))
        if c.fetchone():
            return jsonify({"error": "이미 대기 중인 교재 추가 요청이 있습니다."}), 400
        
        c.execute("INSERT INTO book_requests (username, book_name) VALUES (?, ?)", (username, book_name))
        conn.commit()
    return jsonify({"ok": True})

@app.route('/api/book_requests/<int:req_id>', methods=['DELETE'])
@login_required
def delete_book_request(req_id):
    username = session['username']
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM book_requests WHERE id=? AND username=?", (req_id, username))
        conn.commit()
    return jsonify({"ok": True})

@app.route('/api/admin/book_requests', methods=['GET'])
@admin_required
def admin_get_book_requests():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, book_name, status, created_at FROM book_requests ORDER BY created_at DESC")
        rows = c.fetchall()
        requests = [{
            "id": r[0],
            "username": r[1],
            "book_name": r[2],
            "status": r[3],
            "created_at": r[4]
        } for r in rows]
    return jsonify({"requests": requests})

@app.route('/api/admin/book_requests/<int:req_id>/complete', methods=['POST'])
@admin_required
def admin_complete_book_request(req_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE book_requests SET status='completed' WHERE id=?", (req_id,))
        conn.commit()
    return jsonify({"ok": True})

@app.route('/api/admin/book_requests/<int:req_id>', methods=['DELETE'])
@admin_required
def admin_delete_book_request(req_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM book_requests WHERE id=?", (req_id,))
        conn.commit()
    return jsonify({"ok": True})

BACKUP_TASK_STATUS = {
    'running': False,
    'target': 'github',
    'progress_msg': '',
    'percent': 0,
    'result': None,
    'start_time': 0
}

# ZIP 다운로드 백그라운드 작업 상태
ZIP_TASK_STATUS = {
    'running': False,
    'ready': False,
    'error': None,
    'filepath': None,
    'filename': None,
    'percent': 0,
    'current_file': '',
    'total_files': 0,
    'done_files': 0,
}

def execute_backup_background(cwd):
    global BACKUP_TASK_STATUS
    import subprocess, time, shutil

    BACKUP_TASK_STATUS['running'] = True
    BACKUP_TASK_STATUS['target'] = 'github'
    BACKUP_TASK_STATUS['progress_msg'] = 'GitHub 백업 준비 중...'
    BACKUP_TASK_STATUS['percent'] = 10
    BACKUP_TASK_STATUS['result'] = None
    BACKUP_TASK_STATUS['start_time'] = time.time()

    print("[Backup Task] Started GitHub backup", flush=True)

    lock_file = os.path.join(cwd, '.git_sync.lock')
    github_ok = False
    github_msg = ""
    github_error = None
    commit_msg = None
    changed = False

    try:
        with open(lock_file, 'w') as f:
            f.write(str(time.time()))

        BACKUP_TASK_STATUS['progress_msg'] = 'GitHub 저장소 연결 및 인증 확인 중...'
        BACKUP_TASK_STATUS['percent'] = 25
        print(f"[Backup Task] {BACKUP_TASK_STATUS['progress_msg']}", flush=True)

        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            github_ok = False
            github_error = "GITHUB_TOKEN 환경변수가 설정되지 않았습니다."
        else:
            repo_url = f'https://oauth2:{token}@github.com/Zenon-Ultra/dhekqapdlzj1.git'
            git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}

            remotes = subprocess.run(['git', 'remote'], capture_output=True, text=True, cwd=cwd, env=git_env, timeout=10).stdout.splitlines()
            if 'origin' in remotes:
                subprocess.run(['git', 'remote', 'set-url', 'origin', repo_url], cwd=cwd, check=False, env=git_env, timeout=10)
            else:
                subprocess.run(['git', 'remote', 'add', 'origin', repo_url], cwd=cwd, check=False, env=git_env, timeout=10)

            subprocess.run(['git', 'config', 'user.email', 'bot@render.com'], cwd=cwd, check=False, env=git_env, timeout=10)
            subprocess.run(['git', 'config', 'user.name', 'Render Auto Sync'], cwd=cwd, check=False, env=git_env, timeout=10)

            has_rebase = any(os.path.exists(os.path.join(cwd, reb_dir)) for reb_dir in ['.git/rebase-merge', '.git/rebase-apply'])
            if has_rebase:
                subprocess.run(['git', 'rebase', '--abort'], cwd=cwd, check=False, env=git_env, timeout=10)
                for reb_dir in ['.git/rebase-merge', '.git/rebase-apply']:
                    reb_path = os.path.join(cwd, reb_dir)
                    if os.path.exists(reb_path):
                        shutil.rmtree(reb_path, ignore_errors=True)

            BACKUP_TASK_STATUS['progress_msg'] = '변경된 모든 에셋 및 데이터 파일 감지 중 (git add .)...'
            BACKUP_TASK_STATUS['percent'] = 50
            print(f"[Backup Task] {BACKUP_TASK_STATUS['progress_msg']}", flush=True)
            subprocess.run(['git', 'add', '.'], cwd=cwd, check=False, env=git_env, timeout=20)

            status = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, cwd=cwd, env=git_env, timeout=10)
            changed_files = status.stdout.strip()

            if not changed_files:
                github_ok = True
                github_msg = "변경된 파일이 없습니다. GitHub 저장소가 이미 최신 상태입니다."
                changed = False
                BACKUP_TASK_STATUS['percent'] = 100
            else:
                file_count = len(changed_files.splitlines())
                commit_msg = f'Manual backup by admin at {time.strftime("%Y-%m-%d %H:%M:%S")} ({file_count} files changed)'
                BACKUP_TASK_STATUS['progress_msg'] = f'GitHub 커밋 및 원격 푸시 중 ({file_count}개 파일)...'
                BACKUP_TASK_STATUS['percent'] = 80
                print(f"[Backup Task] {BACKUP_TASK_STATUS['progress_msg']}", flush=True)

                subprocess.run(['git', 'commit', '-m', commit_msg], cwd=cwd, check=True, env=git_env, timeout=20)

                result = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=cwd, capture_output=True, text=True, env=git_env, timeout=30)
                if result.returncode != 0:
                    subprocess.run(['git', 'fetch', 'origin'], cwd=cwd, check=False, env=git_env, timeout=15)
                    result = subprocess.run(['git', 'push', '--force-with-lease', 'origin', 'HEAD:main'], cwd=cwd, capture_output=True, text=True, env=git_env, timeout=30)

                if result.returncode != 0:
                    err_detail = (result.stderr or result.stdout or 'Git push 실패').strip()
                    raise Exception(f"Git push 실패: {err_detail}")

                github_ok = True
                github_msg = f"GitHub 전체 백업 완료! ({file_count}개 변경 파일 커밋/푸시됨)"
                changed = True
                BACKUP_TASK_STATUS['percent'] = 100

        BACKUP_TASK_STATUS['progress_msg'] = '백업 완료!'
        BACKUP_TASK_STATUS['result'] = {
            'ok': github_ok,
            'github_ok': github_ok,
            'github_msg': github_msg or github_error or 'GitHub 백업 완료',
            'github_error': github_error,
            'changed': changed,
            'commit': commit_msg
        }

    except Exception as e:
        BACKUP_TASK_STATUS['percent'] = 100
        BACKUP_TASK_STATUS['result'] = {
            'ok': False,
            'error': f'GitHub 백업 중 예외 발생: {e}'
        }
        print(f"[Backup Task] Severe error: {e}", flush=True)
    finally:
        BACKUP_TASK_STATUS['running'] = False
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception:
                pass

@app.route('/api/admin/github_backup', methods=['POST'])
@admin_required
def github_backup():
    import threading
    global BACKUP_TASK_STATUS

    if BACKUP_TASK_STATUS['running']:
        return jsonify({
            'ok': False,
            'error': '이미 백업 작업이 진행 중입니다.',
            'running': True,
            'progress_msg': BACKUP_TASK_STATUS['progress_msg']
        }), 409

    cwd = os.path.dirname(os.path.abspath(__file__))

    t = threading.Thread(target=execute_backup_background, args=(cwd,), daemon=True)
    t.start()

    return jsonify({
        'ok': True,
        'status': 'started',
        'message': 'GitHub 백업이 시작되었습니다.'
    })

def _run_zip_background(cwd):
    """백그라운드 스레드에서 ZIP 파일을 생성하고 진행 상태를 파일에 기록합니다."""
    global ZIP_TASK_STATUS
    from services.backup import create_project_zip, _write_status

    base = {
        'running': True, 'ready': False, 'error': None,
        'filepath': None, 'filename': None,
        'percent': 0, 'current_file': '', 'total_files': 0, 'done_files': 0,
    }
    ZIP_TASK_STATUS.update(base)
    _write_status(base)
    print("[ZIP Task] Starting ZIP creation...", flush=True)

    try:
        def _on_progress(current, total, filename):
            pct = int(current / total * 100) if total else 0
            ZIP_TASK_STATUS['done_files'] = current
            ZIP_TASK_STATUS['total_files'] = total
            ZIP_TASK_STATUS['percent'] = pct
            ZIP_TASK_STATUS['current_file'] = filename
            # 10파일마다 파일에 기록 (I/O 과부하 방지)
            if current % 10 == 0 or current == total:
                _write_status({
                    'running': True, 'ready': False, 'error': None,
                    'filepath': None, 'filename': None,
                    'percent': pct, 'current_file': filename,
                    'total_files': total, 'done_files': current,
                })

        zip_filepath, zip_filename = create_project_zip(cwd, progress_callback=_on_progress)

        done = {
            'running': False, 'ready': True, 'error': None,
            'filepath': zip_filepath, 'filename': zip_filename,
            'percent': 100, 'current_file': '',
            'total_files': ZIP_TASK_STATUS['total_files'],
            'done_files': ZIP_TASK_STATUS['total_files'],
        }
        ZIP_TASK_STATUS.update(done)
        _write_status(done)
        print(f"[ZIP Task] Done: {zip_filename}", flush=True)

    except Exception as e:
        err = {
            'running': False, 'ready': False, 'error': str(e),
            'filepath': None, 'filename': None,
            'percent': ZIP_TASK_STATUS.get('percent', 0),
            'current_file': '', 'total_files': ZIP_TASK_STATUS.get('total_files', 0),
            'done_files': ZIP_TASK_STATUS.get('done_files', 0),
        }
        ZIP_TASK_STATUS.update(err)
        _write_status(err)
        print(f"[ZIP Task] Error: {e}", flush=True)
    finally:
        ZIP_TASK_STATUS['running'] = False

@app.route('/api/admin/prepare_backup_zip', methods=['POST'])
@admin_required
def prepare_backup_zip():
    """ZIP 압축을 백그라운드에서 시작합니다. 완료 여부는 /api/admin/backup_zip_status로 폴링하세요."""
    import threading
    global ZIP_TASK_STATUS

    if ZIP_TASK_STATUS['running']:
        return jsonify({'ok': False, 'error': '이미 ZIP 생성이 진행 중입니다.'}), 409

    # 이전 ZIP 파일 정리
    old_path = ZIP_TASK_STATUS.get('filepath')
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception:
            pass

    cwd = os.path.dirname(os.path.abspath(__file__))
    t = threading.Thread(target=_run_zip_background, args=(cwd,), daemon=True)
    t.start()
    return jsonify({'ok': True, 'message': 'ZIP 생성이 시작되었습니다. 상태를 폴링하세요.'})

@app.route('/api/admin/backup_zip_status', methods=['GET'])
@admin_required
def backup_zip_status():
    """ZIP 생성 진행 상태를 반환합니다. 파일 기반 상태를 우선 읽어 워커 재시작에도 안전합니다."""
    from services.backup import read_zip_status
    # 파일 기반 상태(워커 재시작 대비) 우선, 없으면 인메모리 폴백
    s = read_zip_status()
    # 인메모리 상태가 더 최신인 경우(같은 워커) 덮어씀
    if ZIP_TASK_STATUS.get('done_files', 0) >= s.get('done_files', 0):
        s = dict(ZIP_TASK_STATUS)
    return jsonify({
        'ok': True,
        'running': s.get('running', False),
        'ready': s.get('ready', False),
        'error': s.get('error'),
        'filename': s.get('filename'),
        'percent': s.get('percent', 0),
        'current_file': s.get('current_file', ''),
        'total_files': s.get('total_files', 0),
        'done_files': s.get('done_files', 0),
    })

@app.route('/api/admin/download_backup_zip', methods=['GET'])
@admin_required
def download_backup_zip():
    """백그라운드에서 생성된 ZIP 파일을 다운로드합니다. prepare_backup_zip 후 ready 상태일 때 호출하세요."""
    from services.backup import read_zip_status
    global ZIP_TASK_STATUS

    # 파일 기반 상태와 인메모리 상태 중 ready인 것 우선
    s = read_zip_status()
    if ZIP_TASK_STATUS.get('ready'):
        s = dict(ZIP_TASK_STATUS)

    zip_filepath = s.get('filepath')
    zip_filename = s.get('filename')

    if not ZIP_TASK_STATUS['ready'] or not zip_filepath or not os.path.exists(zip_filepath):
        return jsonify({'ok': False, 'error': 'ZIP 파일이 아직 준비되지 않았습니다. 먼저 prepare_backup_zip을 호출하세요.'}), 400

    @after_this_request
    def remove_file(response):
        try:
            if os.path.exists(zip_filepath):
                os.remove(zip_filepath)
        except Exception:
            pass
        # 상태 초기화
        ZIP_TASK_STATUS['ready'] = False
        ZIP_TASK_STATUS['filepath'] = None
        ZIP_TASK_STATUS['filename'] = None
        return response

    return send_file(
        zip_filepath,
        as_attachment=True,
        download_name=zip_filename,
        mimetype='application/zip'
    )

@app.route('/api/admin/github_backup_status', methods=['GET'])
@admin_required
def github_backup_status():
    global BACKUP_TASK_STATUS
    return jsonify(BACKUP_TASK_STATUS)

@app.route('/api/admin/github_auto_sync', methods=['GET', 'POST'])
@admin_required
def github_auto_sync_toggle():
    """자동 백업 ON/OFF 상태를 조회하거나 변경합니다."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get('enabled', False))
        set_auto_sync_enabled(enabled)
        return jsonify({'ok': True, 'enabled': is_auto_sync_enabled()})
    return jsonify({'ok': True, 'enabled': is_auto_sync_enabled()})

@app.route('/api/admin/maintenance', methods=['GET', 'POST'])
@admin_required
def maintenance_mode_toggle():
    """점검 모드 ON/OFF 상태를 조회하거나 변경합니다."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get('enabled', False))
        set_maintenance_mode(enabled)
        return jsonify({'ok': True, 'enabled': get_maintenance_mode()})
    return jsonify({'ok': True, 'enabled': get_maintenance_mode()})

if __name__ == '__main__':
    print("Server has started! Open browser and go to http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
