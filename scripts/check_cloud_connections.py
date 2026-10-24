"""Check real cloud connectivity without migrating or deleting application data."""
import argparse
import hashlib
import os
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.config import load_settings
load_settings()
B2_VARS=('B2_ENDPOINT_URL','B2_REGION','B2_BUCKET','B2_KEY_ID','B2_APPLICATION_KEY')

def check(write_probe=False):
    ok=True
    missing=[name for name in B2_VARS if not os.environ.get(name)]
    if missing:
        print('B2: missing '+', '.join(missing));ok=False
    else:
        try:
            from services.storage import Store
            from botocore.config import Config
            store=Store()
            client=store.s3()
            client.list_objects_v2(Bucket=store.bucket,Prefix=store.prefix+'/',MaxKeys=1)
            if write_probe:
                data=uuid.uuid4().hex.encode('ascii')
                key=store.key('_connection-probes/'+uuid.uuid4().hex+'.txt')
                client.put_object(Bucket=store.bucket,Key=key,Body=data,ContentType='text/plain')
                if store.read(key)!=data: raise ValueError('Probe checksum mismatch')
                print('B2: write/read verified; tiny probe retained (no deletion)')
            else: print('B2: authenticated bucket read successful')
        except Exception as exc:
            code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
            print('B2: connection failed ('+str(code)+'); check endpoint, key permissions and network');ok=False
    if not os.environ.get('DATABASE_URL'):
        print('PostgreSQL: missing DATABASE_URL');ok=False
    else:
        try:
            import psycopg
            with psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=10,sslmode='require') as conn:
                conn.execute("SET LOCAL statement_timeout = '5s'")
                if conn.execute('SELECT 1').fetchone()!=(1,):raise ValueError('Unexpected database result')
            print('PostgreSQL: authenticated TLS connection successful; no schema/data changes')
        except Exception as exc:
            print('PostgreSQL: connection failed ('+type(exc).__name__+'); check connection string and network');ok=False
    return ok

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--write-probe',action='store_true',help='Upload and retain one tiny B2 probe to verify write access')
    args=parser.parse_args();sys.exit(0 if check(args.write_probe) else 1)
