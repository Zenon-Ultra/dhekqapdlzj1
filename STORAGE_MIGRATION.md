# HYPERX 저장소 개선 및 이전 안내

변경은 codex/b2-persistent-storage 브랜치와 PR #1에만 반영합니다.
main, 기존 img 파일, 기존 admin.db와 Git 기록은 삭제하지 않습니다.
B2·Neon 실제 연결 및 GitHub 최신 원본의 비파괴 이전·검증을 완료했습니다. Render 운영 전환은 최종 승인 전이며 기존 사이트는 그대로 실행 중입니다.

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

격리된 SQLite, 메모리 S3, 합성 PDF·이미지를 사용한 테스트 32개 통과 (최종 실행 7.61초).
문제 편집, 삭제 후 스크랩 보존, 재시작 목록, 이전 재개/검증, ZIP 복원, 예산 제한,
CSRF/다른 사용자 접근 차단, 업로드 실패 시 기존 목록 보존 등을 검증했습니다.
브라우저에서 로그인·WebP 이미지 실제 로딩·스크랩 저장/조회·관리자 화면 및 ZIP 생성·다운로드 HTTP 200 완료를 확인했습니다.
인쇄 미리보기 호출은 확인했지만 실제 종이 인쇄나 PDF 저장은 하지 않았습니다.
Neon 실제 TLS 접속과 별도 임시 스키마의 테이블/사용자/스크랩/요청/upsert 호환 검증을 통과했고 모두 롤백했습니다. PostgreSQL 운영 DB에 원본 4개 테이블의 모든 행·컬럼을 이전하고 값 일치를 검증했습니다. B2 버킷 전용 키 생성 후 작은 파일의 실제 업로드/다운로드 검증도 통과했습니다. 운영 교재 7권의 B2 이전과 원본/서버 체크섬 검증을 완료했습니다.
Docker가 설치되어 있지 않아 컨테이너 빌드도 미실행입니다. PR은 이 검증 전까지 Draft입니다.
단일 교재 편집과 ZIP에는 임시 디스크 공간이 필요하며, 너무 큰 작업은 제한으로 중단됩니다.


## 실제 계정 연결 준비

최신 상태: B2 hyperx 비공개 버킷의 경로 제한 키 설정·실제 읽기/쓰기, Neon Free 프로젝트·실제 TLS 연결 모두 완료했습니다.
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


## Neon 실제 설정 완료 (2026-10-23)

- 프로젝트/데이터베이스: hyperx / hyperx, production 브랜치
- PostgreSQL 18, AWS US East 2 (Ohio), Free plan 유지
- 컴퓨트 최소/최대 0.25 CU, 5분 유휴 후 scale-to-zero 유지
- 풀링·TLS 연결 문자열을 Git 제외 .env.cloud에 저장. 비밀값은 보고서/커밋에 포함하지 않음
- 실제 SELECT 1 및 임시 스키마의 앱 SQL 호환 검증 통과. 임시 스키마/검증 데이터는 트랜잭션 롤백
- 풀링 연결에서는 시작 options의 statement_timeout이 지원되지 않아 연결 후 SET LOCAL로 적용하도록 검사 도구 수정
- 사용자가 GitHub 저장소를 최신본으로 확인한 뒤 main 40bbefa33d0e41b2a3dfd403f26de83c4e64bdad의 DB를 이전했습니다. users 2, book_requests 1, scraps 4, system_config 1행의 모든 값이 원본과 일치합니다.


## B2 실제 연결 완료 (2026-10-23)

사용자 승인 후 hyperx-render 키를 생성했습니다. 접근 범위는 hyperx 버킷의 hyperx/ 경로,
읽기·쓰기이며 전체 버킷 이름 목록 접근은 꺼 두었습니다. 키 값은 Git 제외 .env.cloud에만
저장했습니다. 실제 연결 검사에서 작은 테스트 파일의 업로드와 다운로드 검증을 통과했습니다.
테스트 객체는 삭제하지 않고 보존했습니다. 교재·회원·스크랩의 실제 이전과 검증을 완료했으며, Render 전환은 최종 승인 전입니다.


## 실제 데이터 이전 완료 (2026-10-24)

