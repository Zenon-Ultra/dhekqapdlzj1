@echo off
cd /d C:\dhekqapdlzj

echo ========================================
echo       GitHub 업데이트 시작
echo ========================================

git add -A

git commit -m "Auto update"

git push origin main

echo.
echo ========================================
echo       GitHub 업데이트 완료
echo ========================================
pause