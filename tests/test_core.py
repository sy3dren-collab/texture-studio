import numpy as np
import pytest
from texture_studio.core import correct_lighting, seamless, seam_quality, save_image, load_image


@pytest.mark.parametrize("kind", ["wood", "stone", "fabric"])
def test_periodic_reconstruction(kind):
    y, x = np.mgrid[:128, :128] / 128
    wave = {"wood": np.sin(2 * np.pi * (8 * x + np.sin(2 * np.pi * y) * .2)),
            "stone": np.sin(2 * np.pi * (3 * x + 2 * y)),
            "fabric": np.cos(2 * np.pi * 16 * x) * np.cos(2 * np.pi * 16 * y)}[kind]
    texture = .5 + .08 * wave
    image = np.repeat((texture + .25 * x + .15 * y)[..., None], 3, axis=2).astype("float32")
    result = seamless(image)
    before, after = seam_quality(image), seam_quality(result)
    assert after["left_right"] < before["left_right"] * .5
    assert after["top_bottom"] < before["top_bottom"] * .5
    # Local high-frequency detail survives away from the boundaries.
    assert np.std(np.diff(result[32:96, 32:96, 0], axis=1)) > .9 * np.std(np.diff(image[32:96, 32:96, 0], axis=1))


def test_lighting_reduces_broad_gradient():
    image = np.broadcast_to(np.linspace(.2, .8, 128)[None, :, None], (128, 128, 3)).copy().astype("float32")
    out = correct_lighting(image, 1, .1, 0)
    assert abs(out[:, :16].mean() - out[:, -16:].mean()) < .6 * abs(image[:, :16].mean() - image[:, -16:].mean())
    np.testing.assert_array_equal(correct_lighting(image, 0), image)


def test_unicode_roundtrip(tmp_path):
    image = np.full((16, 32, 3), .4, dtype="float32")
    path = tmp_path / "木紋測試.png"
    save_image(image, path)
    np.testing.assert_allclose(load_image(path), image, atol=1 / 255)
