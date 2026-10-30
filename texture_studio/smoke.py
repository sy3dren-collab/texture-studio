"""Small end-to-end check used to validate the packaged desktop executable."""
import ctypes
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QTimer
from PySide6.QtWidgets import QApplication
from . import __version__
from .core import save_image
from .perspective import rectify_perspective
from .perspective_ui import PerspectiveDialog
from .ui import Window


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window()
    errors = []
    window.error = errors.append
    window.show()

    def wait(owner):
        deadline = time.monotonic()+30
        quiet = 0
        while time.monotonic() < deadline:
            app.processEvents()
            if owner is window:
                busy = owner.thread is not None or owner.preview_timer.isActive() or owner._pending_preview or owner._pending_export
            else:
                busy = owner.thread is not None or owner.timer.isActive() or owner.pending_preview or owner.pending_export
            quiet = 0 if busy else quiet+1
            if quiet >= 3:
                if errors:
                    raise RuntimeError("; ".join(errors))
                return
            time.sleep(.01)
        raise TimeoutError("Packaged GUI operation did not finish")

    y, x = np.mgrid[:64, :96]
    image = np.stack((.4+.1*np.sin(x/5), .5+.1*np.cos(y/5), np.full(x.shape, .3)), axis=-1).astype("float32")
    source = output / "素材.png"
    save_image(image, source)
    window.add_paths([str(source)])
    wait(window)
    before = window.original.copy()
    corners = [(.1, .1), (.9, .05), (.95, .9), (.05, .95)]

    def select_perspective():
        dialog = None
        try:
            dialog = window.findChild(PerspectiveDialog)
            view = dialog.view
            view.points = [QPointF(x*view.bounds.width(), y*view.bounds.height()) for x, y in corners]
            view.selectionChanged.emit()
            if not dialog.apply_button.isEnabled():
                raise RuntimeError("Perspective selection was rejected")
            dialog.apply_button.click()
        except Exception as error:
            errors.append(str(error))
            if dialog is not None:
                dialog.reject()

    QTimer.singleShot(0, select_perspective)
    window.open_perspective()
    wait(window)
    expected = rectify_perspective(before, corners)
    if window.original.shape != expected.shape or not np.allclose(window.original, expected, atol=1e-6):
        raise RuntimeError("Perspective correction did not update the material")
    window.reset_original()
    baseline = window.original.copy()
    window.material_brightness.setValue(-50)
    window.primary_action()
    wait(window)
    if not np.allclose(window.original, baseline*.5, atol=1e-6):
        raise RuntimeError("Cumulative edit did not preserve pixels")
    window.mode.setCurrentIndex(1)
    window.grid_columns.setValue(3)
    window.grid_rows.setValue(1)
    window.primary_action()
    wait(window)
    if window.original.shape != (64, 288, 3):
        raise RuntimeError("Native layout resolution changed")
    window.dodge_button.setChecked(True)
    wait(window)
    window.begin_clone(QPointF(.5, .5))
    window.finish_clone()
    window.dodge_button.setChecked(False)
    window.repeat.setCurrentText("2")
    window.process(export_request={"path": str(output / "preview.jpg"), "snapshot": window.snapshot()})
    wait(window)
    window.mode.setCurrentIndex(3)
    wait(window)
    dialog = window.bump_windows[0]
    dialog.error = errors.append
    dialog.invert_button.setChecked(True)
    wait(dialog)
    dialog.render(export={"path": output / "BUMP.jpg", "settings": dialog.settings()})
    wait(dialog)
    dialog.normal_button.setChecked(True)
    dialog.render(export={"path": output / "NORMAL.png", "settings": dialog.settings()})
    wait(dialog)
    sizes = {}
    for name, mode in (("preview.jpg", "RGB"), ("BUMP.jpg", "L"), ("NORMAL.png", "RGB")):
        with Image.open(output / name) as check:
            check.load()
            if check.size != (576, 128) or check.mode != mode:
                raise RuntimeError(f"Invalid packaged image output: {name}")
            sizes[name] = list(check.size)
    dialog.close()
    app.processEvents()
    window.close()
    app.processEvents()
    runtime = sys.platform
    if sys.platform == "win32":
        try:
            ctypes.windll.ntdll.wine_get_version
            runtime = "wine"
        except AttributeError:
            runtime = "native_windows"
    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "runtime": runtime,
              "platform": sys.platform, "qt_platform": app.platformName(),
              "console_window": ctypes.windll.kernel32.GetConsoleWindow() if sys.platform == "win32" else None,
              "checks": ["gui", "perspective", "cumulative_edit", "native_layout", "brush", "jpeg", "bump_inversion", "normal"],
              "images": sizes}
    (output / "smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0
