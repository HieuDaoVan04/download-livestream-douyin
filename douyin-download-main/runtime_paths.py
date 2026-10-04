"""Separate bundled resources from user-owned settings and recordings."""

from pathlib import Path
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
_data_override = os.environ.get("DOUYIN_LIVE_DATA_DIR")
if _data_override:
    DATA_ROOT = Path(_data_override).expanduser().resolve()
elif FROZEN:
    DATA_ROOT = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        / "DouyinLive"
    )
else:
    DATA_ROOT = ROOT

if _data_override:
    DEFAULT_OUTPUT = DATA_ROOT / "Videos"
elif FROZEN:
    DEFAULT_OUTPUT = Path.home() / "Videos/DouyinLive"
else:
    DEFAULT_OUTPUT = ROOT / "Downloaded/live"
