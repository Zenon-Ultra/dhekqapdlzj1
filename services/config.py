"""Load local configuration without overriding explicit process values."""
import os
from pathlib import Path
from dotenv import dotenv_values

def load_settings():
    if os.environ.get('HYPERX_IGNORE_ENV_FILES')=='1':return
    root=Path(__file__).resolve().parents[1]
    for name in ('.env','.env.cloud'):
        for key,value in dotenv_values(root/name).items():
            if value and not os.environ.get(key):os.environ[key]=value
