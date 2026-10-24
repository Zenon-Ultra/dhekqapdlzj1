"""Session CSRF protection, including legacy admin EventSource GET actions."""
import html
import re
import secrets
from urllib.parse import urlsplit
from flask import request, session, jsonify

def install_csrf(app):
    @app.before_request
    def csrf_guard():
        protected = request.method in ('POST','PUT','PATCH','DELETE') or request.path.startswith('/api/run/') or request.path == '/logout'
        if not protected: return
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return jsonify({'error':'Cross-site request blocked'}),403
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return jsonify({'error':'Origin mismatch'}),403
        expected=session.get('_csrf')
        actual=request.headers.get('X-CSRF-Token') or request.form.get('_csrf') or request.args.get('_csrf')
        if not expected or not actual or not secrets.compare_digest(expected,actual):
            return jsonify({'error':'Invalid CSRF token; reload the page'}),403

    @app.after_request
    def attach_csrf(response):
        if response.mimetype != 'text/html' or response.status_code >= 400: return response
        token=session.setdefault('_csrf',secrets.token_hex(32))
        response.direct_passthrough=False
        source=response.get_data(as_text=True)
        bootstrap = '<meta name="csrf-token" content="'+html.escape(token)+'"><script src="/static/security.js"></script>'
        source=re.sub(r'(<head\b[^>]*>)',lambda m:m[0]+bootstrap,source,count=1,flags=re.I)
        field='<input type="hidden" name="_csrf" value="'+html.escape(token)+'">'
        source=re.sub(r'(<form\b[^>]*>)',lambda m:m[0]+field,source,flags=re.I)
        response.set_data(source)
        response.headers['Cache-Control']='no-store'
        response.headers.pop('ETag',None)
        response.headers['Referrer-Policy']='same-origin'
        return response
