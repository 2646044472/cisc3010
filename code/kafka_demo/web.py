from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runner import Config, ROOT, Run, SCENARIOS, broker_ready


class Controller:
    def __init__(self, bootstrap):
        self.bootstrap = bootstrap
        self.current = None
        self.thread = None
        latest = {}
        paths = sorted((ROOT / "runs").glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                if result.get("scenario") in SCENARIOS:
                    latest.setdefault(result["scenario"], result)
            except (ValueError, OSError):
                continue
        self.history = [latest[s] for s in SCENARIOS if s in latest]
        self.lock = threading.Lock()

    def start(self, options):
        if not isinstance(options, dict):
            raise ValueError("JSON object required")
        allowed = {k: options[k] for k in ("scenario", "events", "consumers", "processing_ms") if k in options}
        config = Config(**allowed, bootstrap=self.bootstrap)
        config.validate()
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("A run is already active")
            if self.current and self.current.result:
                self.history.append(self.current.result)
            self.current = Run(config)
            self.thread = self.current.start()
            return self.current.run_id

    def snapshot(self):
        with self.lock:
            current = self.current
            history = self.history.copy()
        return {"current": current.snapshot() if current else None, "history": history,
                "busy": bool(self.thread and self.thread.is_alive()),
                "bootstrap": self.bootstrap}

    def close(self):
        if self.current:
            self.current.cancel.set()
            (self.current.directory / "STOP").touch()
        if self.thread:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                self.current.stop_children()


def serve(host, port, bootstrap):
    controller = Controller(bootstrap)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path == "/api/state":
                    return self.send_json(200, controller.snapshot())
                if self.path == "/api/health":
                    return self.send_json(200, {"ok": True, **broker_ready(bootstrap, 3)})
                if self.path not in ("/", "/index.html"):
                    return self.send_json(404, {"error": "Not found"})
                data = (ROOT / "ui" / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                self.send_json(503, {"error": str(exc)})

        def do_POST(self):
            try:
                if self.path != "/api/run":
                    return self.send_json(404, {"error": "Not found"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.send_json(415, {"error": "application/json required"})
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    return self.send_json(400, {"error": "Invalid request size"})
                options = json.loads(self.rfile.read(length))
                self.send_json(202, {"run_id": controller.start(options)})
            except (ValueError, TypeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self.send_json(409, {"error": str(exc)})
            except Exception as exc:
                self.send_json(500, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Kafka demo: http://{host}:{port} | broker {bootstrap}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()
