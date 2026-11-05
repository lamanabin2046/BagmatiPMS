"""डेमो राष्ट्रिय परिचयपत्र (NID) server — वास्तविक API जस्तै छुट्टै HTTP सेवा।

चलाउने:
    python manage.py nid_demo_server            # http://127.0.0.1:8765
    python manage.py nid_demo_server --port 9000 --delay 0.5

अनि .env मा:
    NID_API_URL=http://127.0.0.1:8765/api/person/{nid}/
    NID_API_KEY=demo-key        # (ऐच्छिक) राखे server ले पनि यही key माग्छ

Endpoint:
    GET /                          डेमो NID हरूको सूची
    GET /api/person/<nid>/         एक व्यक्तिको विवरण (200 / 404 / 400 / 401)
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from usercommittee import nid_demo


class Command(BaseCommand):
    help = "डेमो राष्ट्रिय परिचयपत्र (NID) API server चलाउँछ (परीक्षणका लागि)"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument("--delay", type=float, default=0.3, help="हरेक जवाफ अघि ढिलाइ (सेकेन्ड), वास्तविक API जस्तो")
        parser.add_argument("--key", default=None, help="माग्ने API key (नदिए .env को NID_API_KEY)")

    def handle(self, *args, host, port, delay, key, **opts):
        key = key if key is not None else getattr(settings, "NID_API_KEY", "")
        out = self.stdout

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, body):
                data = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = unquote(urlparse(self.path).path).rstrip("/")
                if delay:
                    time.sleep(delay)
                if path in ("", "/api", "/api/person"):
                    return self._send(200, {
                        "service": "डेमो राष्ट्रिय परिचयपत्र API (काल्पनिक data)",
                        "usage": "/api/person/<nid>/",
                        "people": [{"nid": p["nid"], "name": p["full_name_np"], "address": p["address_np"]}
                                   for p in nid_demo.PEOPLE],
                    })
                if not path.startswith("/api/person/"):
                    return self._send(404, {"status": "not_found", "message": "unknown endpoint"})
                if key and self.headers.get("Authorization", "") != f"Bearer {key}":
                    return self._send(401, {"status": "unauthorized", "message": "API key मिलेन"})
                status, body = nid_demo.api_response(path.rsplit("/", 1)[-1])
                return self._send(status, body)

            def log_message(self, fmt, *a):
                out.write(f"  {self.address_string()} {fmt % a}")

        server = ThreadingHTTPServer((host, port), Handler)
        url = f"http://{host}:{port}"
        self.stdout.write(self.style.SUCCESS(f"डेमो NID server चल्यो: {url}"))
        self.stdout.write(f"  .env मा: NID_API_URL={url}/api/person/{{nid}}/")
        if key:
            self.stdout.write(f"           NID_API_KEY={key}")
        self.stdout.write(f"  {len(nid_demo.PEOPLE)} जना काल्पनिक व्यक्ति, जस्तै:")
        for p in nid_demo.PEOPLE[:5]:
            self.stdout.write(f"    {p['nid']}  {p['full_name_np']}  ({p['address_np']})")
        self.stdout.write("  सबै सूची: " + url + "/   ·   रोक्न Ctrl+C")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
