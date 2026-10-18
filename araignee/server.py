"""Tableau de bord : sert index.html et data/ ; mot de passe optionnel (DASHBOARD_PASSWORD)."""
import base64
import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = ("/", "/index.html", "/data/state.json", "/data/backtest.json", "/data/ameliorations.json", "/favicon.svg")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path not in ALLOWED:  # on ne sert jamais le code, la config ou les journaux
            return self.send_error(404)
        pwd = os.environ.get("DASHBOARD_PASSWORD")
        if pwd:
            expected = "Basic " + base64.b64encode(("araignee:" + pwd).encode()).decode()
            if self.headers.get("Authorization") != expected:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="araignee"')
                self.end_headers()
                return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(root, port=None):
    port = int(port or os.environ.get("PORT", 4010))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), functools.partial(Handler, directory=root))
    print("Tableau de bord : http://localhost:{}".format(port))
    httpd.serve_forever()


def serve_background(root):
    threading.Thread(target=serve, args=(root,), daemon=True).start()
