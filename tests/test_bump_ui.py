import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from texture_studio.bump import make_bump, bump_normal
from texture_studio.bump_ui import BumpDialog
from texture_studio.core import save_image


def wait_bump(app, dialog, errors):
    deadline = time.monotonic()+20
    quiet = 0
    while time.monotonic() < deadline:
        app.processEvents()
        busy = dialog.thread is not None or dialog.timer.isActive() or dialog.pending_preview or dialog.pending_export
        quiet = 0 if busy else quiet+1
        if quiet >= 3:
            break
        time.sleep(.01)
    assert quiet >= 3
    assert not errors


@pytest.fixture
def bump_editor(tmp_path):
    app = QApplication.instance() or QApplication([])
    y, x = np.mgrid[:640, :1152]
    source = np.stack((.5+.2*np.sin(x/30), .5+.1*np.cos(y/20), np.full(x.shape, .4)), axis=-1).astype("float32")
    path = tmp_path / "原始材質.jpg"
    save_image(source, path)
    dialog = BumpDialog(source, str(path))
    errors = []
    dialog.error = errors.append
    dialog.show()
    wait_bump(app, dialog, errors)
    yield app, dialog, path, errors
    wait_bump(app, dialog, errors)
    dialog.close()
    app.processEvents()


def test_bump_adjustments_save_separate_full_resolution_grayscale(bump_editor, tmp_path, monkeypatch):
    app, dialog, path, errors = bump_editor
    original_bytes = path.read_bytes()
    original = dialog.source.copy()
    assert dialog.result.shape[1] == 1024
    dialog.brightness.setValue(15)
    dialog.contrast.setValue(160)
    wait_bump(app, dialog, errors)
    target = tmp_path / "材質_BUMP.jpg"
    defaults = []
    def choose(parent, title, default, filters):
        defaults.append(default)
        return str(target), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    dialog.save_file()
    wait_bump(app, dialog, errors)
    assert defaults == ["原始材質_BUMP.jpg"]
    with Image.open(target) as image:
        assert image.mode == "L" and image.size == (2304, 1280)
        assert "icc_profile" not in image.info
    reference = tmp_path / "expected.jpg"
    save_image(make_bump(original, .15, 1.6), reference, color_space="linear", repeat=2)
    assert target.read_bytes() == reference.read_bytes()
    np.testing.assert_array_equal(dialog.source, original)
    assert path.read_bytes() == original_bytes


def test_normal_export_is_lossless_data_and_does_not_change_bump(bump_editor, tmp_path, monkeypatch):
    app, dialog, path, errors = bump_editor
    original = dialog.source.copy()
    dialog.contrast.setValue(150)
    dialog.brightness.setValue(-10)
    wait_bump(app, dialog, errors)
    grayscale = dialog.result.copy()
    dialog.normal_button.setChecked(True)
    dialog.strength.setValue(200)
    wait_bump(app, dialog, errors)
    assert dialog.result.shape[2] == 3
    target = tmp_path / "材質_NORMAL.png"
    defaults = []
    def choose(parent, title, default, filters):
        defaults.append(default)
        return str(target), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    dialog.save_file()
    wait_bump(app, dialog, errors)
    assert defaults == ["原始材質_NORMAL.png"]
    expected = bump_normal(make_bump(original, -.1, 1.5), 4)
    with Image.open(target) as image:
        assert image.mode == "RGB" and image.size == (2304, 1280)
        assert "icc_profile" not in image.info
        np.testing.assert_array_equal(np.asarray(image), np.tile(np.round(expected*255).astype("uint8"), (2, 2, 1)))
    dialog.normal_button.setChecked(False)
    wait_bump(app, dialog, errors)
    np.testing.assert_array_equal(dialog.result, grayscale)
    np.testing.assert_array_equal(dialog.source, original)


def test_bump_editor_refuses_to_replace_original_source(bump_editor, monkeypatch):
    app, dialog, path, errors = bump_editor
    before = path.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    dialog.save_file()
    assert errors == ["請另存新的 BUMP／法線檔案，不能覆蓋原始素材"]
    assert path.read_bytes() == before
    errors.clear()


def test_escape_during_bump_render_cancels_without_destroying_running_thread(bump_editor, monkeypatch):
    import threading
    import texture_studio.bump_ui as module
    app, dialog, path, errors = bump_editor
    entered, release = threading.Event(), threading.Event()
    original = module.make_bump
    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module, "make_bump", blocked)
    dialog.render()
    try:
        assert entered.wait(2)
        QTest.keyClick(dialog, Qt.Key_Escape)
        assert dialog.isVisible()
        assert dialog.thread is not None
    finally:
        release.set()
    wait_bump(app, dialog, errors)


def test_invert_switch_updates_bump_normals_and_full_resolution_file(bump_editor, tmp_path, monkeypatch):
    app, dialog, path, errors = bump_editor
    original = dialog.result.copy()
    dialog.invert_button.setChecked(True)
    wait_bump(app, dialog, errors)
    np.testing.assert_allclose(dialog.result, 1-original, atol=1e-7)
    target = tmp_path / "反轉_BUMP.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog.save_file()
    wait_bump(app, dialog, errors)
    expected = tmp_path / "反轉預期.jpg"
    save_image(1-make_bump(dialog.source), expected, color_space="linear", repeat=2)
    assert target.read_bytes() == expected.read_bytes()
    dialog.normal_button.setChecked(True)
    wait_bump(app, dialog, errors)
    inverted = dialog.result.copy()
    dialog.invert_button.setChecked(False)
    wait_bump(app, dialog, errors)
    np.testing.assert_allclose(inverted[..., :2], 1-dialog.result[..., :2], atol=1e-6)
    np.testing.assert_allclose(inverted[..., 2], dialog.result[..., 2], atol=1e-6)
    dialog.normal_button.setChecked(False)
    wait_bump(app, dialog, errors)
    np.testing.assert_array_equal(dialog.result, original)
