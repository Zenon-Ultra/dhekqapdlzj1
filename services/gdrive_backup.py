import os
import json
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional

# Google Drive API
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False


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

# 제외할 파일명 또는 패턴 목록
EXCLUDE_FILES = {
    ".env",
    ".git_sync.lock",
    ".DS_Store",
    "service_account.json",
    "gdrive_credentials.json"
}


def get_seoul_now_str() -> str:
    """한국 시간(Asia/Seoul, UTC+9) 기준 날짜/시간 문자열을 반환합니다."""
    seoul_tz = timezone(timedelta(hours=9))
    now = datetime.now(seoul_tz)
    return now.strftime("%Y-%m-%d_%H-%M-%S")


def create_project_zip(root_dir: str) -> Tuple[str, str]:
    """
    현재 Render 프로젝트의 핵심 소스 및 데이터(admin.db 포함)를 ZIP으로 압축합니다.
    (이미지는 이미 압축 파일이므로 ZIP_STORED 모드를 적용하여 생성 시간을 1~2초대로 단축)
    
    Returns:
        (zip_filepath, zip_filename)
    """
    time_str = get_seoul_now_str()
    short_id = uuid.uuid4().hex[:6]
    zip_filename = f"HYPERX_Backup_{time_str}_{short_id}.zip"
    zip_filepath = os.path.join(root_dir, zip_filename)

    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_STORED) as zip_file:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # 1. 제외할 디렉터리 필터링
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith('.')]

            for filename in filenames:
                # 2. 자기 자신(새로 생성 중인 zip) 및 제외 대상 파일 필터링
                if filename.endswith('.zip') or filename in EXCLUDE_FILES:
                    continue
                if filename.endswith('.pyc') or filename.endswith('.pyo'):
                    continue

                abs_file = os.path.join(dirpath, filename)
                rel_file = os.path.relpath(abs_file, root_dir)

                # zip 파일에 추가
                zip_file.write(abs_file, rel_file)

    return zip_filepath, zip_filename


def backup_to_google_drive(root_dir: str) -> Tuple[bool, str, Optional[str]]:
    """
    프로젝트를 ZIP으로 압축하여 Google Drive 지정 폴더로 업로드 후 임시 ZIP을 삭제합니다.
    
    Returns:
        (success: bool, message: str, zip_filename: Optional[str])
    """
    if not GDRIVE_AVAILABLE:
        return False, "google-api-python-client 또는 google-auth 패키지가 설치되지 않았습니다.", None

    service_account_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    service_account_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not folder_id:
        return False, "GOOGLE_DRIVE_FOLDER_ID 환경변수가 설정되지 않았습니다.", None

    creds_info = None
    if service_account_env:
        try:
            creds_info = json.loads(service_account_env)
        except Exception as e:
            return False, f"GOOGLE_SERVICE_ACCOUNT_JSON 파싱 실패: {e}", None
    elif service_account_file and os.path.exists(service_account_file):
        try:
            with open(service_account_file, 'r', encoding='utf-8') as f:
                creds_info = json.load(f)
        except Exception as e:
            return False, f"인증 키 파일 읽기 실패: {e}", None
    else:
        return False, "Google Service Account 인증 정보(GOOGLE_SERVICE_ACCOUNT_JSON)가 설정되지 않았습니다.", None

    zip_filepath = None
    zip_filename = None

    try:
        # 1. ZIP 압축 생성
        zip_filepath, zip_filename = create_project_zip(root_dir)

        # 2. Credentials 생성
        scopes = ['https://www.googleapis.com/auth/drive.file']
        credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
        service = build('drive', 'v3', credentials=credentials)

        # 3. Google Drive 업로드
        file_metadata = {
            'name': zip_filename,
            'parents': [folder_id]
        }
        media = MediaFileUpload(zip_filepath, mimetype='application/zip', resumable=True)
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name'
        ).execute()

        file_id = uploaded_file.get('id')
        return True, f"Google Drive 백업 성공! ({zip_filename})", zip_filename

    except Exception as e:
        return False, f"Google Drive 업로드 중 오류 발생: {e}", zip_filename

    finally:
        # 4. 백업 완료 후 Render 서버 내 임시 ZIP 파일 삭제
        if zip_filepath and os.path.exists(zip_filepath):
            try:
                os.remove(zip_filepath)
            except Exception:
                pass
