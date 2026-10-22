import numpy as np
from texture_studio.maps import derive_maps


def test_flat_material_and_normal_unit_vectors():
    image = np.full((32, 64, 3), .5, "float32")
    maps = derive_maps(image)
    np.testing.assert_allclose(maps["normal_reference"], np.broadcast_to([.5, .5, 1], image.shape), atol=1e-6)
    assert np.ptp(maps["height_reference"]) == 0


def test_gap_height_and_normal_variation():
    image = np.full((32, 64, 3), .5, "float32")
    height = np.ones((32, 64), "float32")
    height[:, 30:34] = 0
    maps = derive_maps(image, height=height)
    assert maps["height_reference"][:, 31].mean() < maps["height_reference"][:, 10].mean()
    normal = maps["normal_reference"]*2-1
    np.testing.assert_allclose(np.linalg.norm(normal, axis=2), 1, atol=1e-6)
    assert np.std(normal[..., 0]) > 0
