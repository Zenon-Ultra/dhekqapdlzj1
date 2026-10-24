"""Two explicit PDF renderers; opaque RGB output and optional annotations."""
from contextlib import contextmanager
from threading import RLock
import numpy as np

_pdfium_lock = RLock()  # PDFium must not be called concurrently from request threads.


@contextmanager
def open_document(path, engine='pdfium'):
    if engine == 'pdfium':
        import pypdfium2
        with _pdfium_lock:
            document = pypdfium2.PdfDocument(str(path))
            try: yield document
            finally: document.close()
    elif engine == 'mupdf':
        import fitz
        with fitz.open(str(path)) as document: yield document
    else:
        raise ValueError('지원하지 않는 PDF 렌더링 방식입니다.')


def render_page(document, number, engine='pdfium', annotations=True, scale=2.5):
    if number < 0 or number >= len(document): raise ValueError('PDF 페이지 번호가 잘못되었습니다.')
    if engine == 'pdfium':
        with _pdfium_lock:
            page = document[number]
            try:
                bitmap = page.render(scale=scale, draw_annots=annotations,
                    fill_color=(255,255,255,255), rev_byteorder=True)
                try: return np.array(bitmap.to_pil().convert('RGB'), copy=True)
                finally: bitmap.close()
            finally: page.close()
    import fitz
    pixmap = document[number].get_pixmap(matrix=fitz.Matrix(scale,scale),
        colorspace=fitz.csRGB, alpha=False, annots=annotations)
    return np.frombuffer(pixmap.samples,np.uint8).reshape(pixmap.h,pixmap.w,3).copy()
