"""Windowless Windows entry point and offline packaged-build verification."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

from runtime_paths import DATA_ROOT, FROZEN, RESOURCE_ROOT, ROOT


def self_test(report_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import requests
    from livestream import LiveRecorder, find_ffmpeg

    # Import the existing API without contacting Douyin's ttwid endpoint.
    original_post = requests.post

    class Response:
        class Cookies:
            def items(self):
                return []

        cookies = Cookies()

    requests.post = lambda *args, **kwargs: Response()
    try:
        from src.douyin.douyinapi import DouyinApi
        from src.common import utils
        from src.common.abogus import ABogus
    finally:
        requests.post = original_post
    api = DouyinApi(database_path=None, cookie="ttwid=self-test")
    api.session.close()
    assert utils.getXbogus("aid=6383&web_rid=111")
    assert ABogus().get_value({"aid": "6383", "web_rid": "111"})
    ffmpeg = find_ffmpeg()
    process_options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    )
    version = subprocess.run(
        [ffmpeg, "-version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
        **process_options,
    ).stdout.splitlines()[0]
    assert (RESOURCE_ROOT / "livestream_ui/index.html").is_file()
    with tempfile.TemporaryDirectory(
        prefix="recording-test-", dir=Path(report_path).parent
    ) as directory:
        folder = Path(directory)
        source = folder / "source.flv"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x120:rate=25",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "25",
                "-c:a",
                "aac",
                "-f",
                "flv",
                str(source),
            ],
            check=True,
            timeout=30,
            **process_options,
        )
        content = source.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        class FakeAPI:
            headers = {}
            session = type("Session", (), {"close": lambda self: None})()

            def getLiveInfoApi(self, *args, **kwargs):
                return {
                    "status": "2",
                    "flv_pull_url": f"http://127.0.0.1:{server.server_port}/live.flv",
                }, {}

        def record(room, seconds):
            updates = []
            recorder = LiveRecorder(
                ffmpeg,
                api_factory=lambda cookie: FakeAPI(),
                resolver=lambda *args: room,
            )
            files = recorder.record(
                room,
                seconds / 60,
                folder,
                on_update=lambda **value: updates.append(value),
            )
            assert files and updates[-1]["status"] == "completed", updates
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    files[0],
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-progress",
                    "pipe:1",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
                **process_options,
            )
            assert not result.stderr.strip(), result.stderr
            return {"room": room, "seconds": seconds, "playable": True}

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(record, "111", 1.0)
                second = pool.submit(record, "222", 1.5)
                recordings = [first.result(timeout=30), second.result(timeout=30)]
        finally:
            server.shutdown()
            server.server_close()
    return {
        "ok": True,
        "frozen": FROZEN,
        "executable": sys.executable,
        "bundle_root": str(ROOT),
        "ffmpeg": ffmpeg,
        "ffmpeg_version": version,
        "api_imports": True,
        "request_signing": True,
        "ui_resource": True,
        "recordings": recordings,
    }


def run():
    if "--self-test-report" in sys.argv:
        index = sys.argv.index("--self-test-report")
        report = Path(sys.argv[index + 1]).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = self_test(report)
            report.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            report.write_text(
                json.dumps(
                    {"ok": False, "error": traceback.format_exc()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
        return
    if FROZEN:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        # Windowless apps have no stdout/stderr; keep diagnostic output locally.
        log = open(DATA_ROOT / "application.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    from livestream_gui import main

    main()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        if FROZEN and "--self-test-report" in sys.argv:
            sys.exit(1)
        if FROZEN and "--self-test-report" not in sys.argv:
            traceback.print_exc()
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"Không thể mở Douyin Live.\nChi tiết: {DATA_ROOT / 'application.log'}",
                "Douyin Live",
                0x10,
            )
            sys.exit(1)
        raise
