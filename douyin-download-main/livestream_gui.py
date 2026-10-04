"""Local browser interface. Run: python livestream_gui.py"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import threading
import time
import webbrowser
from urllib.request import build_opener, ProxyHandler
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from livestream import ROOT, LiveRecorder, find_ffmpeg, normalize_link, parse_minutes
from runtime_paths import DATA_ROOT, DEFAULT_OUTPUT, RESOURCE_ROOT, FROZEN

ACTIVE = {"resolving", "recording", "reconnecting", "stopping"}
SETTINGS_FILE = DATA_ROOT / "livestream_settings.json"


class RecordingManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}
        self.workers = {}
        self.stops = {}
        self.settings = {
            "output": str(DEFAULT_OUTPUT),
            "ffmpeg": "",
            "cookie": "",
        }
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                for key in ("output", "ffmpeg"):
                    if isinstance(saved.get(key), str):
                        self.settings[key] = saved[key]
            except (ValueError, OSError):
                pass

    def snapshot(self):
        with self.lock:
            return {"jobs": [dict(job) for job in self.jobs.values()]}

    def public_settings(self):
        with self.lock:
            result = {key: self.settings[key] for key in ("output", "ffmpeg")}
            result["cookie_configured"] = bool(self.settings["cookie"])
        try:
            result["detected_ffmpeg"] = find_ffmpeg(result["ffmpeg"])
        except ValueError:
            result["detected_ffmpeg"] = ""
        result["dependencies_ready"] = all(
            importlib.util.find_spec(name) is not None for name in ("requests", "gmssl")
        )
        result["packaged"] = FROZEN
        return result

    def update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)

    def start(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValueError("Không tìm thấy luồng live.")
            if job_id in self.workers and self.workers[job_id].is_alive():
                return
            settings = dict(self.settings)
            recorder = LiveRecorder(settings["ffmpeg"])
            if not self.public_settings()["dependencies_ready"]:
                raise ValueError(
                    "Ứng dụng thiếu thành phần. Giải nén đầy đủ ZIP và mở lại DouyinLive.exe."
                    if FROZEN
                    else "Thiếu thư viện Python. Chạy pip install -r requirements.txt."
                )
            stop = threading.Event()
            self.stops[job_id] = stop
            self.update(
                job_id,
                status="resolving",
                elapsed=0,
                bytes=0,
                files=[],
                current_file="",
                message="Đang chuẩn bị ghi…",
                nickname="",
            )

            def run():
                try:
                    recorder.record(
                        job["link"],
                        job["minutes"],
                        settings["output"],
                        settings["cookie"],
                        stop=stop,
                        on_update=lambda **values: self.update(job_id, **values),
                    )
                except Exception:
                    self.update(
                        job_id, status="error", message="Không thể khởi chạy luồng ghi."
                    )

            worker = threading.Thread(target=run, name="live-" + job_id, daemon=True)
            self.workers[job_id] = worker
            worker.start()

    def stop(self, job_id):
        with self.lock:
            if job_id in self.stops and self.jobs[job_id]["status"] in ACTIVE:
                self.jobs[job_id].update(
                    status="stopping", message="Đang dừng và lưu video…"
                )
                self.stops[job_id].set()

    def stop_all(self):
        with self.lock:
            for job_id in self.jobs:
                self.stop(job_id)

    def shutdown(self):
        self.stop_all()
        with self.lock:
            workers = list(self.workers.values())
        deadline = time.monotonic() + 22
        for worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))

    def action(self, payload):
        action = payload.get("action")
        job_id = payload.get("id")
        with self.lock:
            if action == "add":
                link = normalize_link(payload.get("link", ""))
                minutes = parse_minutes(payload.get("minutes"))
                job_id = uuid4().hex
                self.jobs[job_id] = {
                    "id": job_id,
                    "link": link,
                    "minutes": minutes,
                    "status": "queued",
                    "elapsed": 0,
                    "bytes": 0,
                    "files": [],
                    "current_file": "",
                    "nickname": "",
                    "message": "Sẵn sàng ghi.",
                }
            elif action == "edit":
                job = self.jobs.get(job_id)
                if job is None or job["status"] in ACTIVE:
                    raise ValueError("Chỉ sửa được luồng chưa ghi hoặc đã dừng.")
                link = normalize_link(payload.get("link", ""))
                minutes = parse_minutes(payload.get("minutes"))
                job.update(link=link, minutes=minutes)
            elif action == "delete":
                if job_id not in self.jobs:
                    raise ValueError("Không tìm thấy luồng.")
                worker = self.workers.get(job_id)
                if worker is not None and worker.is_alive():
                    raise ValueError("Hãy dừng luồng trước khi xóa.")
                del self.jobs[job_id]
                self.workers.pop(job_id, None)
                self.stops.pop(job_id, None)
            elif action == "start":
                self.start(job_id)
            elif action == "stop":
                self.stop(job_id)
            elif action == "start_all":
                for current in list(self.jobs):
                    if self.jobs[current]["status"] not in ACTIVE:
                        self.start(current)
            elif action == "stop_all":
                self.stop_all()
            elif action == "settings":
                output = str(payload.get("output", "")).strip()
                if not output:
                    raise ValueError("Nhập thư mục lưu video.")
                ffmpeg = str(payload.get("ffmpeg", "")).strip()
                if ffmpeg:
                    find_ffmpeg(ffmpeg)
                destination = Path(output).expanduser().resolve()
                destination.mkdir(parents=True, exist_ok=True)
                cookie = payload.get("cookie")
                if cookie is not None and ("\r" in cookie or "\n" in cookie):
                    raise ValueError("Cookie phải nằm trên một dòng.")
                persisted = {"output": str(destination), "ffmpeg": ffmpeg}
                SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                temp = SETTINGS_FILE.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(persisted, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp.replace(SETTINGS_FILE)
                self.settings.update(persisted)
                if cookie is not None:
                    self.settings["cookie"] = str(cookie).strip()
            elif action == "open_folder":
                if os.name != "nt":
                    raise ValueError("Thư mục: " + self.settings["output"])
                folder = Path(self.settings["output"])
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(str(folder))
            else:
                raise ValueError("Thao tác không hợp lệ.")
        return self.snapshot()


def make_server(manager, host="127.0.0.1", port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            data = (
                body.encode("utf-8")
                if isinstance(body, str)
                else json.dumps(body, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            # Bind to loopback; reject cross-origin requests, including reads of
            # the page containing the per-session API token (DNS rebinding).
            expected = f"127.0.0.1:{self.server.server_port}"
            return (
                self.headers.get("Host") == expected
                and self.headers.get("Sec-Fetch-Site", "none") != "cross-site"
            )

        def do_GET(self):
            if not self.authorized():
                self.send(403, {"error": "Truy cập không hợp lệ."})
                return
            if self.path == "/":
                page = (RESOURCE_ROOT / "livestream_ui/index.html").read_text(
                    encoding="utf-8"
                )
                self.send(
                    200,
                    page.replace("__API_TOKEN__", token),
                    "text/html; charset=utf-8",
                )
            elif self.path == "/api/instance":
                self.send(
                    200,
                    {
                        "application": "DouyinLive",
                        "version": "1.0.0",
                        "pid": os.getpid(),
                    },
                )
            elif self.path.startswith("/api/"):
                if not secrets.compare_digest(
                    self.headers.get("X-Live-Token", ""), token
                ):
                    self.send(403, {"error": "Phiên không hợp lệ; tải lại giao diện."})
                elif self.path == "/api/jobs":
                    self.send(200, manager.snapshot())
                elif self.path == "/api/settings":
                    self.send(200, manager.public_settings())
                else:
                    self.send(404, {"error": "Không tìm thấy."})
            else:
                self.send(404, {"error": "Không tìm thấy."})

        def do_POST(self):
            # Drain a bounded request before replying. Closing a Windows socket
            # with an unread body can reset it before the client receives 403.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise ValueError("Dữ liệu gửi không hợp lệ.")
                self.connection.settimeout(5)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Dữ liệu gửi chưa đầy đủ.")
            except (ValueError, OSError):
                self.send(400, {"error": "Dữ liệu gửi không hợp lệ."})
                return
            if not self.authorized() or not secrets.compare_digest(
                self.headers.get("X-Live-Token", ""), token
            ):
                self.send(403, {"error": "Phiên không hợp lệ; tải lại giao diện."})
                return
            if self.path != "/api/action":
                self.send(404, {"error": "Không tìm thấy."})
                return
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("Dữ liệu gửi không hợp lệ.")
                if payload.get("action") == "shutdown":
                    manager.stop_all()
                    self.send(200, manager.snapshot())
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                self.send(200, manager.action(payload))
            except (ValueError, OSError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception:
                self.send(
                    500, {"error": "Không thể thực hiện thao tác. Kiểm tra cài đặt."}
                )

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(
        description="Giao diện ghi nhiều livestream Douyin"
    )
    parser.add_argument("--port", type=int, default=8766 if FROZEN else 8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.port:
        try:
            existing_url = f"http://127.0.0.1:{args.port}"
            with build_opener(ProxyHandler({})).open(
                existing_url + "/api/instance", timeout=1
            ) as response:
                existing = json.load(response)
            if existing.get("application") == "DouyinLive":
                if not args.no_browser:
                    webbrowser.open(existing_url)
                return
        except (OSError, ValueError):
            pass
    manager = RecordingManager()
    try:
        server = make_server(manager, port=args.port)
    except OSError:
        server = make_server(manager, port=0)
    url = f"http://127.0.0.1:{server.server_port}"
    if args.ready_file:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text(
            json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8"
        )
    print(
        f"Douyin Live: {url}\nPress Ctrl+C to stop the app and save recordings.",
        flush=True,
    )
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
