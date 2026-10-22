import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPointF, QObject, Signal, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSpinBox, QDoubleSpinBox, QPushButton, QColorDialog, QFileDialog
from PySide6.QtGui import QColor, QImage
from texture_studio.ui import Window
from texture_studio.core import crop_image, load_image, save_image


def wait_job(app, window, errors):
    deadline = time.monotonic()+20
    while window.thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert window.thread is None
    assert not errors


def wait_render(app, window, errors):
    deadline = time.monotonic()+20
    quiet = 0
    while time.monotonic() < deadline:
        app.processEvents()
        busy = window.thread is not None or window.preview_timer.isActive() or window._pending_preview or window._pending_export
        quiet = 0 if busy else quiet+1
        if quiet >= 3:
            break
        time.sleep(.01)
    assert quiet >= 3
    assert not errors


@pytest.fixture
def desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window()
    errors = []
    window.error = errors.append
    source = np.full((96, 160, 3), [.4, .5, .6], dtype="float32")
    source[:16] = source[-16:] = source[:, :16] = source[:, -16:] = [1, 0, 0]
    path = tmp_path / "框選原圖.png"
    save_image(source, path)
    window.show()
    window.add_paths([str(path)])
    wait_job(app, window, errors)
    yield app, window, path, errors
    if window.thread is not None:
        window.cancel()
        wait_job(app, window, errors)
    window.close()
    app.processEvents()


def drag(preview, start, end):
    viewport = preview.viewport()
    QTest.mousePress(viewport, Qt.LeftButton, pos=preview.mapFromScene(start))
    QTest.mouseMove(viewport, preview.mapFromScene(end), delay=10)
    QTest.mouseRelease(viewport, Qt.LeftButton, pos=preview.mapFromScene(end))


def test_draw_move_resize_and_reset_source_selection(desktop):
    app, window, path, errors = desktop
    window.crop_button.setChecked(True)
    app.processEvents()
    preview = window.preview
    w, h = preview.image_bounds.width(), preview.image_bounds.height()
    drag(preview, QPointF(w*.2, h*.25), QPointF(w*.75, h*.7))
    first = np.array(window.regions[str(path)])
    np.testing.assert_allclose(first, [.2, .25, .75, .7], atol=.01)
    before = preview._crop_rect
    drag(preview, before.center(), before.center()+QPointF(w*.08, h*.05))
    moved = np.array(window.regions[str(path)])
    np.testing.assert_allclose(moved[2:]-moved[:2], first[2:]-first[:2], atol=1e-6)
    assert moved[0] > first[0]
    rect = preview._crop_rect
    drag(preview, rect.bottomRight(), rect.bottomRight()+QPointF(w*.05, h*.05))
    enlarged = np.array(window.regions[str(path)])
    assert enlarged[2]-enlarged[0] > moved[2]-moved[0]
    assert enlarged[3]-enlarged[1] > moved[3]-moved[1]
    window.reset_crop()
    assert str(path) not in window.regions
    assert preview._crop_rect is None


def test_selected_pixels_drive_processing_without_modifying_source(desktop):
    app, window, path, errors = desktop
    source_bytes = path.read_bytes()
    region = [.2, .25, .8, .75]
    window.set_crop(region)
    window.light.setValue(0)
    window.process()
    wait_job(app, window, errors)
    first = window.result.copy()
    assert first.shape == (48, 96, 3)
    np.testing.assert_allclose(first, crop_image(load_image(path), region), atol=1e-6)
    window.process()
    wait_job(app, window, errors)
    np.testing.assert_array_equal(first, window.result)
    assert path.read_bytes() == source_bytes


def test_modes_show_only_primary_numeric_controls(desktop):
    app, window, path, errors = desktop
    for mode, expected in [(0, 0), (1, 1), (2, 3)]:
        window.mode.setCurrentIndex(mode)
        app.processEvents()
        controls = [widget for widget in window.findChildren(QSpinBox)+window.findChildren(QDoubleSpinBox) if widget.isVisible()]
        assert len(controls) == expected
    assert window.pattern.currentText() == "二分之一錯縫"


def test_output_size_preserves_selected_aspect(desktop):
    app, window, path, errors = desktop
    window.set_crop([.2, .25, .8, .75])
    window.resolution.setCurrentIndex(window.resolution.findData(1024))
    window.process()
    wait_job(app, window, errors)
    assert window.result.shape == (512, 1024, 3)


def test_quick_board_pipeline_and_reshuffle(desktop):
    app, window, path, errors = desktop
    window.set_crop([.2, .25, .8, .75])
    window.mode.setCurrentIndex(2)
    window.pattern.setCurrentIndex(window.pattern.findData("random"))
    window.process()
    wait_job(app, window, errors)
    first = window.result.copy()
    assert first.shape == (512, 1024, 3)
    assert window.processed_settings["regions"][str(path)] == [.2, .25, .8, .75]
    seed = window.processed_settings["settings"]["seed"]
    window.reshuffle()
    wait_job(app, window, errors)
    assert window.processed_settings["settings"]["seed"] == seed+1
    assert not np.array_equal(first, window.result)


