# HYPERX 저장소 개선 및 이전 안내

변경은 codex/b2-persistent-storage 브랜치와 PR #1에만 반영합니다.
main, 기존 img 파일, 기존 admin.db와 Git 기록은 삭제하지 않습니다.
실제 B2·Neon 계정이 없다는 사용자 답변에 따라 외부 서비스 생성·이전·배포는 실행하지 않았습니다.

## 구현 내용

- B2의 SHA-256 기반 불변 객체와 검증 후 전환하는 교재 목록, 복구용 과거 목록.
- 편집할 교재만 임시 다운로드하고, 분할·합치기·삭제·여백·표지 편집 후 검증하여 저장.
- 삭제된 문제와 번호가 바뀐 문제의 스크랩도 원래 이미지에 연결.
- PDF 추출 WebP 압축. 같은 이름의 업로드·교재를 자동 덮어쓰지 않음.
- 같은 출처 이미지 응답으로 외부 CORS 설정·서명 URL 만료 없이 뷰어/스크랩 사용.
- GitHub 자동 커밋/강제 푸시 중지. 기존 백업 탭에서 전체 ZIP 다운로드 제공.
- 클라우드 현재 이미지 + 스크랩 과거 이미지 + 일관된 DB 내보내기(database.json)를 ZIP에 포함.
- ZIP 전체 체크섬 검증, 새 디렉터리에만 복원하고 로컬 SQLite DB를 재구성.
- SQLite 로컬 운영, 외부 PostgreSQL 선택 연결. Render에서는 외부 DB·B2·세션 키 필수.
- 알려진 기본 관리자 비밀번호 중지, 새 관리자 환경변수로 초기 생성.
- 폼/fetch/EventSource 요청에 세션 CSRF 토큰, 교차 출처 검사, 경로 검증과 안전한 로그인 리디렉션.
- Docker 배포에서 기존 이미지·DB를 복사하지 않아 런타임 디스크에 누적 원본이 들어오지 않음.
  원본은 Git/별도 백업에 그대로 유지. 실제 Docker 빌드는 이 환경에 Docker가 없어 실행하지 못함.

## 로컬 실행

Python 3.11 가상환경에서 requirements.txt와 pytest 설치 후 python app.py 실행.
인증키가 없으면 SQLite와 로컬 이미지로 동작합니다.
SECRET_KEY를 고정하지 않은 개발 실행은 재시작 시 로그인이 풀립니다.

python -m pytest -q
python tests/browser_smoke_server.py

두 번째 명령은 합성 이미지와 메모리 B2로 http://127.0.0.1:5077 에서만 동작하는
개발용 UI 서버입니다. 계정 smoke-admin / local-smoke-password는 이 개발 서버 전용이며,
실서비스에 사용하면 안 됩니다. 실제 데이터와 분리된 .browser-smoke 디렉터리를 사용합니다.

## 필요한 환경변수

| 변수 | 용도 |
|---|---|
| SECRET_KEY | 최소 32자 무작위 세션 키, Render 필수 |
| ADMIN_USERNAME / ADMIN_PASSWORD | 새 관리자 초기 생성, 비밀번호 최소 12자. 기존 커스텀 계정 암호는 재설정하지 않음 |
| DATABASE_URL | Neon PostgreSQL 연결 문자열, sslmode=require 권장. Render 필수 |
| STORAGE_BACKEND | local(개발 기본) 또는 b2(Render 필수) |
| B2_ENDPOINT_URL | https://s3.REGION.backblazeb2.com |
| B2_REGION / B2_BUCKET | 리전과 전용 비공개 버킷 |
| B2_KEY_ID / B2_APPLICATION_KEY | 해당 버킷 범위로 제한한 읽기/쓰기 키 |
| B2_PREFIX | 기본 hyperx, 전용 경로 |
| B2_MAX_BATCH_BYTES | 기본 500000000, 교재 업로드 작업의 바이트 제한 |
| BACKUP_MAX_BYTES | 기본 500000000, ZIP 백업 바이트 제한 |
| BACKUP_DIRECTORY | 기본 앱 루트의 .storage-backup, 충분한 임시 공간 필요 |
| DB_PATH | 로컬 SQLite 경로, 생략 시 admin.db |

