import numpy as np
from texture_studio.variants import generate_variants, periodic_rotate
from texture_studio.core import seam_quality


def texture():
    y, x = np.mgrid[:64, :64] / 64
    return np.repeat((.5 + .1 * np.cos(2*np.pi*4*x) * np.sin(2*np.pi*3*y))[..., None], 3, axis=2).astype("float32")


def test_seed_reproducible_and_different():
    image = texture()
    first = generate_variants(image, 4, 12)
    second = generate_variants(image, 4, 12)
    other = generate_variants(image, 4, 13)
    assert all(np.array_equal(a, b) for a, b in zip(first, second))
    assert any(not np.array_equal(a, b) for a, b in zip(first, other))


def test_arbitrary_rotation_restores_boundary():
    image = texture()
    result = periodic_rotate(image, 33)
    quality = seam_quality(result)
    assert max(quality["left_right"], quality["top_bottom"]) < .04
    assert result.shape == image.shape


def test_direction_and_disabled_changes():
    image = texture()
    variants = generate_variants(image, 4, seed=3, direction=True, mirror=False,
        brightness=0, hue=0, saturation=0, contrast=0, translate=False)
    assert all(np.array_equal(v, image) or np.array_equal(v, np.rot90(image, 2)) for v in variants)
