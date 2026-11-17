"""Local preview with correct JS MIME types, including on Windows."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from scripts.common import ROOT


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), partial(Handler, directory=str(ROOT / "_site")))
    print("Preview: http://127.0.0.1:8765", flush=True)
    server.serve_forever()
