# 작업 목록 (Task List)

- `[x]` 1. 데이터베이스 및 앱 설정 (app.py)
  - `[x]` sqlite3 및 werkzeug.security 임포트
  - `[x]` app.secret_key 설정
  - `[x]` DB 초기화 및 기본 admin 계정 생성 로직 작성
  - `[x]` `@login_required` 데코레이터 구현
- `[x]` 2. 인증 엔드포인트 구현 (app.py)
  - `[x]` `/login` (GET/POST) 라우트 추가
  - `[x]` `/logout` 라우트 추가
- `[x]` 3. 라우트 보호 적용 (app.py)
  - `[x]` `/admin` 경로에 로그인 요구
  - `[x]` `/api/upload_pdf` 경로에 로그인 요구
  - `[x]` 모든 `/api/run/*` 경로에 로그인 요구
- `[x]` 4. 프론트엔드 UI 업데이트
  - `[x]` `templates/login.html` 파일 생성 및 디자인 적용
  - `[x]` `templates/admin.html`에 로그아웃 버튼 추가
- `[x]` 5. 전체 기능 테스트 및 검증
