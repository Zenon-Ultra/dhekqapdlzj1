import os
import uuid
import zipfile
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Tuple

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

def get_seoul_now_str() -> str:
    """한국 시간(Asia/Seoul, UTC+9) 기준 날짜/시간 문자열을 반환합니다."""
    seoul_tz = timezone(timedelta(hours=9))
    now = datetime.now(seoul_tz)
    return now.strftime("%Y-%m-%d_%H-%M-%S")

def create_project_zip(root_dir: str) -> Tuple[str, str]:
    """
    현재 프로젝트의 핵심 소스 및 데이터(admin.db, 교재 에셋 포함)를 ZIP으로 압축합니다.
    시스템 임시 폴더에 생성을 진행하여 프로젝트 오염을 방지합니다.
    
    Returns:
        (zip_filepath, zip_filename)
    """
    time_str = get_seoul_now_str()
    short_id = uuid.uuid4().hex[:6]
    zip_filename = f"HYPERX_Backup_{time_str}_{short_id}.zip"
    temp_dir = tempfile.gettempdir()
    zip_filepath = os.path.join(temp_dir, zip_filename)

    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # 1. 제외할 디렉터리 필터링
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith('.')]

            for filename in filenames:
                # 2. 제외 대상 파일 필터링
                if filename.endswith('.zip') or filename in EXCLUDE_FILES:
                    continue
                if filename.endswith('.pyc') or filename.endswith('.pyo'):
                    continue

                abs_file = os.path.join(dirpath, filename)
                rel_file = os.path.relpath(abs_file, root_dir)

                # zip 파일에 추가
                try:
                    zip_file.write(abs_file, rel_file)
                except Exception as write_err:
                    print(f"[ZIP Warning] Skipping file {abs_file}: {write_err}")

    return zip_filepath, zip_filename
