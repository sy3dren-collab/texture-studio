"""Traditional Chinese desktop interface; computation runs outside the UI thread."""
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QIcon, QPen
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QLabel, QFileDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QProgressBar, QGraphicsView, QGraphicsScene, QScrollArea, QSlider)
from .core import load_image, save_image, correct_lighting, seamless, repeat_preview, crop_image
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

    def set_crop_mode(self, enabled):
        self.crop_mode = enabled
        self._drag = None
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.viewport().update()

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if .03 < self.transform().m11() * factor < 50:
            self.scale(factor, factor)

    def show_image(self, image, count, guides=False, region=None):
        # Limit interactive preview memory, retain full resolution result for export.
        import cv2
        h, w = image.shape[:2]
        self.source_shape = (h, w)
        if self.crop_mode:
            count = 1
        ratio = min(1, 1600 / (max(h, w) * count))
        small = cv2.resize(image, (max(1, round(w * ratio)), max(1, round(h * ratio))))
        pixels = (np.clip(repeat_preview(small, count), 0, 1) * 255).astype("uint8")
        qimage = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        if guides and count > 1:
            painter = QPainter(pixmap)
            painter.setPen(QColor("#ff4655"))
            for i in range(1, count):
                painter.drawLine(i * small.shape[1], 0, i * small.shape[1], pixels.shape[0])
                painter.drawLine(0, i * small.shape[0], pixels.shape[1], i * small.shape[0])
            painter.end()
        self.scene().clear()
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(pixmap.rect())
        self.image_bounds = QRectF(0, 0, pixels.shape[1], pixels.shape[0])
        self._crop_rect = (QRectF(region[0]*small.shape[1], region[1]*small.shape[0],
                                (region[2]-region[0])*small.shape[1], (region[3]-region[1])*small.shape[0])
                           if region is not None and self.crop_mode else None)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

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
            return super().mouseReleaseEvent(event)
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


