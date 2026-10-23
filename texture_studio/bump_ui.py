"""Independent BUMP editor. Source materials are never changed here."""
from pathlib import Path
import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Slot
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QComboBox
from .bump import make_bump, bump_normal
from .core import save_image
from .widgets import Preview, PercentControl, Worker


class BumpDialog(QDialog):
    def __init__(self, image, source_path, parent=None, source_paths=()):
        super().__init__(parent)
        self.setWindowTitle("建立 BUMP")
        self.resize(900, 650)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.source = image
        self.source_path = Path(source_path)
        self.source_paths = {Path(path).resolve() for path in (*source_paths, source_path)}
        self.result = None
        self.thread = self.worker = None
        self.generation = 0
        self.pending_preview = False
        self.pending_export = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.brightness = PercentControl(0, -100, 100, resettable=True)
        self.contrast = PercentControl(100, 0, 300, resettable=True)
        self.strength = PercentControl(100, 0, 400, resettable=True)
        form.addRow("明暗度", self.brightness)
        form.addRow("對比", self.contrast)
        form.addRow("法線強度", self.strength)
        self.form = form
        form.setRowVisible(self.strength, False)
        layout.addLayout(form)
        tools = QHBoxLayout()
        self.normal_button = QPushButton("生成法線貼圖")
        self.normal_button.setCheckable(True)
        self.normal_button.toggled.connect(self.toggle_normal)
        tools.addWidget(self.normal_button)
        tools.addWidget(QLabel("預覽"))
        self.repeat = QComboBox()
        self.repeat.addItems(["1", "2", "3", "4"])
        self.repeat.setCurrentText("2")
        self.repeat.currentTextChanged.connect(self.refresh)
        tools.addWidget(self.repeat)
        tools.addStretch()
        layout.addLayout(tools)
        self.preview = Preview()
        layout.addWidget(self.preview, 1)
        self.status = QLabel("獨立製作 BUMP，不修改彩色貼圖；儲存使用完整解析度")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save_button = QPushButton("儲存檔案")
        self.save_button.clicked.connect(self.save_file)
        layout.addWidget(self.save_button)
        for control in (self.brightness, self.contrast, self.strength):
            control.valueChanged.connect(self.request_preview)
        self.request_preview()

    def toggle_normal(self, normal):
        self.normal_button.setText("返回 BUMP" if normal else "生成法線貼圖")
        self.form.setRowVisible(self.strength, normal)
        self.request_preview()

    def settings(self):
        return {"brightness": self.brightness.value()/100, "contrast": self.contrast.value()/100,
                "strength": self.strength.value()/50, "normal": self.normal_button.isChecked(),
                "generation": self.generation, "repeat": int(self.repeat.currentText())}

    def request_preview(self, *_):
        self.generation += 1
        self.pending_preview = True
        self.timer.start(150)

    def refresh(self, *_):
        if self.result is not None:
            image = np.repeat(self.result[..., None], 3, axis=2) if self.result.ndim == 2 else self.result
            self.preview.show_image(image, int(self.repeat.currentText()))
            count = int(self.repeat.currentText())
            kind = "黑白 BUMP" if self.result.ndim == 2 else "法線貼圖"
            self.status.setText(f"{kind} · 儲存尺寸 {self.source.shape[1]*count} × {self.source.shape[0]*count} px · 依預覽數量鋪排")

    def save_file(self):
        normal = self.normal_button.isChecked()
        suffix, label = ("_NORMAL.png", "PNG 圖片 (*.png)") if normal else ("_BUMP.jpg", "JPEG 圖片 (*.jpg *.jpeg)")
        path, _ = QFileDialog.getSaveFileName(self, "儲存法線貼圖" if normal else "儲存 BUMP", self.source_path.stem+suffix, label)
        if not path:
            return
        destination = Path(path)
        accepted = {".png"} if normal else {".jpg", ".jpeg"}
        if destination.suffix.lower() not in accepted:
            destination = destination.with_suffix(".png" if normal else ".jpg")
            if destination.exists() and QMessageBox.question(self, "儲存檔案", f"{destination.name} 已存在，是否覆蓋？") != QMessageBox.Yes:
                return
        if destination.resolve() in self.source_paths:
            self.error("請另存新的 BUMP／法線檔案，不能覆蓋原始素材")
            return
        self.save_button.setEnabled(False)
        self.timer.stop()
        self.render(export={"path": destination, "settings": self.settings()})

    def render(self, export=None):
        if self.thread is not None:
            if export:
                self.pending_export = export
            else:
                self.pending_preview = True
            return
        self.timer.stop()
        self.pending_preview = False
        settings = export["settings"] if export else self.settings()

        def operation(progress):
            image = self.source
            ratio = 1 if export else min(1, 1024/max(image.shape[:2]))
            if ratio < 1:
                image = cv2.resize(image, (max(4, round(image.shape[1]*ratio)), max(4, round(image.shape[0]*ratio))), interpolation=cv2.INTER_AREA)
            height = make_bump(image, settings["brightness"], settings["contrast"])
            progress(50)
            result = bump_normal(height, settings["strength"]*ratio) if settings["normal"] else height
            progress(90)
            if export:
                save_image(result, export["path"], color_space="linear", repeat=settings["repeat"])
            return result

        self._settings, self._export = settings, export
        thread = QThread(self)
        worker = Worker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.rendered, Qt.QueuedConnection)
        worker.failed.connect(self.failed)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self.job_done)
        thread.finished.connect(thread.deleteLater)
        self.thread, self.worker = thread, worker
        thread.start()

    @Slot(object)
    def rendered(self, result):
        if self._settings["generation"] == self.generation:
            self.result = result
            self.refresh()
        if self._export:
            count = self._settings["repeat"]
            self.status.setText(f"已儲存：{self._export['path'].name} · {self.source.shape[1]*count} × {self.source.shape[0]*count} px")

    @Slot(str)
    def failed(self, message):
        self.pending_preview = False
        if message.startswith("已取消"):
            self.status.setText(message)
        else:
            self.error(message)

    @Slot()
    def job_done(self):
        self.thread = self.worker = None
        if self.pending_export is not None:
            request, self.pending_export = self.pending_export, None
            self.render(export=request)
        else:
            self.save_button.setEnabled(True)
            if self.pending_preview:
                self.timer.start(0)

    def error(self, message):
        QMessageBox.warning(self, "建立 BUMP", message)

    def reject(self):
        # Escape invokes reject() directly, bypassing closeEvent(). Keep the
        # QObject and QThread alive until the worker has actually stopped.
        self.timer.stop()
        self.pending_preview = False
        self.pending_export = None
        if self.thread is not None:
            self.thread.requestInterruption()
            self.status.setText("正在取消運算，完成後即可關閉")
            return
        super().reject()

    def closeEvent(self, event):
        self.timer.stop()
        self.pending_preview = False
        self.pending_export = None
        if self.thread is not None:
            self.thread.requestInterruption()
            self.status.setText("正在取消運算，完成後即可關閉")
            event.ignore()
        else:
            super().closeEvent(event)
