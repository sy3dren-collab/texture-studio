import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSpinBox, QDoubleSpinBox
from texture_studio.ui import Window
from texture_studio.core import crop_image, load_image, save_image


def wait_job(app, window, errors):
    deadline = time.monotonic()+20
    while window.thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert window.thread is None
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


def test_selected_pixels_drive_processing_and_project_reload(desktop, tmp_path):
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
    project = tmp_path / "選取區域專案.json"
    window.write_project(project)
    window.reset_crop()
    window.light.setValue(100)
    window.load_project(project)
    wait_job(app, window, errors)
    assert window.regions[str(path)] == region
    assert window.light.value() == 0
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
