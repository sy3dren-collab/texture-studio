import numpy as np
import pytest
from PIL import Image
from texture_studio.core import save_image
from texture_studio.storage import replace_source, file_signature


@pytest.mark.parametrize("suffix,format_name", [(".png", "PNG"), (".jpg", "JPEG"), (".tiff", "TIFF"), (".bmp", "BMP")])
def test_explicit_source_replacement_retains_real_format(tmp_path, suffix, format_name):
    path = tmp_path / ("原始素材"+suffix)
    save_image(np.full((16, 24, 3), .7, "float32"), path)
    modified = np.full((32, 48, 3), [.2, .3, .4], "float32")
    replace_source(modified, path, file_signature(path))
    with Image.open(path) as image:
        image.load()
        assert image.format == format_name
        assert image.size == (48, 32)
        np.testing.assert_allclose(np.asarray(image).mean(axis=(0, 1))/255, [.2, .3, .4], atol=.01)
    assert not list(tmp_path.glob(".texture-save-*"))


def test_failed_replace_preserves_original_bytes(tmp_path, monkeypatch):
    import texture_studio.storage as storage
    path = tmp_path / "原圖.png"
    save_image(np.full((16, 24, 3), .7, "float32"), path)
    before = path.read_bytes()
    def fail(*args):
        raise OSError("simulated replacement failure")
    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failure"):
        replace_source(np.zeros((16, 24, 3), "float32"), path, file_signature(path))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".texture-save-*"))


def test_external_change_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "原圖.png"
    save_image(np.full((16, 24, 3), .7, "float32"), path)
    expected = file_signature(path)
    save_image(np.full((32, 24, 3), .2, "float32"), path)
    changed = path.read_bytes()
    with pytest.raises(OSError, match="外部變更"):
        replace_source(np.zeros((16, 24, 3), "float32"), path, expected)
    assert path.read_bytes() == changed


def test_invalid_render_never_replaces_source(tmp_path):
    path = tmp_path / "原圖.png"
    save_image(np.full((16, 24, 3), .7, "float32"), path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="無效數值"):
        replace_source(np.full((16, 24, 3), np.nan, "float32"), path, file_signature(path))
    assert path.read_bytes() == before


def test_confirmed_replacement_saves_whole_preview_grid(tmp_path):
    path = tmp_path / "整張預覽.png"
    tile = np.random.default_rng(42).random((24, 40, 3), dtype=np.float32)
    save_image(tile, path)
    replace_source(tile, path, file_signature(path), repeat=3)
    with Image.open(path) as image:
        assert image.size == (120, 72)
        expected = np.tile(np.round(tile*255).astype("uint8"), (3, 3, 1))
        np.testing.assert_array_equal(np.asarray(image), expected)
