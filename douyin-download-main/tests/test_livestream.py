"""Offline behavior tests plus actual FFmpeg recording over local HTTP."""

import json
import re
import subprocess
import threading
import time
import runpy
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import pytest

from livestream import (
    LiveRecorder,
    find_ffmpeg,
    normalize_link,
    parse_live_response,
    parse_minutes,
    resolve_room_id,
)
from livestream_gui import RecordingManager, make_server


def test_packaged_paths_separate_assets_from_user_files(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "application/DouyinLive.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("DOUYIN_LIVE_DATA_DIR", raising=False)
    paths = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "runtime_paths.py")
    )
    assert paths["ROOT"] == (tmp_path / "application").resolve()
    assert paths["DATA_ROOT"] == tmp_path / "profile/DouyinLive"
    assert paths["DEFAULT_OUTPUT"] == Path.home() / "Videos/DouyinLive"
    assert paths["RESOURCE_ROOT"] != paths["DATA_ROOT"]


@pytest.mark.parametrize("frozen", [False, True])
def test_explicit_data_directory_is_respected(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("DOUYIN_LIVE_DATA_DIR", str(tmp_path / "dữ liệu"))
    paths = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "runtime_paths.py")
    )
    assert paths["DATA_ROOT"] == (tmp_path / "dữ liệu").resolve()
    assert paths["DEFAULT_OUTPUT"] == paths["DATA_ROOT"] / "Videos"


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("  ", None),
        (0, None),
        ("0.0", None),
        ("1,5", 1.5),
        ("2.25", 2.25),
    ],
)
def test_duration(value, expected):
    assert parse_minutes(value) == expected


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "hello"])
def test_invalid_duration(value):
    with pytest.raises(ValueError):
        parse_minutes(value)


def test_live_response_quality_fallback_and_offline():
    raw = {
        "status_code": 0,
        "data": {
            "data": [
                {
                    "status": 2,
                    "owner": {"nickname": "Test"},
                    "stream_url": {
                        "flv_pull_url": {"SD1": "http://localhost/live.flv"}
                    },
                }
            ]
        },
    }
    info, _ = parse_live_response(raw)
    assert info["flv_pull_url"] == "http://localhost/live.flv"
    raw["data"]["data"][0] = {"status": 4}
    assert parse_live_response(raw)[0]["status"] == "4"
    with pytest.raises(ValueError):
        parse_live_response({"status_code": 0, "data": {"data": []}})


def test_link_validation():
    assert normalize_link("12345") == "https://live.douyin.com/12345"
    assert (
        normalize_link("分享 https://v.douyin.com/ABC/ 复制")
        == "https://v.douyin.com/ABC/"
    )
    with pytest.raises(ValueError):
        normalize_link("https://douyin.com.example.org/123")


def test_share_link_resolution_and_cancel():
    api = type("API", (), {"headers": {"Cookie": "ttwid=test"}})()
    stop = threading.Event()
    with patch("requests.Session") as session:
        transport = session.return_value.__enter__.return_value
        transport.get.return_value.url = "https://live.douyin.com/111/?from=share"
        assert resolve_room_id(api, "https://v.douyin.com/ABC/", stop) == "111"
        assert transport.get.call_args.kwargs["timeout"] == (5, 10)
        transport.get.reset_mock()
        stop.set()
        assert resolve_room_id(api, "https://v.douyin.com/ABC/", stop) is None
        transport.get.assert_not_called()


class FakeAPI:
    headers = {"User-Agent": "test", "Cookie": "test_cookie=example"}

    def __init__(self, url, barrier=None, active_calls=1):
        self.url = url
        self.barrier = barrier
        self.active_calls = active_calls
        self.calls = 0
        self.session = type("Session", (), {"close": lambda self: None})()

    def getLiveInfoApi(self, room_id, stop_event=None):
        self.calls += 1
        if self.barrier and self.calls == 1:
            self.barrier.wait(timeout=10)
        return (
            {"status": "2", "flv_pull_url": self.url, "nickname": room_id}
            if self.calls <= self.active_calls
            else {"status": "4"}
        ), {}


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    try:
        ffmpeg = find_ffmpeg()
    except ValueError:
        pytest.skip("FFmpeg is required for local recording integration tests")
    folder = tmp_path_factory.mktemp("live_media")
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
            "4",
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
    )
    content = source.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/x-flv")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                for start in range(0, len(content), 1024):
                    self.wfile.write(content[start : start + 1024])
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield ffmpeg, ffmpeg, f"http://127.0.0.1:{server.server_port}/source.flv"
    server.shutdown()
    server.server_close()


