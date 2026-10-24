"""Disposable local UI smoke server with memory-backed B2 (no credentials needed)."""
import os
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNTIME=ROOT/'.browser-smoke'
RUNTIME.mkdir(exist_ok=True)
os.environ['HYPERX_IGNORE_ENV_FILES']='1'
os.environ.update(DB_PATH=str(RUNTIME/'admin.db'),SECRET_KEY='local-smoke-only-secret-key-0123456789',ADMIN_USERNAME='smoke-admin',ADMIN_PASSWORD='local-smoke-password',STORAGE_BACKEND='local')
os.environ.pop('DATABASE_URL',None);os.environ.pop('RENDER',None)
import app as web
from services.storage import store
from tests.test_storage import MemoryS3
from PIL import Image,ImageDraw
from book_assets import generate_book_assets
from jinja2 import FileSystemLoader
shutil.copytree(ROOT/'templates',RUNTIME/'templates',dirs_exist_ok=True)
(RUNTIME/'textbooks').mkdir(exist_ok=True);(RUNTIME/'uploads').mkdir(exist_ok=True)
folder=RUNTIME/'img'/'smoke';folder.mkdir(parents=True,exist_ok=True)
for n in (1,2):
    im=Image.new('RGB',(600,420),'white');draw=ImageDraw.Draw(im)
    draw.text((40,50),f'HYPERX TEST QUESTION {n}',fill='black');draw.rectangle((40,100,520,280),outline='black',width=4)
    im.save(folder/f'{n:03d}.webp')
generate_book_assets('smoke',image_dir=folder,output_dir=RUNTIME/'textbooks',index_path=RUNTIME/'templates'/'main.html')
store.root=RUNTIME;store.enabled=True;store.client=MemoryS3();store.publish(['smoke']);store.evict(['smoke'])
web.BASE_DIR=str(RUNTIME);web.UPLOAD_FOLDER=str(RUNTIME/'uploads')
web.app.jinja_loader=FileSystemLoader(str(RUNTIME/'templates'))
os.chdir(RUNTIME)
if __name__=='__main__': web.app.run(host='127.0.0.1',port=5077,debug=False)
