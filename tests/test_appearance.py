import numpy as np
from texture_studio.appearance import adjust_material
from texture_studio.core import seam_quality


def test_color_replacement_preserves_grain_and_removes_original_chroma():
    y, x = np.mgrid[:64, :64]
    original = np.stack((.35+.05*np.sin(x), .45+.04*np.cos(y), .25+.03*np.sin(x+y)), axis=2).astype("float32")
    before = original.copy()
    target = [.2, .6, .3]
    result = adjust_material(original, tint=target)
    np.testing.assert_allclose(result.mean(axis=(0, 1)), target, atol=1e-5)
    np.testing.assert_allclose(result[..., 0]/result[..., 1], target[0]/target[1], atol=1e-6)
    assert np.std(result[..., 1]) > .01
    np.testing.assert_array_equal(original, before)


def test_saturation_and_brightness_are_real_pixel_edits():
    image = np.full((32, 32, 3), [.2, .3, .4], dtype="float32")
    gray = adjust_material(image, saturation=0)
    np.testing.assert_allclose(gray[..., 0], gray[..., 2], atol=1e-6)
    np.testing.assert_allclose(adjust_material(image, brightness=.5), image*2, atol=1e-6)
    np.testing.assert_allclose(adjust_material(image, brightness=-.5), image*.5, atol=1e-6)
    np.testing.assert_array_equal(adjust_material(image), image)


def test_zoom_changes_motif_size_without_changing_canvas():
    y, x = np.mgrid[:128, :128]
    image = np.repeat((.5+.1*np.cos(2*np.pi*8*x/128))[..., None], 3, axis=2).astype("float32")
    def frequency(result):
        row = result.mean(axis=0)[:, 0]
        return np.argmax(abs(np.fft.rfft(row-row.mean())))
    assert frequency(adjust_material(image, scale=2)) == 4
    assert frequency(adjust_material(image, scale=.5)) == 16
    assert adjust_material(image, scale=2).shape == image.shape
    rotated = adjust_material(image, angle=90)
    assert np.std(rotated.mean(axis=1)[:, 0]) > .05
    assert np.std(rotated.mean(axis=0)[:, 0]) < .005


def test_arbitrary_rotation_has_no_empty_corners_and_keeps_center():
    image = np.full((80, 120, 3), .4, dtype="float32")
    np.testing.assert_allclose(adjust_material(image, angle=33, scale=.5), image, atol=1e-6)
    y, x = np.mgrid[:129, :129]
    spot = .3+.2*np.exp(-((x-64)**2+(y-64)**2)/100)
    image = np.repeat(spot[..., None], 3, axis=2).astype("float32")
    result = adjust_material(image, angle=37, scale=1.5)
    assert np.unravel_index(result[..., 0].argmax(), result.shape[:2]) == (64, 64)
    quality = seam_quality(result)
    assert max(quality["left_right"], quality["top_bottom"]) < .01