class PercentControl(QWidget):
    def __init__(self, value=85):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.label = QLabel()
        self.slider.valueChanged.connect(lambda current: self.label.setText(f"{current}%"))
        layout.addWidget(self.slider)
        layout.addWidget(self.label)
        self.slider.setValue(value)

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
        self.processed_settings = None
        self.original = self.result = None
        self.outputs = []
        self.thread = None
        self.dirty = False
        self.seed_value = 42
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
        self.button(left, "匯入圖片", self.import_images)
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
        self.crop_hint = QLabel("框選後，僅使用範圍內的素材製作貼圖；不修改原始檔")
        self.crop_hint.setWordWrap(True)
        center.addWidget(self.crop_hint)
        self.preview = Preview()
        self.preview.cropChanged.connect(self.set_crop)
        center.addWidget(self.preview)
        preview_tools = QHBoxLayout()
        preview_tools.addWidget(QLabel("預覽"))
        self.repeat = QComboBox()
        self.repeat.addItems(["1", "2", "3", "5"])
        self.repeat.setCurrentText("3")
        preview_tools.addWidget(self.repeat)
        self.compare = QCheckBox("原圖比較")
        self.guides = QCheckBox("接縫線")
        preview_tools.addWidget(self.compare)
        preview_tools.addWidget(self.guides)
        preview_tools.addStretch()
        center.addLayout(preview_tools)
        self.metrics = QLabel("匯入 → 選範圍 → 一鍵製圖 → 輸出")
        center.addWidget(self.metrics)
        self.progress = QProgressBar()
        center.addWidget(self.progress)

        self.mode = QComboBox()
        self.mode.addItems(["無縫貼圖", "隨機變體", "木地板"])
        right.addRow("製圖模式", self.mode)
        self.light = PercentControl(85)
        right.addRow("去暗角／陰影", self.light)
        self.variant_count = self.number(right, "生成張數", 4, 2, 50, True)
        self.variation = PercentControl(20)
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
        self.selection = QComboBox()
        right.addRow("查看結果", self.selection)
        self.shuffle_button = QPushButton("換一組排列")
        self.shuffle_button.clicked.connect(self.reshuffle)
        right.addRow(self.shuffle_button)
        for text, function in [("一鍵製圖", self.process), ("取消", self.cancel),
                ("回到上次結果", self.undo), ("輸出圖片", self.export), ("輸出全部", self.export_all),
                ("儲存專案", self.save_project), ("開啟專案", self.open_project)]:
            button = QPushButton(text)
            button.clicked.connect(function)
            right.addRow(button)
        self.assets.currentRowChanged.connect(self.select_asset)
        self.repeat.currentTextChanged.connect(self.refresh)
        self.compare.toggled.connect(self.refresh)
        self.guides.toggled.connect(self.refresh)
        self.selection.currentIndexChanged.connect(self.select_output)
        self.mode.currentIndexChanged.connect(self.update_mode)
        self.board_width.valueChanged.connect(self.update_board_limits)
        self.board_length.valueChanged.connect(self.update_board_limits)
        self.update_mode()

    def update_mode(self, *_):
        mode = self.mode.currentIndex()
        for widget in (self.variant_count, self.variation, self.direction):
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

    def current_path(self):
        index = self.assets.currentRow()
        return self.paths[index] if 0 <= index < len(self.paths) else None

    def edit_crop(self, enabled):
        self.preview.set_crop_mode(enabled)
        self.crop_hint.setText("拖曳框選範圍；框內拖曳移動，四角調整大小；按一鍵製圖套用" if enabled else
                              "框選後，僅使用範圍內的素材製作貼圖；不修改原始檔")
        self.refresh()

    def set_crop(self, region):
        path = self.current_path()
        if path is not None:
            self.regions[path] = list(region)
            self.dirty = True
            self.update_source_info()

    def reset_crop(self):
        path = self.current_path()
        if path is not None:
            self.regions.pop(path, None)
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
            self.weights.pop(index)
            self.assets.blockSignals(True)
            self.assets.takeItem(index)
            self.assets.blockSignals(False)
            if self.paths:
                self.select_asset(self.assets.currentRow())
            else:
                self.original = self.result = None
                self.outputs = []
                self.selection.clear()
                self.preview.scene().clear()
                self.info.setText("先匯入圖片，再按一鍵製圖")

    def select_asset(self, index):
        if not 0 <= index < len(self.paths):
            return
        path = self.paths[index]
        self.run_job(lambda progress: load_image(path), self.loaded)

    def loaded(self, image):
        self.original = image
        self.result = image
        self.outputs = []
        self.selection.clear()
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
                "blend": 1, "seed": self.seed_value, "variant_count": self.variant_count.value(),
                "board_width": width, "board_length": length, "gap": self.gap.value(),
                "world_width": length*4, "world_height": width*12,
                "min_length": length*.5, "max_length": length*4/3, "bevel": 1, "offset": .5,
                "brightness": amount*.15, "hue": amount*.05, "saturation": amount*.25,
                "random_contrast": amount*.25, "direction": self.direction.isChecked(),
                "mirror": False, "color": False, "periodic": True, "arbitrary": False,
                "translate": True, "derived": False, "pattern": self.pattern.currentData(),
                "width": output_w, "height": output_h, "resize_output": edge is not None,
                "output_size": edge, "variation": self.variation.value(), "quick_ui": True}
        return data

    def process(self):
        if self.thread is not None:
            return
        if not self.paths:
            self.error("請先匯入圖片")
            return
        settings = self.settings()
        paths = self.paths.copy()
        weights = self.weights.copy()
        regions = {path: region.copy() for path, region in self.regions.items()}
        index = max(0, self.assets.currentRow())
        self.crop_button.setChecked(False)
        self.compare.setChecked(False)
        def operation(progress):
            if settings["mode"] != 2:
                image = crop_image(load_image(paths[index]), regions.get(paths[index]))
                progress(10)
                image = correct_lighting(image, settings["light"], settings["radius"], settings["contrast"], settings["color"])
                progress(35)
                if settings["resize_output"]:
                    import cv2
                    image = cv2.resize(image, (settings["width"], settings["height"]), interpolation=cv2.INTER_CUBIC)
                image = seamless(image, settings["blend"])
                progress(60)
            if settings["mode"] == 0:
                outputs = [("base_color", image)]
                if settings["derived"]:
                    from .maps import derive_maps
                    outputs += list(derive_maps(image).items())
                return outputs
            if settings["mode"] == 1:
                from .variants import generate_variants
                return [(f"variant_{i:02d}", result) for i, result in enumerate(generate_variants(
                    image, count=settings["variant_count"], seed=settings["seed"], direction=settings["direction"],
                    mirror=settings["mirror"], progress=progress, brightness=settings["brightness"],
                    hue=settings["hue"], saturation=settings["saturation"], contrast=settings["random_contrast"],
                    translate=settings["translate"], arbitrary_angle=settings["arbitrary"]))]
            from .boards import BoardSettings, generate_boards
            images = []
            for i, path in enumerate(paths):
                images.append(crop_image(load_image(path), regions.get(path)))
                progress(10+int(30*(i+1)/len(paths)))
            config = BoardSettings(width=settings["width"], height=settings["height"], board_width_mm=settings["board_width"],
                board_length_mm=settings["board_length"], gap_mm=settings["gap"], pattern=settings["pattern"],
                offset=settings["offset"], seed=settings["seed"], periodic=settings["periodic"],
                world_width_mm=settings["world_width"], world_height_mm=settings["world_height"],
                min_length_mm=settings["min_length"], max_length_mm=settings["max_length"],
                bevel_mm=settings["bevel"], brightness=settings["brightness"], mirror=settings["mirror"], weights=tuple(weights),
                lighting_strength=settings["light"])
            result = generate_boards(images, config, progress=progress)
            if settings["derived"]:
                from .maps import derive_maps
                result.update(derive_maps(result["base_color"], result["height_reference"]))
            return list(result.items())
        def completed(outputs):
            self.processed_settings = {"settings": settings, "inputs": paths, "weights": weights, "regions": regions}
            self.processed(outputs)
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
        worker.finished.connect(callback)
        worker.failed.connect(self.error)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self.job_done)
        thread.finished.connect(thread.deleteLater)
        self.thread, self.worker = thread, worker
        self.assets.setEnabled(False)
        self.crop_button.setEnabled(False)
        self.full_image_button.setEnabled(False)
        thread.start()

    def job_done(self):
        self.thread = self.worker = None
        self.assets.setEnabled(True)
        self.crop_button.setEnabled(True)
        self.full_image_button.setEnabled(True)

    def cancel(self):
        if self.thread:
            self.thread.requestInterruption()

    def processed(self, outputs):
        self.previous_outputs = self.outputs
        self.outputs = outputs
        self.dirty = True
        self.selection.clear()
        labels = {"base_color": "完成貼圖", "gap_mask": "板縫遮罩", "height_reference": "高度參考圖",
                  "roughness_reference": "粗糙度參考圖", "normal_reference": "法線參考圖"}
        for name, _ in outputs:
            label = f"變體 {int(name.split('_')[-1])+1}" if name.startswith("variant_") else labels.get(name, name)
            self.selection.addItem(label, name)
        self.select_output(0)

    def undo(self):
        if self.previous_outputs and not self.thread:
            previous = self.previous_outputs
            self.processed(previous)

    def select_output(self, index):
        if 0 <= index < len(self.outputs):
            self.result = self.outputs[index][1]
            self.refresh()

    def refresh(self, *_):
        editing = self.crop_button.isChecked()
        image = self.original if self.compare.isChecked() or editing else self.result
        if image is None:
            return
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)
        self.preview.show_image(image, int(self.repeat.currentText()), self.guides.isChecked(), self.regions.get(self.current_path()))
        self.metrics.setText("正在選取原圖範圍" if editing else
                             "原圖比較" if self.compare.isChecked() else
                             "可用重複預覽檢查接縫，再輸出圖片")

    def export(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "輸出貼圖", "texture.png", "PNG (*.png);;JPEG (*.jpg);;TIFF (*.tiff)")
        if path:
            image = self.result
            name = self.selection.currentData()
            self.run_job(lambda progress: self.export_to(path, image, name), lambda _: self.metrics.setText("貼圖已輸出"))

    def export_to(self, path, image, output_name=None):
        if Path(path).resolve() in {Path(source).resolve() for source in self.paths}:
            raise ValueError("不可覆寫原始素材")
        selected = output_name or self.selection.currentData()
        is_data = selected in ("normal_reference", "roughness_reference", "height_reference", "gap_mask")
        save_image(image, path, color_space="linear" if is_data else "sRGB")

    def export_all(self):
        if not self.outputs:
            return
        directory = QFileDialog.getExistingDirectory(self, "批次輸出資料夾")
        if directory:
            outputs = self.outputs.copy()
            seed = self.seed_value
            project = Path(directory) / "texture_project.json"
            targets = [Path(directory) / f"{name}_seed{seed}.png" for name, _ in outputs]
            if any(path.exists() for path in targets+[project]):
                self.error("輸出檔案已存在；請選擇新的資料夾")
                return
            self.write_project(project)
            def operation(progress):
                for index, ((name, image), path) in enumerate(zip(outputs, targets)):
                    progress(int(index/len(outputs)*100))
                    self.export_to(path, image, name)
            self.run_job(operation, lambda _: self.metrics.setText("全部貼圖與專案資訊已輸出"))

    def write_project(self, path):
        settings = self.settings()
        data = {"version": __version__, "inputs": self.paths, "weights": self.weights, "settings": self.settings(),
                "regions": self.regions,
                "last_render": self.processed_settings,
                "physical_size_mm": [settings["world_width"], settings["world_height"]],
                "uv_ratio": settings["world_width"]/settings["world_height"],
                "color_space": "Base Color: sRGB; data maps: linear/non-color",
                "limitations": "RGB 衍生的高度、粗糙度及法線僅為估算，需目視驗證無縫品質。"}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "儲存專案", "texture_project.json", "JSON (*.json)")
        if path:
            try:
                self.write_project(path)
                self.dirty = False
            except Exception as error:
                self.error(str(error))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟專案", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.load_project(path)
        except Exception as error:
            self.error(str(error))

    def load_project(self, path):
        if self.thread is not None:
            raise ValueError("請等待目前運算結束再開啟專案")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = data["settings"]
        regions = data.get("regions", {})
        for region in regions.values():
            if len(region) != 4 or not all(np.isfinite(region)) or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1):
                raise ValueError("專案中的製圖範圍無效")
        self.mode.setCurrentIndex(settings.get("mode", 0))
        self.light.setValue(settings.get("light", .85)*100)
        self.variant_count.setValue(settings.get("variant_count", 4))
        self.direction.setChecked(settings.get("direction", True))
        self.variation.setValue(settings.get("variation", min(100, settings.get("brightness", .03)/.15*100)))
        self.seed_value = settings.get("seed", 42)
        for name in ("board_width", "board_length", "gap"):
            if name in settings:
                getattr(self, name).setValue(settings[name])
        pattern = self.pattern.findData(settings.get("pattern", "half"))
        self.pattern.setCurrentIndex(max(0, pattern))
        edge = settings.get("output_size")
        if "output_size" not in settings and settings.get("resize_output"):
            edge = max(settings.get("width", 1024), settings.get("height", 1024))
        resolution = self.resolution.findData(edge)
        self.resolution.setCurrentIndex(max(0, resolution))
        self.assets.clear()
        self.paths.clear()
        self.weights.clear()
        self.regions = regions
        self.add_paths(data["inputs"])
        self.weights = data.get("weights", [1]*len(self.paths))

    def error(self, message):
        QMessageBox.warning(self, "Texture Studio", message)

    def closeEvent(self, event):
        if self.thread:
            self.cancel()
            self.error("正在取消運算，完成後即可關閉")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    return app.exec()