def test_each_source_retains_its_own_region(desktop, tmp_path):
    app, window, path, errors = desktop
    first = [.2, .25, .8, .75]
    second_path = tmp_path / "第二張.png"
    save_image(np.full((120, 80, 3), .3, "float32"), second_path)
    window.set_crop(first)
    window.add_paths([str(second_path)])
    window.assets.setCurrentRow(1)
    wait_job(app, window, errors)
    window.set_crop([.1, .1, .9, .9])
    window.assets.setCurrentRow(0)
    wait_job(app, window, errors)
    window.crop_button.setChecked(True)
    assert window.regions[str(path)] == first
    assert window.preview.source_shape == (96, 160)
    window.process()
    wait_job(app, window, errors)
    assert window.result.shape == (48, 96, 3)


def test_tiny_selection_is_ignored_and_drag_stays_inside_source(desktop):
    app, window, path, errors = desktop
    window.crop_button.setChecked(True)
    app.processEvents()
    preview = window.preview
    drag(preview, QPointF(20, 20), QPointF(20.1, 20.1))
    assert str(path) not in window.regions
    drag(preview, QPointF(20, 20), QPointF(300, 200))
    region = window.regions[str(path)]
    assert 0 <= region[0] < region[2] <= 1
    assert 0 <= region[1] < region[3] <= 1


def test_removing_source_loads_next_image_and_its_region(desktop, tmp_path):
    app, window, path, errors = desktop
    second_path = tmp_path / "下一張.png"
    save_image(np.full((120, 80, 3), .3, "float32"), second_path)
    window.add_paths([str(second_path)])
    window.regions[str(second_path)] = [.1, .2, .9, .8]
    window.remove_asset()
    wait_job(app, window, errors)
    assert window.current_path() == str(second_path)
    assert window.original.shape == (120, 80, 3)
    window.process()
    wait_job(app, window, errors)
    assert window.result.shape == (72, 64, 3)
    window.remove_asset()
    assert window.original is None
    assert window.result is None


def test_live_sliders_and_color_dialog_edit_real_pixels(desktop, monkeypatch):
    app, window, path, errors = desktop
    original = path.read_bytes()
    window.set_crop([.2, .25, .8, .75])
    window.light.setValue(0)
    window.process()
    wait_job(app, window, errors)
    cached = next(iter(window._source_cache.values())).copy()
    window.material_saturation.setValue(0)
    wait_render(app, window, errors)
    np.testing.assert_allclose(window.result[..., 0], window.result[..., 2], atol=1e-6)
    gray = window.result.copy()
    window.material_brightness.setValue(-50)
    wait_render(app, window, errors)
    np.testing.assert_allclose(window.result, gray*.5, atol=1e-6)
    window.material_saturation.setValue(100)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor.fromRgbF(.1, .6, .2))
    window.choose_color()
    wait_render(app, window, errors)
    np.testing.assert_allclose(window.result.mean(axis=(0, 1)), [.05, .3, .1], atol=2e-5)
    window.clear_color()
    wait_render(app, window, errors)
    np.testing.assert_array_equal(next(iter(window._source_cache.values())), cached)
    assert path.read_bytes() == original


def test_jpeg_export_renders_full_resolution_after_small_preview(desktop, tmp_path, monkeypatch):
    from PIL import Image
    app, window, path, errors = desktop
    window.set_crop([.2, .25, .8, .75])
    window.light.setValue(0)
    window.resolution.setCurrentIndex(window.resolution.findData(2048))
    window.material_scale.setValue(150)
    window.material_brightness.setValue(-50)
    wait_render(app, window, errors)
    assert window.result.shape == (512, 1024, 3)
    target = tmp_path / "成品.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export()
    wait_render(app, window, errors)
    assert not target.exists()
    with Image.open(target.with_suffix(".jpg")) as image:
        assert image.format == "JPEG"
        assert image.size == (2048, 1024)
        np.testing.assert_allclose(np.asarray(image).mean(axis=(0, 1))/255, [.2, .25, .3], atol=.01)


def test_captured_image_is_selected_and_used_as_a_source(desktop):
    app, window, path, errors = desktop
    pixels = np.full((80, 120, 3), [80, 120, 160], dtype="uint8")
    shot = QImage(pixels.data, 120, 80, pixels.strides[0], QImage.Format_RGB888).copy()
    window.import_capture(shot)
    wait_render(app, window, errors)
    assert len(window.paths) == 2
    assert window.assets.currentRow() == 1
    assert "螢幕截圖" in window.assets.currentItem().text()
    assert window.original.shape == (80, 120, 3)
    window.set_crop([.25, .25, .75, .75])
    window.process()
    wait_render(app, window, errors)
    assert window.result.shape == (40, 60, 3)


