"""Run the real windowless Windows entry when a Windows runner is available."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows Script Host and pythonw.exe")
def test_windowless_entry_handles_unicode_paths_and_creates_no_console(tmp_path):
    root = tmp_path / "素材工作室 with spaces"
    root.mkdir()
    source = Path(__file__).resolve().parents[1] / "TextureStudio.vbs"
    shutil.copyfile(source, root / source.name)
    (root / "texture_studio").mkdir()
    (root / "texture_studio" / "ui.py").write_text("", encoding="utf-8")
    (root / "launch.py").write_text('''import ctypes, json, os
from pathlib import Path
Path("boot.json").write_text(json.dumps({"cwd": os.getcwd(), "console": ctypes.windll.kernel32.GetConsoleWindow()}), encoding="utf-8")
''', encoding="utf-8")
    environment = os.environ.copy()
    environment["TEXTURE_STUDIO_VENV"] = str(Path(sys.executable).parent.parent)
    host = Path(os.environ["SystemRoot"]) / "System32" / "wscript.exe"
    result = subprocess.run([str(host), "//B", "//NoLogo", str(root / source.name)], env=environment, timeout=10)
    assert result.returncode == 0
    end = time.monotonic()+10
    while not (root / "boot.json").exists() and time.monotonic() < end:
        time.sleep(.05)
    state = json.loads((root / "boot.json").read_text(encoding="utf-8"))
    assert Path(state["cwd"]) == root
    assert state["console"] == 0
