"""Verify the delivered ZIP from a new Unicode path with Python removed from PATH."""

from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
import zipfile
from urllib.request import build_opener, ProxyHandler, Request

ROOT = Path(__file__).resolve().parent


def verify():
    archive = ROOT / "dist/DouyinLive-Windows-x64.zip"
    stage = ROOT / ".build" / ("máy khác có dấu " + uuid.uuid4().hex[:8])
    assert stage.resolve().is_relative_to(ROOT)
    stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        for name in package.namelist():
            assert (stage / name).resolve().is_relative_to(stage)
            assert not any(
                part in name.split("/")
                for part in (".venv", "Downloaded", "livestream_settings.json")
            )
        package.extractall(stage)
    executable = stage / "DouyinLive/DouyinLive.exe"
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(key, None)
    windows = Path(environment.get("SystemRoot", "C:/Windows"))
    environment["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    environment["DOUYIN_LIVE_DATA_DIR"] = str(stage / "user-data")
    options = {
        "env": environment,
        "cwd": stage,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }
    report = stage / "self-test.json"
    test = subprocess.run(
        [str(executable), "--self-test-report", str(report)], timeout=50, **options
    )
    result = json.loads(report.read_text(encoding="utf-8"))
    assert test.returncode == 0 and result.get("ok") and result.get("frozen"), result
    assert result["recordings"][0]["playable"] and result["recordings"][1]["playable"]
    ready = stage / "ready.json"
    process = subprocess.Popen(
        [str(executable), "--no-browser", "--port", "0", "--ready-file", str(ready)],
        **options
    )
    opener = build_opener(ProxyHandler({}))
    try:
        deadline = time.monotonic() + 15
        while (
            not ready.exists()
            and time.monotonic() < deadline
            and process.poll() is None
        ):
            time.sleep(0.1)
        assert ready.exists(), "Packaged app did not start"
        base = json.loads(ready.read_text(encoding="utf-8"))["url"]
        html = opener.open(base, timeout=5).read().decode("utf-8")
        assert "SỐ PHÚT CẦN GHI" in html
        token = re.search("const token='([^']+)'", html).group(1)

        def get(path):
            return json.load(
                opener.open(
                    Request(base + path, headers={"X-Live-Token": token}), timeout=5
                )
            )

        def action(payload):
            return json.load(
                opener.open(
                    Request(
                        base + "/api/action",
                        data=json.dumps(payload).encode(),
                        headers={
                            "X-Live-Token": token,
                            "Content-Type": "application/json",
                        },
                    ),
                    timeout=5,
                )
            )

        settings = get("/api/settings")
        assert settings["dependencies_ready"] and settings["detected_ffmpeg"]
        assert Path(settings["detected_ffmpeg"]).is_relative_to(stage)
        action({"action": "add", "link": "111", "minutes": 2.5})
        jobs = action({"action": "add", "link": "222", "minutes": ""})["jobs"]
        assert [job["minutes"] for job in jobs] == [2.5, None]
        action({"action": "edit", "id": jobs[0]["id"], "link": "111", "minutes": 3})
        action(
            {
                "action": "settings",
                "output": str(stage / "recordings"),
                "cookie": "ttwid=test-not-saved",
            }
        )
        saved = json.loads(
            (stage / "user-data/livestream_settings.json").read_text(encoding="utf-8")
        )
        assert (
            Path(saved["output"]) == (stage / "recordings").resolve()
            and "cookie" not in saved
        )
        instance = get("/api/instance")
        repeated = subprocess.run(
            [str(executable), "--no-browser", "--port", base.rsplit(":", 1)[1]],
            timeout=10,
            **options
        )
        assert (
            repeated.returncode == 0 and get("/api/instance")["pid"] == instance["pid"]
        )
        action({"action": "shutdown"})
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    result.update(
        {
            "zip": archive.name,
            "zip_megabytes": round(archive.stat().st_size / 1024 / 1024, 1),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "clean_path": environment["PATH"],
            "unicode_relocation": True,
            "packaged_http_ui": True,
            "settings": True,
            "independent_durations": True,
            "shutdown": True,
            "reopen_existing_instance": True,
        }
    )
    final = ROOT / "dist/verification-report.json"
    final.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    verify()
