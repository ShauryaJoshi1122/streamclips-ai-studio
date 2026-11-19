#!/usr/bin/env python3
"""Launcher for StreamClips AI Studio Web Application."""

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
VENV = Path.home() / ".streamclips" / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")

if IS_WIN:
    winget_pkgs = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget_pkgs.exists():
        for p in winget_pkgs.glob("*FFmpeg*/**/ffmpeg.exe"):
            os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
            break


def in_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def main():
    if not in_venv():
        if not VENV_PY.exists():
            print("StreamClips environment is not ready yet.", file=sys.stderr)
            sys.exit(1)
        env = dict(os.environ)
        bin_dir = str(VENV_PY.parent)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))

    import uvicorn
    from web.server import app

    port = int(os.environ.get("PORT", 8000))
    url = f"http://localhost:{port}"

    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n=======================================================")
    print(f"🎬 StreamClips AI Studio Web Application Running!")
    print(f"👉 Opening: {url}")
    print(f"=======================================================\n")

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
