import html
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote


def slugify(name: str) -> str:
    text = re.sub(r"\s+", "_", name.strip())
    text = re.sub(r"[^0-9A-Za-z가-힣._-]", "", text)
    return text or "book"


def _write_shared_viewer(output_dir: Path, book_name: str, title: str, subtitle: str) -> Path:
    viewer_path = output_dir / "viewer.html"
    if viewer_path.exists():
        return viewer_path

    viewer_html = f"""<!DOCTYPE html>
<html lang=\"ko\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #222; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin-bottom: 8px; }}
    p {{ color: #666; }}
    .grid {{ display: grid; gap: 24px; }}
    .card {{ background: white; border-radius: 12px; padding: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
    img {{ width: 100%; height: auto; display: block; border-radius: 8px; }}
    figcaption {{ text-align: center; color: #666; margin-top: 8px; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1 id=\"bookTitle\">{html.escape(title)}</h1>
    <p id=\"bookSubtitle\">{html.escape(subtitle)}</p>
    <div class=\"grid\" id=\"imageList\"></div>
  </div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const bookName = params.get('book') || '{book_name}';
    const jsonPath = './' + bookName + '.json';

    async function loadBook() {{
      try {{
        const response = await fetch(jsonPath);
        const data = await response.json();
        document.getElementById('bookTitle').textContent = data.title || '{html.escape(title)}';
        document.getElementById('bookSubtitle').textContent = data.subtitle || '{html.escape(subtitle)}';
        const list = document.getElementById('imageList');
        list.innerHTML = '';
        (data.images || []).forEach((image, index) => {{
          const card = document.createElement('div');
          card.className = 'card';
          const img = document.createElement('img');
          img.src = new URL(image.file, window.location.href).href;
          img.alt = `${{index + 1}}번 문제`;
          img.loading = 'lazy';
          const caption = document.createElement('figcaption');
          caption.textContent = `${{index + 1}}번 문제`;
          card.appendChild(img);
          card.appendChild(caption);
          list.appendChild(card);
        }});
      }} catch (error) {{
        document.getElementById('imageList').innerHTML = '<p>이미지를 불러오지 못했습니다.</p>';
      }}
    }}

    loadBook();
  </script>
</body>
</html>
"""
    viewer_path.write_text(viewer_html, encoding="utf-8")
    return viewer_path


def _append_index_card(index_path: Path, book_name: str, title: str, subtitle: str, html_name: str, preview_image: Optional[str] = None) -> None:
    if not index_path.exists():
        index_path.write_text(
            "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"UTF-8\" /><title>교재 목록</title></head><body><div class=\"card-grid\" id=\"cardGrid\"></div></body></html>",
            encoding="utf-8",
        )

    html_text = index_path.read_text(encoding="utf-8")

    preview_src = preview_image or ""
    if preview_src:
        if not preview_src.startswith(("http://", "https://", "//")):
            preview_src = quote(preview_src, safe="/")

    # 이미 카드가 존재하면 → card-thumb src만 교체하고 반환
    if f'href="textbooks/{html_name}"' in html_text:
        if preview_src:
            # 해당 카드 안의 card-thumb img src를 정규식으로 교체
            html_text = re.sub(
                r'(<a[^>]+href="textbooks/' + re.escape(html_name) + r'"[^>]*>.*?<img\s+class="card-thumb"\s+src=")[^"]*(")',
                r'\g<1>' + preview_src.replace('\\', '\\\\') + r'\g<2>',
                html_text,
                count=1,
                flags=re.DOTALL,
            )
            index_path.write_text(html_text, encoding="utf-8")
        return

    marker = '<div class="card-grid" id="cardGrid">'
    if marker not in html_text:
        html_text = html_text.replace("</body>", f"<div class=\"card-grid\" id=\"cardGrid\"></div></body>", 1)
        html_text = html_text.replace("<div class=\"card-grid\" id=\"cardGrid\"></div>", marker + "\n", 1)

    card_html = f"""
    <a class="card" href="textbooks/{html_name}" data-title="{html.escape(title)}" data-id="{html.escape(book_name)}">
      <button class="pin-btn" onclick="event.preventDefault(); togglePin(this)" title="고정">📌</button>
      <img class="card-thumb" src="{preview_src}" alt="표지" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
      <div class="card-thumb-placeholder" style="display:none;">📖</div>
      <div class="card-body">
        <div class="card-title">{html.escape(title)}</div>
        <div class="card-sub">{html.escape(subtitle)}</div>
        <div class="card-badge">빠른정답</div>
        <div class="card-id">ID {html.escape(book_name)}</div>
      </div>
    </a>
    """
    html_text = html_text.replace(marker, marker + card_html, 1)
    index_path.write_text(html_text, encoding="utf-8")


