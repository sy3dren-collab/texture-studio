import numpy as np
from texture_studio.bump import make_bump, bump_normal


def test_bump_uses_luminance_and_independent_brightness_contrast():
    image = np.full((32, 64, 3), [.2, .4, .8], dtype="float32")
    before = image.copy()
    base = make_bump(image)
    np.testing.assert_allclose(base, .2126*.2+.7152*.4+.0722*.8, atol=1e-7)
    np.testing.assert_allclose(make_bump(image, .1, 2), (base-.5)*2+.6, atol=1e-7)
    np.testing.assert_allclose(make_bump(image, -1), 0)
    np.testing.assert_allclose(make_bump(image, 1), 1)
    np.testing.assert_array_equal(image, before)


def test_bump_normals_are_unit_vectors_use_periodic_derivatives_and_opengl_y():
    y, x = np.mgrid[:64, :96]
    height = (.5+.1*np.sin(2*np.pi*x/96)+.1*np.sin(2*np.pi*y/64)).astype("float32")
    normal = bump_normal(height, 4)*2-1
    np.testing.assert_allclose(np.linalg.norm(normal, axis=2), 1, atol=1e-6)
    assert normal[0, 0, 0] < 0
    assert normal[0, 0, 1] > 0
    assert np.abs(normal[:, 0]-normal[:, -1]).max() < .002
    assert np.abs(normal[0]-normal[-1]).max() < .002
    np.testing.assert_allclose(bump_normal(height, 0), np.broadcast_to([.5, .5, 1], normal.shape))
