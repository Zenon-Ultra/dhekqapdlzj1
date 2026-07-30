import os
import json
import traceback
import cv2
import fitz
import numpy as np
from PIL import Image, ImageChops

# 로컬 경로 수입
from book_assets import generate_book_assets

def yield_msg(msg, percent=-1):
    data = {"msg": msg}
    if percent >= 0:
        data["percent"] = percent
    return f"data: {json.dumps(data)}\n\n"

# ==========================================
# 여백 자르기 유틸리티
# ==========================================
def trim_bottom_whitespace(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        fn = lambda x: 255 if x > 230 else x
        img_clean = img.point(fn)
        bg = Image.new("RGB", img_clean.size, (255, 255, 255))
        diff = ImageChops.difference(img_clean, bg)
        bbox = diff.getbbox()
        if bbox:
            bottom_y = min(img.height, bbox[3] + 15) 
            cropped_img = img.crop((0, 0, img.width, bottom_y))
            cropped_img.save(image_path)
    except Exception as e:
        pass

def trim_all_whitespace(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        pixels = img.load()
        width, height = img.size
        whitespace_threshold = 230
        
        def is_white_row(y):
            for x in range(width):
                r, g, b = pixels[x, y]
                if max(r, g, b) < whitespace_threshold:
                    return False
            return True
        
        def is_white_col(x):
            for y in range(height):
                r, g, b = pixels[x, y]
                if max(r, g, b) < whitespace_threshold:
                    return False
            return True
        
        top = 0
        for y in range(height):
            if not is_white_row(y):
                top = max(0, y - 10)
                break
        bottom = height
        for y in range(height - 1, -1, -1):
            if not is_white_row(y):
                bottom = min(height, y + 15)
                break
        left = 0
        for x in range(width):
            if not is_white_col(x):
                left = max(0, x - 10)
                break
        right = width
        for x in range(width - 1, -1, -1):
            if not is_white_col(x):
                right = min(width, x + 15)
                break
                
        if left < right and top < bottom:
            cropped_img = img.crop((left, top, right, bottom))
            cropped_img.save(image_path)
            return True
        return False
    except Exception as e:
        return False

# ==========================================
# 1. 문제 추출 (PDF -> 이미지)
# ==========================================
def extract_pdf_task(file_path, workbook_name, is_two_column):
    yield yield_msg(f"📁 저장 폴더: img/{workbook_name}", 5)
    output_dir = os.path.join("img", workbook_name)
    os.makedirs(output_dir, exist_ok=True)
    yield yield_msg("⚙️ 스캔본 여백 분석 및 정밀 크롭 진행 중...", 10)

    try:
        pdf_doc = fitz.open(file_path)
        total_pages = len(pdf_doc)
        q_num = 1
        
        for page_num in range(total_pages):
            page = pdf_doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            
            if pix.n == 4: img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
            elif pix.n == 1: img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
            
            height, width = thresh.shape
            top_margin = int(height * 0.08)
            bottom_margin = int(height * 0.92)
            
            if is_two_column:
                mid_x = width // 2
                columns = [(0, mid_x), (mid_x, width)]
            else:
                columns = [(0, width)]
                
            for (x0, x1) in columns:
                col_thresh = thresh[:, x0:x1]
                col_img = img[:, x0:x1]
                row_sums = np.sum(col_thresh, axis=1)
                is_blank = row_sums < (255 * 10)
                
                cut_y_points = [top_margin]
                blank_start = None
                
                for y in range(top_margin, bottom_margin):
                    if is_blank[y]:
                        if blank_start is None: blank_start = y
                    else:
                        if blank_start is not None:
                            blank_length = y - blank_start
                            if blank_length > 65:
                                cut_y_points.append(blank_start + (blank_length // 2))
                            blank_start = None
                            
                cut_y_points.append(bottom_margin)
                
                for i in range(len(cut_y_points) - 1):
                    start_y = cut_y_points[i]
                    end_y = cut_y_points[i+1]
                    if end_y - start_y > 100:
                        temp_thresh = col_thresh[start_y:end_y]
                        temp_img = col_img[start_y:end_y]
                        trim_margin_x = int(temp_thresh.shape[1] * 0.05)
                        core_thresh = temp_thresh[:, trim_margin_x:-trim_margin_x]
                        temp_row_sums = np.sum(core_thresh, axis=1)
                        text_rows = np.where(temp_row_sums > 255 * 5)[0]
                        
                        if len(text_rows) > 0:
                            true_start = text_rows[0]
                            true_end = text_rows[-1]
                            padding = 30
                            final_start = max(0, true_start - padding)
                            final_end = min(temp_img.shape[0], true_end + padding)
                            final_img = temp_img[final_start:final_end]
                            
                            if final_img.shape[0] > 100:
                                save_img = cv2.cvtColor(final_img, cv2.COLOR_RGB2BGR)
                                out_path = os.path.join(output_dir, f"{q_num:03d}.png")
                                extension = os.path.splitext(out_path)[1]
                                result, encoded_img = cv2.imencode(extension, save_img)
                                if result:
                                    with open(out_path, mode='w+b') as f:
                                        encoded_img.tofile(f)
                                yield yield_msg(f"✅ [페이지 {page_num+1}/{total_pages}] {q_num:03d}번 문항 저장 완료")
                                q_num += 1

            # Update progress per page
            pct = 10 + int(80 * (page_num + 1) / total_pages)
            yield yield_msg(f"⏳ 페이지 {page_num+1}/{total_pages} 분석 완료...", pct)
            
        pdf_doc.close()
        yield yield_msg("🎉 모든 문항 추출 완료!", 100)
    except Exception as e:
        yield yield_msg(f"🚨 오류 발생: {e}", 100)
        traceback.print_exc()

# ==========================================
# 2. 여백 정리
# ==========================================
def cleanup_images_task(selected_folders):
    base_dir = "img"
    total_count = 0
    folder_count = len(selected_folders)

    for i, folder in enumerate(selected_folders):
        folder_path = os.path.join(base_dir, folder)
        img_files = [f for f in os.listdir(folder_path) if f.endswith('.png')]
        yield yield_msg(f"📁 {folder} 폴더 처리 중... (총 {len(img_files)}개 이미지)", int(100 * i / folder_count))
        
        for j, img_file in enumerate(img_files):
            img_path = os.path.join(folder_path, img_file)
            if trim_all_whitespace(img_path):
                total_count += 1
            if j % 5 == 0:
                pct = int(100 * (i + (j / len(img_files))) / folder_count)
                yield yield_msg(f"⏳ {img_file} 여백 제거 중...", pct)
        
        yield yield_msg(f"✨ {folder} 완료!")

    yield yield_msg(f"🎉 모든 이미지 여백 정리 완료! (총 {total_count}개 변경)", 100)

# ==========================================
# 3. 교재 에셋 자동 생성
# ==========================================
def generate_assets_task(selected_folders, cover_url=None):
    base_dir = "img"
    total = len(selected_folders)
    yield yield_msg("⚙️ 교재 에셋 자동 생성을 시작합니다...", 5)
    
    for i, folder in enumerate(selected_folders):
        image_dir = os.path.join(base_dir, folder)
        yield yield_msg(f"⏳ {folder} 생성 중...", int(100 * i / total))
        try:
            html_path, json_path = generate_book_assets(
                folder_name=folder,
                image_dir=image_dir,
                output_dir=os.path.join("textbooks"),
                title=folder,
                subtitle="자동 생성",
                index_path=os.path.join("templates", "main.html"),
                custom_cover_url=cover_url
            )
            json_str = f"{os.path.basename(json_path)} / " if json_path else ""
            yield yield_msg(f"✅ {folder}: {json_str}{os.path.basename(html_path)}")
        except Exception as e:
            yield yield_msg(f"⚠️ {folder} 생성 실패: {e}")
            
    yield yield_msg("🎉 교재 생성 작업이 모두 완료되었습니다!", 100)

# ==========================================
# 4. 이미지 분할 및 번호 밀기
# ==========================================
def split_image_task(selected_folder, target_num_or_file):
    yield yield_msg("⚙️ 이미지 분할 시작...", 5)
    base_dir = "img"
    img_dir = os.path.join(base_dir, selected_folder)
    
    import re
    if isinstance(target_num_or_file, str) and '.' in target_num_or_file:
        # 파일명 모드
        filename = target_num_or_file
        match = re.search(r'(\d+)', filename)
        if not match:
            yield yield_msg(f"🚨 파일명에서 번호를 찾을 수 없습니다: {filename}", 100)
            return
        target_num = int(match.group(1))
        img_path = os.path.join(img_dir, filename)
        ext = os.path.splitext(filename)[1]
    else:
        # 숫자 모드 (admin 탭 호환)
        target_num = int(target_num_or_file)
        existing_files = [f for f in os.listdir(img_dir) if f.startswith(f"{target_num:03d}.")]
        if not existing_files:
            yield yield_msg(f"🚨 {target_num:03d} 번호로 시작하는 파일을 찾을 수 없습니다.", 100)
            return
        img_path = os.path.join(img_dir, existing_files[0])
        ext = os.path.splitext(existing_files[0])[1]
    
    yield yield_msg(f"🔍 선택된 파일: {img_path}", 15)
    
    try:
        img_array = np.fromfile(img_path, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if img is None:
            yield yield_msg("🚨 이미지를 읽을 수 없습니다.", 100)
            return
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
        row_sums = np.sum(thresh, axis=1)
        is_blank = row_sums < (255 * 10)
        
        height = img.shape[0]
        start_y = int(height * 0.2)
        end_y = int(height * 0.8)
        
        max_blank_length = 0
        best_cut_y = height // 2
        blank_start = None
        
        for y in range(start_y, end_y):
            if is_blank[y]:
                if blank_start is None: blank_start = y
            else:
                if blank_start is not None:
                    blank_length = y - blank_start
                    if blank_length > max_blank_length:
                        max_blank_length = blank_length
                        best_cut_y = blank_start + (blank_length // 2)
                    blank_start = None
                    
        if blank_start is not None:
            blank_length = end_y - blank_start
            if blank_length > max_blank_length:
                best_cut_y = blank_start + (blank_length // 2)
                
        yield yield_msg("⏳ 분할 위치 계산 완료, 파일명 밀기 진행...", 40)
        top_img = img[:best_cut_y, :]
        bottom_img = img[best_cut_y:, :]
        
        # 폴더 내 모든 이미지 파일 대상 (+1 밀기)
        valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        all_files_info = []
        for f in os.listdir(img_dir):
            name_part, file_ext = os.path.splitext(f)
            if file_ext.lower() in valid_exts and name_part.isdigit():
                all_files_info.append((int(name_part), file_ext, f))
                
        # 큰 번호부터 뒤로 밀기
        all_files_info.sort(key=lambda x: x[0], reverse=True)
        
        for n, file_ext, f in all_files_info:
            if n > target_num:
                old_path = os.path.join(img_dir, f)
                new_path = os.path.join(img_dir, f"{n+1:03d}{file_ext}")
                os.rename(old_path, new_path)
                
        top_path = os.path.join(img_dir, f"{target_num:03d}{ext}")
        bottom_path = os.path.join(img_dir, f"{target_num+1:03d}{ext}")
        
        result_top, encoded_top = cv2.imencode(ext, top_img)
        if result_top:
            with open(top_path, "wb") as f: f.write(encoded_top.tobytes())
                
        result_bot, encoded_bot = cv2.imencode(ext, bottom_img)
        if result_bot:
            with open(bottom_path, "wb") as f: f.write(encoded_bot.tobytes())
                
        yield yield_msg("⏳ 여백 절삭 중...", 80)
        trim_all_whitespace(top_path)
        trim_all_whitespace(bottom_path)
        
        yield yield_msg(f"🎉 성공적으로 분할되었습니다! (이후 문제 번호 +1 밀림)", 100)
    except Exception as e:
        yield yield_msg(f"🚨 오류 발생: {e}", 100)

# ==========================================
# 5. 이미지 합치기 (Merge) 및 번호 당기기
# ==========================================
def merge_images_task(selected_folder, start_num_or_files, end_num=None):
    """start_num ~ end_num 번 이미지 또는 지정된 파일 리스트를 세로로 합쳐서 저장하고,
    이후 번호들을 당깁니다."""
    yield yield_msg("⚙️ 이미지 합치기 시작...", 5)
    base_dir = "img"
    img_dir = os.path.join(base_dir, selected_folder)

    import re
    # 콤마로 구분된 파일 리스트가 전달된 경우
    if isinstance(start_num_or_files, str) and (',' in start_num_or_files or start_num_or_files.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'))):
        filenames = [f.strip() for f in start_num_or_files.split(',') if f.strip()]
        nums = []
        for f in filenames:
            m = re.search(r'(\d+)', f)
            if not m:
                yield yield_msg(f"🚨 파일명에서 번호를 찾을 수 없습니다: {f}", 100)
                return
            nums.append(int(m.group(1)))

        # 번호와 파일명을 동시에 정렬
        sorted_pairs = sorted(zip(nums, filenames))
        nums = [p[0] for p in sorted_pairs]
        filenames = [p[1] for p in sorted_pairs]

        start_num = nums[0]
        end_num = nums[-1]

        target_paths = []
        for f in filenames:
            p = os.path.join(img_dir, f)
            if not os.path.exists(p):
                yield yield_msg(f"🚨 파일을 찾을 수 없습니다: {f}", 100)
                return
            target_paths.append(p)
        ext = os.path.splitext(filenames[0])[1]
    else:
        # 숫자 모드 (admin 탭 호환)
        start_num = int(start_num_or_files)
        end_num = int(end_num)
        if start_num >= end_num:
            yield yield_msg("🚨 시작 번호는 끝 번호보다 작아야 합니다.", 100)
            return

        target_paths = []
        ext = ".png"
        for n in range(start_num, end_num + 1):
            matches = [f for f in os.listdir(img_dir) if f.startswith(f"{n:03d}.")]
            if not matches:
                yield yield_msg(f"🚨 {n:03d} 번호 파일을 찾을 수 없습니다.", 100)
                return
            target_paths.append(os.path.join(img_dir, matches[0]))
            ext = os.path.splitext(matches[0])[1]

    yield yield_msg(f"🔍 합칠 이미지: {start_num:03d} ~ {end_num:03d} ({len(target_paths)}장)", 15)

    try:
        imgs = []
        max_w = 0
        for p in target_paths:
            arr = np.fromfile(p, np.uint8)
            im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if im is None:
                yield yield_msg(f"🚨 이미지를 읽을 수 없습니다: {p}", 100)
                return
            imgs.append(im)
            max_w = max(max_w, im.shape[1])

        # 너비를 최대값으로 맞춘 뒤 세로로 이어 붙이기
        padded = []
        for im in imgs:
            h, w = im.shape[:2]
            if w < max_w:
                pad = np.full((h, max_w - w, 3), 255, dtype=np.uint8)
                im = np.hstack([im, pad])
            padded.append(im)

        merged = np.vstack(padded)

        # 합쳐진 이미지를 첫 파일 확장자 형태로 임시 저장
        merged_path = os.path.join(img_dir, f"__merge_tmp{ext}")
        result, encoded = cv2.imencode(ext, merged)
        if not result:
            yield yield_msg("🚨 이미지 인코딩에 실패했습니다.", 100)
            return
        with open(merged_path, "wb") as f:
            f.write(encoded.tobytes())

        yield yield_msg("⏳ 번호 당기기 진행 중...", 50)

        # 첫 번째 파일을 제외한 나머지 대상 파일 삭제
        for p in target_paths[1:]:
            if os.path.exists(p):
                os.remove(p)

        # end_num 이후 파일들을 (end_num - start_num)만큼 앞으로 당기기
        shift = end_num - start_num
        
        valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        all_files_info = []
        for f in os.listdir(img_dir):
            if f.startswith("__"):
                continue
            name_part, file_ext = os.path.splitext(f)
            if file_ext.lower() in valid_exts and name_part.isdigit():
                all_files_info.append((int(name_part), file_ext, f))
                
        # 작은 번호 순으로 정렬
        all_files_info.sort(key=lambda x: x[0])

        for n, file_ext, f in all_files_info:
            if n > end_num:
                old_path = os.path.join(img_dir, f)
                new_path = os.path.join(img_dir, f"{n - shift:03d}{file_ext}")
                os.rename(old_path, new_path)

        # 임시 파일을 첫 이미지 경로에 최종 저장
        final_path = target_paths[0]
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(merged_path, final_path)

        yield yield_msg("⏳ 여백 절삭 중...", 85)
        trim_all_whitespace(final_path)

        yield yield_msg(
            f"🎉 성공! {start_num:03d}번 위치에 합쳐서 저장되었습니다. "
            f"이후 번호 -{shift} 당겨짐.",
            100
        )
    except Exception as e:
        tmp = os.path.join(img_dir, f"__merge_tmp{ext}")
        if os.path.exists(tmp):
            os.remove(tmp)
        yield yield_msg(f"🚨 오류 발생: {e}", 100)

