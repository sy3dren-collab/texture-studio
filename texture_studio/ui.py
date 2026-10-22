"""Traditional Chinese desktop interface; computation runs outside the UI thread."""
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QLabel, QFileDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QProgressBar, QGraphicsView, QGraphicsScene, QScrollArea)
from .core import load_image, save_image, correct_lighting, seamless, repeat_preview, seam_quality
from . import __version__


class Preview(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if .03 < self.transform().m11() * factor < 50:
            self.scale(factor, factor)

    def show_image(self, image, count, guides=False):
        # Limit interactive preview memory, retain full resolution result for export.
        import cv2
        h, w = image.shape[:2]
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
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


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
        self.setWindowTitle("Texture Studio — 無縫貼圖與板材生成器")
        self.resize(1350, 850)
        self.setAcceptDrops(True)
        self.paths = []
        self.weights = []
        self.previous_outputs = []
        self.processed_settings = None
        self.original = self.result = None
        self.outputs = []
        self.thread = None
        self.dirty = False
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        left, center, right = QVBoxLayout(), QVBoxLayout(), QFormLayout()
        layout.addLayout(left, 1)
        layout.addLayout(center, 4)
        parameter_widget = QWidget()
        parameter_widget.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(parameter_widget)
        layout.addWidget(scroll, 2)
        self.assets = QListWidget()
        left.addWidget(QLabel("素材（拖入圖片；不覆寫原始檔）"))
        left.addWidget(self.assets)
        self.button(left, "匯入圖片", self.import_images)
        self.button(left, "移除選取素材", self.remove_asset)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 100)
        self.weight.setValue(1)
        self.weight.valueChanged.connect(self.update_weight)
        left.addWidget(QLabel("選取素材權重（0 為停用）"))
        left.addWidget(self.weight)
        self.info = QLabel("尚未載入圖片")
        left.addWidget(self.info)
        self.preview = Preview()
        center.addWidget(self.preview)
        self.metrics = QLabel("接縫數值僅供輔助；不代表自然程度")
        center.addWidget(self.metrics)
        self.progress = QProgressBar()
        center.addWidget(self.progress)
        self.mode = QComboBox()
        self.mode.addItems(["無縫貼圖", "隨機變體", "板材生成"])
        right.addRow("模式", self.mode)
        self.light = self.number(right, "光照校正強度", .7, 0, 1)
        self.radius = self.number(right, "光照校正範圍", .15, .01, .5)
        self.contrast = self.number(right, "原始明暗保留", .4, 0, 1)
        self.color = QCheckBox("同時校正色偏")
        right.addRow(self.color)
        self.blend = self.number(right, "週期性重建強度", 1, 0, 1)
        self.seed = self.number(right, "隨機 Seed", 42, 0, 2147483647, True)
        self.variant_count = self.number(right, "變體數量", 4, 2, 50, True)
        self.direction = QCheckBox("方向保護（僅 0°／180°）")
        self.direction.setChecked(True)
        right.addRow(self.direction)
        self.mirror = QCheckBox("允許鏡像")
        right.addRow(self.mirror)
        self.arbitrary = QCheckBox("任意角度（自由模式）")
        right.addRow(self.arbitrary)
        self.translate = QCheckBox("隨機週期性平移")
        self.translate.setChecked(True)
        right.addRow(self.translate)
        self.brightness = self.number(right, "隨機亮度（0 關閉）", .03, 0, .5)
        self.hue = self.number(right, "隨機色相（0 關閉）", .01, 0, .5)
        self.saturation = self.number(right, "隨機飽和度（0 關閉）", .05, 0, .5)
        self.random_contrast = self.number(right, "隨機對比（0 關閉）", .05, 0, .5)
        self.pattern = QComboBox()
        self.pattern.addItems(["straight", "half", "third", "quarter", "random", "variable", "herringbone", "chevron", "basketweave", "custom"])
        right.addRow("排列", self.pattern)
        self.board_width = self.number(right, "板寬 mm", 150, 10, 2000)
        self.board_length = self.number(right, "板長 mm", 900, 20, 10000)
        self.world_width = self.number(right, "整面寬 mm", 3600, 100, 100000)
        self.world_height = self.number(right, "整面長 mm", 1800, 100, 100000)
        self.min_length = self.number(right, "最短板長 mm", 450, 10, 10000)
        self.max_length = self.number(right, "最長板長 mm", 1200, 10, 10000)
        self.gap = self.number(right, "板縫 mm", 2, 0, 50)
        self.bevel = self.number(right, "倒角寬度 mm", 1, 0, 50)
        self.offset = self.number(right, "自訂錯縫比例", .5, 0, 1)
        self.width = self.number(right, "輸出寬 px", 1024, 64, 8192, True)
        self.height = self.number(right, "輸出高 px", 1024, 64, 8192, True)
        self.periodic = QCheckBox("週期性拼板（不相容尺寸會拒絕）")
        self.periodic.setChecked(True)
        right.addRow(self.periodic)
        self.resize_output = QCheckBox("貼圖／變體調整至輸出解析度（可能改變比例）")
        right.addRow(self.resize_output)
        self.derived = QCheckBox("輸出高度／粗糙度／法線參考圖（非量測）")
        right.addRow(self.derived)
        self.repeat = QComboBox()
        self.repeat.addItems(["1", "2", "3", "5"])
        self.repeat.setCurrentText("3")
        right.addRow("重複預覽", self.repeat)
        self.compare = QCheckBox("顯示原圖")
        self.guides = QCheckBox("接縫輔助線")
        right.addRow(self.compare)
        right.addRow(self.guides)
        self.selection = QComboBox()
        right.addRow("輸出／變體預覽", self.selection)
        for text, function in [("自動處理／重新生成", self.process), ("取消運算", self.cancel),
                ("回到上次結果", self.undo),
                ("輸出選取貼圖", self.export), ("批次輸出全部", self.export_all),
                ("儲存專案 JSON", self.save_project), ("開啟專案 JSON", self.open_project)]:
            button = QPushButton(text)
            button.clicked.connect(function)
            right.addRow(button)
        self.assets.currentRowChanged.connect(self.select_asset)
        self.repeat.currentTextChanged.connect(self.refresh)
        self.compare.toggled.connect(self.refresh)
        self.guides.toggled.connect(self.refresh)
        self.selection.currentIndexChanged.connect(self.select_output)

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
            widget.setDecimals(3)
            widget.setSingleStep(.05)
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
        for path in paths:
            if path and path not in self.paths:
                self.paths.append(path)
                self.weights.append(1)
                self.assets.addItem(Path(path).name)
        if self.assets.currentRow() < 0 and self.paths:
            self.assets.setCurrentRow(0)

    def remove_asset(self):
        index = self.assets.currentRow()
        if index >= 0:
            self.paths.pop(index)
            self.weights.pop(index)
            self.assets.takeItem(index)

    def update_weight(self, value):
        index = self.assets.currentRow()
        if 0 <= index < len(self.weights):
            self.weights[index] = value

    def select_asset(self, index):
        if not 0 <= index < len(self.paths):
            return
        path = self.paths[index]
        self.weight.blockSignals(True)
        self.weight.setValue(self.weights[index])
        self.weight.blockSignals(False)
        self.run_job(lambda progress: load_image(path), self.loaded)

    def loaded(self, image):
        self.original = image
        self.result = image
        self.info.setText(f"{image.shape[1]} × {image.shape[0]} px · sRGB")
        pixels = (image[::max(1, image.shape[0]//96), ::max(1, image.shape[1]//96)]*255).astype("uint8").copy()
        thumbnail = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format_RGB888).copy()
        item = self.assets.currentItem()
        if item:
            item.setIcon(QIcon(QPixmap.fromImage(thumbnail)))
        self.refresh()

    def settings(self):
        names = ("light", "radius", "contrast", "blend", "seed", "variant_count", "board_width", "board_length", "gap", "offset", "width", "height", "world_width", "world_height", "min_length", "max_length", "bevel", "brightness", "hue", "saturation", "random_contrast")
        data = {name: getattr(self, name).value() for name in names}
        data.update({name: getattr(self, name).isChecked() for name in ("color", "direction", "mirror", "periodic", "arbitrary", "translate", "resize_output", "derived")})
        data.update(mode=self.mode.currentIndex(), pattern=self.pattern.currentText())
        return data

    def process(self):
        if not self.paths:
            self.error("請先匯入圖片")
            return
        settings = self.settings()
        paths = self.paths.copy()
        weights = self.weights.copy()
        index = max(0, self.assets.currentRow())
        def operation(progress):
            image = load_image(paths[index])
            progress(10)
            image = correct_lighting(image, settings["light"], settings["radius"], settings["contrast"], settings["color"])
            progress(35)
            image = seamless(image, settings["blend"])
            progress(60)
            if settings["resize_output"] and settings["mode"] != 2:
                import cv2
                image = cv2.resize(image, (settings["width"], settings["height"]), interpolation=cv2.INTER_CUBIC)
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
            images = [load_image(path) for path in paths]
            config = BoardSettings(width=settings["width"], height=settings["height"], board_width_mm=settings["board_width"],
                board_length_mm=settings["board_length"], gap_mm=settings["gap"], pattern=settings["pattern"],
                offset=settings["offset"], seed=settings["seed"], periodic=settings["periodic"],
                world_width_mm=settings["world_width"], world_height_mm=settings["world_height"],
                min_length_mm=settings["min_length"], max_length_mm=settings["max_length"],
                bevel_mm=settings["bevel"], brightness=settings["brightness"], mirror=settings["mirror"], weights=tuple(weights))
            result = generate_boards(images, config, progress=progress)
            if settings["derived"]:
                from .maps import derive_maps
                result.update(derive_maps(result["base_color"], result["height_reference"]))
            return list(result.items())
        def completed(outputs):
            self.processed_settings = {"settings": settings, "inputs": paths, "weights": weights}
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
        thread.start()

    def job_done(self):
        self.thread = self.worker = None

    def cancel(self):
        if self.thread:
            self.thread.requestInterruption()

    def processed(self, outputs):
        self.previous_outputs = self.outputs
        self.outputs = outputs
        self.dirty = True
        self.selection.clear()
        self.selection.addItems([name for name, _ in outputs])
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
        image = self.original if self.compare.isChecked() else self.result
        if image is None:
            return
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)
        self.preview.show_image(image, int(self.repeat.currentText()), self.guides.isChecked())
        quality = seam_quality(image)
        self.metrics.setText(f"左右差 {quality['left_right']:.4f} · 上下差 {quality['top_bottom']:.4f}（越小越連續；仍需目視檢查）")

    def export(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "輸出貼圖", "texture.png", "PNG (*.png);;JPEG (*.jpg);;TIFF (*.tiff)")
        if path:
            image = self.result
            name = self.selection.currentText()
            self.run_job(lambda progress: self.export_to(path, image, name), lambda _: self.metrics.setText("貼圖已輸出"))

    def export_to(self, path, image, output_name=None):
        if Path(path).resolve() in {Path(source).resolve() for source in self.paths}:
            raise ValueError("不可覆寫原始素材")
        selected = output_name or self.selection.currentText()
        is_data = selected in ("normal_reference", "roughness_reference", "height_reference", "gap_mask")
        save_image(image, path, color_space="linear" if is_data else "sRGB")

    def export_all(self):
        if not self.outputs:
            return
        directory = QFileDialog.getExistingDirectory(self, "批次輸出資料夾")
        if directory:
            outputs = self.outputs.copy()
            seed = self.seed.value()
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
        data = {"version": __version__, "inputs": self.paths, "weights": self.weights, "settings": self.settings(),
                "last_render": self.processed_settings,
                "physical_size_mm": [self.world_width.value(), self.world_height.value()],
                "uv_ratio": self.world_width.value()/self.world_height.value(),
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
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for name, value in data["settings"].items():
                widget = getattr(self, name, None)
                if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(value)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                elif name == "mode":
                    self.mode.setCurrentIndex(value)
                elif name == "pattern":
                    self.pattern.setCurrentText(value)
            self.assets.clear()
            self.paths.clear()
            self.weights.clear()
            self.add_paths(data["inputs"])
            self.weights = data.get("weights", [1]*len(self.paths))
        except Exception as error:
            self.error(str(error))

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
