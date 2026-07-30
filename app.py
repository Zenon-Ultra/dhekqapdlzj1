from flask import Flask, render_template, request, Response, jsonify, send_from_directory, session, redirect, url_for
import os
import sqlite3
from functools import wraps

from services.tasks import extract_pdf_task, cleanup_images_task, generate_assets_task, split_image_task, merge_images_task
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super_secret_admin_key'
DB_PATH = os.path.join(os.path.dirname(__file__), 'admin.db')

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
        c.execute("SELECT * FROM users WHERE username='admin123'")
        if not c.fetchone():
            hashed = generate_password_hash('admin123')
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin123', hashed))
        conn.commit()

# 앱 시작 시 DB 초기화
init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            # API 요청인 경우 401 반환, 일반 페이지 요청인 경우 리다이렉트
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('login'))
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
def main_page():
    return render_template('main.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE username=?", (username,))
            user = c.fetchone()
            if user and check_password_hash(user[0], password):
                session['logged_in'] = True
                return redirect(url_for('admin'))
            else:
                return render_template('login.html', error="아이디 또는 비밀번호가 잘못되었습니다.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

@app.route('/tutorial.html')
def tutorial():
    return render_template('tutorial.html')

@app.route('/new-textbook.html')
def new_textbook():
    return render_template('new-textbook.html')

@app.route('/template_editor.html')
def template_editor():
    return render_template('template_editor.html')

@app.route('/ebsi_sc.html')
def ebsi_sc():
    return render_template('ebsi_sc.html')

# ==========================================
# Static Files Routes (img / textbooks)
# ==========================================
@app.route('/img/<path:filename>')
def serve_img(filename):
    return send_from_directory('img', filename)

@app.route('/textbooks/<path:filename>')
def serve_textbooks(filename):
    return send_from_directory('textbooks', filename)

# ==========================================
# Admin API
# ==========================================
@app.route('/api/folders', methods=['GET'])
def list_folders():
    base_dir = "img"
    if not os.path.exists(base_dir):
        return jsonify({"folders": []})
    folders = [f for f in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, f))]
    return jsonify({"folders": folders})

@app.route('/api/upload_pdf', methods=['POST'])
@login_required
def upload_pdf():
    """PDF 파일을 서버 uploads/ 폴더에 저장합니다."""
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
@login_required
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
@login_required
def run_trim():
    folder = request.args.get('folder', '')
    return Response(cleanup_images_task([folder]), mimetype='text/event-stream')

@app.route('/api/run/build', methods=['GET'])
@login_required
def run_build():
    folder = request.args.get('folder', '')
    cover_url = request.args.get('cover_url', '') or None
    return Response(generate_assets_task([folder], cover_url=cover_url), mimetype='text/event-stream')

@app.route('/api/run/split_sync', methods=['GET'])
@login_required
def run_split_sync():
    """ebsi_sc.html에서 즉시 분할 호출 — 완료될 때까지 기다렸다가 JSON 반환."""
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
@login_required
def run_build_sync():
    """ebsi_sc.html에서 즉시 에셋 재생성 — 완료될 때까지 기다렸다가 JSON 반환."""
    folder = request.args.get('folder', '')
    cover_url = request.args.get('cover_url', '') or None
    list(generate_assets_task([folder], cover_url=cover_url))
    return jsonify({"ok": True})

@app.route('/api/run/split', methods=['GET'])
@login_required
def run_split():
    folder = request.args.get('folder', '')
    num_str = request.args.get('num', '')
    try:
        num = int(num_str)
    except ValueError:
        return Response("data: {\"msg\": \"🚨 숫자 형식이 잘못되었습니다.\", \"percent\": 100}\n\n", mimetype='text/event-stream')
    return Response(split_image_task(folder, num), mimetype='text/event-stream')

@app.route('/api/run/merge', methods=['GET'])
@login_required
def run_merge():
    folder = request.args.get('folder', '')
    try:
        start = int(request.args.get('start', ''))
        end   = int(request.args.get('end', ''))
    except ValueError:
        return Response("data: {\"msg\": \"🚨 숫자 형식이 잘못되었습니다.\", \"percent\": 100}\n\n", mimetype='text/event-stream')
    return Response(merge_images_task(folder, start, end), mimetype='text/event-stream')

@app.route('/api/run/merge_sync', methods=['GET'])
@login_required
def run_merge_sync():
    """ebsi_sc.html에서 즉시 합치기 호출 — 완료될 때까지 기다렸다가 JSON 반환."""
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

if __name__ == '__main__':
    # Flask 앱 실행
    print("Server has started! Open browser and go to http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
