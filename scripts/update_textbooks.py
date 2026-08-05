import os
from book_assets import generate_book_assets

if __name__ == '__main__':
    base_img = 'img'
    if os.path.exists(base_img):
        folders = [f for f in os.listdir(base_img) if os.path.isdir(os.path.join(base_img, f))]
        for folder in folders:
            try:
                generate_book_assets(folder)
                print(f"✅ 에셋 생성 완료: {folder}")
            except Exception as e:
                print(f"⚠️ {folder} 에셋 생성 실패: {e}")
