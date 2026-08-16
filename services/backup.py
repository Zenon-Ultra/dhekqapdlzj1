import os
import json
import uuid
import zipfile
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Callable

# 제외할 디렉터리 명칭 목록
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "node_modules",
    "scratch",
    "tmp",
    "temp",
    ".gemini",
    ".agents"
}

# 제외할 파일명 목록
EXCLUDE_FILES = {
    ".env",
    ".git_sync.lock",
    ".DS_Store"
}

# 이미 압축된 포맷 → ZIP_STORED(무압축)로 처리해 CPU 낭비 방지
_STORE_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.heic',
    '.mp4', '.mov', '.avi', '.mkv', '.webm',
    '.mp3', '.aac', '.ogg', '.flac', '.wav',
    '.zip', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.woff', '.woff2', '.ttf', '.otf',
    '.pdf',
}

# 진행 상태를 기록하는 임시 JSON 파일 경로 (워커 재시작 대비)
ZIP_STATUS_FILE = os.path.join(tempfile.gettempdir(), 'hyperx_zip_status.json')

def _write_status(data: dict):
    """진행 상태를 JSON 파일에 원자적으로 기록합니다."""
    try:
        tmp = ZIP_STATUS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, ZIP_STATUS_FILE)
    except Exception:
        pass

def read_zip_status() -> dict:
    """JSON 파일에서 진행 상태를 읽습니다. 파일이 없으면 기본값 반환."""
    try:
        with open(ZIP_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            'running': False, 'ready': False, 'error': None,
            'filepath': None, 'filename': None,
            'percent': 0, 'current_file': '',
            'total_files': 0, 'done_files': 0,
        }

def get_seoul_now_str() -> str:
    """한국 시간(Asia/Seoul, UTC+9) 기준 날짜/시간 문자열을 반환합니다."""
    seoul_tz = timezone(timedelta(hours=9))
    now = datetime.now(seoul_tz)
    return now.strftime("%Y-%m-%d_%H-%M-%S")

def _collect_files(root_dir: str) -> list:
    """압축 대상 파일 목록을 미리 수집합니다."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for filename in filenames:
            if filename.endswith('.zip') or filename in EXCLUDE_FILES:
                continue
            if filename.endswith('.pyc') or filename.endswith('.pyo'):
                continue
            abs_file = os.path.join(dirpath, filename)
            rel_file = os.path.relpath(abs_file, root_dir)
            files.append((abs_file, rel_file))
    return files

def create_project_zip(
    root_dir: str,
    progress_callback: Optional[Callable] = None
) -> Tuple[str, str]:
    """
    현재 프로젝트의 핵심 소스 및 데이터(admin.db, 교재 에셋 포함)를 ZIP으로 압축합니다.
    이미지·폰트 등 이미 압축된 파일은 ZIP_STORED(무압축)로 처리하여 속도를 극대화합니다.

    Args:
        root_dir: 압축할 루트 디렉터리
        progress_callback: (current, total, filename) 시그니처의 선택적 콜백 함수

    Returns:
        (zip_filepath, zip_filename)
    """
    time_str = get_seoul_now_str()
    short_id = uuid.uuid4().hex[:6]
    zip_filename = f"HYPERX_Backup_{time_str}_{short_id}.zip"
    temp_dir = tempfile.gettempdir()
    zip_filepath = os.path.join(temp_dir, zip_filename)

    # 전체 파일 목록 사전 수집 → 진행률 계산 가능
    all_files = _collect_files(root_dir)
    total = len(all_files)

    with zipfile.ZipFile(zip_filepath, 'w') as zip_file:
        for idx, (abs_file, rel_file) in enumerate(all_files, start=1):
            # 이미 압축된 포맷은 STORED, 그 외는 DEFLATED
            ext = os.path.splitext(rel_file)[1].lower()
            compress = zipfile.ZIP_STORED if ext in _STORE_EXTS else zipfile.ZIP_DEFLATED
            try:
                zip_file.write(abs_file, rel_file, compress_type=compress)
            except Exception as write_err:
                print(f"[ZIP Warning] Skipping file {abs_file}: {write_err}")
            if progress_callback:
                progress_callback(idx, total, rel_file)

    return zip_filepath, zip_filename

