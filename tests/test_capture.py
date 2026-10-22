import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QSize
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication
from texture_studio.capture import CaptureOverlay, selected_pixels


def screenshot():
    y, x = np.mgrid[:320, :400]
    pixels = np.stack((x%256, y%256, (x+y)%256), axis=2).astype("uint8")
    return QImage(pixels.data, 400, 320, pixels.strides[0], QImage.Format_RGB888).copy()


def test_dpi_scaled_selection_uses_native_pixels():
    source = screenshot()
    result = selected_pixels(source, QRectF(40, 30, 100, 90), QSize(200, 160))
    assert result.size() == QSize(200, 180)
    assert result.pixelColor(0, 0) == source.pixelColor(80, 60)
    assert result.pixelColor(199, 179) == source.pixelColor(279, 239)
    assert result.devicePixelRatio() == 1
    with pytest.raises(ValueError):
        selected_pixels(source, QRectF(20, 20, 1, 1), QSize(200, 160))


def test_overlay_mouse_selection_and_escape():
    app = QApplication.instance() or QApplication([])
    overlay = CaptureOverlay(screenshot(), QRect(0, 0, 200, 160))
    selected, cancelled = QSignalSpy(overlay.selected), QSignalSpy(overlay.cancelled)
    overlay.show()
    app.processEvents()
    QTest.mousePress(overlay, Qt.LeftButton, pos=QPoint(40, 30))
    QTest.mouseMove(overlay, QPoint(140, 120), delay=10)
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(140, 120))
    assert selected.count() == 1
    assert selected.at(0)[0].size() == QSize(200, 180)
    QTest.keyClick(overlay, Qt.Key_Escape)
    assert cancelled.count() == 1
    overlay.hide()
    overlay.deleteLater()
