from flask import Flask, render_template, request, Response, jsonify, send_from_directory, session, redirect, url_for
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

        # admin123 계정 생성 또는 역할 업데이트
        c.execute("SELECT role FROM users WHERE username='admin123'")
        row = c.fetchone()
        hashed = generate_password_hash('admin123')
        if not row:
            c.execute("INSERT INTO users (username, password, role) VALUES ('admin123', ?, 'admin')", (hashed,))
        else:
            c.execute("UPDATE users SET role='admin' WHERE username='admin123'")
        conn.commit()

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


UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
    return Response(cleanup_images_task([folder]), mimetype='text/event-stream')

@app.route('/api/run/build', methods=['GET'])
@admin_required
def run_build():
    folder = request.args.get('folder', '')
    cover_url = request.args.get('cover_url', '') or None
    return Response(generate_assets_task([folder], cover_url=cover_url), mimetype='text/event-stream')

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

if __name__ == '__main__':
    print("Server has started! Open browser and go to http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