키를 HTML/저장소/채팅에 넣지 마세요. .env.example은 값이 없는 예제입니다.
단일 인스턴스, 단일 워커 구성만 지원하며, 같은 버킷 경로에 동시 배포가 쓰면 안 됩니다.

## 기존 데이터 이전 순서

1. 점검 모드에서 쓰기를 멈추고, 운영 img 전체와 일관된 SQLite 백업을 별도로 보관합니다.
   로컬 SQLite 백업은 정지 상태 복사 또는 SQLite backup API를 사용하세요.
2. 모든 원본 img가 있는 별도 전체 체크아웃에서 아래 명령을 실행합니다.
   python scripts/migrate_storage.py
   출력된 교재 수·파일 수·용량 및 .migration-inventory.json을 확인합니다.
3. B2 환경변수를 설정하고 다음 명령을 실행합니다.
   python scripts/migrate_storage.py --apply --verify
   파일별 SHA-256을 원본과 비교합니다. 로컬 원본을 바꾸거나 비우지 않습니다.
   중단 후 재개는 --apply --resume --verify이며, 원본과 다른 원격 데이터가 있으면 중지합니다.
   교재별로 반영하므로 완료 전까지 서비스 점검을 유지하세요.
4. 빈 Neon Free DB를 직접 준비하고 DATABASE_URL을 설정합니다.
   python scripts/migrate_database.py original-admin.db
   위 명령은 인증키 없이 원본 행 수만 확인합니다.
   python scripts/migrate_database.py original-admin.db --apply
   단일 트랜잭션으로 테이블·값·ID를 복사하고 검증합니다. 비어 있지 않은 대상은 거부합니다.
   앱을 먼저 실행하면 관리자 행이 생길 수 있으므로 DB 이전부터 완료하세요.
5. Render에서 이 브랜치의 Dockerfile로 무료 서비스를 구성합니다. 자동 배포를 끄고,
   환경변수를 설정한 뒤 검증된 B2 목록·Neon DB에 연결하여 배포합니다.
   .dockerignore가 img, textbooks, *.db, 업로드, 비밀키를 런타임 이미지에서 제외합니다.
   재시작 시 B2 목록으로 이미지 이름과 교재 HTML만 복구하고 이미지 본문은 임시로만 사용합니다.
6. 로그인, 교재 수·파일 수, 스크랩, 분할·합치기·삭제·여백·표지·PDF 추출과 ZIP 복원을
   실제 서비스에서 확인한 다음 점검을 해제합니다.

## 백업 검증·복원 및 롤백

관리자 데이터 백업 탭의 ZIP에는 database.json과 backup-manifest.json이 포함됩니다.
python scripts/restore_backup.py BACKUP.zip
python scripts/restore_backup.py BACKUP.zip --destination NEW_DIRECTORY

첫 명령은 검증만, 두 번째는 존재하지 않는 새 디렉터리에만 복원합니다.
복원된 admin.db와 이미지로 인증키 없이 로컬 실행할 수 있습니다.
과거 스크랩 이미지는 img/_restored_scraps로 연결합니다. 원본 계정/행은 그대로 보존됩니다.
백업은 비밀번호 해시와 회원 정보를 포함하므로 접근을 제한해 보관하세요.

실패 시 기존 코드와 보관한 원본 DB·이미지로 되돌릴 수 있습니다.
B2는 객체를 자동 삭제하지 않으며 snapshots/<hash>.json 목록을 보존합니다.
원격 목록을 과거 버전으로 되돌릴 때는 모든 쓰기를 멈춘 상태에서 선택한 목록을
catalog.json으로 복사해야 합니다. DB는 별도의 일관된 시점 백업으로 복구하세요.

## 무료 운영 한도와 과금 위험

공식 페이지 확인 기준: 2026-10-23.
- https://www.backblaze.com/cloud-storage/pricing
- https://www.backblaze.com/cloud-storage/transaction-pricing
- https://neon.com/pricing
- https://render.com/docs/free

B2: 저장 10GB 무료, 월 평균 저장량 3배까지 다운로드 무료. 추가 다운로드는 $0.01/GB,
일반 저장은 현재 $6.95/TB/월부터이며 공식 페이지는 무료 트랜잭션을 안내합니다.
과거 객체도 저장 용량에 포함되고 검증·백업·편집 임시 다운로드도 전송량을 사용합니다.
계정의 용량/요금 경고·제한을 직접 설정하고, 엄격히 0원을 원하면 결제 수단을 추가하지
말고 무료 범위에 머물러야 합니다. 앱의 작업별 바이트 제한은 계정 전체 과금 차단 장치가 아닙니다.

