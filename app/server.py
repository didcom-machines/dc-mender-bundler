import http.server
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yaml  # noqa: F401
except ImportError:
    print("Missing dependency: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from .builder import run_build_job
from .compose import parse_compose_file, parse_compose_string

_HTML = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
_jobs: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/":
            body = _HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/stream/"):
            job_id = self.path[len("/stream/"):]
            if job_id not in _jobs:
                self.send_json({"error": "Job not found"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = _jobs[job_id]["queue"]
            try:
                while True:
                    try:
                        item = q.get(timeout=25)
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    if item is None:
                        job = _jobs[job_id]
                        payload = json.dumps({"status": job["status"], "artifact": job["artifact"]})
                        self.wfile.write(f"event: done\ndata: {payload}\n\n".encode())
                        self.wfile.flush()
                        break
                    kind, line = item
                    data = json.dumps({"line": line, "kind": kind})
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path.startswith("/artifact/"):
            job_id = self.path[len("/artifact/"):]
            if job_id not in _jobs:
                self.send_json({"error": "Job not found"}, 404)
                return
            job = _jobs[job_id]
            if job["status"] != "success" or not job["artifact"]:
                self.send_json({"error": "Artifact not available"}, 400)
                return
            artifact_path = job["artifact"]
            if not os.path.isfile(artifact_path):
                self.send_json({"error": "Artifact file not found on disk"}, 404)
                return
            filename = os.path.basename(artifact_path)
            size = os.path.getsize(artifact_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            try:
                with open(artifact_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == "/images/local":
            try:
                result = subprocess.run(
                    ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                    capture_output=True, text=True, timeout=10,
                )
                images = sorted(set(
                    l.strip() for l in result.stdout.splitlines()
                    if l.strip() and "<none>" not in l
                ))
                self.send_json(images)
            except Exception:
                self.send_json([])

        elif self.path.startswith("/images/search"):
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not q:
                self.send_json([])
                return
            try:
                result = subprocess.run(
                    ["docker", "search", "--format", "{{.Name}}", "--limit", "25", q],
                    capture_output=True, text=True, timeout=20,
                )
                self.send_json([l.strip() for l in result.stdout.splitlines() if l.strip()])
            except Exception:
                self.send_json([])

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/parse-yaml":
            try:
                body = self.read_json()
                result = parse_compose_string(body["content"])
                self.send_json(result)
            except Exception as exc:
                self.send_json({"services": [], "networks": [], "error": str(exc)})

        elif self.path == "/parse":
            try:
                body = self.read_json()
                self.send_json({"services": parse_compose_file(body["path"])})
            except FileNotFoundError:
                self.send_json({"error": "File not found"})
            except Exception as exc:
                self.send_json({"error": str(exc)})

        elif self.path == "/start":
            try:
                params = self.read_json()
                job_id = uuid.uuid4().hex[:10]
                job = {"queue": queue.Queue(), "status": "running", "artifact": ""}
                _jobs[job_id] = job
                threading.Thread(target=run_build_job, args=(job, params), daemon=True).start()
                self.send_json({"jobId": job_id})
            except Exception as exc:
                self.send_json({"error": str(exc)})

        else:
            self.send_json({"error": "Not found"}, 404)


def start(host: str = "127.0.0.1", port: int = 8888, no_browser: bool = False):
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    url = f"http://localhost:{port}"
    print(f"Mender Bundle GUI → {url}")
    print("Ctrl+C to stop\n")
    if not no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
