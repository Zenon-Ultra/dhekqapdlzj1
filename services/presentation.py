"""Apply the shared interface to templates and previously generated book HTML."""
import re
from flask import request


def install_presentation(app):
    @app.after_request
    def apply_presentation(response):
        if response.mimetype != 'text/html' or response.status_code >= 400:
            return response
        response.direct_passthrough = False
        source = response.get_data(as_text=True)
        if 'data-hyperx-design' in source: return response
        path = request.path
        page = ('library' if path in ('/main', '/main.html') else
                'admin' if path == '/admin' else
                'auth' if path in ('/login', '/signup') else
                'editor' if 'template_editor' in path else
                'viewer' if path.startswith('/textbooks/') else 'landing')
        assets = ('<link rel="stylesheet" href="/static/motion.css?v=1" data-hyperx-design>'
                  '<script src="/static/motion.js?v=1" defer></script>')
        source = re.sub(r'</head\s*>', lambda match: assets+match[0], source, count=1, flags=re.I)
        source = re.sub(r'<body\b', lambda match: match[0]+' data-hx-page="'+page+'"', source, count=1, flags=re.I)
        response.set_data(source)
        response.headers.pop('ETag', None)
        return response
