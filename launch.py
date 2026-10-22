"""Desktop bootstrap: retain import failures as well as GUI startup errors."""
import logging
import os
from pathlib import Path
import platform
import sys
import tempfile


def configure_logging():
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "TextureStudio"
    else:
        base = Path(__file__).resolve().parent
    directory = base / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(tempfile.gettempdir()) / "TextureStudio-logs"
        directory.mkdir(parents=True, exist_ok=True)
    path = directory / "texture-studio.log"
    logger = logging.getLogger("texture_studio.launch")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handlers = [logging.FileHandler(path, encoding="utf-8", mode="w")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger, path


def launch():
    logger, path = configure_logging()
    logger.info("Texture Studio startup: Python %s; %s; %s-bit", platform.python_version(), platform.system(), 64 if sys.maxsize > 2**32 else 32)
    try:
        from texture_studio.ui import main
        return main()
    except Exception:
        logger.exception("Texture Studio failed to start")
        if sys.stderr is None and sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"Texture Studio 無法啟動。\n錯誤紀錄：{path}", "Texture Studio", 0x10)
        return 1

if __name__ == "__main__":
    raise SystemExit(launch())
