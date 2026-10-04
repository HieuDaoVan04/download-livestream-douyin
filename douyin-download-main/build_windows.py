"""Build the folder distribution and ZIP without including local user data."""

from pathlib import Path
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUNDLE = DIST / "DouyinLive"


def build():
    if os.name != "nt":
        raise RuntimeError("Build the Windows exe on Windows.")
    # PyInstaller may replace its output; constrain every generated path here.
    for target in (BUNDLE, ROOT / ".build"):
        assert target.resolve().is_relative_to(ROOT)
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / ".build/pyinstaller-cache")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(ROOT / ".build"),
            "--distpath",
            str(DIST),
            str(ROOT / "DouyinLive.spec"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    ffmpeg = ROOT / ".tools/ffmpeg/bin/ffmpeg.exe"
    if not ffmpeg.is_file():
        import imageio_ffmpeg

        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    (BUNDLE / "ffmpeg").mkdir(exist_ok=True)
    shutil.copy2(ffmpeg, BUNDLE / "ffmpeg/ffmpeg.exe")
    (BUNDLE / "HUONG_DAN.txt").write_text(
        "DOUYIN LIVE 1.0 — WINDOWS 64-BIT\n\n"
        "1. Giải nén toàn bộ thư mục DouyinLive.\n"
        "2. Mở DouyinLive.exe. Giao diện tự mở trong trình duyệt.\n"
        "3. Nhập link live và số phút cho từng phòng; thêm nhiều phòng rồi Bắt đầu tất cả.\n"
        "4. Để trống hoặc nhập 0 để ghi từ lúc bắt đầu đến khi live kết thúc.\n"
        "5. Nhấn Dừng để giữ phần đã ghi, hoặc Thoát để đóng ứng dụng.\n\n"
        "Không cần cài Python hoặc FFmpeg. Giữ nguyên thư mục _internal và ffmpeg cạnh exe.\n"
        "Video mặc định: thư mục Videos\\DouyinLive trong tài khoản Windows.\n"
        "Cấu hình và nhật ký: %LOCALAPPDATA%\\DouyinLive.\n"
        "Đổi thư mục lưu trong Cài đặt. Cookie chỉ giữ trong phiên, không lưu xuống đĩa.\n"
        "Khi ngắt kết nối, các phần được ghi sang file riêng; không tự gộp.\n"
        "Đóng tab trình duyệt vẫn tiếp tục ghi. Dùng nút Thoát để dừng ứng dụng.\n"
        "Nếu giao diện không mở tự động: http://127.0.0.1:8766 (cổng có thể khác nếu bận).\n\n"
        "Yêu cầu: Windows 10/11 64-bit, Internet, trình duyệt; cookie Douyin khi phòng yêu cầu.\n"
        "Ứng dụng chưa ký mã số. Bản này đã kiểm tra cục bộ, chưa thử trên máy Windows khác.\n\n"
        "Mã nguồn để sửa/build lại nằm trong thư mục source.\n",
        encoding="utf-8-sig",
    )
    source = BUNDLE / "source"
    source.mkdir(exist_ok=True)
    for name in (
        "livestream.py",
        "livestream_gui.py",
        "runtime_paths.py",
        "packaged_entry.py",
        "DouyinLive.spec",
        "build_windows.py",
        "requirements.txt",
        "requirements-build.txt",
        "verify_windows_bundle.py",
        "README.md",
    ):
        shutil.copy2(ROOT / name, source / name)
    for directory in ("src", "livestream_ui", "tests"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".html"):
                target = source / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    licenses = BUNDLE / "licenses"
    licenses.mkdir(exist_ok=True)
    metadata = []
    for name in (
        "requests",
        "urllib3",
        "certifi",
        "charset-normalizer",
        "idna",
        "gmssl",
        "pycryptodomex",
        "Brotli",
        "pyinstaller",
    ):
        distribution = importlib.metadata.distribution(name)
        metadata.append(
            {
                "name": name,
                "version": distribution.version,
                "license": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License", ""),
                "homepage": distribution.metadata.get("Home-page", ""),
            }
        )
        for item in distribution.files or []:
            if any(
                "license" in part.lower() or part.lower().startswith("copying")
                for part in item.parts
            ):
                original = Path(distribution.locate_file(item))
                if original.is_file():
                    target = licenses / name / item
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
    (licenses / "libraries.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    license_cache = ROOT / ".tools/ffmpeg/COPYING.GPLv3"
    if not license_cache.exists():
        import requests

        response = requests.get(
            "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/COPYING.GPLv3",
            timeout=30,
        )
        response.raise_for_status()
        license_cache.parent.mkdir(parents=True, exist_ok=True)
        license_cache.write_bytes(response.content)
    shutil.copy2(license_cache, licenses / "FFmpeg-GPLv3.txt")
    version = subprocess.run(
        [str(ffmpeg), "-version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    (licenses / "THIRD_PARTY_NOTICES.txt").write_text(
        "FFmpeg executable: " + version + "\n"
        "Windows build provider: https://www.gyan.dev/ffmpeg/builds/\n"
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/n7.1\n"
        "FFmpeg license: FFmpeg-GPLv3.txt\n"
        "Source code for this application and its existing Douyin API is in ../source.\n"
        "Original project: https://github.com/datnndd/douyin-download\n"
        "Original downloader credit: https://github.com/jiji262/douyin-downloader\n"
        "Signing algorithm credits/licenses are preserved in source/src/common/abogus.py.\n"
        "Python dependencies: libraries.json and the accompanying license files.\n"
        "Python runtime: https://www.python.org/psf/license/\n",
        encoding="utf-8",
    )
    # Include the Python runtime's license when the distribution provides it.
    for filename in ("LICENSE.txt", "LICENSE"):
        candidate = Path(sys.base_prefix) / filename
        if candidate.is_file():
            shutil.copy2(candidate, licenses / "Python-LICENSE.txt")
            break
    archive = DIST / "DouyinLive-Windows-x64.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as output:
        for path in sorted(BUNDLE.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(DIST))
    print(
        f"Ready: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MB)", flush=True
    )


if __name__ == "__main__":
    build()