- 최신 원본: 사용자가 확인한 GitHub main 40bbefa33d0e41b2a3dfd403f26de83c4e64bdad.
- 7권, 이미지·메타데이터 3,873개, 원본 446,744,088바이트. 교재 HTML 7개를 포함해 B2 목록 3,880개.
- 원본 SHA-256 및 B2 서버 Content-MD5/ETag/크기 검증 통과. 원본 파일과 DB를 삭제·덮어쓰지 않았습니다.
- 무료 읽기 요청 상한 때문에 전체 GET 재검증 대신 업로드 Content-MD5와 서버 ETag·크기를 검증했습니다. 실제 단일 PUT 객체의 ETag 일치를 사전 확인했고, 대표 이미지의 다운로드 SHA-256도 확인했습니다.
- B2_UPLOAD_VERIFICATION=etag는 이 방식이며 기본 readback은 다운로드 후 SHA-256 검증을 유지합니다. B2_UPLOAD_WORKERS 기본 2, 범위 1~8. 이전 실행에는 8을 사용했습니다.
- Neon의 원본 4개 테이블 모든 값 일치, 기존 스크랩 4개 모두 이전된 이미지에 연결 가능.
- 원본 DB 백업, 파일별 SHA-256 목록, 검증 요약은 로컬 work/migration-records에 보관. 사용자 데이터와 비밀값은 Git에 올리지 않았습니다.
- 사용자 승인으로 hyperx-admin의 강력한 비밀번호를 로컬에 생성·보관. 운영 DB 계정 활성화는 배포 시 수행합니다. 기본 admin123 로그인은 새 앱 시작 시 차단됩니다.
- B2 계정 화면의 비용 상한: 저장·다운로드 각 $0/일, Class B·C 각 2,500회/일. 변경·상향하지 않았습니다. 한도에 닿으면 요청이 차단될 수 있습니다.
- 기존 Render 서비스는 Python Free입니다. 같은 서비스와 도메인에서 전환하면 기존 Git 원본의 약 447MB 고정 용량은 남습니다. 새 문제·편집본·DB는 외부 저장되므로 새 영구 데이터가 Render 디스크에 누적되지 않습니다. 이미지가 제외된 Docker 배포는 별도 경로이며 현재 서비스에 자동 적용되지 않습니다.
- 배포 예정: codex/b2-persistent-storage 브랜치, pip install -r requirements.txt, gunicorn app:app --workers 1 --threads 4 --timeout 180. Free 요금제·기존 URL 유지, 자동 배포 해제 후 수동 전환.

최종 로컬 테스트: 32 passed in 7.61s. 실제 운영 서비스에서의 로그인·뷰어·스크랩 검증은 Render 전환 후 남아 있습니다.

## 관리자 추가 기능 (2026-10-24)

