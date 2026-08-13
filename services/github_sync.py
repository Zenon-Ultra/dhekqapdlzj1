import os
import subprocess
import threading
import time
from dotenv import load_dotenv

load_dotenv()

# 자동 동기화 활성화 여부 (기본값: False)
AUTO_SYNC_ENABLED = os.environ.get("AUTO_SYNC_ENABLED", "0").lower() in ["1", "true", "yes"]

def is_auto_sync_enabled():
    global AUTO_SYNC_ENABLED
    return AUTO_SYNC_ENABLED

def set_auto_sync_enabled(enabled: bool):
    global AUTO_SYNC_ENABLED
    AUTO_SYNC_ENABLED = enabled
    print(f"[GitHub Sync] Auto sync set to: {AUTO_SYNC_ENABLED}")

def auto_sync_loop():
    time.sleep(10) # 앱 시작 후 10초 대기
    while True:
        try:
            if AUTO_SYNC_ENABLED:
                token = os.environ.get("GITHUB_TOKEN")
                if token:
                    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    repo_url = f"https://oauth2:{token}@github.com/Zenon-Ultra/dhekqapdlzj1.git"
                    
                    # 멀티 워커 환경에서 동시 git 실행 방지 (간단한 파일 락)
                    lock_file = os.path.join(cwd, ".git_sync.lock")
                    if os.path.exists(lock_file):
                        # 락이 너무 오래된 경우(30초 이상) 해제
                        if time.time() - os.path.getmtime(lock_file) > 30:
                            try:
                                os.remove(lock_file)
                            except Exception:
                                pass
                        else:
                            time.sleep(60)
                            continue
                            
                    with open(lock_file, 'w') as f:
                        f.write(str(time.time()))
                        
                    try:
                        # git 저장소 초기화 및 origin 설정 (Render 환경 대비)
                        if not os.path.exists(os.path.join(cwd, ".git")):
                            print("[GitHub Sync] Git repository not found. Initializing...")
                            subprocess.run(["git", "init"], cwd=cwd, check=True)
                            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=cwd, check=False)
                            subprocess.run(["git", "fetch", "origin"], cwd=cwd, check=True)
                            subprocess.run(["git", "reset", "--mixed", "origin/main"], cwd=cwd, check=True)
                        else:
                            # 토큰이 포함된 URL로 origin 업데이트
                            subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=cwd, check=False)
        
                        # 변경사항 확인
                        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=cwd)
                        if status.stdout.strip():
                            print("[GitHub Sync] Changes detected, syncing to GitHub...")
                            
                            subprocess.run(["git", "config", "user.email", "bot@render.com"], cwd=cwd, check=False)
                            subprocess.run(["git", "config", "user.name", "Render Auto Sync"], cwd=cwd, check=False)
                            subprocess.run(["git", "add", "."], cwd=cwd, check=True)
                            subprocess.run(["git", "commit", "-m", "Auto-sync data from Render"], cwd=cwd, check=True)
                            
                            subprocess.run(["git", "fetch", "origin"], cwd=cwd, check=False)
                            subprocess.run(["git", "push", "--force-with-lease", "origin", "main"], cwd=cwd, check=True)
                            print("[GitHub Sync] Successfully synced to GitHub.")
                    finally:
                        if os.path.exists(lock_file):
                            try:
                                os.remove(lock_file)
                            except Exception:
                                pass
        except Exception as e:
            print(f"[GitHub Sync] Error: {e}")
            
        time.sleep(60)  # 60초마다 반복

def start_auto_sync():
    thread = threading.Thread(target=auto_sync_loop, daemon=True)
    thread.start()

