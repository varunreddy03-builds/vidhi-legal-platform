"""The Gemini client must stay alive for the whole call. Used as a temporary (`_client().aio...`), the client was garbage-collected mid-request and the call failed with an
AssertionError inside aiohttp before anything reached Google. This runs the real `_call_text` against a local fake server that answers like Gemini (no network, no key, no cost)."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from lib import ai


class _Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_a_gemini_call_completes_when_the_client_is_only_held_by_the_call(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from google import genai
        from google.genai import types

        monkeypatch.setattr(ai, "_client", lambda: genai.Client(api_key="x-local-test", http_options=types.HttpOptions(base_url=f"http://127.0.0.1:{server.server_port}")))
        text = asyncio.run(ai._call_text("gemini", "Reply with JSON.", "Return {}", json_mode=True))
        assert json.loads(text) == {"ok": True}
    finally:
        server.shutdown()
