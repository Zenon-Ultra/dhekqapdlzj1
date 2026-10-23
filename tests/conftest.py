import os
import tempfile
import atexit
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
atexit.register(_tmp.cleanup)
os.environ['DB_PATH'] = str(Path(_tmp.name)/'test.db')
os.environ['ADMIN_USERNAME'] = 'test-admin'
os.environ['ADMIN_PASSWORD'] = 'test-password-1234'
os.environ['STORAGE_BACKEND'] = 'local'
os.environ.pop('DATABASE_URL', None)
os.environ.pop('RENDER', None)