def test_removed_actions_are_absent_from_desktop(desktop):
    app, window, path, errors = desktop
    labels = {button.text() for button in window.findChildren(QPushButton)}
    assert "截圖匯入素材" in labels
    assert "輸出 JPEG 圖片" in labels
    assert not labels.intersection({"輸出全部", "儲存專案", "開啟專案", "儲存專案 JSON", "開啟專案 JSON"})


def test_undo_restores_edit_controls_and_export_matches_restored_result(desktop, tmp_path, monkeypatch):
    from PIL import Image
    app, window, path, errors = desktop
    window.set_crop([.2, .25, .8, .75])
    window.light.setValue(0)
    window.process()
    wait_render(app, window, errors)
    before = window.result.copy()
    window.material_brightness.setValue(-50)
    wait_render(app, window, errors)
    assert window.result.mean() < before.mean()*.6
    window.undo()
    assert window.material_brightness.value() == 0
    np.testing.assert_array_equal(window.result, before)
    target = tmp_path / "復原後.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export()
    wait_render(app, window, errors)
    with Image.open(target) as image:
        np.testing.assert_allclose(np.asarray(image).mean(axis=(0, 1))/255, before.mean(axis=(0, 1)), atol=.01)


def test_export_waits_for_active_preview_and_uses_latest_controls(desktop, tmp_path, monkeypatch):
    from PIL import Image
    app, window, path, errors = desktop
    window.set_crop([.2, .25, .8, .75])
    window.light.setValue(0)
    window.process(preview=True)
    window.material_brightness.setValue(-50)
    target = tmp_path / "最新調整.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export()
    assert window._pending_export is not None
    wait_render(app, window, errors)
    with Image.open(target) as image:
        np.testing.assert_allclose(np.asarray(image).mean(axis=(0, 1))/255, [.2, .25, .3], atol=.01)
    assert window.material_brightness.value() == -50


def test_screen_capture_cancel_restores_window_without_new_material(desktop, monkeypatch):
    import texture_studio.ui as ui
    app, window, path, errors = desktop
    started = []
    class CancelCapture(QObject):
        selected = Signal(object)
        cancelled = Signal()
        def start(self):
            started.append(not window.isVisible())
            self.cancelled.emit()
        def close_overlays(self):
            pass
    monkeypatch.setattr(ui, "ScreenCapture", CancelCapture)
    window.start_capture()
    assert not window.isVisible()
    deadline = time.monotonic()+3
    while not started and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert started == [True]
    assert window.isVisible()
    assert window.paths == [str(path)]
    assert window._capture_session is None
    assert not errors


def test_background_render_delivers_widget_updates_on_ui_thread(desktop, monkeypatch):
    app, window, path, errors = desktop
    observed = []
    original = window.processed
    def observe(outputs):
        observed.append(QThread.currentThread() == app.thread())
        original(outputs)
    monkeypatch.setattr(window, "processed", observe)
    window.process()
    wait_render(app, window, errors)
    window.material_brightness.setValue(-20)
    wait_render(app, window, errors)
    assert observed == [True, True]


def test_board_rotation_changes_grain_without_rotating_board_joints(desktop, tmp_path):
    app, window, path, errors = desktop
    y, x = np.mgrid[:128, :512]
    grain = np.repeat((.45+.07*np.sin(2*np.pi*x/32))[..., None], 3, axis=2).astype("float32")
    board = tmp_path / "直向紋理.png"
    save_image(grain, board)
    window.add_paths([str(board)])
    window.assets.setCurrentRow(1)
    wait_render(app, window, errors)
    window.assets.setCurrentRow(0)
    wait_render(app, window, errors)
    window.remove_asset()
    wait_render(app, window, errors)
    window.light.setValue(0)
    window.mode.setCurrentIndex(2)
    window.pattern.setCurrentIndex(window.pattern.findData("straight"))
    window.gap.setValue(20)
    window.process()
    wait_render(app, window, errors)
    before = window.result.copy()
    window.material_angle.setValue(35)
    window.material_scale.setValue(150)
    wait_render(app, window, errors)
    after = window.result
    np.testing.assert_array_equal((before < .09).all(axis=2), (after < .09).all(axis=2))
    old_grain = before[12:30, 30:220, 0]
    new_grain = after[12:30, 30:220, 0]
    assert np.abs(np.diff(old_grain, axis=0)).mean() < .001
    assert np.abs(np.diff(new_grain, axis=0)).mean() > .003
