"""Shared Qt preview, centered controls and cancellable worker."""
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QColor, QPen, QBrush, QTransform
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QGraphicsView,
                              QGraphicsScene, QSlider)
from .core import repeat_preview


class Preview(QGraphicsView):
    cropChanged = Signal(object)
    clonePicked = Signal(object)
    cloneStarted = Signal(object)
    cloneMoved = Signal(object)
    cloneEnded = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.crop_mode = False
        self._crop_rect = None
        self._drag = None
        self.image_bounds = QRectF()
        self.source_shape = (0, 0)
        self.fill_mode = False
        self._tile_brush = None
        self._fill_count = None
        self._fill_period = QPointF(256, 256)
        self._view_period = QPointF(1, 1)
        self.clone_mode = self.clone_suspended = self.pick_clone_source = False
        self.brush_kind = "clone"
        self.clone_diameter = 64
        self.clone_reference = self._brush_hover = None
        self._cloning = False
        self._pan_start = None
        self.setMouseTracking(True)

    def set_clone_mode(self, enabled):
        self.clone_mode = enabled
        self._cloning = False
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.viewport().update()

    def set_crop_mode(self, enabled):
        self.crop_mode = enabled
        self._drag = None
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.viewport().update()

    def clear_image(self):
        self.fill_mode = False
        self._tile_brush = None
        self._crop_rect = None
        self.image_bounds = QRectF()
        self.source_shape = (0, 0)
        self.scene().clear()
        self.viewport().update()

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if .03 < self.transform().m11() * factor < 50:
            self.scale(factor, factor)

    def show_image(self, image, count, region=None, fill=False, preserve_view=False):
        # Limit interactive preview memory, retain full resolution result for export.
        import cv2
        h, w = image.shape[:2]
        self.source_shape = (h, w)
        was_fill = self.fill_mode
        self.fill_mode = bool(fill and not self.crop_mode)
        if self.crop_mode:
            count = 1
        if self.fill_mode:
            ratio = min(1, 1600/max(h, w))
            small = cv2.resize(image, (max(1, round(w*ratio)), max(1, round(h*ratio))))
            pixels = np.ascontiguousarray(np.clip(small, 0, 1)*255, dtype="uint8")
            qimage = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qimage)
            unit = 256/max(pixmap.width(), pixmap.height())
            period = QPointF(pixmap.width()*unit, pixmap.height()*unit)
            refit = not was_fill or self._fill_count != count or abs(period.x()/period.y()-self._fill_period.x()/self._fill_period.y()) > .01
            self._tile_brush = QBrush(pixmap)
            self._tile_brush.setTransform(QTransform.fromScale(unit, unit))
            self._fill_period, self._fill_count = period, count
            self._view_period = period
            self.scene().clear()
            self.scene().setSceneRect(-1e7, -1e7, 2e7, 2e7)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._crop_rect = None
            if refit:
                self.resetTransform()
                factor = min(max(1, self.viewport().width()-4)/(period.x()*count),
                             max(1, self.viewport().height()-4)/(period.y()*count))
                self.scale(factor, factor)
                self.centerOn(period.x()*count/2, period.y()*count/2)
            self.viewport().update()
            return
        self._tile_brush = None
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        ratio = min(1, 1600 / (max(h, w) * count))
        small = cv2.resize(image, (max(1, round(w * ratio)), max(1, round(h * ratio))))
        self._view_period = QPointF(small.shape[1], small.shape[0])
        pixels = (np.clip(repeat_preview(small, count), 0, 1) * 255).astype("uint8")
        qimage = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        self.scene().clear()
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(pixmap.rect())
        self.image_bounds = QRectF(0, 0, pixels.shape[1], pixels.shape[0])
        self._crop_rect = (QRectF(region[0]*small.shape[1], region[1]*small.shape[0],
                                (region[2]-region[0])*small.shape[1], (region[3]-region[1])*small.shape[0])
                           if region is not None and self.crop_mode else None)
        if not preserve_view:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def drawBackground(self, painter, rect):
        if self.fill_mode and self._tile_brush is not None:
            painter.fillRect(rect, self._tile_brush)
        else:
            painter.fillRect(rect, self.palette().base())

    def _recenter_fill(self):
        if self.fill_mode:
            center = self.mapToScene(self.viewport().rect().center())
            # Moving by whole periods leaves the view unchanged and prevents
            # repeated drags from ever approaching the scene's scroll limits.
            self.centerOn(center.x()%self._fill_period.x(), center.y()%self._fill_period.y())

    def _bounded_point(self, position):
        point = self.mapToScene(position)
        return QPointF(np.clip(point.x(), 0, self.image_bounds.width()),
                       np.clip(point.y(), 0, self.image_bounds.height()))

    def mousePressEvent(self, event):
        if self.clone_mode and not self.clone_suspended:
            if event.button() == Qt.MiddleButton:
                self._pan_start = event.position().toPoint()
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                point = self._clone_point(event.position().toPoint())
                if point is not None:
                    if self.brush_kind == "clone" and (event.modifiers() & Qt.AltModifier or self.pick_clone_source):
                        self.clonePicked.emit(point)
                    else:
                        self._cloning = True
                        self.cloneStarted.emit(point)
                event.accept()
                return
        if not self.crop_mode or event.button() != Qt.LeftButton or self.image_bounds.isEmpty():
            return super().mousePressEvent(event)
        point = self._bounded_point(event.position().toPoint())
        self._start_point = point
        self._start_rect = QRectF(self._crop_rect) if self._crop_rect else None
        self._anchor = point
        self._drag = "draw"
        if self._crop_rect:
            rect = self._crop_rect
            corners = [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
            tolerance = 10/max(self.transform().m11(), .01)
            for index, corner in enumerate(corners):
                if (point-corner).manhattanLength() <= tolerance:
                    self._drag = "resize"
                    self._anchor = corners[(index+2)%4]
                    break
            else:
                if rect.contains(point):
                    self._drag = "move"
        event.accept()

    def mouseMoveEvent(self, event):
        if self.clone_mode:
            self._brush_hover = self.mapToScene(event.position().toPoint())
            self.viewport().update()
            if self._pan_start is not None:
                delta = event.position().toPoint()-self._pan_start
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
                self._pan_start = event.position().toPoint()
                event.accept()
                return
            if self._cloning and not self.clone_suspended:
                point = self._clone_point(event.position().toPoint(), allow_outside=True)
                self.cloneMoved.emit(point)
                event.accept()
                return
        if not self.crop_mode or not self._drag:
            return super().mouseMoveEvent(event)
        point = self._bounded_point(event.position().toPoint())
        if self._drag == "move":
            rect = self._start_rect.translated(point-self._start_point)
            rect.moveLeft(np.clip(rect.left(), 0, self.image_bounds.width()-rect.width()))
            rect.moveTop(np.clip(rect.top(), 0, self.image_bounds.height()-rect.height()))
        else:
            rect = QRectF(self._anchor, point).normalized().intersected(self.image_bounds)
        self._crop_rect = rect
        self.viewport().update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.clone_mode and event.button() == Qt.MiddleButton:
            self._pan_start = None
            self._recenter_fill()
            event.accept()
            return
        if self._cloning and event.button() == Qt.LeftButton:
            self.mouseMoveEvent(event)
            self._cloning = False
            self.cloneEnded.emit()
            event.accept()
            return
        if not self.crop_mode or event.button() != Qt.LeftButton or not self._drag:
            super().mouseReleaseEvent(event)
            self._recenter_fill()
            return
        # Some platforms deliver no intermediate move event for short drags.
        self.mouseMoveEvent(event)
        self._drag = None
        rect = self._crop_rect
        h, w = self.source_shape
        if rect is None or rect.width()/self.image_bounds.width()*w < 4 or rect.height()/self.image_bounds.height()*h < 4:
            self._crop_rect = self._start_rect
        else:
            self.cropChanged.emit((rect.left()/self.image_bounds.width(), rect.top()/self.image_bounds.height(),
                                   rect.right()/self.image_bounds.width(), rect.bottom()/self.image_bounds.height()))
        self.viewport().update()
        event.accept()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.clone_mode and self._brush_hover is not None:
            pen = QPen(QColor("white"), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            h, w = self.source_shape
            radius = min(self.clone_diameter, h, w)/max(1, w)*self._view_period.x()/2
            painter.drawEllipse(self._brush_hover, radius, radius)
            if self.clone_reference is not None:
                source = QPointF((self.clone_reference.x()%1+np.floor(self._brush_hover.x()/self._view_period.x()))*self._view_period.x(),
                                 (self.clone_reference.y()%1+np.floor(self._brush_hover.y()/self._view_period.y()))*self._view_period.y())
                size = 6/max(self.transform().m11(), .01)
                painter.drawLine(source-QPointF(size, 0), source+QPointF(size, 0))
                painter.drawLine(source-QPointF(0, size), source+QPointF(0, size))
        if not self.crop_mode or self._crop_rect is None:
            return
        selected, bounds = self._crop_rect, self.image_bounds
        shade = QColor(0, 0, 0, 125)
        for area in (QRectF(0, 0, bounds.width(), selected.top()),
                     QRectF(0, selected.bottom(), bounds.width(), bounds.height()-selected.bottom()),
                     QRectF(0, selected.top(), selected.left(), selected.height()),
                     QRectF(selected.right(), selected.top(), bounds.width()-selected.right(), selected.height())):
            painter.fillRect(area, shade)
        pen = QPen(QColor("#ffca4f"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(selected)
        size = 7/max(self.transform().m11(), .01)
        painter.setBrush(QColor("#ffca4f"))
        for point in (selected.topLeft(), selected.topRight(), selected.bottomLeft(), selected.bottomRight()):
            painter.drawRect(QRectF(point.x()-size/2, point.y()-size/2, size, size))

    def _clone_point(self, position, allow_outside=False):
        point = self.mapToScene(position)
        if not self.fill_mode and not allow_outside and not self.image_bounds.contains(point):
            return None
        return QPointF(point.x()/self._view_period.x(), point.y()/self._view_period.y())


class ResetSlider(QSlider):
    def __init__(self, default_value):
        super().__init__(Qt.Horizontal)
        self.default_value = default_value
        self.setToolTip(f"按滑鼠右鍵恢復預設值 {default_value}")

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.setValue(self.default_value)
            event.accept()
        else:
            super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        event.accept()


class PercentControl(QWidget):
    valueChanged = Signal(int)

    def __init__(self, value=85, minimum=0, maximum=100, suffix="%", resettable=False):
        super().__init__()
        self.default_value, self.minimum, self.maximum = value, minimum, maximum
        self.suffix = suffix
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Separate handle position from the displayed value. Each half keeps
        # its original range, with the existing default exactly at the center.
        self.slider = ResetSlider(0) if resettable else QSlider(Qt.Horizontal)
        self.slider.setRange(-1000, 1000)
        self.slider.setSingleStep(10)
        if resettable:
            self.slider.setToolTip(f"按滑鼠右鍵恢復預設值 {value}{suffix}")
        self.label = QLabel()
        self.slider.valueChanged.connect(self._position_changed)
        layout.addWidget(self.slider)
        layout.addWidget(self.label)
        self.label.setText(f"{value}{suffix}")

    def _position_changed(self, position):
        value = self.value()
        self.label.setText(f"{value}{self.suffix}")
        self.valueChanged.emit(value)

    def value(self):
        position = self.slider.value()/1000
        span = self.maximum-self.default_value if position >= 0 else self.default_value-self.minimum
        return round(self.default_value+position*span)

    def setValue(self, value):
        value = min(self.maximum, max(self.minimum, round(value)))
        span = self.maximum-self.default_value if value >= self.default_value else self.default_value-self.minimum
        self.slider.setValue(round((value-self.default_value)*1000/span))


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int)
    done = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self):
        try:
            def checkpoint(value):
                if QThread.currentThread().isInterruptionRequested():
                    raise InterruptedError("已取消；保留上次結果")
                self.progress.emit(value)
            result = self.operation(checkpoint)
            checkpoint(100)
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.done.emit()


