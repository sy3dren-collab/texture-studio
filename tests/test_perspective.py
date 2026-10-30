import cv2
import numpy as np
import pytest

from texture_studio.perspective import perspective_geometry, rectify_perspective


def test_identity_keeps_every_pixel_and_original_size():
    image = np.random.default_rng(4).random((73, 109, 3), dtype=np.float32)
    corrected = rectify_perspective(image, [(0, 0), (1, 0), (1, 1), (0, 1)])
    assert corrected.shape == image.shape
    np.testing.assert_allclose(corrected, image, atol=1e-6)


def test_rectifies_a_known_projective_distortion():
    y, x = np.mgrid[:120, :180]
    image = np.stack((x/179, y/119, ((x//20+y//20) % 2)*.7+.15), axis=-1).astype(np.float32)
    source = np.float32([[0, 0], [179, 0], [179, 119], [0, 119]])
    target = np.float32([[30, 30], [234, 12], [260, 160], [16, 150]])
    transform = cv2.getPerspectiveTransform(source, target)
    photo = cv2.warpPerspective(image, transform, (280, 180), flags=cv2.INTER_LINEAR)
    corrected = rectify_perspective(photo, target / [279, 179])
    expected = cv2.resize(image, (corrected.shape[1], corrected.shape[0]), interpolation=cv2.INTER_LINEAR)
    # Interpolation occurs once during distortion and once during correction.
    assert np.mean(np.abs(corrected[3:-3, 3:-3] - expected[3:-3, 3:-3])) < .012
    assert corrected.shape[1] >= 244 and corrected.shape[0] >= 150


@pytest.mark.parametrize("corners", [
    [(0, 0), (1, 1), (1, 0), (0, 1)],  # crossed
    [(0, 0), (1, 0), (.2, .2), (0, 1)],  # concave
    [(0, 0), (0, 0), (1, 1), (0, 1)],  # coincident
    [(0, 0), (.01, 0), (.01, .01), (0, .01)],  # too small
    [(0, 0), (float('nan'), 0), (1, 1), (0, 1)],
    [(-.1, 0), (1, 0), (1, 1), (0, 1)],
])
def test_invalid_selections_are_rejected(corners):
    with pytest.raises(ValueError):
        perspective_geometry((100, 100, 3), corners)


def test_oversized_input_is_reported_without_allocating():
    with pytest.raises(ValueError, match="32766"):
        perspective_geometry((100, 32767, 3), [(0, 0), (1, 0), (1, 1), (0, 1)])