Neon Free: 프로젝트당 1GB, 월 100 CU-hours, 카드 없이 이용 가능. 유료 플랜으로 전환하지
마세요. 전송·컴퓨트 한도도 콘솔에서 확인하세요. Render Free는 15분 유휴 후 중지되고
재배포/재시작에 로컬 변경이 사라지므로, Render 무료 PostgreSQL을 영구 DB로 사용하지 않습니다.
앱 경유 이미지 응답은 Render 전송량도 사용합니다. 무제한 무료나 무중단 운영을 보장하지 않습니다.

## 검증 범위와 남은 외부 검증

격리된 SQLite, 메모리 S3, 합성 PDF·이미지를 사용한 테스트 24개 통과.
문제 편집, 삭제 후 스크랩 보존, 재시작 목록, 이전 재개/검증, ZIP 복원, 예산 제한,
CSRF/다른 사용자 접근 차단, 업로드 실패 시 기존 목록 보존 등을 검증했습니다.
브라우저에서 로그인·WebP 이미지 실제 로딩·스크랩 저장/조회·관리자 화면 및 ZIP 생성·다운로드 HTTP 200 완료를 확인했습니다.
인쇄 미리보기 호출은 확인했지만 실제 종이 인쇄나 PDF 저장은 하지 않았습니다.
B2·Neon 계정이 없어 실제 API·PostgreSQL 이전·운영 교재 이전은 실행하지 않았습니다.
Docker가 설치되어 있지 않아 컨테이너 빌드도 미실행입니다. PR은 이 검증 전까지 Draft입니다.
단일 교재 편집과 ZIP에는 임시 디스크 공간이 필요하며, 너무 큰 작업은 제한으로 중단됩니다.


## 실제 계정 연결 준비

사용자 확인: B2와 Neon 모두 아직 계정/설정이 필요합니다.
가입·본인 인증·약관 동의는 사용자가 직접 진행합니다. 카드 등록/유료 전환은 하지 않습니다.

1. Backblaze B2 계정을 만들고, 비공개 버킷 하나를 생성합니다.
   버킷의 S3 Endpoint와 리전, 이름을 .env.cloud의 B2_ENDPOINT_URL / B2_REGION / B2_BUCKET에 입력합니다.
   그 버킷만 허용하는 읽기/쓰기/목록 권한의 Application Key를 직접 생성하여
   keyID를 B2_KEY_ID, applicationKey를 B2_APPLICATION_KEY에 넣습니다.
2. Neon Free에서 프로젝트를 만들고 Connect 화면의 PostgreSQL 연결 문자열을
   .env.cloud의 DATABASE_URL에 입력합니다. sslmode=require를 포함하세요.
   처음에는 빈 대상 DB를 사용합니다. 기존 DB 이전 전에 앱을 실행하지 마세요.
3. 비밀값은 채팅이나 GitHub에 보내지 않고 로컬 .env.cloud 또는 Render 비밀 환경변수로만 보관합니다.
   .env는 Git 제외 대상이며, 이미 로컬 전용 SECRET_KEY를 안전하게 생성해 두었습니다.
4. python scripts/check_cloud_connections.py 로 실제 B2 읽기와 PostgreSQL TLS 접속을 검사합니다.
   --write-probe는 작은 B2 파일 1개를 올리고 다시 읽어 쓰기 권한도 확인합니다.
   검사 자체는 교재/DB를 이전하거나 삭제하지 않습니다.
5. 성공하면 위의 기존 데이터 이전 순서를 진행한 뒤 STORAGE_BACKEND=b2로 전환합니다.
   관리자 새 계정이 필요하면 ADMIN_USERNAME과 12자 이상의 ADMIN_PASSWORD도 지정합니다.

변경 파일: app.py, book_assets.py, services/storage.py·database.py·tasks.py·github_sync.py·backup.py·data_export.py·security.py,
scripts/migrate_storage.py·migrate_database.py·restore_backup.py·check_cloud_connections.py,
templates/main.html·admin.html, static/security.js, Dockerfile, .dockerignore,
.env.example, .gitignore, git_update.bat, pytest.ini 및 tests/.
