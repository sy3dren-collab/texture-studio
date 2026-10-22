"""Traditional Chinese desktop interface; computation runs outside the UI thread."""
from pathlib import Path
import tempfile
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor, QIcon, QPen, QBrush, QTransform
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QLabel, QFileDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QProgressBar, QGraphicsView, QGraphicsScene, QScrollArea, QSlider, QColorDialog)
from .core import load_image, save_image, correct_lighting, seamless, repeat_preview, crop_image
from .appearance import adjust_material
from .capture import ScreenCapture
from .storage import file_signature, replace_source
from . import __version__


class Preview(QGraphicsView):
    cropChanged = Signal(object)

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

    def show_image(self, image, count, region=None, fill=False):
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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = ResetSlider(value) if resettable else QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.label = QLabel()
        self.slider.valueChanged.connect(lambda current: self.label.setText(f"{current}{suffix}"))
        self.slider.valueChanged.connect(self.valueChanged)
        layout.addWidget(self.slider)
        layout.addWidget(self.label)
        self.slider.setValue(value)
        self.label.setText(f"{self.slider.value()}{suffix}")

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(round(value))


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


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Texture Studio {__version__} — 快速製圖")
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        self.paths, self.weights = [], []
        self.regions = {}
        self.previous_outputs = []
        self._previous_snapshot = None
        self._restoring = False
        self._closing = False
        self.processed_settings = None
        self.original = self.result = None
        self.original_path = None
        self._working_sources = {}
        self._capture_paths = set()
        self.outputs = []
        self.thread = None
        self.dirty = False
        self.seed_value = 42
        self.tint_color = None
        self._source_cache = {}
        self._pending_preview = False
        self._pending_export = None
        self._generation = 0
        self._capture_session = None
        self._capture_temp = None
        self._capture_count = 0
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(lambda: self.process(preview=True))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        left, center = QVBoxLayout(), QVBoxLayout()
        self.quick_form = right = QFormLayout()
        layout.addLayout(left, 1)
        layout.addLayout(center, 4)
        parameter_widget = QWidget()
        parameter_widget.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(parameter_widget)
        layout.addWidget(scroll, 2)
        self.assets = QListWidget()
        left.addWidget(QLabel("素材 · 可直接拖入圖片"))
        left.addWidget(self.assets)
        self.capture_button = QPushButton("截圖匯入素材")
        self.capture_button.clicked.connect(self.start_capture)
        left.addWidget(self.capture_button)
        self.button(left, "匯入圖片", self.import_images)
        self.save_button = QPushButton("儲存檔案")
        self.save_button.clicked.connect(self.save_current)
        left.addWidget(self.save_button)
        self.button(left, "移除素材", self.remove_asset)
        self.info = QLabel("先匯入圖片，再按一鍵製圖")
        self.info.setWordWrap(True)
        left.addWidget(self.info)

        source_tools = QHBoxLayout()
        self.crop_button = QPushButton("框選製圖範圍")
        self.crop_button.setCheckable(True)
        self.crop_button.setToolTip("在原圖拖曳框選；拖曳框內移動、四角調整大小")
        self.crop_button.toggled.connect(self.edit_crop)
        source_tools.addWidget(self.crop_button)
        self.full_image_button = QPushButton("恢復整張")
        self.full_image_button.clicked.connect(self.reset_crop)
        source_tools.addWidget(self.full_image_button)
        source_tools.addStretch()
        center.addLayout(source_tools)
        self.crop_hint = QLabel("框選後僅使用範圍內的素材製圖；完成後按「儲存檔案」")
        self.crop_hint.setWordWrap(True)
        center.addWidget(self.crop_hint)
        self.preview = Preview()
        self.preview.cropChanged.connect(self.set_crop)
        center.addWidget(self.preview)
        preview_tools = QHBoxLayout()
        preview_tools.addWidget(QLabel("預覽"))
        self.repeat = QComboBox()
        self.repeat.addItems(["1", "2", "3", "4", "5"])
        self.repeat.setCurrentText("3")
        preview_tools.addWidget(self.repeat)
        self.fill_button = QPushButton("全屏")
        self.fill_button.setCheckable(True)
        self.fill_button.setToolTip("將目前貼圖重複鋪滿上方檢視區；拖曳平移、滾輪縮放")
        self.fill_button.toggled.connect(self.toggle_fill)
        preview_tools.addWidget(self.fill_button)
        preview_tools.addStretch()
        center.addLayout(preview_tools)
        self.metrics = QLabel("匯入 → 選範圍 → 一鍵製圖 → 儲存檔案")
        center.addWidget(self.metrics)
        self.progress = QProgressBar()
        center.addWidget(self.progress)

        self.mode = QComboBox()
        self.mode.addItems(["無縫貼圖", "隨機變體", "木地板"])
        right.addRow("製圖模式", self.mode)
        self.light = PercentControl(85)
        right.addRow("去暗角／陰影", self.light)
        self.material_saturation = PercentControl(100, 0, 200, resettable=True)
        self.material_saturation.setToolTip("100% 保留原飽和度，0% 轉為灰階")
        right.addRow("飽和度", self.material_saturation)
        self.material_brightness = PercentControl(0, -100, 100, resettable=True)
        self.material_brightness.setToolTip("0% 保留原明暗；向右變亮，向左變暗")
        right.addRow("明暗度", self.material_brightness)
        color_tools = QWidget()
        color_layout = QHBoxLayout(color_tools)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_button = QPushButton("上色…")
        self.color_button.clicked.connect(self.choose_color)
        self.clear_color_button = QPushButton("恢復原色")
        self.clear_color_button.clicked.connect(self.clear_color)
        color_layout.addWidget(self.color_button)
        color_layout.addWidget(self.clear_color_button)
        right.addRow("素材顏色", color_tools)
        self.material_scale = PercentControl(100, 25, 400, resettable=True)
        self.material_scale.setToolTip("100% 原始大小；200% 紋路放大兩倍，輸出圖片尺寸不變")
        right.addRow("素材縮放", self.material_scale)
        self.material_angle = PercentControl(0, -180, 180, "°", resettable=True)
        self.material_angle.setToolTip("以單張素材中心旋轉紋路，不旋轉整面木地板排列")
        right.addRow("旋轉角度", self.material_angle)
        self.variation = PercentControl(20, resettable=True)
        right.addRow("變化程度", self.variation)
        self.direction = QCheckBox("保留木紋方向")
        self.direction.setChecked(True)
        right.addRow(self.direction)
        self.pattern = QComboBox()
        for label, value in [("直鋪", "straight"), ("二分之一錯縫", "half"),
                ("三分之一錯縫", "third"), ("四分之一錯縫", "quarter"),
                ("隨機錯縫", "random"), ("隨機長短板", "variable")]:
            self.pattern.addItem(label, value)
        self.pattern.setCurrentIndex(1)
        right.addRow("排列方式", self.pattern)
        self.board_width = self.number(right, "板寬 mm", 150, 10, 2000)
        self.board_length = self.number(right, "板長 mm", 900, 20, 10000)
        self.gap = self.number(right, "板縫 mm", 2, 0, 50)
        self.resolution = QComboBox()
        for label, value in [("自動（保留比例）", None), ("1K · 快速", 1024), ("2K", 2048), ("4K", 4096), ("8K", 8192)]:
            self.resolution.addItem(label, value)
        right.addRow("輸出大小", self.resolution)
        self.size_hint = QLabel("自動保留比例；木地板整面尺寸自動計算")
        self.size_hint.setWordWrap(True)
        right.addRow(self.size_hint)
        self.shuffle_button = QPushButton("換一組排列")
        self.shuffle_button.clicked.connect(self.reshuffle)
        right.addRow(self.shuffle_button)
        for text, function in [("一鍵製圖", self.process), ("取消", self.cancel),
                ("回到上次結果", self.undo)]:
            button = QPushButton(text)
            button.clicked.connect(function)
            right.addRow(button)
        self.assets.currentRowChanged.connect(self.select_asset)
        self.repeat.currentTextChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.update_mode)
        self.board_width.valueChanged.connect(self.update_board_limits)
        self.board_length.valueChanged.connect(self.update_board_limits)
        for control in (self.light, self.material_saturation, self.material_brightness,
                        self.material_scale, self.material_angle, self.variation):
            control.valueChanged.connect(self.request_preview)
        for control in (self.board_width, self.board_length, self.gap):
            control.valueChanged.connect(self.request_preview)
        for control in (self.mode, self.pattern, self.resolution):
            control.currentIndexChanged.connect(self.request_preview)
        self.direction.toggled.connect(self.request_preview)
        self.update_mode()

    def choose_color(self):
        color = QColorDialog.getColor(QColor.fromRgbF(*(self.tint_color or [.5, .5, .5])), self, "選擇素材顏色")
        if color.isValid():
            self.tint_color = list(color.getRgbF()[:3])
            self.color_button.setText(color.name())
            self.color_button.setStyleSheet(f"border: 2px solid {color.name()};")
            self.request_preview()

    def clear_color(self):
        self.tint_color = None
        self.color_button.setText("上色…")
        self.color_button.setStyleSheet("")
        self.request_preview()

    def request_preview(self, *_):
        if self._restoring or self._closing:
            return
        self._generation += 1
        if self.paths:
            self._pending_preview = True
            self.preview_timer.start(180)

    def start_capture(self):
        if self.thread is not None or self._capture_session is not None:
            return
        self.preview_timer.stop()
        self._pending_preview = False
        self._capture_maximized = self.isMaximized()
        self.hide()
        # Let Windows repaint the desktop before grabbing it, so the app is
        # absent from the screenshot and the overlay is never captured.
        QTimer.singleShot(220, self.open_capture)

    def open_capture(self):
        if self._closing:
            return
        try:
            self._capture_session = ScreenCapture(self)
            self._capture_session.selected.connect(self.capture_ready)
            self._capture_session.cancelled.connect(self.restore_after_capture)
            self._capture_session.start()
        except Exception as error:
            self.restore_after_capture()
            self.error(str(error))

    def restore_after_capture(self):
        if self._capture_session is not None:
            self._capture_session.close_overlays()
            self._capture_session.deleteLater()
            self._capture_session = None
        self.showMaximized() if getattr(self, "_capture_maximized", False) else self.showNormal()
        self.raise_()
        self.activateWindow()

    def capture_ready(self, image):
        self.restore_after_capture()
        self.import_capture(image)

    def import_capture(self, image):
        if self._capture_temp is None:
            self._capture_temp = tempfile.TemporaryDirectory(prefix="texture-studio-capture-", ignore_cleanup_errors=True)
        self._capture_count += 1
        path = Path(self._capture_temp.name)/f"螢幕截圖_{self._capture_count:03d}.png"
        if image.isNull() or min(image.width(), image.height()) < 4 or not image.save(str(path), "PNG"):
            self.error("截圖無效或無法儲存")
            return
        self._capture_paths.add(str(path))
        self.add_paths([str(path)])
        index = self.paths.index(str(path))
        if self.assets.currentRow() != index:
            self.assets.setCurrentRow(index)

    def update_mode(self, *_):
        mode = self.mode.currentIndex()
        for widget in (self.variation, self.direction):
            self.quick_form.setRowVisible(widget, mode == 1)
        for widget in (self.pattern, self.board_width, self.board_length, self.gap):
            self.quick_form.setRowVisible(widget, mode == 2)
        self.quick_form.setRowVisible(self.shuffle_button, mode != 0)
        self.shuffle_button.setText("換一組變體" if mode == 1 else "換一組排列")
        self.size_hint.setText("整面尺寸自動計算；自動輸出為 1K" if mode == 2 else "依選取範圍保留比例；自動使用原始解析度")

    def update_board_limits(self, *_):
        self.board_length.setMinimum(self.board_width.value())
        self.gap.setMaximum(min(50, self.board_width.value()/3))

    def reshuffle(self):
        if self.thread is None:
            self.seed_value = (self.seed_value+1) % 2147483647
            self.process()

    def toggle_fill(self, enabled):
        self.fill_button.setText("返回預覽" if enabled else "全屏")
        if enabled:
            self.crop_button.setChecked(False)
        self.refresh()

    def current_path(self):
        index = self.assets.currentRow()
        return self.paths[index] if 0 <= index < len(self.paths) else None

    def edit_crop(self, enabled):
        if enabled:
            self.preview_timer.stop()
            self._pending_preview = False
            self._generation += 1
        self.preview.set_crop_mode(enabled)
        self.crop_hint.setText("拖曳框選範圍；框內拖曳移動，四角調整大小；按一鍵製圖套用" if enabled else
                              "框選後僅使用範圍內的素材製圖；完成後按「儲存檔案」")
        self.refresh()

    def set_crop(self, region):
        path = self.current_path()
        if path is not None:
            self.regions[path] = list(region)
            self._generation += 1
            self.dirty = True
            self.update_source_info()

    def reset_crop(self):
        path = self.current_path()
        if path is not None:
            self.regions.pop(path, None)
            self._generation += 1
            self.preview_timer.stop()
            self._pending_preview = False
            self.dirty = True
            self.update_source_info()
            self.refresh()

    def update_source_info(self):
        if self.original is None:
            return
        cropped = crop_image(self.original, self.regions.get(self.current_path()))
        h, w = self.original.shape[:2]
        ch, cw = cropped.shape[:2]
        self.info.setText(f"原圖 {w} × {h} px\n製圖範圍 {cw} × {ch} px")

    @staticmethod
    def button(layout, text, function):
        button = QPushButton(text)
        button.clicked.connect(function)
        layout.addWidget(button)

    @staticmethod
    def number(form, text, value, minimum, maximum, integer=False):
        widget = QSpinBox() if integer else QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        if not integer:
            widget.setDecimals(1)
            widget.setSingleStep(1 if "板縫" in text else 10)
        widget.setValue(value)
        form.addRow(text, widget)
        return widget

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([url.toLocalFile() for url in event.mimeData().urls()])

    def import_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "選取素材", "", "圖片 (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        self.add_paths(paths)

    def add_paths(self, paths):
        if self.thread is not None:
            self.error("請等待目前運算結束再匯入素材")
            return
        for path in paths:
            if path and path not in self.paths:
                self.paths.append(path)
                self.weights.append(1)
                self.assets.addItem(Path(path).name)
        if self.assets.currentRow() < 0 and self.paths:
            self.assets.setCurrentRow(0)

    def remove_asset(self):
        if self.thread is not None:
            return
        index = self.assets.currentRow()
        if index >= 0:
            path = self.paths.pop(index)
            self.regions.pop(path, None)
            self._working_sources.pop(path, None)
            self._capture_paths.discard(path)
            self.weights.pop(index)
            self.assets.blockSignals(True)
            self.assets.takeItem(index)
            self.assets.blockSignals(False)
            if self.paths:
                self.select_asset(self.assets.currentRow())
            else:
                self.original = self.result = None
                self.outputs = []
                self.previous_outputs = []
                self._previous_snapshot = None
                self.processed_settings = None
                self.preview_timer.stop()
                self._pending_preview = False
                self._source_cache.clear()
                self.original_path = None
                self._working_sources.clear()
                self.preview.clear_image()
                self.info.setText("先匯入圖片，再按一鍵製圖")

    def select_asset(self, index):
        if not 0 <= index < len(self.paths):
            return
        path = self.paths[index]
        self._generation += 1
        self.save_button.setEnabled(False)
        self.run_job(lambda progress: self._working_sources[path] if path in self._working_sources else load_image(path),
                     lambda image: self.loaded(image, path))

    def loaded(self, image, path=None):
        self.original = image
        self.original_path = path or self.current_path()
        self.result = image
        self.outputs = []
        self.previous_outputs = []
        self._previous_snapshot = None
        self.processed_settings = None
        self.update_source_info()
        pixels = (image[::max(1, image.shape[0]//96), ::max(1, image.shape[1]//96)]*255).astype("uint8").copy()
        thumbnail = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
        item = self.assets.currentItem()
        if item:
            item.setIcon(QIcon(QPixmap.fromImage(thumbnail)))
        self.refresh()

    def settings(self):
        mode = self.mode.currentIndex()
        length, width = self.board_length.value(), self.board_width.value()
        if mode == 2:
            # Four board lengths by twelve rows is compatible with all quick
            # stagger patterns. Physical and raster aspect ratios agree.
            source_h, source_w = width*12, length*4
        elif self.original is not None:
            source_h, source_w = crop_image(self.original, self.regions.get(self.current_path())).shape[:2]
        else:
            source_h = source_w = 1024
        edge = self.resolution.currentData()
        factor = (edge or (1024 if mode == 2 else max(source_h, source_w)))/max(source_h, source_w)
        output_w, output_h = max(4, round(source_w*factor)), max(4, round(source_h*factor))
        amount = self.variation.value()/100
        data = {"mode": mode, "light": self.light.value()/100, "radius": .1, "contrast": .7,
                "blend": 1, "seed": self.seed_value, "variant_count": 1,
                "board_width": width, "board_length": length, "gap": self.gap.value(),
                "world_width": length*4, "world_height": width*12,
                "min_length": length*.5, "max_length": length*4/3, "bevel": 1, "offset": .5,
                "brightness": amount*.15, "hue": amount*.05, "saturation": amount*.25,
                "random_contrast": amount*.25, "direction": self.direction.isChecked(),
                "mirror": False, "color": False, "periodic": True, "arbitrary": False,
                "translate": True, "derived": False, "pattern": self.pattern.currentData(),
                "width": output_w, "height": output_h, "resize_output": edge is not None,
                "output_size": edge, "variation": self.variation.value(), "quick_ui": True,
                "material_saturation": self.material_saturation.value()/100,
                "material_brightness": self.material_brightness.value()/100,
                "material_scale": self.material_scale.value()/100,
                "material_angle": self.material_angle.value(),
                "tint": self.tint_color.copy() if self.tint_color is not None else None}
        return data

    def snapshot(self):
        baselines = self._working_sources.copy()
        if self.original is not None and self.original_path == self.current_path():
            baselines[self.current_path()] = self.original
        return {"settings": self.settings(), "inputs": self.paths.copy(), "weights": self.weights.copy(),
                "regions": {path: region.copy() for path, region in self.regions.items()},
                "index": max(0, self.assets.currentRow()), "generation": self._generation,
                "source_baselines": baselines}

    def prepared_source(self, path, region, strength, baselines):
        baseline = baselines.get(path)
        try:
            signature = file_signature(path)
        except FileNotFoundError:
            if baseline is None:
                raise
            signature = None
        key = (path, signature, id(baseline) if baseline is not None else None, tuple(region) if region else None, strength)
        if key not in self._source_cache:
            image = crop_image(baseline if baseline is not None else load_image(path), region)
            image = seamless(correct_lighting(image, strength))
            while len(self._source_cache) >= 4:
                self._source_cache.pop(next(iter(self._source_cache)))
            self._source_cache[key] = image
        return self._source_cache[key]

    def process(self, preview=False, export_request=None):
        if self._closing:
            return
        if self.thread is not None:
            if preview:
                self._pending_preview = True
            elif export_request:
                self._pending_export = export_request
            return
        if not self.paths and export_request is None:
            if not preview:
                self.error("請先匯入圖片")
            return
        self.preview_timer.stop()
        self._pending_preview = False
        snapshot = export_request["snapshot"] if export_request else self.snapshot()
        settings = snapshot["settings"].copy()
        paths, weights, regions = snapshot["inputs"], snapshot["weights"], snapshot["regions"]
        index = snapshot["index"]
        if preview:
            ratio = min(1, 1024/max(settings["width"], settings["height"]))
            settings["width"] = max(4, round(settings["width"]*ratio))
            settings["height"] = max(4, round(settings["height"]*ratio))
        self.crop_button.setChecked(False)

        def appearance(image):
            return adjust_material(image, settings["material_saturation"], settings["material_brightness"],
                                   settings["tint"], settings["material_scale"], settings["material_angle"])

        def operation(progress):
            import cv2
            if settings["mode"] != 2:
                image = self.prepared_source(paths[index], regions.get(paths[index]), settings["light"], snapshot["source_baselines"])
                progress(25)
                size = (settings["width"], settings["height"])
                if (image.shape[1], image.shape[0]) != size:
                    image = cv2.resize(image, size, interpolation=cv2.INTER_AREA if preview else cv2.INTER_CUBIC)
                image = appearance(image)
                progress(60)
                if settings["mode"] == 0:
                    outputs = [("base_color", image)]
                else:
                    from .variants import generate_variants
                    outputs = [(f"variant_{i:02d}", result) for i, result in enumerate(generate_variants(
                        image, count=settings["variant_count"], seed=settings["seed"], direction=settings["direction"],
                        mirror=False, progress=progress, brightness=settings["brightness"], hue=settings["hue"],
                        saturation=settings["saturation"], contrast=settings["random_contrast"], translate=True))]
            else:
                from .boards import BoardSettings, generate_boards
                images = []
                for i, path in enumerate(paths):
                    image = self.prepared_source(path, regions.get(path), settings["light"], snapshot["source_baselines"])
                    if preview and max(image.shape[:2]) > 1024:
                        factor = 1024/max(image.shape[:2])
                        image = cv2.resize(image, (max(4, round(image.shape[1]*factor)), max(4, round(image.shape[0]*factor))),
                                           interpolation=cv2.INTER_AREA)
                    images.append(appearance(image))
                    progress(10+int(30*(i+1)/len(paths)))
                config = BoardSettings(width=settings["width"], height=settings["height"],
                    board_width_mm=settings["board_width"], board_length_mm=settings["board_length"],
                    gap_mm=settings["gap"], pattern=settings["pattern"], offset=.5, seed=settings["seed"], periodic=True,
                    world_width_mm=settings["world_width"], world_height_mm=settings["world_height"],
                    min_length_mm=settings["min_length"], max_length_mm=settings["max_length"],
                    bevel_mm=1, brightness=settings["brightness"], mirror=False, weights=tuple(weights), lighting_strength=0)
                result = generate_boards(images, config, progress=progress)
                outputs = [("base_color", result["base_color"])]
            if export_request:
                progress(97)
                name, selected = outputs[0]
                if export_request.get("overwrite"):
                    replace_source(selected, export_request["path"], export_request["signature"])
                else:
                    self.export_to(export_request["path"], selected, name, paths)
            return outputs

        def completed(outputs):
            if export_request and export_request.get("overwrite"):
                path = export_request["path"]
                self._working_sources[path] = snapshot["source_baselines"][path]
            if snapshot["generation"] == self._generation:
                previous = self.processed_settings
                self.processed(outputs)
                self._previous_snapshot = previous
                self.processed_settings = snapshot
                if preview:
                    self.metrics.setText("調整預覽 · 儲存時會使用所選的完整解析度")
            else:
                self._pending_preview = True
            if export_request:
                self.metrics.setText(f"已儲存：{Path(export_request['path']).name}")
        self.run_job(operation, completed)

    def run_job(self, operation, callback):
        if self.thread is not None:
            self.error("運算進行中，請稍候或取消")
            return
        self.progress.setValue(0)
        thread = QThread(self)
        worker = Worker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress.setValue)
        self._job_callback = callback
        worker.finished.connect(self.job_result, Qt.QueuedConnection)
        worker.failed.connect(self.job_failed)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self.job_done)
        thread.finished.connect(thread.deleteLater)
        self.thread, self.worker = thread, worker
        self.assets.setEnabled(False)
        self.crop_button.setEnabled(False)
        self.full_image_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        thread.start()

    @Slot(object)
    def job_result(self, result):
        # A plain Python closure connected directly to Worker.finished runs in
        # the worker thread under PySide. Route all UI callbacks through this
        # QObject slot so widget/timer updates always happen on the UI thread.
        if not self._closing:
            self._job_callback(result)

    @Slot()
    def job_done(self):
        self.thread = self.worker = None
        self.assets.setEnabled(True)
        self.crop_button.setEnabled(True)
        self.full_image_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.save_button.setEnabled(True)
        if self._pending_export is not None:
            request, self._pending_export = self._pending_export, None
            QTimer.singleShot(0, lambda: self.process(export_request=request))
        elif self._pending_preview:
            self.preview_timer.start(0)

    @Slot(str)
    def job_failed(self, message):
        if message.startswith("已取消"):
            self.metrics.setText(message)
        else:
            self._pending_preview = False
            self.error(message)

    def cancel(self):
        self.preview_timer.stop()
        self._pending_preview = False
        self._pending_export = None
        if self.thread:
            self.thread.requestInterruption()

    def processed(self, outputs):
        self.previous_outputs = self.outputs
        self.outputs = outputs
        self.dirty = True
        self.result = outputs[0][1]
        self.refresh()

    def undo(self):
        if not self.previous_outputs or self.thread or self._previous_snapshot is None:
            return
        self.preview_timer.stop()
        self._pending_preview = False
        previous = self._previous_snapshot
        old_snapshot = self.processed_settings
        settings = previous["settings"]
        self._restoring = True
        try:
            self.mode.setCurrentIndex(settings["mode"])
            self.light.setValue(settings["light"]*100)
            for name in ("material_saturation", "material_brightness", "material_scale"):
                getattr(self, name).setValue(settings[name]*100)
            self.material_angle.setValue(settings["material_angle"])
            self.tint_color = settings["tint"].copy() if settings["tint"] else None
            color = QColor.fromRgbF(*self.tint_color) if self.tint_color else None
            self.color_button.setText(color.name() if color else "上色…")
            self.color_button.setStyleSheet(f"border: 2px solid {color.name()};" if color else "")
            for name in ("board_width", "board_length", "gap", "variation"):
                getattr(self, name).setValue(settings[name])
            self.direction.setChecked(settings["direction"])
            self.pattern.setCurrentIndex(self.pattern.findData(settings["pattern"]))
            self.resolution.setCurrentIndex(self.resolution.findData(settings["output_size"]))
            self.seed_value = settings["seed"]
            self.regions = {path: region.copy() for path, region in previous["regions"].items()}
        finally:
            self._restoring = False
        self._generation += 1
        self.processed(self.previous_outputs)
        self.processed_settings = {**previous, "generation": self._generation}
        self._previous_snapshot = old_snapshot
        self.update_source_info()

    def refresh(self, *_):
        editing = self.crop_button.isChecked()
        image = self.original if editing else self.result
        if image is None:
            return
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)
        self.preview.show_image(image, int(self.repeat.currentText()), self.regions.get(self.current_path()), self.fill_button.isChecked())
        self.metrics.setText("正在選取原圖範圍" if editing else
                             "貼圖已鋪滿檢視區 · 拖曳平移、滾輪縮放" if self.fill_button.isChecked() else
                             "可用重複預覽檢查接縫，再按「儲存檔案」")

    def confirm_save(self, path):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("儲存檔案")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText("是否覆蓋原檔案？")
        dialog.setInformativeText(str(path))
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        dialog.button(QMessageBox.Yes).setText("覆蓋原檔")
        dialog.button(QMessageBox.No).setText("另存 JPEG")
        dialog.button(QMessageBox.Cancel).setText("取消")
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec()

    def save_current(self):
        if self.result is None or self.current_path() is None:
            self.error("請先匯入圖片")
            return
        path = self.current_path()
        writable_format = Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
        if path not in self._capture_paths and writable_format and Path(path).is_file():
            answer = self.confirm_save(path)
            if answer == QMessageBox.Yes:
                try:
                    signature = file_signature(path)
                    snapshot = self.snapshot()
                    if path not in snapshot["source_baselines"]:
                        raise ValueError("請等待原圖載入完成後再儲存")
                except (OSError, ValueError) as error:
                    self.error(str(error))
                    return
                request = {"path": path, "snapshot": snapshot, "signature": signature, "overwrite": True}
                self.preview_timer.stop()
                self.process(export_request=request)
            elif answer == QMessageBox.No:
                self.save_as()
        else:
            self.save_as()

    def save_as(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "儲存檔案 — 另存 JPEG", "texture.jpg", "JPEG 圖片 (*.jpg *.jpeg)")
        if path:
            destination = Path(path)
            if destination.suffix.lower() not in {".jpg", ".jpeg"}:
                destination = destination.with_suffix(".jpg")
                if destination.exists() and QMessageBox.question(self, "覆寫 JPEG", f"{destination.name} 已存在，是否覆寫？") != QMessageBox.Yes:
                    return
            request = {"path": str(destination), "snapshot": self.snapshot()}
            self.preview_timer.stop()
            self.process(export_request=request)

    def export_to(self, path, image, output_name=None, source_paths=None):
        if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError("請使用 .jpg 或 .jpeg 輸出")
        if Path(path).is_file() and Path(path).resolve() in {Path(source).resolve() for source in (source_paths if source_paths is not None else self.paths)}:
            raise ValueError("不可覆寫原始素材")
        selected = output_name
        is_data = selected in ("normal_reference", "roughness_reference", "height_reference", "gap_mask")
        save_image(image, path, color_space="linear" if is_data else "sRGB")

    def error(self, message):
        QMessageBox.warning(self, "Texture Studio", message)

    def closeEvent(self, event):
        self.preview_timer.stop()
        self._pending_preview = False
        self._pending_export = None
        if self.thread:
            self.cancel()
            self.error("正在取消運算，完成後即可關閉")
            event.ignore()
        else:
            self._closing = True
            if self._capture_temp is not None:
                self._capture_temp.cleanup()
            event.accept()


def main():
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    return app.exec()
