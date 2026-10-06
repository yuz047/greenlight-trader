"""Private localhost preview; maps /data to gitignored runtime outputs."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from config import ROOT, DATA_DIR


class Preview(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = unquote(urlsplit(path).path)
        if clean.startswith('/data/'):
            base, relative = DATA_DIR, clean[6:]
        elif clean.startswith('/web/'):
            base, relative = ROOT / 'web', clean[5:]
        else:
            base, relative = ROOT / 'web', clean.lstrip('/')
        target = (base / relative).resolve()
        if not target.is_relative_to(base.resolve()):
            return str(ROOT / 'web' / '__not_found__')
        return str(target)


if __name__ == '__main__':
    print(f'Private preview http://127.0.0.1:8765/web/ using {DATA_DIR}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Preview).serve_forever()
