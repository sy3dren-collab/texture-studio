import numpy as np
import pytest
from texture_studio.core import correct_lighting, seamless, seam_quality, save_image, load_image, crop_image


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


@pytest.mark.parametrize("kind", ["vignette", "bottom_shadow", "side_gradient"])
def test_strong_shadow_removal_preserves_real_texture(kind):
    y, x = np.mgrid[-1:1:256j, -1:1:192j]
    texture = .55+.035*np.sin(2*np.pi*20*x)*np.cos(2*np.pi*17*y)
    # A narrow dark natural vein must remain distinguishable after correction.
    vein = np.abs(x-.12*np.sin(y*5)) < .025
    texture[vein] *= .45
    illumination = {"vignette": np.exp(-.6*(x*x+y*y)),
        "bottom_shadow": .3+.7/(1+np.exp((y-.65)*14)),
        "side_gradient": .35+.65*(x+1)/2}[kind]
    image = np.repeat((texture*illumination)[..., None], 3, axis=2).astype("float32")
    output = correct_lighting(image, strength=1)[..., 0]
    # Compare to known clean material, not a flatness score that rewards
    # erasing the dark vein along with the shadow.
    before = np.log(np.maximum(image[..., 0], 1e-6)/texture)
    after = np.log(np.maximum(output, 1e-6)/texture)
    assert np.std(after) < .28*np.std(before)
    assert output[vein].mean() < output[~vein].mean()*.65
    # Texture contrast relative to its local brightness should survive.
    np.testing.assert_allclose(output[vein].mean()/output[~vein].mean(),
                               texture[vein].mean()/texture[~vein].mean(), rtol=.12)


def test_lighting_keeps_color_and_uniform_material():
    image = np.broadcast_to(np.array([.12, .32, .55], "float32"), (64, 96, 3)).copy()
    np.testing.assert_allclose(correct_lighting(image), image, atol=2e-5)
    y, x = np.mgrid[-1:1:64j, -1:1:96j]
    shaded = image*np.exp(-.5*(x*x+y*y))[..., None]
    output = correct_lighting(shaded.astype("float32"), 1)
    np.testing.assert_allclose(output[..., 0]/output[..., 1], .12/.32, atol=1e-6)


def test_source_region_is_exact_and_non_destructive():
    image = np.random.default_rng(5).random((80, 120, 3), dtype=np.float32)
    before = image.copy()
    selected = crop_image(image, [.25, .125, .75, .875])
    np.testing.assert_array_equal(selected, image[10:70, 30:90])
    seamless(correct_lighting(selected))
    np.testing.assert_array_equal(image, before)
    for region in ([-.1, 0, 1, 1], [0, 0, float("nan"), 1], [0, 0, .001, .001], [1, 1, 0, 0]):
        with pytest.raises(ValueError):
            crop_image(image, region)


def test_default_pipeline_removes_repeated_bottom_shadow_band():
    y, x = np.mgrid[-1:1:256j, -1:1:192j]
    material = .55+.035*np.sin(20*np.pi*x)*np.cos(17*np.pi*y)
    shaded = material*(.3+.7/(1+np.exp((y-.65)*14)))
    image = np.repeat(shaded[..., None], 3, axis=2).astype("float32")
    output = seamless(correct_lighting(image))[..., 0]
    # Flatness relative to a known textured target detects the repeating dark
    # stripe without rewarding blurring away the material.
    before = np.std(np.log(shaded/material))
    after = np.std(np.log(np.maximum(output, 1e-6)/material))
    assert after < before*.2