def probe(ffmpeg, path):
    # Decode both streams completely; this verifies playable audio/video as
    # well as duration without requiring a second executable (ffprobe).
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
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
        timeout=10,
    )
    times = re.findall(r"out_time_us=(\d+)", result.stdout)
    assert times and not result.stderr.strip()
    return int(times[-1]) / 1_000_000


def test_two_real_recordings_with_independent_durations(media, tmp_path):
    ffmpeg, ffprobe, url = media
    barrier = threading.Barrier(2)

    def run(room, minutes):
        updates = []
        recorder = LiveRecorder(
            ffmpeg,
            api_factory=lambda cookie: FakeAPI(url, barrier),
            resolver=lambda api, link, stop: room,
        )
        files = recorder.record(
            room, minutes, tmp_path, on_update=lambda **values: updates.append(values)
        )
        assert updates[-1]["status"] == "completed"
        assert len(files) == 1
        return files[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        short = pool.submit(run, "111", 1.5 / 60)
        long = pool.submit(run, "222", 2.5 / 60)
        short_file, long_file = short.result(timeout=25), long.result(timeout=25)
    assert short_file != long_file
    assert abs(probe(ffprobe, short_file) - 1.5) < 0.3
    assert abs(probe(ffprobe, long_file) - 2.5) < 0.3


def test_blank_duration_records_until_verified_end_and_reconnects(media, tmp_path):
    ffmpeg, ffprobe, url = media
    fake = FakeAPI(url, active_calls=2)
    updates = []
    recorder = LiveRecorder(
        ffmpeg, api_factory=lambda cookie: fake, resolver=lambda *args: "333"
    )
    files = recorder.record(
        "333", "", tmp_path, on_update=lambda **values: updates.append(values)
    )
    assert fake.calls == 3  # Active again after the first EOF; offline after the next.
    assert len(files) == 2
    assert updates[-1]["status"] == "completed"
    assert any(update.get("status") == "reconnecting" for update in updates)
    assert all(probe(ffprobe, file) >= 3.9 for file in files)


def test_stop_preserves_playable_video(media, tmp_path):
    ffmpeg, ffprobe, url = media
    stop = threading.Event()
    updates = []

    def progress(**values):
        updates.append(values)
        if values.get("elapsed", 0) >= 0.5:
            stop.set()

    recorder = LiveRecorder(
        ffmpeg, api_factory=lambda cookie: FakeAPI(url), resolver=lambda *args: "444"
    )
    files = recorder.record("444", None, tmp_path, stop=stop, on_update=progress)
    assert updates[-1]["status"] == "stopped"
    assert files and probe(ffprobe, files[0]) > 0


def test_offline_does_not_create_recording(media, tmp_path):
    ffmpeg, _, url = media
    updates = []
    recorder = LiveRecorder(
        ffmpeg,
        api_factory=lambda cookie: FakeAPI(url, active_calls=0),
        resolver=lambda *args: "555",
    )
    assert (
        recorder.record(
            "555", None, tmp_path, on_update=lambda **values: updates.append(values)
        )
        == []
    )
    assert updates[-1]["status"] == "offline"
    assert not list(tmp_path.glob("*.mp4"))


def test_manager_simultaneous_start_and_stop_preserve_each_duration(tmp_path):
    calls = []
    barrier = threading.Barrier(2)

    class Recorder:
        def __init__(self, *args):
            pass

        def record(self, link, minutes, output, cookie, stop, on_update):
            calls.append((link, minutes))
            barrier.wait(timeout=5)
            on_update(status="recording")
            stop.wait(5)
            on_update(status="stopped")

    with patch("livestream_gui.SETTINGS_FILE", tmp_path / "settings.json"), patch(
        "livestream_gui.LiveRecorder", Recorder
    ):
        manager = RecordingManager()
        manager.public_settings = lambda: {"dependencies_ready": True}
        manager.action({"action": "add", "link": "111", "minutes": "1,5"})
        manager.action({"action": "add", "link": "222", "minutes": ""})
        manager.action({"action": "start_all"})
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sorted(calls) == [
            ("https://live.douyin.com/111", 1.5),
            ("https://live.douyin.com/222", None),
        ]
        job_id = next(iter(manager.jobs))
        with pytest.raises(ValueError):
            manager.action({"action": "edit", "id": job_id, "link": "333"})
        with pytest.raises(ValueError):
            manager.action({"action": "delete", "id": job_id})
        manager.shutdown()
        assert all(job["status"] == "stopped" for job in manager.snapshot()["jobs"])


def test_http_ui_actions_and_token_protection(tmp_path):
    with patch("livestream_gui.SETTINGS_FILE", tmp_path / "settings.json"):
        manager = RecordingManager()
        server = make_server(manager, port=0)
        server_worker = threading.Thread(target=server.serve_forever, daemon=True)
        server_worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            html = urlopen(base).read().decode()
            assert "SỐ PHÚT CẦN GHI" in html
            token = re.search("const token='([^']+)'", html).group(1)
            request = Request(
                base + "/api/action",
                data=json.dumps(
                    {"action": "add", "link": "111", "minutes": ""}
                ).encode(),
                headers={"X-Live-Token": token, "Content-Type": "application/json"},
            )
            jobs = json.load(urlopen(request))["jobs"]
            assert jobs[0]["minutes"] is None
            with pytest.raises(Exception) as error:
                urlopen(
                    Request(
                        base + "/api/action",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                    )
                )
            assert error.value.code == 403
            # A foreign Host cannot read the page containing the token.
            with pytest.raises(Exception) as error:
                urlopen(Request(base, headers={"Host": "evil.example"}))
            assert error.value.code == 403
            manager.action(
                {
                    "action": "settings",
                    "output": str(tmp_path / "videos"),
                    "cookie": "sid_guard=secret",
                }
            )
            assert "secret" not in (tmp_path / "settings.json").read_text()
            assert "cookie" not in manager.public_settings()
            request = Request(
                base + "/api/action",
                data=b'{"action":"shutdown"}',
                headers={"X-Live-Token": token, "Content-Type": "application/json"},
            )
            assert "jobs" in json.load(urlopen(request))
            server_worker.join(timeout=2)
            assert not server_worker.is_alive()
        finally:
            server.shutdown()
            server.server_close()


def test_room_api_retries_are_bounded_and_cancellable():
    # Import under a mocked ttwid registration: these tests never call Douyin.
    with patch("requests.post") as registration:
        registration.return_value.cookies.items.return_value = []
        from src.douyin.douyinapi import DouyinApi
    api = DouyinApi(database_path=None, cookie="sid_guard=first")
    other = DouyinApi(database_path=None, cookie="sid_guard=second")
    assert api.headers["Cookie"] == "sid_guard=first"
    assert other.headers["Cookie"] == "sid_guard=second"
    with patch("src.douyin.douyinapi.requests.Session") as session, patch(
        "src.douyin.douyinapi.time.sleep"
    ):
        transport = session.return_value.__enter__.return_value
        transport.get.return_value.json.return_value = {"status_code": 1}
        with pytest.raises(ValueError):
            api.getLiveInfoApi("111")
        assert transport.get.call_count == 3
        transport.get.reset_mock()
        stop = threading.Event()
        stop.set()
        assert api.getLiveInfoApi("111", stop_event=stop) is None
        transport.get.assert_not_called()
    api.session.close()
    other.session.close()


def test_cli_yaml_raw_cookie_and_live_duration(tmp_path):
    with patch("requests.post") as registration:
        registration.return_value.cookies.items.return_value = []
        from douyinCommand import Config, build_parser
    config = tmp_path / "config.yml"
    config.write_text(
        'link: ["https://live.douyin.com/111"]\ncookies: {ttwid: old}\ncookie: "ttwid=new"\nlive_minutes: 2.5\n'
    )
    loaded = Config.from_yaml(str(config))
    assert loaded.cookie == "ttwid=new"
    assert loaded.live_minutes == 2.5
    parsed = Config.from_args(
        build_parser().parse_args(
            [
                "--cmd",
                "True",
                "--link",
                "https://live.douyin.com/111",
                "--live-minutes",
                "3",
            ]
        )
    )
    assert parsed.live_minutes == 3
