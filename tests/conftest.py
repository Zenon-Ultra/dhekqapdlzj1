import os
import tempfile
import atexit
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
atexit.register(_tmp.cleanup)
os.environ['HYPERX_IGNORE_ENV_FILES'] = '1'
os.environ['DB_PATH'] = str(Path(_tmp.name)/'test.db')
os.environ['ADMIN_USERNAME'] = 'test-admin'
os.environ['ADMIN_PASSWORD'] = 'test-password-1234'
os.environ['STORAGE_BACKEND'] = 'local'
os.environ.pop('DATABASE_URL', None)
os.environ.pop('RENDER', None)
import secrets
import pytest
from flask.testing import FlaskClient

class BrowserClient(FlaskClient):
    """Simulate the token automatically attached by the actual browser bootstrap."""
    def open(self, *args, **kwargs):
        with self.session_transaction() as session:
            token=session.setdefault('_csrf',secrets.token_hex(32))
        headers=dict(kwargs.pop('headers',{}) or {})
        headers.setdefault('X-CSRF-Token',token)
        kwargs['headers']=headers
        return super().open(*args,**kwargs)

@pytest.fixture(autouse=True)
def browser_client_tokens(monkeypatch):
    from app import app
    monkeypatch.setattr(app,'test_client_class',BrowserClient)
