"""Interactive four-corner selection for perspective correction."""
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QDialog, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout)

from .perspective import perspective_geometry


class PerspectiveView(QGraphicsView):
    selectionChanged = Signal()

    def __init__(self, image, region=None):
        super().__init__()
        h, w = image.shape[:2]
        ratio = min(1, 1600/max(h, w))
        small = cv2.resize(image, (max(4, round(w*ratio)), max(4, round(h*ratio))),
                           interpolation=cv2.INTER_AREA)
        pixels = np.ascontiguousarray(np.clip(small, 0, 1)*255, dtype=np.uint8)
        qimage = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
        scene = QGraphicsScene(self)
        scene.addPixmap(QPixmap.fromImage(qimage))
        self.setScene(scene)
        self.bounds = QRectF(0, 0, pixels.shape[1]-1, pixels.shape[0]-1)
        margin = max(8, max(self.bounds.width(), self.bounds.height())*.04)
        scene.setSceneRect(self.bounds.adjusted(-margin, -margin, margin, margin))
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.viewport().setCursor(Qt.CrossCursor)
        self._region = region
        self._drag = None
        self._pan_start = None
        self.valid = True
        self.reset_selection()

    def reset_selection(self):
        left, top, right, bottom = self._region or (.08, .08, .92, .92)
        self.points = [QPointF(left*self.bounds.width(), top*self.bounds.height()),
                       QPointF(right*self.bounds.width(), top*self.bounds.height()),
                       QPointF(right*self.bounds.width(), bottom*self.bounds.height()),
                       QPointF(left*self.bounds.width(), bottom*self.bounds.height())]
        self.viewport().update()
        self.selectionChanged.emit()

    def normalized_points(self):
        return [(p.x()/self.bounds.width(), p.y()/self.bounds.height()) for p in self.points]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def _point(self, position):
        point = self.mapToScene(position)
        return QPointF(np.clip(point.x(), 0, self.bounds.width()),
                       np.clip(point.y(), 0, self.bounds.height()))

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if .03 < self.transform().m11()*factor < 50:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        position = event.position().toPoint()
        distances = [(self.mapFromScene(p)-position).manhattanLength() for p in self.points]
        self._previous_points = [QPointF(p) for p in self.points]
        if min(distances) <= 18:
            self._drag = int(np.argmin(distances))
        else:
            self._drag = "rectangle"
            self._anchor = self._point(position)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position().toPoint()-self._pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        if self._drag is None:
            return super().mouseMoveEvent(event)
        point = self._point(event.position().toPoint())
        if self._drag == "rectangle":
            rect = QRectF(self._anchor, point).normalized()
            self.points = [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
        else:
            self.points[self._drag] = point
        self.selectionChanged.emit()
        self.viewport().update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            event.accept()
            return
        if self._drag is None or event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        self.mouseMoveEvent(event)
        if self._drag == "rectangle":
            rect = QRectF(self.points[0], self.points[2]).normalized()
            if rect.width()*self.transform().m11() < 5 or rect.height()*self.transform().m11() < 5:
                self.points = self._previous_points
                self.selectionChanged.emit()
                self.viewport().update()
        self._drag = None
        event.accept()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        polygon = QPolygonF(self.points)
        shaded = QPainterPath()
        shaded.addRect(self.bounds)
        shaded.addPolygon(polygon)
        shaded.setFillRule(Qt.OddEvenFill)
        painter.fillPath(shaded, QColor(0, 0, 0, 125))
        color = QColor("#ffca4f" if self.valid else "#ff6b6b")
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolygon(polygon)
        radius = 7/max(self.transform().m11(), .01)
        painter.setBrush(color)
        for point in self.points:
            painter.drawEllipse(point, radius, radius)


class PerspectiveDialog(QDialog):
    def __init__(self, image, region=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("透視矯正")
        self.resize(900, 700)
        self.image_shape = image.shape
        layout = QVBoxLayout(self)
        hint = QLabel("拖曳四個圓點對準圖案的四個角；也可先拖曳框選，再調整四角。滾輪縮放，中鍵拖曳平移。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.view = PerspectiveView(image, region)
        self.view.selectionChanged.connect(self.update_selection)
        layout.addWidget(self.view, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        reset = QPushButton("重設選取")
        reset.clicked.connect(self.view.reset_selection)
        buttons.addWidget(reset)
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.apply_button = QPushButton("套用矯正")
        self.apply_button.clicked.connect(self.accept)
        self.apply_button.setDefault(True)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.update_selection()

    def update_selection(self):
        try:
            _, (width, height) = perspective_geometry(self.image_shape, self.view.normalized_points())
        except ValueError as error:
            self.view.valid = False
            self.status.setText(str(error))
        else:
            self.view.valid = True
            self.status.setText(f"矯正後約 {width} × {height} 像素；四角不交叉，對準圖案邊緣。")
        self.apply_button.setEnabled(self.view.valid)
        self.view.viewport().update()
