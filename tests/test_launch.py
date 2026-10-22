"""Exercise the actual launcher, including missing dependencies in a subprocess."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_missing_dependency_keeps_traceback(tmp_path):
    launcher = tmp_path / "launch.py"
    shutil.copyfile(ROOT / "launch.py", launcher)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    # -S intentionally removes third-party dependencies, reproducing an
    # incomplete setup without changing the real development environment.
    result = subprocess.run([sys.executable, "-S", str(launcher)], env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    log = (tmp_path / "logs" / "texture-studio.log").read_text(encoding="utf-8")
    assert "ModuleNotFoundError" in log
    assert "Texture Studio failed to start" in result.stderr


def test_real_gui_launch_exits_cleanly(tmp_path):
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    code = """
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import launch
launch.__file__ = str(Path(sys.argv[1]) / 'launch.py')
app = QApplication([])
QTimer.singleShot(500, app.quit)
raise SystemExit(launch.launch())
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT,
                            env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "Texture Studio startup" in (tmp_path / "logs" / "texture-studio.log").read_text(encoding="utf-8")