def generate_book_assets(
    folder_name: str,
    image_dir: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    template_path: Optional[Path | str] = None,
    index_path: Optional[Path | str] = None,
    custom_cover_url: Optional[str] = None,
):
    root = Path(__file__).resolve().parent

    if image_dir is None:
        image_dir = root / "img" / folder_name
    else:
        image_dir = Path(image_dir)
        if not image_dir.is_absolute():
            image_dir = root / image_dir

    if output_dir is None:
        output_dir = root / "textbooks"
    else:
        output_dir = Path(output_dir)
        if not output_dir.is_absolute():
            output_dir = root / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    if not image_dir.exists():
        raise FileNotFoundError(f"이미지 폴더가 없습니다: {image_dir}")

    image_files = sorted(
        [p.name for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}]
    )

    if not image_files:
        raise FileNotFoundError(f"이미지 폴더에 이미지가 없습니다: {image_dir}")

    book_name = slugify(folder_name)
    title = title or folder_name
    subtitle = subtitle or ""

    images = []
    for img_file in image_files:
        rel_image_path = os.path.relpath(image_dir / img_file, output_dir).replace(os.sep, "/")
        images.append({"file": rel_image_path, "page": 0})

    data = {"title": title, "subtitle": subtitle, "images": images}

    html_path = output_dir / f"{book_name}.html"
    ebsi_path = root / "templates" / "ebsi_sc.html"

    if index_path is None:
        index_path = root / "templates" / "main.html"
    else:
        index_path = Path(index_path)
        if not index_path.is_absolute():
            index_path = root / index_path

    preview_image = custom_cover_url

    # meta.json 저장 / 읽기 (표지 URL 지속성)
    meta_path = image_dir / "meta.json"
    if custom_cover_url:
        # 새 URL이 전달되었으면 저장
        meta_data = {}
        if meta_path.exists():
            try:
                meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        meta_data["custom_cover_url"] = custom_cover_url
        meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
    elif meta_path.exists():
        # URL이 없는 경우 meta.json에서 불러오기
        try:
            meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_data.get("custom_cover_url"):
                preview_image = meta_data["custom_cover_url"]
        except Exception:
            pass

    if not preview_image and images:
        from urllib.parse import quote
        preview_image = f"/img/{quote(folder_name)}/{quote(image_files[0])}"

    if ebsi_path.exists():
        viewer_html = ebsi_path.read_text(encoding="utf-8")
        
        viewer_html = re.sub(r"const BOOK_TITLE = '.*?';", f"const BOOK_TITLE = '{title}';", viewer_html)
        viewer_html = re.sub(r"const BOOK_SUB\s*= '.*?';", f"const BOOK_SUB   = '{subtitle}';", viewer_html)
        if "const BOOK_FOLDER" in viewer_html:
            viewer_html = re.sub(r"const BOOK_FOLDER\s*=\s*'.*?';", f"const BOOK_FOLDER = '{folder_name}';", viewer_html)
        else:
            viewer_html = viewer_html.replace("const BOOK_TITLE =", f"const BOOK_FOLDER = '{folder_name}';\n    const BOOK_TITLE =", 1)
        
        images_js = ",\n".join([f"{{ file: '{img['file']}', page: 0 }}" for img in images])
        viewer_html = re.sub(r"const IMAGES = \[.*?\];", f"const IMAGES = [\n{images_js}\n];", viewer_html, flags=re.DOTALL)
    else:
        book_json = json.dumps(data, ensure_ascii=False)
        viewer_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #222; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin-bottom: 8px; }}
    p {{ color: #666; }}
    .grid {{ display: grid; gap: 24px; }}
    .card {{ background: white; border-radius: 12px; padding: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
    img {{ width: 100%; height: auto; display: block; border-radius: 8px; }}
    figcaption {{ text-align: center; color: #666; margin-top: 8px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1 id="bookTitle">{html.escape(title)}</h1>
    <p id="bookSubtitle">{html.escape(subtitle)}</p>
    <div class="grid" id="imageList"></div>
  </div>
  <script>
    const bookData = {book_json};
    const list = document.getElementById('imageList');
    document.getElementById('bookTitle').textContent = bookData.title || '{html.escape(title)}';
    document.getElementById('bookSubtitle').textContent = bookData.subtitle || '{html.escape(subtitle)}';
    list.innerHTML = '';
    (bookData.images || []).forEach((image, index) => {{
      const card = document.createElement('div');
      card.className = 'card';
      const img = document.createElement('img');
      img.src = new URL(image.file, window.location.href).href;
      img.alt = `${{index + 1}}번 문제`;
      img.loading = 'lazy';
      const caption = document.createElement('figcaption');
      caption.textContent = `${{index + 1}}번 문제`;
      card.appendChild(img);
      card.appendChild(caption);
      list.appendChild(card);
    }});
  </script>
</body>
</html>
"""
    html_path.write_text(viewer_html, encoding="utf-8")


    if index_path.exists() or index_path.parent.exists():
        _append_index_card(index_path, book_name, title, subtitle, html_path.name, preview_image)

    return html_path, None
