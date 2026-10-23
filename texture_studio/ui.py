"""Traditional Chinese desktop interface; computation runs outside the UI thread."""
from pathlib import Path
import tempfile
import numpy as np
from PySide6.QtCore import QThread, Slot, Qt, QPointF, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QLabel, QFileDialog, QFormLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QProgressBar, QScrollArea, QColorDialog)
from .core import load_image, save_image, correct_lighting, seamless, crop_image
from .appearance import adjust_material
from .capture import ScreenCapture
from .storage import file_signature, replace_source
from .painting import PeriodicCloneStroke, PeriodicDodgeStroke
from .widgets import Preview, PercentControl, Worker
from . import __version__


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
        self._imported_sources = {}
        self._staged_sources = set()
        self._capture_paths = set()
        self.outputs = []
        self.thread = None
        self.seed_value = 42
        self.tint_color = None
        self._source_cache = {}
        self._pending_preview = False
        self._pending_export = None
        self._applying_variant = self._active_apply = False
        self._clone_stroke = self._clone_undo = None
        self._clone_source = self._clone_offset = None
        self.bump_windows = []
        self._last_mode = 0
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
        self.clone_button = QPushButton("印章畫筆")
        self.clone_button.setCheckable(True)
        self.clone_button.toggled.connect(self.toggle_clone)
        source_tools.addWidget(self.clone_button)
        self.dodge_button = QPushButton("明暗筆刷")
        self.dodge_button.setCheckable(True)
        self.dodge_button.toggled.connect(lambda enabled: self.toggle_clone(enabled, "dodge"))
        source_tools.addWidget(self.dodge_button)
        source_tools.addStretch()
        center.addLayout(source_tools)
        self.clone_tools = QWidget()
        brush_tools = QHBoxLayout(self.clone_tools)
        brush_tools.setContentsMargins(0, 0, 0, 0)
        self.clone_pick_button = QPushButton("選取參考點")
        self.clone_pick_button.setCheckable(True)
        self.clone_pick_button.toggled.connect(lambda checked: setattr(self.preview, "pick_clone_source", checked))
        brush_tools.addWidget(self.clone_pick_button)
        self.dodge_mode = QComboBox()
        self.dodge_mode.addItems(["刷亮", "刷暗"])
        brush_tools.addWidget(self.dodge_mode)
        self.clone_undo_button = QPushButton("復原上一筆")
        self.clone_undo_button.clicked.connect(self.undo_clone)
        self.clone_undo_button.setEnabled(False)
        brush_tools.addWidget(self.clone_undo_button)
        brush_tools.addWidget(QLabel("大小"))
        self.clone_size = PercentControl(64, 1, 512, " px", resettable=True)
        self.clone_size.setToolTip("完整解析度的畫筆直徑；最大以素材短邊為限")
        self.clone_size.valueChanged.connect(self.update_clone_size)
        brush_tools.addWidget(self.clone_size, 1)
        brush_tools.addWidget(QLabel("透明度"))
        self.clone_opacity = PercentControl(50, resettable=True)
        self.clone_opacity.setToolTip("0% 不修改，100% 完全複製；同一筆不會因重複經過而加深")
        brush_tools.addWidget(self.clone_opacity, 1)
        center.addWidget(self.clone_tools)
        self.clone_tools.hide()
        self.crop_hint = QLabel("框選後僅使用範圍內的素材製圖；完成後按「儲存檔案」")
        self.crop_hint.setWordWrap(True)
        center.addWidget(self.crop_hint)
        self.preview = Preview()
        self.preview.cropChanged.connect(self.set_crop)
        self.preview.clonePicked.connect(self.pick_clone)
        self.preview.cloneStarted.connect(self.begin_clone)
        self.preview.cloneMoved.connect(self.move_clone)
        self.preview.cloneEnded.connect(self.finish_clone)
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
        self.mode.addItems(["無縫貼圖", "隨機變體", "木地板", "建立 BUMP"])
        right.addRow("製圖模式", self.mode)
        self.light = PercentControl(85, resettable=True)
        right.addRow("去暗角／陰影", self.light)
        self.material_saturation = PercentControl(100, 0, 200, resettable=True)
        self.material_saturation.setToolTip("100% 保留原飽和度，0% 轉為灰階")
        right.addRow("飽和度", self.material_saturation)
        self.material_brightness = PercentControl(0, -100, 100, resettable=True)
        self.material_brightness.setToolTip("0% 保留原明暗；向右變亮，向左變暗")
        right.addRow("明暗度", self.material_brightness)
        self.color_tools = color_tools = QWidget()
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
        self.shift_x = PercentControl(20, resettable=True)
        self.shift_y = PercentControl(20, resettable=True)
        self.shift_x.setToolTip("每張素材各自隨機左右位移；數值是最大幅度，100% 為一張素材寬，0% 不位移；右鍵恢復 20%")
        self.shift_y.setToolTip("每張素材各自隨機上下位移；數值是最大幅度，100% 為一張素材高，0% 不位移；右鍵恢復 20%")
        right.addRow("X 軸隨機位移", self.shift_x)
        right.addRow("Y 軸隨機位移", self.shift_y)
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
        right.addRow("單張素材大小", self.resolution)
        self.size_hint = QLabel("自動保留比例；木地板整面尺寸自動計算")
        self.size_hint.setWordWrap(True)
        right.addRow(self.size_hint)
        self.shuffle_button = QPushButton("換一組排列")
        self.shuffle_button.clicked.connect(self.reshuffle)
        right.addRow(self.shuffle_button)
        self.primary_button = QPushButton("一鍵製圖")
        self.primary_button.clicked.connect(self.primary_action)
        right.addRow(self.primary_button)
        self.reset_button = QPushButton("回到原圖")
        self.reset_button.setToolTip("清除本次素材的修改，回到匯入時的原圖；不改寫磁碟上的檔案")
        self.reset_button.clicked.connect(self.reset_original)
        right.addRow(self.reset_button)
        for text, function in [("取消", self.cancel),
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
                        self.material_scale, self.material_angle, self.shift_x, self.shift_y):
            control.valueChanged.connect(self.request_preview)
        for control in (self.board_width, self.board_length, self.gap):
            control.valueChanged.connect(self.request_preview)
        for control in (self.pattern, self.resolution):
            control.currentIndexChanged.connect(self.request_preview)
        self.direction.toggled.connect(self.request_preview)
        self.edit_controls = (self.mode, self.light, self.material_saturation, self.material_brightness,
                              self.material_scale, self.material_angle, self.shift_x, self.shift_y,
                              self.color_button, self.clear_color_button, self.direction, self.pattern,
                              self.board_width, self.board_length, self.gap, self.resolution, self.shuffle_button,
                              self.primary_button)
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
        if mode == 3:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self._last_mode)
            self.mode.blockSignals(False)
            self.open_bump()
            return
        self._last_mode = mode
        self.primary_button.setText("儲存變更" if mode == 1 else "一鍵製圖")
        self.quick_form.setRowVisible(self.reset_button, mode == 0)
        for widget in (self.light, self.material_saturation, self.material_brightness, self.color_tools):
            self.quick_form.setRowVisible(widget, mode != 1)
        for widget in (self.direction, self.shift_x, self.shift_y):
            self.quick_form.setRowVisible(widget, mode == 1)
        for widget in (self.pattern, self.board_width, self.board_length, self.gap):
            self.quick_form.setRowVisible(widget, mode == 2)
        self.quick_form.setRowVisible(self.shuffle_button, mode != 0)
        self.shuffle_button.setText("換一組變體" if mode == 1 else "換一組排列")
        self.size_hint.setText("單張整面自動為 1K；存檔依預覽數量鋪排" if mode == 2 else
                               "每份素材保留像素；4×4 隨機排列會擴大整張尺寸" if mode == 1 else
                               "單張保留原始比例；存檔依預覽數量鋪排")
        self.request_preview()

    def reset_original(self):
        path = self.current_path()
        if self.thread is not None or self._applying_variant:
            return
        if path not in self._imported_sources:
            self.error("請先匯入圖片")
            return
        self.preview_timer.stop()
        self._pending_preview = False
        self._pending_export = None
        self.clone_button.setChecked(False)
        self.dodge_button.setChecked(False)
        self._restoring = True
        try:
            self._generation += 1
            image = self._imported_sources[path]
            self._working_sources[path] = image
            self._staged_sources.add(path)
            self._source_cache.clear()
            self.regions.pop(path, None)
            self._clone_stroke = self._clone_undo = None
            self._clone_source = self._clone_offset = None
            self.mode.setCurrentIndex(0)
            self.crop_button.setChecked(False)
            self.fill_button.setChecked(False)
            self.repeat.setCurrentText("1")
            self.light.setValue(0)
            self.material_saturation.setValue(100)
            self.material_brightness.setValue(0)
            self.material_scale.setValue(100)
            self.material_angle.setValue(0)
            self.clear_color()
            self.shift_x.setValue(20)
            self.shift_y.setValue(20)
            self.direction.setChecked(True)
            self.board_width.setValue(150)
            self.board_length.setValue(900)
            self.gap.setValue(2)
            self.pattern.setCurrentIndex(self.pattern.findData("half"))
            self.resolution.setCurrentIndex(0)
            self.seed_value = 42
            self.loaded(image, path)
            self.outputs = [("base_color", image)]
            self.processed_settings = self.snapshot()
            self.metrics.setText("已回到匯入時的原圖，所有素材修改已清除")
        finally:
            self._restoring = False

    def open_bump(self):
        if self.original is None or self.original_path != self.current_path():
            self.error("請先匯入圖片，並等待載入完成")
            return
        if self._pending_export is not None or self._applying_variant:
            self.error("正在儲存，請稍候")
            return
        request = {"snapshot": self.snapshot(), "bump": True}
        self.lock_variant(True)
        self.preview_timer.stop()
        self.process(export_request=request)

    def show_bump(self, image, snapshot):
        from .bump_ui import BumpDialog
        source = snapshot["inputs"][snapshot["index"]]
        dialog = BumpDialog(image, source, self, snapshot["inputs"])
        self.bump_windows.append(dialog)
        dialog.finished.connect(lambda _: self.bump_windows.remove(dialog))
        dialog.show()

    def primary_action(self):
        if self.mode.currentIndex() != 1:
            self.process()
            return
        self.prepare_material()

    def prepare_material(self, clone=False):
        if self.original is None or self.original_path != self.current_path():
            self.error("請先匯入圖片，並等待載入完成")
            return False
        if self._pending_export is not None or self._applying_variant:
            self.error("正在儲存，請稍候")
            return False
        request = {"snapshot": self.snapshot(), "apply_variant": True, "clone": clone}
        self.lock_variant(True)
        self.preview_timer.stop()
        self.process(export_request=request)
        return True

    def lock_variant(self, locked):
        self._applying_variant = locked
        for control in self.edit_controls:
            control.setEnabled(not locked and not self.preview.clone_mode)
        self.save_button.setEnabled(not locked)

    def toggle_clone(self, enabled, kind="clone"):
        button = self.dodge_button if kind == "dodge" else self.clone_button
        if enabled:
            other = self.clone_button if kind == "dodge" else self.dodge_button
            other.setChecked(False)
            # Switching tools on the accepted working material needs no render.
            if self.preview.clone_mode:
                self.finish_clone()
                self.activate_clone(kind)
                self.lock_variant(False)
            elif not self.prepare_material(clone=kind):
                button.setChecked(False)
        else:
            other = self.clone_button if kind == "dodge" else self.dodge_button
            if other.isChecked():
                return
            self.finish_clone()
            self.preview.set_clone_mode(False)
            self._clone_source = self._clone_offset = self._clone_undo = None
            self.clone_tools.hide()
            self.clone_pick_button.setChecked(False)
            self.lock_variant(self._applying_variant)
            self.crop_button.setEnabled(self.thread is None and not self._applying_variant)
            self.full_image_button.setEnabled(self.crop_button.isEnabled())
            self.crop_hint.setText("框選後僅使用範圍內的素材製圖；完成後按「儲存檔案」")

    def activate_clone(self, kind="clone"):
        self._clone_source = self._clone_offset = self._clone_undo = None
        self.preview.brush_kind = kind
        self.preview.set_clone_mode(True)
        self.clone_tools.show()
        self.clone_pick_button.setVisible(kind == "clone")
        self.dodge_mode.setVisible(kind == "dodge")
        self.clone_undo_button.setEnabled(False)
        self.update_clone_size()
        if kind == "dodge":
            self.crop_hint.setText("選擇刷亮／刷暗後拖曳塗抹；大小與透明度控制範圍及程度；中鍵平移；再按「明暗筆刷」離開")
            self.metrics.setText("明暗筆刷已就緒，可選擇刷亮或刷暗")
            self.clone_opacity.setToolTip("0% 不修改，100% 改變一級曝光；同一筆重複經過不累加，另畫一筆可繼續調整")
        else:
            self.crop_hint.setText("Alt＋點擊或按「選取參考點」取樣，再拖曳塗抹；中鍵拖曳平移；再按「印章畫筆」離開")
            self.metrics.setText("印章畫筆已就緒，請先選取參考點")
            self.clone_opacity.setToolTip("0% 不修改，100% 完全複製；同一筆不會因重複經過而加深")

    def update_clone_size(self, *_):
        self.preview.clone_diameter = self.clone_size.value()
        self.preview.viewport().update()

    def pick_clone(self, point):
        self._clone_source = QPointF(point)
        self._clone_offset = None
        self.clone_pick_button.setChecked(False)
        self.metrics.setText("已選取參考點，可拖曳塗抹；Alt＋點擊重新取樣")
        self.preview.viewport().update()

    def begin_clone(self, point):
        if self.thread is not None or self.result is None:
            return
        if self.preview.brush_kind == "clone" and self._clone_source is None:
            self.metrics.setText("請先 Alt＋點擊，或按「選取參考點」後點擊圖面")
            return
        h, w = self.result.shape[:2]
        if self.preview.brush_kind == "dodge":
            self._clone_stroke = PeriodicDodgeStroke(self.result, self.clone_size.value(), self.clone_opacity.value()/100,
                                                    lighten=self.dodge_mode.currentIndex() == 0)
        else:
            if self._clone_offset is None:
                self._clone_offset = self._clone_source-point
            offset = (self._clone_offset.x()*w, self._clone_offset.y()*h)
            self._clone_stroke = PeriodicCloneStroke(self.result, offset, self.clone_size.value(), self.clone_opacity.value()/100)
        self.save_button.setEnabled(False)
        self.clone_undo_button.setEnabled(False)
        self.move_clone(point)

    def move_clone(self, point):
        if self._clone_stroke is None:
            return
        h, w = self._clone_stroke.image.shape[:2]
        self._clone_stroke.paint_to((point.x()*w-.5, point.y()*h-.5))
        self.result = self._clone_stroke.image
        self.show_clone_result()

    def show_clone_result(self):
        self.preview.show_image(self.result, int(self.repeat.currentText()), fill=self.fill_button.isChecked(), preserve_view=True)

    def finish_clone(self):
        stroke, self._clone_stroke = self._clone_stroke, None
        if stroke is None:
            return
        if stroke.changed:
            self._clone_undo = stroke.base
            self.store_clone_result(stroke.image)
            self.metrics.setText("筆觸已同步套用全部重複貼圖；可復原上一筆")
        else:
            self.result = stroke.base
        self.save_button.setEnabled(True)
        self.clone_undo_button.setEnabled(self._clone_undo is not None)

    def store_clone_result(self, image):
        path = self.current_path()
        self.original = self.result = image
        self._working_sources[path] = image
        self._staged_sources.add(path)
        self._source_cache.clear()
        self._generation += 1
        self.outputs = [("base_color", image)]
        self.previous_outputs = []
        self._previous_snapshot = None
        self.processed_settings = self.snapshot()
        self.show_clone_result()

    def undo_clone(self):
        if self._clone_undo is None or self._clone_stroke is not None or self.thread is not None:
            return
        image, self._clone_undo = self._clone_undo, None
        self.store_clone_result(image)
        self.clone_undo_button.setEnabled(False)
        self.metrics.setText("已復原上一筆筆觸")

    def apply_variant(self, image, snapshot):
        path = snapshot["inputs"][snapshot["index"]]
        self._restoring = True
        try:
            self._working_sources[path] = image
            self._staged_sources.add(path)
            self._source_cache.clear()
            self.regions.pop(path, None)
            self.preview_timer.stop()
            self._pending_preview = False
            self._generation += 1
            # These adjustments have been baked into the new working material.
            self.light.setValue(0)
            self.material_saturation.setValue(100)
            self.material_brightness.setValue(0)
            self.material_scale.setValue(100)
            self.material_angle.setValue(0)
            self.clear_color()
            self.resolution.setCurrentIndex(0)
            self.mode.setCurrentIndex(0)
            self.loaded(image, path)
            self.outputs = [("base_color", image)]
            self.processed_settings = self.snapshot()
            self.metrics.setText("已儲存變更，可繼續修改無縫貼圖；寫入圖片請按「儲存檔案」")
        finally:
            self._restoring = False

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
            self.update_source_info()

    def reset_crop(self):
        path = self.current_path()
        if path is not None:
            self.regions.pop(path, None)
            self._generation += 1
            self.preview_timer.stop()
            self._pending_preview = False
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
        if self.thread is not None or self._applying_variant:
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
        if self.thread is not None or self._applying_variant:
            return
        index = self.assets.currentRow()
        if index >= 0:
            self.clone_button.setChecked(False)
            self.dodge_button.setChecked(False)
            path = self.paths.pop(index)
            self.regions.pop(path, None)
            self._working_sources.pop(path, None)
            self._imported_sources.pop(path, None)
            self._staged_sources.discard(path)
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
                self._imported_sources.clear()
                self._staged_sources.clear()
                self.preview.clear_image()
                self.info.setText("先匯入圖片，再按一鍵製圖")

    def select_asset(self, index):
        if not 0 <= index < len(self.paths):
            return
        path = self.paths[index]
        self.clone_button.setChecked(False)
        self.dodge_button.setChecked(False)
        self._generation += 1
        self.save_button.setEnabled(False)
        self.run_job(lambda progress: self._working_sources[path] if path in self._working_sources else load_image(path),
                     lambda image: self.loaded(image, path))

    def loaded(self, image, path=None):
        self.original = image
        self.original_path = path or self.current_path()
        self._imported_sources.setdefault(self.original_path, image)
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
        if mode == 1:
            output_w, output_h = output_w*4, output_h*4
        data = {"mode": mode, "light": self.light.value()/100, "seed": self.seed_value,
                "board_width": width, "board_length": length, "gap": self.gap.value(),
                "world_width": length*4, "world_height": width*12,
                "min_length": length*.5, "max_length": length*4/3,
                "brightness": .03, "direction": self.direction.isChecked(),
                "pattern": self.pattern.currentData(),
                "width": output_w, "height": output_h,
                "output_size": edge,
                "shift_x": self.shift_x.value()/100, "shift_y": self.shift_y.value()/100,
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
                "source_baselines": baselines, "staged_paths": self._staged_sources.copy(),
                "repeat_count": int(self.repeat.currentText())}

    def prepared_source(self, path, region, strength, baselines, staged_paths=()):
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
            if not (path in staged_paths and region is None and strength == 0):
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
        self._active_apply = bool(export_request and (export_request.get("apply_variant") or export_request.get("bump")))
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
            if not preview:
                repeats = snapshot["repeat_count"] if export_request and not (export_request.get("apply_variant") or export_request.get("bump")) else 1
                if settings["width"]*settings["height"]*repeats*repeats > 160_000_000:
                    raise ValueError("鋪排後超過 1.6 億像素，請降低預覽數量或單張素材大小；不會自動縮小像素")
            if settings["mode"] != 2:
                image = self.prepared_source(paths[index], regions.get(paths[index]), settings["light"], snapshot["source_baselines"], snapshot["staged_paths"])
                progress(25)
                divisor = 4 if settings["mode"] == 1 else 1
                size = (max(4, settings["width"]//divisor), max(4, settings["height"]//divisor))
                if (image.shape[1], image.shape[0]) != size:
                    image = cv2.resize(image, size, interpolation=cv2.INTER_AREA if preview else cv2.INTER_CUBIC)
                image = appearance(image)
                progress(60)
                if settings["mode"] == 0:
                    outputs = [("base_color", image)]
                else:
                    from .variants import generate_variants, stagger_tiles
                    variants = generate_variants(
                        image, count=1, seed=settings["seed"], direction=settings["direction"],
                        mirror=False, progress=progress, brightness=0, hue=0,
                        saturation=0, contrast=0, translate=False)
                    outputs = [(f"variant_{i:02d}", stagger_tiles(result, settings["shift_x"], settings["shift_y"],
                                                               settings["seed"], progress, output_size=(settings["width"], settings["height"])))
                               for i, result in enumerate(variants)]
            else:
                from .boards import BoardSettings, generate_boards
                images = []
                for i, path in enumerate(paths):
                    image = self.prepared_source(path, regions.get(path), settings["light"], snapshot["source_baselines"], snapshot["staged_paths"])
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
            if export_request and not (export_request.get("apply_variant") or export_request.get("bump")):
                progress(97)
                _, selected = outputs[0]
                if export_request.get("overwrite"):
                    replace_source(selected, export_request["path"], export_request["signature"], repeat=snapshot["repeat_count"])
                else:
                    self.export_to(export_request["path"], selected, paths, repeat=snapshot["repeat_count"])
            return outputs

        def completed(outputs):
            if export_request and export_request.get("bump"):
                self.show_bump(outputs[0][1], snapshot)
                return
            if export_request and export_request.get("apply_variant"):
                self.apply_variant(outputs[0][1], snapshot)
                if export_request.get("clone"):
                    self.activate_clone(export_request["clone"])
                return
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
                count = snapshot["repeat_count"]
                h, w = outputs[0][1].shape[:2]
                self.metrics.setText(f"已儲存：{Path(export_request['path']).name} · {w*count} × {h*count} px")
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
        self.clone_button.setEnabled(False)
        self.dodge_button.setEnabled(False)
        self.clone_tools.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.preview.clone_suspended = True
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
        if self._active_apply:
            self._active_apply = False
            self.lock_variant(False)
        self.preview.clone_suspended = False
        self.clone_button.setEnabled(not self._applying_variant)
        self.dodge_button.setEnabled(not self._applying_variant)
        self.clone_tools.setEnabled(True)
        if not self._applying_variant and self.clone_button.isChecked() and not self.preview.clone_mode:
            self.clone_button.setChecked(False)
        if not self._applying_variant and self.dodge_button.isChecked() and not self.preview.clone_mode:
            self.dodge_button.setChecked(False)
        self.assets.setEnabled(not self._applying_variant)
        self.crop_button.setEnabled(not self._applying_variant and not self.preview.clone_mode)
        self.full_image_button.setEnabled(not self._applying_variant and not self.preview.clone_mode)
        self.capture_button.setEnabled(not self._applying_variant)
        self.save_button.setEnabled(not self._applying_variant)
        self.reset_button.setEnabled(not self._applying_variant)
        if self._pending_export is not None:
            request, self._pending_export = self._pending_export, None
            self.process(export_request=request)
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
        if self._applying_variant and not self._active_apply:
            self.lock_variant(False)
        if self.thread:
            self.thread.requestInterruption()

    def processed(self, outputs):
        self.previous_outputs = self.outputs
        self.outputs = outputs
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
            for name in ("shift_x", "shift_y"):
                getattr(self, name).setValue(settings[name]*100)
            self.tint_color = settings["tint"].copy() if settings["tint"] else None
            color = QColor.fromRgbF(*self.tint_color) if self.tint_color else None
            self.color_button.setText(color.name() if color else "上色…")
            self.color_button.setStyleSheet(f"border: 2px solid {color.name()};" if color else "")
            for name in ("board_width", "board_length", "gap"):
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

    def export_to(self, path, image, source_paths=None, repeat=1):
        if Path(path).suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError("請使用 .jpg 或 .jpeg 輸出")
        if Path(path).is_file() and Path(path).resolve() in {Path(source).resolve() for source in (source_paths if source_paths is not None else self.paths)}:
            raise ValueError("不可覆寫原始素材")
        save_image(image, path, repeat=repeat)

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
            closed = [dialog.close() for dialog in self.bump_windows.copy()]
            if not all(closed):
                event.ignore()
                return
            self._closing = True
            if self._capture_temp is not None:
                self._capture_temp.cleanup()
            event.accept()


def main():
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    return app.exec()
