"""Native Qt screen-region capture; no network or external capture utility."""
from PySide6.QtCore import QObject, Signal, Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QDialog


def selected_pixels(image, selection, logical_size):
    """Convert screen-local logical coordinates to native screenshot pixels."""
    rect = QRectF(selection).normalized().intersected(QRectF(0, 0, logical_size.width(), logical_size.height()))
    sx, sy = image.width()/logical_size.width(), image.height()/logical_size.height()
    x0, y0 = round(rect.left()*sx), round(rect.top()*sy)
    x1, y1 = round(rect.right()*sx), round(rect.bottom()*sy)
    if min(x1-x0, y1-y0) < 4:
        raise ValueError("截圖範圍至少需要 4×4 像素")
    output = image.copy(QRect(x0, y0, x1-x0, y1-y0))
    output.setDevicePixelRatio(1)
    return output


class CaptureOverlay(QDialog):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, image, geometry):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.image = image
        self.selection = None
        self.anchor = None
        self.setGeometry(geometry)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(self.rect(), self.image)
        rect = self.selection or QRectF()
        shade = QColor(0, 0, 0, 115)
        for area in (QRectF(0, 0, self.width(), rect.top()),
                     QRectF(0, rect.bottom(), self.width(), self.height()-rect.bottom()),
                     QRectF(0, rect.top(), rect.left(), rect.height()),
                     QRectF(rect.right(), rect.top(), self.width()-rect.right(), rect.height())):
            painter.fillRect(area, shade)
        if self.selection:
            painter.setPen(QPen(QColor("#ffca4f"), 2))
            painter.drawRect(self.selection)
        painter.setPen(Qt.white)
        painter.fillRect(QRect(12, 12, 390, 38), QColor(0, 0, 0, 180))
        painter.drawText(QRect(22, 12, 370, 38), Qt.AlignVCenter, "拖曳框選截圖範圍 · Esc 或右鍵取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.LeftButton:
            self.anchor = event.position()
            self.selection = QRectF(self.anchor, self.anchor)
            self.update()

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.selection = QRectF(self.anchor, event.position()).normalized().intersected(QRectF(self.rect()))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.anchor is None:
            return
        self.mouseMoveEvent(event)
        self.anchor = None
        try:
            image = selected_pixels(self.image, self.selection, self.size())
        except ValueError:
            self.selection = None
            self.update()
            return
        self.selected.emit(image)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def reject(self):
        self.cancelled.emit()


class ScreenCapture(QObject):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays = []

    def start(self):
        screens = QApplication.screens()
        # Grab every screen before displaying any overlay. Each screen retains
        # its own pixel density and coordinates, including negative origins.
        shots = [(screen.grabWindow(0).toImage(), screen.geometry()) for screen in screens]
        if not shots or any(image.isNull() for image, _ in shots):
            raise RuntimeError("無法擷取螢幕；請確認系統允許螢幕截圖")
        for image, geometry in shots:
            overlay = CaptureOverlay(image, geometry)
            overlay.selected.connect(self.finish)
            overlay.cancelled.connect(self.cancel)
            self.overlays.append(overlay)
        for overlay in self.overlays:
            overlay.show()
            overlay.raise_()
        self.overlays[-1].activateWindow()

    def close_overlays(self):
        for overlay in self.overlays:
            overlay.hide()
            overlay.deleteLater()
        self.overlays.clear()

    def finish(self, image):
        self.close_overlays()
        self.selected.emit(image)

    def cancel(self):
        self.close_overlays()
        self.cancelled.emit()
