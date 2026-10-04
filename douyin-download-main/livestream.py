"""Concurrent Douyin recording, shared by the local UI and command line."""

from __future__ import annotations

import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from runtime_paths import ROOT


def parse_minutes(value):
    """Blank or zero means record until the broadcast ends."""
    if value is None or str(value).strip() in ("", "0"):
        return None
    try:
        minutes = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Số phút phải là một số lớn hơn 0, hoặc để trống.") from None
    if not math.isfinite(minutes) or minutes < 0:
        raise ValueError("Số phút phải hữu hạn và không âm.")
    return minutes or None


def normalize_link(value):
    value = str(value).strip()
    if value.isdigit():
        return "https://live.douyin.com/" + value
    match = re.search(r"https?://[^\s<>]+", value)
    if not match:
        raise ValueError("Nhập link live Douyin hoặc ID phòng live.")
    link = match.group().rstrip(".,;，。)")
    host = (urlparse(link).hostname or "").lower()
    if not any(
        host == domain or host.endswith("." + domain)
        for domain in ("douyin.com", "iesdouyin.com")
    ):
        raise ValueError("Link phải thuộc Douyin.")
    return link


def find_ffmpeg(value=""):
    if value and str(value).strip():
        candidate = Path(str(value).strip().strip('"')).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(str(value).strip())
        if found:
            return found
        raise ValueError("Không tìm thấy FFmpeg tại đường dẫn đã nhập.")
    for candidate in (
        ROOT / "ffmpeg/ffmpeg.exe",
        ROOT / "ffmpeg/bin/ffmpeg.exe",
        ROOT / ".tools/ffmpeg/bin/ffmpeg.exe",
        ROOT / ".tools/ffmpeg.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if not found:
        raise ValueError("Chưa tìm thấy FFmpeg. Chọn file ffmpeg.exe trong Cài đặt.")
    return found


def parse_live_response(raw):
    """Handle offline rooms and fall back when FULL_HD1 is absent."""
    if not isinstance(raw, dict) or raw.get("status_code") != 0:
        raise ValueError("Douyin từ chối yêu cầu. Kiểm tra cookie hoặc thử lại.")
    payload = raw.get("data") or {}
    rooms = payload.get("data") or []
    room = rooms[0] if rooms else payload.get("room")
    if not isinstance(room, dict):
        raise ValueError("Không lấy được thông tin phòng live. Kiểm tra link/cookie.")
    owner = room.get("owner") or payload.get("user") or {}
    status = str(room.get("status_str", room.get("status", "")))
    info = {
        "awemeType": "2",
        "status": status,
        "title": room.get("title", ""),
        "nickname": owner.get("nickname", ""),
        "sec_uid": owner.get("sec_uid", ""),
    }
    if status == "4":
        return info, raw
    stream = room.get("stream_url") or {}
    for field in ("flv_pull_url", "hls_pull_url_map"):
        choices = stream.get(field) or {}
        if not isinstance(choices, dict):
            continue
        for quality in ("FULL_HD1", "HD1", "SD1", "SD2", "ORIGIN", *choices):
            url = choices.get(quality)
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                info["flv_pull_url"] = url
                return info, raw
    hls = stream.get("hls_pull_url")
    if isinstance(hls, str) and hls.startswith(("https://", "http://")):
        info["flv_pull_url"] = hls
        return info, raw
    raise ValueError("Phòng live chưa có luồng phát có thể ghi. Kiểm tra cookie.")


def create_live_api(cookie):
    # Import and network initialization happen in a worker, never in the UI.
    from src.douyin.douyinapi import DouyinApi

    return DouyinApi(database_path=None, cookie=cookie or None)


def resolve_room_id(api, link, stop):
    url = normalize_link(link)
    parsed = urlparse(url)
    if parsed.hostname == "live.douyin.com" and re.fullmatch(r"/\d+/?", parsed.path):
        return parsed.path.strip("/")
    if stop.is_set():
        return None
    import requests

    # Do not inherit the general API's automatic retry adapter during stop.
    with requests.Session() as session:
        response = session.get(url, headers=api.headers, timeout=(5, 10))
        response.raise_for_status()
        if stop.is_set():
            return None
        parsed = urlparse(response.url)
        if parsed.hostname == "live.douyin.com" and re.fullmatch(
            r"/\d+/?", parsed.path
        ):
            return parsed.path.strip("/")
        match = re.search(r"/webcast/reflow/(\d+)", parsed.path)
        if match:
            from src.common import utils

            params = utils.getXbogus(f"live_id=1&room_id={match.group(1)}&app_id=1128")
            response = session.get(
                api.urls.LIVE2 + params, headers=api.headers, timeout=(5, 10)
            )
            response.raise_for_status()
            owner = ((response.json().get("data") or {}).get("room") or {}).get(
                "owner"
            ) or {}
            if str(owner.get("web_rid", "")).isdigit():
                return str(owner["web_rid"])
    raise ValueError("Link này không dẫn tới phòng livestream Douyin.")


class LiveRecorder:
    def __init__(
        self, ffmpeg="", api_factory=create_live_api, resolver=resolve_room_id
    ):
        self.ffmpeg = find_ffmpeg(ffmpeg)
        self.api_factory = api_factory
        self.resolver = resolver

    def record(self, link, minutes, output_dir, cookie="", stop=None, on_update=None):
        stop = stop or threading.Event()
        on_update = on_update or (lambda **values: None)
        minutes = parse_minutes(minutes)
        limit = minutes * 60 if minutes is not None else None
        recorded = 0.0
        paths = []
        api = None
        on_update(status="resolving", message="Đang lấy thông tin phòng live…")
        try:
            api = self.api_factory(cookie)
            room_id = self.resolver(api, link, stop)
            if stop.is_set():
                on_update(status="stopped", message="Đã dừng.")
                return paths
            output_dir = Path(output_dir).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            prefix = f"live_{room_id}_{stamp}_{uuid4().hex[:6]}"
            failures = 0
            part_number = 0
            while not stop.is_set():
                try:
                    result = api.getLiveInfoApi(room_id, stop_event=stop)
                    if stop.is_set():
                        break
                    if not result:
                        raise ValueError(
                            "Không lấy được phòng live. Kiểm tra cookie/kết nối."
                        )
                    info, _ = result
                    if str(info.get("status")) == "4":
                        on_update(
                            status="completed" if paths else "offline",
                            message=(
                                "Live đã kết thúc."
                                if paths
                                else "Phòng hiện không phát live."
                            ),
                        )
                        return paths
                    url = info.get("flv_pull_url")
                    if not url:
                        raise ValueError("Không tìm thấy URL luồng live.")
                    on_update(nickname=info.get("nickname", ""))
                    remaining = limit - recorded if limit is not None else None
                    if remaining is not None and remaining <= 0.05:
                        on_update(status="completed", message="Đã ghi đủ thời lượng.")
                        return paths
                    part_number += 1
                    target = output_dir / f"{prefix}_part{part_number:03d}.mp4"
                    on_update(status="resolving", message="Đang kết nối luồng phát…")
                    duration, returncode = self._record_part(
                        url,
                        target,
                        remaining,
                        api.headers,
                        stop,
                        lambda **values: on_update(
                            **{**values, "elapsed": recorded + values.get("elapsed", 0)}
                        ),
                    )
                    if target.exists() and target.stat().st_size > 0 and duration > 0:
                        paths.append(str(target))
                    elif target.exists():
                        # Discard only this newly created header-only output.
                        target.unlink()
                    recorded += duration
                    on_update(elapsed=recorded, files=list(paths))
                    if stop.is_set():
                        break
                    if limit is not None and recorded >= limit - 0.25:
                        on_update(status="completed", message="Đã ghi đủ thời lượng.")
                        return paths
                    # EOF may be a dropped connection. Confirm the room status and
                    # fetch a fresh signed URL before declaring that the live ended.
                    failures = 0 if duration >= 10 else failures + 1
                    if failures >= 5:
                        raise RuntimeError(
                            f"Không ghi được dữ liệu live (FFmpeg {returncode}). Kiểm tra cookie/kết nối."
                        )
                    on_update(
                        status="reconnecting", message="Kiểm tra live và kết nối lại…"
                    )
                    stop.wait(2)
                except (ValueError, OSError, RuntimeError):
                    if stop.is_set():
                        break
                    failures += 1
                    if failures >= 5:
                        raise
                    on_update(
                        status="reconnecting",
                        message=f"Đang thử kết nối lại ({failures}/5)…",
                    )
                    stop.wait(2)
            on_update(
                status="stopped", message="Đã dừng; các đoạn đã ghi được giữ lại."
            )
            return paths
        except Exception as exc:
            if stop.is_set():
                on_update(status="stopped", message="Đã dừng.", files=list(paths))
            else:
                # Do not display raw requests errors containing signed URLs/cookies.
                message = (
                    str(exc)
                    if isinstance(exc, (ValueError, RuntimeError))
                    else "Lỗi kết nối hoặc thiếu thư viện. Kiểm tra cài đặt/cookie."
                )
                on_update(status="error", message=message, files=list(paths))
            return paths
        finally:
            if api is not None:
                api.session.close()

    @staticmethod
    def _stop_process(process):
        if process.poll() is not None:
            return
        try:
            process.stdin.write("q\n")
            process.stdin.flush()
            process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def _record_part(self, url, target, seconds, headers, stop, update):
        request_headers = "".join(
            f"{key}: {headers[key]}\r\n"
            for key in ("User-Agent", "Referer", "referer", "Cookie")
            if headers.get(key)
        )
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-rw_timeout",
            "15000000",
            "-headers",
            request_headers,
            "-i",
            url,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
        ]
        if seconds is not None:
            command += ["-t", f"{seconds:.6f}"]
        command += [
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            "-progress",
            "pipe:1",
            "-nostats",
            str(target),
        ]
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **options,
        )
        lines = queue.Queue()

        def read_progress():
            for line in process.stdout:
                lines.put(line.strip())

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        elapsed = 0.0
        last_data = time.monotonic()
        last_update = 0.0
        try:
            while process.poll() is None or reader.is_alive() or not lines.empty():
                if stop.is_set() or time.monotonic() - last_data > 35:
                    self._stop_process(process)
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    continue
                key, _, value = line.partition("=")
                if key == "out_time_us":
                    try:
                        current = max(0.0, int(value) / 1_000_000)
                    except ValueError:
                        continue
                    if current > elapsed:
                        last_data = time.monotonic()
                        elapsed = current
                    if time.monotonic() - last_update >= 0.5 and elapsed > 0:
                        update(
                            status="recording",
                            message="Đang ghi live…",
                            elapsed=elapsed,
                            current_file=str(target),
                            bytes=target.stat().st_size if target.exists() else 0,
                        )
                        last_update = time.monotonic()
            return elapsed, process.wait()
        finally:
            self._stop_process(process)
            reader.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