- 문제 사진 삭제 탭에 교재 전체 삭제 추가. 교재 이름 재입력 후 POST·CSRF·관리자 권한 검사를 통과해야 실행됩니다.
- 문제사진·표지·메타데이터·HTML/JSON 에셋·업로드 PDF를 활성 목록에서 함께 제거합니다. 다른 교재와 공용 뷰어는 유지합니다.
- B2 삭제 기록을 목록에 저장하여 재배포 시 Git 원본이 다시 나타나는 것을 막습니다. 목록 저장 실패 시 원본과 활성 교재를 유지합니다.
- 사용자 추가 요청에 따라 교재 전체 삭제 시 해당 교재의 모든 사용자 스크랩도 함께 삭제합니다. 개별 문제 편집·삭제 시 스크랩을 보존하는 기존 동작은 유지합니다.
- B2 전용 문제사진·표지·에셋은 현재 목록과 과거 목록을 조사해 VersionId를 지정하여 모든 객체 버전과 삭제 표시를 영구 삭제합니다. 다른 교재·과거 교재 목록·다른 교재 스크랩이 공유하는 파일은 유지합니다.
- 삭제 계획을 B2 목록에 먼저 저장합니다. 권한·네트워크·부분 삭제 오류 시 성공으로 표시하지 않으며 재시작 후 같은 교재를 선택해 재시도할 수 있습니다. 대기 중에는 새로운 파일 게시를 차단하여 공유 파일이 손상되지 않도록 합니다.
- 과거 목록은 전역 복구 기록으로 유지되지만 영구 삭제된 교재의 이미지를 복구할 수는 없습니다. 과거에 실패한 업로드로 목록 어디에도 기록되지 않은 미확인 객체는 다른 교재 보호를 위해 일괄 삭제하지 않습니다.
- 독립된 Git 원본·최초 마이그레이션 백업과 서버 작업 파일의 로컬 복구본은 유지합니다. 운영 데이터에 대한 실제 삭제는 실행하지 않았습니다.
- 저장공간 대시보드 추가: PostgreSQL 실제 pg_database_size 또는 SQLite 페이지 크기, 회원·스크랩·요청 수, 활성 교재 수·파일 수·바이트, 서버 파일시스템 여유 공간.
- B2 활성 목록의 합계를 표시하며 과거 객체·버전·접속 검사 파일은 제외합니다. B2 버킷 전체 사용량과 혼동하지 않도록 화면에 표시합니다. 자동 폴링과 객체별 요청은 하지 않습니다.
- DB 무료 용량 기준값 DB_FREE_STORAGE_BYTES 기본 1,000,000,000. Neon 요금제 변경 시 콘솔 기준에 맞춰 수정해야 합니다. 컴퓨트·전송 한도와 별개입니다.
- 추가 변경 파일: services/usage.py, services/book_deletion.py, tests/test_admin_management.py. 인증키 없는 삭제·버전 제거·공유 파일 보호·스크랩 제거·용량 조회·접근 제어·실패 복구 테스트와 브라우저 화면 확인 완료.
- 실제 B2 버전 목록 조회 성공. 실제 영구 삭제는 특정 운영 교재에 실행하지 않았으며 버전이 있는 메모리 S3로 검증했습니다.
- 실제 Neon 용량 조회: 7,995,392바이트. B2 활성 파일 3,880개 합계 447,311,471바이트. 확인 시점의 수치이며 화면 새로고침으로 재측정합니다.


## 업로드 차단 수정 (2026-10-24)

실제 Render 로그에서 두 문제를 확인했습니다. PDF 추출 요청은 filelock의 `inherited across fork` 예외로 시작 전에 실패했고, 이미지 요청에는 B2 다운로드·Class B 상한 초과 AccessDenied가 기록되어 있었습니다. 사용자 PDF 크기 4,818KB는 앱 100MiB 제한보다 작습니다.

- Gunicorn 작업 프로세스마다 파일 잠금과 B2 연결 풀을 새로 생성합니다. 프로세스 전환 회귀 테스트를 추가했습니다.
- 업로드 기본 검증을 Content-MD5/ETag로 변경해 파일별 재다운로드 요청을 제거했습니다. readback 모드는 선택할 수 있습니다.
- 검증된 Git 원본을 재사용하고, 32MiB 한도의 메모리 LRU 캐시와 이미지 조건부 304 응답으로 반복 B2 읽기를 줄입니다. 원본이 수정된 경우 SHA-256이 일치할 때만 재사용합니다.
- PDF 추출 진행을 실시간 표시하고 B2 저장이 완료된 뒤에만 최종 100%를 보냅니다. B2 저장 중에도 진행·대기 메시지를 전송합니다.
- 동일 PDF를 같은 이름으로 다시 올리면 SHA-256을 비교해 기존 업로드를 재사용합니다. 다른 PDF는 기존 파일을 덮어쓰지 않습니다.
- B2에 아직 게시되지 않은 실패한 추출 폴더는 로컬 복구본으로 보존한 뒤 같은 PDF로 재시도합니다. 게시된 교재는 덮어쓰지 않습니다. 새 교재 에셋도 B2 저장 전에 생성합니다.
- 한도·권한 오류를 관리자 화면에 안내하며 오류를 성공으로 표시하지 않습니다. 무료 상한을 올리거나 카드를 등록하지 않았습니다.
- 환경변수: B2_UPLOAD_VERIFICATION=etag (새 기본값), B2_READ_CACHE_BYTES=33554432 (선택).
- 최종 로컬 테스트: 38 passed in 5.83s. 신규 테스트는 업로드 GET 0회, 원본 재사용, 304, 캐시 예산, 동일 PDF 재시도, 한도 오류·복구와 Gunicorn 프로세스 전환을 검증합니다.
