# PyInstaller folder build. FFmpeg is copied alongside the exe by build_windows.py.
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / "packaged_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "livestream_ui/index.html"), "livestream_ui")],
    hiddenimports=["src.douyin.douyinapi", "gmssl.sm3", "gmssl.func", "brotli"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "black", "imageio_ffmpeg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DouyinLive",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DouyinLive")
