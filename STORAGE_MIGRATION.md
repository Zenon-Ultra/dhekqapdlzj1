# HYPERX storage review and migration (2026-10-23)

This branch preserves the existing admin templates and editing algorithms. Images were
local files, generated viewers were mutable HTML, SQLite held users/scraps/requests,
and runtime Git code staged all data and force-pushed main. Runtime Git writes are now
disabled, including the old batch helper. No tracked image/database has been removed.

## Configuration

Local: install requirements.txt and pytest in a venv; run `python app.py`.
No cloud credentials needed. SQLite and local images are the default.
Set a persistent SECRET_KEY locally if sessions must survive restarts.

Production variables:

- SECRET_KEY: at least 32 random bytes; required on Render.
- ADMIN_USERNAME / ADMIN_PASSWORD: optional bootstrap for a NEW account only;
  password minimum 12 characters. Does not reset existing custom accounts.
  The known admin123/admin123 password is disabled while retaining the row.
- DATABASE_URL: Neon PostgreSQL URL with sslmode=require, required on Render.
- STORAGE_BACKEND=b2
- B2_ENDPOINT_URL=https://s3.REGION.backblazeb2.com
- B2_REGION, B2_BUCKET, B2_KEY_ID, B2_APPLICATION_KEY
- B2_PREFIX=hyperx (dedicated prefix)
- B2_MAX_BATCH_BYTES=500000000 (per upload batch guard, NOT a billing cap)
- DB_PATH: optional local SQLite location for development/tests.

Use a private B2 bucket, a bucket-scoped read/write key, and CORS allowing GET/HEAD
from the application origin. Viewer canvas/export needs CORS on the redirected image
response. Never put keys in HTML or commit .env. One worker AND one instance only;
do not run overlapping deployments or independent writers against the same catalog.

## Safe migration sequence

1. Enable maintenance; export and keep the complete original deployment and a consistent
   SQLite backup (SQLite backup API or stopped writes). Keep all original Git history.
2. Use a separate full checkout with all img files, not the sparse development checkout.
   `python scripts/migrate_storage.py` writes a local inventory and prints counts/bytes.
3. Set B2 variables, then `python scripts/migrate_storage.py --apply`.
   Uploads are content-addressed and read back with SHA-256 verification; live catalog
   switches only after all uploads succeed. Existing remote catalogs are refused.
   Local originals and remote old objects are retained. `--verify` reads all remote objects.
4. Create an EMPTY Neon Free database yourself. With DATABASE_URL set, run
   `python scripts/migrate_database.py original-admin.db` (inventory), then add `--apply`.
   Tables, row values and IDs are copied in one transaction; nonempty destinations abort.
   No source rows are modified. Take a separate backup before and after deployment.
5. Deploy the branch with the variables above. Recheck login, every book count,
   image rendering, scraps, split/merge/delete/trim, cover upload, PDF extraction and
   browser canvas export before ending maintenance. Compare inventory and counts.
6. Rollback: redeploy prior code with the untouched original files/database. For B2
   rollback, copy an explicitly selected snapshots/<hash>.json back to catalog.json
   while all writers are stopped. No automatic remote garbage collection is performed.

Images keep /img/book/file URLs. On edits only that book is hydrated, then uploaded
and verified; edited local image bytes are evicted after success. JSON metadata stays
local. Remote old objects/snapshot catalogs stay available for recovery. Existing
scraps are frozen to immutable object keys before bulk edits, retaining their original
filename for viewer selection; the dashboard gets a temporary download URL.

## Costs and operational limits

Official pages checked 2026-10-23:
https://www.backblaze.com/cloud-storage/pricing
https://www.backblaze.com/cloud-storage/transaction-pricing
https://neon.com/pricing
https://render.com/docs/free

B2: first 10 GB storage free; free egress up to 3x average monthly stored bytes;
extra egress $0.01/GB. Current standard storage starts at $6.95/TB/month; official
page advertises free transactions. Old immutable versions consume storage too.
Configure B2 account caps/alerts yourself and avoid adding payment details if strict
zero spending is required. The batch guard cannot enforce account-wide storage or
traffic budgets. Verification/hydration also download data and consume bandwidth.
Neon Free: 1 GB/project, 100 CU-hours/month/project, no credit card required.
Remain on Free; do not enable a paid plan. Check transfer and compute limits in console.
Render Free sleeps after 15 minutes and loses local changes on sleep/redeploy;
its free PostgreSQL is unsuitable as an indefinite persistent database.

## Remaining deployment validation / limitations

This is a draft for integration review until tested against real B2 and PostgreSQL.
No production credentials, purchases, migration or deployment were performed.
A full image checkout still contains the legacy tracked images on startup: the branch
intentionally does not remove them. A code-only build checkout after verified migration
is required to eliminate that historical disk use. The sparse local checkout demonstrates
that layout; keep original images separately. PDF uploads are temporary local files;
keep original PDFs separately. A very large single book still needs temporary disk space.
The existing ZIP exporter uses local files and is not a complete cloud backup after
eviction: use B2 snapshots plus a PostgreSQL export instead. B2 cloud backup UI/export
integration and browser-level canvas/CORS acceptance still need verification.
The existing state-changing GET endpoints remain for admin compatibility; full CSRF
conversion is outside this patch. Short-lived signed links in an open scrap dashboard
need refreshing after one hour. No multi-instance conflict resolution is implemented.

## Local validation

`python -m pytest -q`: 14 passed (4.27 seconds). `compileall` and `git diff --check` passed.
Tests use an isolated SQLite database, memory-backed S3, and synthetic PDF/images.
Real B2 API, PostgreSQL migration and browser acceptance were not run.
Changed source: app.py, book_assets.py, services/{storage,database,tasks,github_sync}.py,
templates/main.html, migration scripts, tests, requirements, git ignore/helper, env example.
