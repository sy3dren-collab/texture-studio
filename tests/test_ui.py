import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
from PySide6.QtWidgets import QApplication
from texture_studio.ui import Window
from texture_studio.core import save_image


def test_phase1_real_worker_and_jpeg_export(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window()
    errors = []
    window.error = errors.append
    image = np.random.default_rng(3).uniform(.2, .8, (64, 96, 3)).astype("float32")
    source = tmp_path / "測試原圖.png"
    save_image(image, source)
    original_bytes = source.read_bytes()
    window.add_paths([str(source)])
    def wait():
        deadline = time.monotonic() + 15
        while window.thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.thread is None
        assert not errors
    wait()
    window.process()
    wait()
    assert len(window.outputs) == 1
    assert window.result.shape == image.shape
    assert window.processed_settings["settings"]["seed"] == 42
    output = tmp_path / "輸出.jpg"
    window.export_to(output, window.result)
    assert output.is_file()
    from PIL import Image
    with Image.open(output) as exported:
        assert exported.format == "JPEG"
    assert source.read_bytes() == original_bytes
    window.close()
